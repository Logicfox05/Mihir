"""Session state machine, spec section 3, with interactive menus.

START --verify phone--> AWAIT_SO (SO list menu) --SO picked/typed, 1 FG--> DONE (buttons: another / done)
  | not found                                     | SO found, many FG
  v                                               v
FAILED (apology, reset)                     AWAIT_FG (FG list menu) --FG picked--> DONE
                                                  | FG not in SO -> re-ask, max N tries, then apology
Voice input -> CONFIRM (Yes/No buttons) before any lookup.

Every menu row title is plain text the phone sends back ("SO 45240", "FG-2002", "Yes"), so a tapped
option and a typed answer go through exactly the same parser and checks.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Session, utcnow
from . import menus, templates
from .intent import Parsed
from .menus import Options
from .replies import ReplyContext
from .verify import customer_orders, filter_fg, find_customer, lookup_orders


@dataclass
class Outcome:
    template: str
    ctx: ReplyContext
    code: str  # outcome code for stats: status_delivered | not_found | verify_failed | mismatch | ask_so | ask_fg | confirm | welcome | bye
    language: str
    options: Options | None = None


def reset(session: Session) -> None:
    session.step = "START"
    session.so_no = None
    session.po_no = None
    session.fg_code = None
    session.pending_value = None
    session.pending_kind = None
    session.attempts = 0


async def get_or_create_session(db: AsyncSession, phone: str) -> Session:
    s = await db.get(Session, phone)
    if s is None:
        s = Session(phone_e164=phone, step="START")
        db.add(s)
        await db.flush()
    else:
        idle = (utcnow() - s.updated_at).total_seconds() if s.updated_at else 0
        if idle > get_settings().session_timeout_min * 60:
            reset(s)
    return s


async def step(db: AsyncSession, session: Session, parsed: Parsed, from_audio: bool) -> Outcome:
    settings = get_settings()
    support = settings.support_contact
    # language: what the customer wrote in; a code-only / tapped message keeps the session's language
    lang = parsed.language if parsed.language in ("en", "hi", "gu") else (session.language if session.language in ("en", "hi", "gu") else "en")
    session.language = lang

    # 1. verify phone on every message
    customer = await find_customer(db, session.phone_e164)
    if customer is None:
        reset(session)
        return Outcome("verify_failed", ReplyContext(support=support), "verify_failed", lang)

    # 2. resolve what the customer gave us (typed or tapped)
    so_no, po_no, fg_code = parsed.so_no, parsed.po_no, parsed.fg_code
    if parsed.bare_codes and not (so_no or po_no or fg_code):
        if session.step == "AWAIT_FG":
            fg_code = parsed.bare_codes[0]
        else:
            so_no = parsed.bare_codes[0]

    # 2b. admin-defined keyword replies (template editor). Never for codes or a Yes/No answer.
    if not (so_no or po_no or fg_code) and parsed.intent not in ("confirm_yes", "confirm_no"):
        custom = templates.registry.match_custom(parsed.raw_text)
        if custom:
            return Outcome(f"custom:{custom.key}", ReplyContext(support=support), "custom", lang, options=menus.custom_buttons(custom.buttons, lang))

    # 3. CONFIRM handling (after voice)
    if session.step == "CONFIRM":
        if parsed.intent == "confirm_yes" and session.pending_value:
            kind, value = session.pending_kind, session.pending_value
            session.pending_value = session.pending_kind = None
            if kind == "so":
                so_no, po_no, fg_code = value, None, None
            elif kind == "po":
                so_no, po_no, fg_code = None, value, None
            else:
                so_no, po_no, fg_code = None, None, value
            from_audio = False
            session.step = "AWAIT_FG" if kind == "fg" else "AWAIT_SO"
        elif parsed.intent == "confirm_no" and not (so_no or po_no or fg_code):
            kind = session.pending_kind
            session.pending_value = session.pending_kind = None
            if kind == "fg" and session.so_no:
                session.step = "AWAIT_FG"
                return await _ask_fg_again(db, session, customer, support, lang)
            return await _menu(db, session, customer, support, lang, welcome=False)
        elif not (so_no or po_no or fg_code) and parsed.intent not in ("menu", "bye"):
            tpl = f"confirm_{session.pending_kind or 'so'}"
            return Outcome(tpl, ReplyContext(value=session.pending_value, support=support), "confirm", lang, options=menus.confirm_buttons(lang))
        else:
            session.pending_value = session.pending_kind = None
            session.step = "AWAIT_FG" if (fg_code and session.so_no) else "AWAIT_SO"

    # 4. bye / menu / greeting without codes
    if parsed.intent == "bye" and not (so_no or po_no or fg_code):
        reset(session)
        return Outcome("bye", ReplyContext(support=support), "bye", lang)
    if parsed.intent == "menu" or (parsed.intent == "greeting" and not (so_no or po_no or fg_code)):
        return await _menu(db, session, customer, support, lang, welcome=True)

    # 5. SO / PO given -> (confirm if audio) -> lookup
    if so_no or po_no:
        if from_audio:
            session.step = "CONFIRM"
            session.pending_kind = "so" if so_no else "po"
            session.pending_value = so_no or po_no
            return Outcome(f"confirm_{session.pending_kind}", ReplyContext(value=session.pending_value, support=support), "confirm", lang, options=menus.confirm_buttons(lang))
        return await _lookup_so(db, session, customer, so_no, po_no, fg_code, support, lang)

    # 6. FG given while we are waiting for one
    if fg_code and session.step == "AWAIT_FG" and session.so_no:
        if from_audio:
            session.step = "CONFIRM"
            session.pending_kind = "fg"
            session.pending_value = fg_code
            return Outcome("confirm_fg", ReplyContext(value=fg_code, support=support), "confirm", lang, options=menus.confirm_buttons(lang))
        return await _lookup_fg(db, session, customer, fg_code, support, lang)

    # 7. nothing usable -> show the right menu for the current step
    if session.step == "AWAIT_FG" and session.so_no:
        return await _ask_fg_again(db, session, customer, support, lang)
    return await _menu(db, session, customer, support, lang, welcome=(session.step == "START"))


async def _menu(db, session, customer, support, lang, welcome: bool) -> Outcome:
    """Welcome / ask-SO with an interactive list of the customer's own SOs."""
    rows = await customer_orders(db, customer)
    reset(session)
    session.step = "AWAIT_SO"
    code = "welcome" if welcome else "ask_so"
    if not rows:
        return Outcome("welcome_no_orders" if welcome else "ask_so", ReplyContext(support=support), code, lang)
    opts = menus.so_list(rows, lang)
    return Outcome("welcome_list" if welcome else "ask_so_list", ReplyContext(support=support), code, lang, options=opts)


async def _lookup_so(db, session, customer, so_no, po_no, fg_code, support, lang) -> Outcome:
    result = await lookup_orders(db, customer, so_no=so_no, po_no=po_no)
    if result.kind == "not_found":
        session.step = "AWAIT_SO"
        return Outcome("not_found", ReplyContext(so_no=so_no or po_no, support=support), "not_found", lang, options=menus.not_found_buttons(lang))
    if result.kind == "mismatch":
        reset(session)
        return Outcome("verify_failed", ReplyContext(support=support), "mismatch", lang)

    session.so_no = result.so_no
    session.po_no = po_no
    session.attempts = 0
    rows = result.rows
    if fg_code:
        rows_fg = filter_fg(rows, fg_code)
        if rows_fg:
            rows = rows_fg
    if len(rows) == 1:
        r = rows[0]
        session.step = "DONE"
        session.fg_code = r.fg_item_code
        return Outcome(
            "result",
            ReplyContext(real_status=r.real_status, so_no=r.so_no, fg_code=r.fg_item_code if _multi_item_so(result.rows) else None, support=support),
            "status_delivered",
            lang,
            options=menus.after_result_buttons(lang),
        )
    session.step = "AWAIT_FG"
    return _ask_fg_outcome(result.so_no, rows, support, lang)


async def _lookup_fg(db, session, customer, fg_code, support, lang) -> Outcome:
    settings = get_settings()
    result = await lookup_orders(db, customer, so_no=session.so_no)
    if result.kind != "ok":
        reset(session)
        return Outcome("verify_failed" if result.kind == "mismatch" else "not_found", ReplyContext(support=support), result.kind, lang)
    rows = filter_fg(result.rows, fg_code)
    if rows:
        r = rows[0]
        session.step = "DONE"
        session.fg_code = r.fg_item_code
        session.attempts = 0
        return Outcome(
            "result",
            ReplyContext(real_status=r.real_status, so_no=r.so_no, fg_code=r.fg_item_code, support=support),
            "status_delivered",
            lang,
            options=menus.after_result_buttons(lang),
        )
    session.attempts += 1
    if session.attempts >= settings.fg_max_attempts:
        reset(session)
        session.step = "AWAIT_SO"
        return Outcome("not_found", ReplyContext(so_no=session.so_no, fg_code=fg_code, support=support), "not_found", lang, options=menus.not_found_buttons(lang))
    return Outcome(
        "ask_fg_retry",
        ReplyContext(so_no=session.so_no, fg_code=fg_code, n_items=len(result.rows), support=support),
        "ask_fg",
        lang,
        options=menus.fg_list(result.rows, lang),
    )


async def _ask_fg_again(db, session, customer, support, lang) -> Outcome:
    result = await lookup_orders(db, customer, so_no=session.so_no)
    if result.kind != "ok":
        return await _menu(db, session, customer, support, lang, welcome=False)
    return _ask_fg_outcome(session.so_no, result.rows, support, lang)


def _ask_fg_outcome(so_no, rows, support, lang) -> Outcome:
    opts = menus.fg_list(rows, lang)
    n = len({r.fg_item_code for r in rows})
    tpl = "ask_fg_list" if opts else "ask_fg"
    return Outcome(tpl, ReplyContext(so_no=so_no, n_items=n, support=support), "ask_fg", lang, options=opts)


def _multi_item_so(rows) -> bool:
    return len({r.fg_item_code for r in rows}) > 1
