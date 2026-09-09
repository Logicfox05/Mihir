"""Message processing pipeline, spec section 6.

audio? -> WATI getMedia -> STT -> text
tapped list row / button -> its title becomes the text
text -> intent -> state machine -> reply template (+ menu options) -> WATI send -> log
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import MessageLog
from . import alerts, intent, rate_limit, replies, stt
from .menus import Options
from .state_machine import get_or_create_session, step
from .wati import wati

log = structlog.get_logger(__name__)

AUDIO_TYPES = {"audio", "voice", "ptt"}
# Message types WATI may use for a tapped interactive option (checked case-insensitively)
INTERACTIVE_TYPES = {"interactive", "button", "buttons", "list", "list_reply", "button_reply", "quick_reply", "interactive_reply"}


@dataclass
class ProcessResult:
    phone: str
    inbound_text: str | None
    transcript: str | None
    reply_text: str | None
    outcome: str
    step_after: str | None
    parsed: dict | None = None
    options: dict | None = None
    replies: list[str] | None = None  # every bot message sent for this inbound message, in order


def selection_title(payload: dict) -> str | None:
    """The title of a tapped list row / button, checking every field name WATI / Cloud API are known to use."""
    for key in ("listReply", "buttonReply", "interactiveButtonReply", "quickReplyButton", "list_reply", "button_reply", "buttonText"):
        v = payload.get(key)
        if isinstance(v, dict):
            t = v.get("title") or v.get("text") or v.get("id")
            if t:
                return str(t)
        elif isinstance(v, str) and v.strip():
            return v.strip()
    inter = payload.get("interactive")
    if isinstance(inter, dict):
        for key in ("list_reply", "button_reply", "listReply", "buttonReply"):
            v = inter.get(key)
            if isinstance(v, dict):
                t = v.get("title") or v.get("text") or v.get("id")
                if t:
                    return str(t)
    return None


def extract_message(payload: dict) -> tuple[str, str, str | None, str | None]:
    """Returns (phone, msg_type, text, media_file)."""
    phone = str(payload.get("waId") or payload.get("whatsappNumber") or "").strip()
    msg_type = str(payload.get("type") or "text").lower()
    text = payload.get("text")
    picked = selection_title(payload)
    if picked and (msg_type in INTERACTIVE_TYPES or not text):
        text = picked
        msg_type = "interactive"
    media = payload.get("data") if msg_type in AUDIO_TYPES else None
    return phone, msg_type, (str(text) if text is not None else None), (str(media) if media else None)


async def _log_out(db: AsyncSession, phone: str, text: str, outcome: str, step_after: str | None, options: Options | None = None) -> None:
    db.add(
        MessageLog(
            phone_e164=phone, direction="out", msg_type=(options.kind if options else "text"), text=text, outcome=outcome,
            step_after=step_after, options=json.dumps(options.to_dict(), ensure_ascii=False) if options else None,
        )
    )


async def process_payload(db: AsyncSession, payload: dict, message_log_id: int | None = None) -> ProcessResult:
    settings = get_settings()
    phone, msg_type, text, media = extract_message(payload)
    bound = log.bind(phone_e164=phone, wati_msg_id=payload.get("id"))
    transcript: str | None = None
    in_row = await db.get(MessageLog, message_log_id) if message_log_id else None

    try:
        allowed, just_exceeded = await rate_limit.check(db, phone)
        if not allowed:
            bound.warning("rate_limited")
            reply = replies.build("rate_limited", replies.ReplyContext(support=settings.support_contact), "en") if just_exceeded else None
            if reply:
                await wati.send_text(phone, reply)
                await _log_out(db, phone, reply, "rate_limited", None)
            if in_row:
                in_row.outcome = "rate_limited"
            return ProcessResult(phone, text, None, reply, "rate_limited", None)

        from_audio = msg_type in AUDIO_TYPES
        voice_blocked = False  # a voice note arrived but speech-to-text is off / not configured
        if from_audio:
            try:
                audio = await wati.get_media(media or "")
                transcript = await stt.transcribe(audio, filename=(media or "voice.ogg").split("/")[-1])
                text = transcript
                if in_row:
                    in_row.transcript = transcript
            except stt.SttUnavailable as e:
                # Never guess at a number we could not hear: that would look up someone else's order.
                voice_blocked, from_audio, text = True, False, None
                bound.info("voice_note_not_transcribed", reason=str(e))
                if settings.voice_notes:  # asked for, but cannot work -> a real misconfiguration
                    await alerts.notify_throttled("voice_notes_broken", "Voice notes are on but cannot be transcribed", str(e), level="warning")

        # The session is loaded first so the parser knows the step: while the bot asks for an item,
        # an unprefixed number means an item, not an order. A tapped option is an exact string the
        # regex already understands, so it never needs the AI call.
        session = await get_or_create_session(db, phone)
        parsed = await intent.parse(text or "", allow_ai=(msg_type != "interactive"), step=session.step)
        # one customer message can produce several bot messages (greeting, then the language question)
        outcomes = await step(db, session, parsed, from_audio, voice_blocked=voice_blocked)

        sent: list[str] = []
        for outcome in outcomes:
            reply = replies.build(outcome.template, outcome.ctx, outcome.language)
            await wati.send_options(phone, reply, outcome.options)
            await _log_out(db, phone, reply, outcome.code, session.step, outcome.options)
            sent.append(reply)
        last = outcomes[-1]
        if in_row:
            in_row.outcome = last.code
            in_row.step_after = session.step
            if msg_type == "interactive":
                in_row.msg_type = "interactive"
                in_row.text = text
        bound.info("processed", outcome=last.code, step=session.step, intent=parsed.intent, source=parsed.source,
                   messages=len(sent), menu=last.options.kind if last.options else None)
        return ProcessResult(
            phone, text, transcript, sent[-1], last.code, session.step,
            parsed={"intent": parsed.intent, "so_no": parsed.so_no, "po_no": parsed.po_no, "fg_code": parsed.fg_code,
                    "bare_codes": parsed.bare_codes, "language": parsed.language, "source": parsed.source},
            options=last.options.to_dict() if last.options else None,
            replies=sent,
        )
    except Exception as e:  # noqa: BLE001 - never leave the customer hanging
        bound.error("processing_failed", error=str(e), tb=traceback.format_exc())
        await alerts.notify("Message processing failed", f"phone={phone} msg={payload.get('id')}\n{e}\n{traceback.format_exc()[-1500:]}")
        reply = replies.build("service_down", replies.ReplyContext(support=settings.support_contact), "en")
        try:
            if phone:
                await wati.send_text(phone, reply)
                await _log_out(db, phone, reply, "service_down", None)
        except Exception as e2:  # noqa: BLE001
            bound.error("service_down_send_failed", error=str(e2))
        if in_row:
            in_row.outcome = "service_down"
        return ProcessResult(phone, text, transcript, reply, "service_down", None)
