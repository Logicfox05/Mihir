"""Editable customer-facing text: conversation templates, menu labels, custom keyword replies.

Defaults live in code (replies.DEFAULTS, menus.DEFAULT_LABELS). Admin overrides live in the
`templates` table and are cached in memory (`registry`). The cache is reloaded after every save
and every 60 s by the scheduler, so a second server process also picks changes up.

Every save is validated (placeholders, required fields, length limits) so an edit can never make
the bot crash or send a WATI payload that WhatsApp rejects.
"""
from __future__ import annotations

import json
import re
import string
from dataclasses import asdict, dataclass, field

import structlog
from sqlalchemy import delete, select

from ..db import session_scope
from ..models import Template, TemplateHistory, utcnow

log = structlog.get_logger(__name__)

LANGS = ("en", "hi", "gu")
LANG_NAMES = {"en": "English", "hi": "Hindi", "gu": "Gujarati"}

# Sample values used for validation and for the live preview in the editor
SAMPLE = {"so_no": "45240", "fg_code": "FG-2002", "n_items": 3, "value": "45240", "support": "+91-98765 43210", "item": ", item FG-2002", "real_status": "In Production"}

# ---------------- specs ----------------
@dataclass(frozen=True)
class TemplateSpec:
    key: str
    title: str
    when: str
    allowed: frozenset
    required: frozenset = frozenset()
    max_len: int = 1024
    trilingual: bool = False  # sent stacked in all three languages
    menu: str = ""  # which menu is attached (for the preview)


_S = frozenset({"support"})
TEMPLATE_SPECS: dict[str, TemplateSpec] = {
    s.key: s
    for s in [
        TemplateSpec("welcome_list", "Welcome + order list", "Customer greets (hi / hello / menu) and has orders in the PPC table. Sent with the list of their SO numbers.", _S, menu="so_list"),
        TemplateSpec("welcome_no_orders", "Welcome, no orders found", "Customer greets but no rows in the PPC table match their name.", _S),
        TemplateSpec("welcome", "Welcome (plain)", "Fallback welcome without a list.", _S),
        TemplateSpec("ask_so_list", "Ask SO + order list", "Bot needs an SO number and can show the list again (e.g. after 'No' on a voice confirmation).", _S, menu="so_list"),
        TemplateSpec("ask_so", "Ask SO (plain)", "Bot needs an SO number, no list available.", _S),
        TemplateSpec("ask_fg_list", "Ask item + item list", "The SO has several FG items; sent with the list of item codes.", frozenset({"so_no", "n_items", "support"}), frozenset({"so_no"}), menu="fg_list"),
        TemplateSpec("ask_fg", "Ask item (plain)", "The SO has more than 10 items, so no list can be shown.", frozenset({"so_no", "n_items", "support"}), frozenset({"so_no"})),
        TemplateSpec("ask_fg_retry", "Item not in SO, ask again", "Customer sent an item code that is not in the chosen SO (before the retry limit).", frozenset({"so_no", "fg_code", "n_items", "support"}), frozenset({"so_no"}), menu="fg_list"),
        TemplateSpec("confirm_so", "Confirm SO (after voice note)", "A voice note was transcribed; bot echoes the SO number with Yes / No buttons.", frozenset({"value", "support"}), frozenset({"value"}), menu="confirm"),
        TemplateSpec("confirm_po", "Confirm PO (after voice note)", "Same as above for a PO number.", frozenset({"value", "support"}), frozenset({"value"}), menu="confirm"),
        TemplateSpec("confirm_fg", "Confirm item (after voice note)", "Same as above for an FG item code.", frozenset({"value", "support"}), frozenset({"value"}), menu="confirm"),
        TemplateSpec("result", "Real Status result", "The answer. {real_status} is the only order field ever sent. {item} expands to ', item FG-…' when the SO has several items, else empty.", frozenset({"so_no", "fg_code", "item", "real_status", "support"}), frozenset({"real_status", "so_no"}), menu="after_result"),
        TemplateSpec("not_found", "SO / item not found", "The SO or PO does not exist, or the item was wrong too many times.", frozenset({"so_no", "fg_code", "support"}), menu="not_found"),
        TemplateSpec("verify_failed", "Verification failed", "Number not in the customer Excel, or the PPC customer name does not match byte-for-byte. Sent in all three languages together.", _S, trilingual=True),
        TemplateSpec("service_down", "Service unavailable", "Unexpected error while processing. Sent in all three languages together.", _S, trilingual=True),
        TemplateSpec("rate_limited", "Too many messages", "Customer exceeded the per-phone rate limit.", _S),
        TemplateSpec("bye", "Goodbye", "Customer taps Done or says thanks / bye.", _S),
    ]
}


@dataclass(frozen=True)
class LabelSpec:
    key: str
    title: str
    when: str
    max_len: int
    placeholders: frozenset = frozenset()


LABEL_SPECS: dict[str, LabelSpec] = {
    s.key: s
    for s in [
        LabelSpec("yes", "Button: Yes", "Voice-note confirmation button. Must still be understood as 'yes' by the bot.", 20),
        LabelSpec("no", "Button: No", "Voice-note confirmation button. Must still be understood as 'no'.", 20),
        LabelSpec("another", "Button: Check another SO", "Shown after a status. Re-opens the SO list.", 20),
        LabelSpec("done", "Button: Done", "Shown after a status / not found. Ends the session.", 20),
        LabelSpec("my_orders", "Button: Show my orders", "Shown after 'not found'. Re-opens the SO list.", 20),
        LabelSpec("menu", "Button: Main menu", "Reserved button label that re-opens the SO list.", 20),
        LabelSpec("select_so", "List button: Select SO", "The button that opens the SO list.", 20),
        LabelSpec("select_item", "List button: Select item", "The button that opens the FG item list.", 20),
        LabelSpec("your_orders", "List section title: Your orders", "Section title above the SO rows.", 24),
        LabelSpec("items_of_so", "List section title: Items in SO {so}", "Section title above the item rows.", 24, frozenset({"so"})),
        LabelSpec("n_items", "Row description: {n} items", "Under each SO row when it has several items.", 60, frozenset({"n"})),
        LabelSpec("one_item", "Row description: 1 item", "Under each SO row with a single item.", 60),
        LabelSpec("more_hint", "List footer: Not listed? Type your SO number.", "Footer shown when the customer has more than 10 SOs.", 60),
        LabelSpec("type_hint", "List footer: Or type the code.", "Footer under the item list.", 60),
    ]
}

# button labels that stand for an intent: the parser recognises the CURRENT label text (intent.label_intent)
LABEL_INTENTS = {"yes": "confirm_yes", "no": "confirm_no", "another": "menu", "my_orders": "menu", "menu": "menu", "done": "bye"}
_LABEL_INTENT = LABEL_INTENTS
CUSTOM_BUTTON_CHOICES = ("my_orders", "another", "done", "menu")


@dataclass
class CustomReply:
    key: str
    title: str
    triggers: list[str]
    texts: dict[str, str]
    buttons: list[str] = field(default_factory=list)  # label keys from CUSTOM_BUTTON_CHOICES
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- helpers ----------------
_FMT = string.Formatter()
_PUNCT = re.compile(r"[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~।]")


def placeholders_in(text: str) -> set[str]:
    out = set()
    for _, name, _, _ in _FMT.parse(text):
        if name is not None:
            out.add(name.split(".")[0].split("[")[0])
    return out


def norm_trigger(s: str) -> str:
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", s)).strip().casefold()


def _defaults():
    from .menus import DEFAULT_LABELS
    from .replies import DEFAULTS

    return DEFAULTS, DEFAULT_LABELS


# ---------------- validation ----------------
def validate_template(key: str, lang: str, text: str) -> list[str]:
    spec = TEMPLATE_SPECS.get(key)
    if not spec:
        return [f"unknown template '{key}'"]
    errors = []
    t = text or ""
    if not t.strip():
        errors.append("text is empty")
    if len(t) > spec.max_len:
        errors.append(f"too long ({len(t)} > {spec.max_len} characters)")
    try:
        used = placeholders_in(t)
    except ValueError as e:
        return errors + [f"unbalanced braces: {e}"]
    unknown = used - spec.allowed
    if unknown:
        errors.append("unknown placeholder(s): " + ", ".join(f"{{{u}}}" for u in sorted(unknown)) + ". Allowed: " + ", ".join(f"{{{a}}}" for a in sorted(spec.allowed)))
    missing = spec.required - used
    if missing:
        errors.append("missing required placeholder(s): " + ", ".join(f"{{{m}}}" for m in sorted(missing)))
    if not errors:
        try:
            t.format(**SAMPLE)
        except (KeyError, IndexError, ValueError) as e:
            errors.append(f"cannot render: {e}")
    return errors


def validate_label(key: str, lang: str, text: str) -> list[str]:
    spec = LABEL_SPECS.get(key)
    if not spec:
        return [f"unknown label '{key}'"]
    errors = []
    t = (text or "").strip()
    if not t:
        errors.append("text is empty")
    try:
        used = placeholders_in(t)
    except ValueError as e:
        return errors + [f"unbalanced braces: {e}"]
    if used - spec.placeholders:
        errors.append("unknown placeholder(s): " + ", ".join(f"{{{u}}}" for u in sorted(used - spec.placeholders)))
    if spec.placeholders - used:
        errors.append("missing placeholder(s): " + ", ".join(f"{{{m}}}" for m in sorted(spec.placeholders - used)))
    rendered = t
    if not errors:
        try:
            rendered = t.format(so="45240", n=10)
        except (KeyError, IndexError, ValueError) as e:
            errors.append(f"cannot render: {e}")
    if len(rendered) > spec.max_len:
        errors.append(f"too long ({len(rendered)} > {spec.max_len} characters; WhatsApp limit)")
    intent = _LABEL_INTENT.get(key)
    if intent and not errors:
        from .intent import regex_parse

        p = regex_parse(rendered, use_labels=False)
        if p.so_no or p.po_no or p.fg_code or p.bare_codes:
            errors.append("a button label must not look like an SO / PO / item code")
        elif p.intent not in ("other", intent):
            errors.append(f"this text already means '{p.intent}' to the bot; it cannot double as '{intent}'")
        # must not collide with another intent button's label in the same language
        n = norm_trigger(rendered)
        for other, other_intent in _LABEL_INTENT.items():
            if other != key and other_intent != intent and norm_trigger(registry.label(other, lang)) == n:
                errors.append(f"same text as the '{LABEL_SPECS[other].title}' button")
                break
    return errors


def validate_custom(reply: CustomReply) -> list[str]:
    errors = []
    if not re.fullmatch(r"[a-z0-9_\-]{2,40}", reply.key or ""):
        errors.append("key must be 2-40 characters: lowercase letters, digits, - or _")
    if reply.key in TEMPLATE_SPECS:
        errors.append("key clashes with a built-in template")
    if not (reply.title or "").strip():
        errors.append("title is empty")
    trig = [norm_trigger(t) for t in reply.triggers if norm_trigger(t)]
    if not trig:
        errors.append("at least one trigger word is required")
    if any(len(t) < 2 for t in trig):
        errors.append("trigger words must be at least 2 characters")
    if not any((reply.texts.get(lg) or "").strip() for lg in LANGS):
        errors.append("text is required in at least one language")
    for lg in LANGS:
        t = reply.texts.get(lg) or ""
        if len(t) > 1024:
            errors.append(f"{LANG_NAMES[lg]} text too long ({len(t)} > 1024)")
        try:
            used = placeholders_in(t)
        except ValueError as e:
            errors.append(f"{LANG_NAMES[lg]}: unbalanced braces: {e}")
            continue
        if used - {"support"}:
            errors.append(f"{LANG_NAMES[lg]}: only {{support}} is allowed as a placeholder")
    bad = [b for b in reply.buttons if b not in CUSTOM_BUTTON_CHOICES]
    if bad:
        errors.append("unknown button(s): " + ", ".join(bad))
    if len(reply.buttons) > 3:
        errors.append("at most 3 buttons")
    return errors


# ---------------- registry (in-memory cache) ----------------
class Registry:
    def __init__(self) -> None:
        self.templates: dict[tuple[str, str], str] = {}
        self.labels: dict[tuple[str, str], str] = {}
        self.custom: dict[str, CustomReply] = {}
        self.loaded_at = None

    # reads (hot path)
    def text(self, key: str, lang: str) -> str:
        defaults, _ = _defaults()
        t = self.templates.get((key, lang))
        if t:
            return t
        d = defaults.get(key)
        if d is None:
            raise KeyError(f"unknown template {key}")
        return d.get(lang) or d["en"]

    def label(self, key: str, lang: str) -> str:
        _, defaults = _defaults()
        t = self.labels.get((key, lang))
        if t:
            return t
        d = defaults[key]
        return d.get(lang) or d["en"]

    def custom_text(self, key: str, lang: str) -> str:
        c = self.custom[key]
        return c.texts.get(lang) or c.texts.get("en") or next(t for t in c.texts.values() if t)

    def match_custom(self, message: str) -> CustomReply | None:
        m = norm_trigger(message or "")
        if not m:
            return None
        for c in self.custom.values():
            if not c.enabled:
                continue
            for trig in c.triggers:
                t = norm_trigger(trig)
                if not t:
                    continue
                if m == t or (len(t) >= 4 and t in m):
                    return c
        return None

    def is_overridden(self, kind: str, key: str, lang: str) -> bool:
        store = self.templates if kind == "template" else self.labels
        return (key, lang) in store


registry = Registry()


async def load_from_db() -> None:
    templates: dict[tuple[str, str], str] = {}
    labels: dict[tuple[str, str], str] = {}
    custom_rows: dict[str, dict] = {}
    async with session_scope() as db:
        rows = (await db.execute(select(Template))).scalars().all()
    for r in rows:
        if r.kind == "template":
            templates[(r.key, r.lang)] = r.text
        elif r.kind == "label":
            labels[(r.key, r.lang)] = r.text
        elif r.kind == "custom":
            custom_rows.setdefault(r.key, {})[r.lang] = r.text
    custom: dict[str, CustomReply] = {}
    for key, per_lang in custom_rows.items():
        try:
            meta = json.loads(per_lang.get("meta") or "{}")
        except ValueError:
            meta = {}
        custom[key] = CustomReply(
            key=key, title=meta.get("title") or key, triggers=list(meta.get("triggers") or []),
            texts={lg: per_lang.get(lg, "") for lg in LANGS}, buttons=list(meta.get("buttons") or []), enabled=bool(meta.get("enabled", True)),
        )
    registry.templates, registry.labels, registry.custom = templates, labels, custom
    registry.loaded_at = utcnow()
    log.info("templates_loaded", templates=len(templates), labels=len(labels), custom=len(custom))


async def _history(db, kind: str, key: str, lang: str, old_text: str | None, action: str) -> None:
    db.add(TemplateHistory(kind=kind, key=key, lang=lang, text=old_text, action=action))


async def save_text(kind: str, key: str, lang: str, text: str) -> list[str]:
    """Save one template/label override. Returns validation errors (empty = saved)."""
    if lang not in LANGS:
        return [f"unknown language '{lang}'"]
    errors = validate_template(key, lang, text) if kind == "template" else validate_label(key, lang, text)
    if errors:
        return errors
    text = text.strip() if kind == "label" else text
    defaults, default_labels = _defaults()
    default = (defaults if kind == "template" else default_labels)[key][lang]
    async with session_scope() as db:
        row = (await db.execute(select(Template).where(Template.kind == kind, Template.key == key, Template.lang == lang))).scalar_one_or_none()
        if text == default:
            # identical to the default -> drop the override
            if row:
                await _history(db, kind, key, lang, row.text, "reset")
                await db.delete(row)
        elif row:
            if row.text != text:
                await _history(db, kind, key, lang, row.text, "save")
                row.text = text
        else:
            await _history(db, kind, key, lang, None, "save")
            db.add(Template(kind=kind, key=key, lang=lang, text=text))
    await load_from_db()
    return []


async def reset_key(kind: str, key: str) -> None:
    """Remove all language overrides of a template/label (back to defaults)."""
    async with session_scope() as db:
        rows = (await db.execute(select(Template).where(Template.kind == kind, Template.key == key))).scalars().all()
        for r in rows:
            await _history(db, kind, key, r.lang, r.text, "reset")
            await db.delete(r)
    await load_from_db()


async def save_custom(reply: CustomReply) -> list[str]:
    reply.triggers = [t.strip() for t in reply.triggers if t and t.strip()]
    errors = validate_custom(reply)
    if errors:
        return errors
    meta = json.dumps({"title": reply.title.strip(), "triggers": reply.triggers, "buttons": reply.buttons, "enabled": reply.enabled}, ensure_ascii=False)
    async with session_scope() as db:
        existing = {r.lang: r for r in (await db.execute(select(Template).where(Template.kind == "custom", Template.key == reply.key))).scalars()}
        for lang, text in [(lg, reply.texts.get(lg, "") or "") for lg in LANGS] + [("meta", meta)]:
            row = existing.get(lang)
            if row:
                if row.text != text:
                    if lang != "meta":
                        await _history(db, "custom", reply.key, lang, row.text, "save")
                    row.text = text
            else:
                db.add(Template(kind="custom", key=reply.key, lang=lang, text=text))
    await load_from_db()
    return []


async def delete_custom(key: str) -> bool:
    async with session_scope() as db:
        rows = (await db.execute(select(Template).where(Template.kind == "custom", Template.key == key))).scalars().all()
        if not rows:
            return False
        for r in rows:
            if r.lang != "meta":
                await _history(db, "custom", key, r.lang, r.text, "delete")
        await db.execute(delete(Template).where(Template.kind == "custom", Template.key == key))
    await load_from_db()
    return True


async def history(kind: str, key: str, limit: int = 50) -> list[dict]:
    async with session_scope() as db:
        rows = (await db.execute(select(TemplateHistory).where(TemplateHistory.kind == kind, TemplateHistory.key == key).order_by(TemplateHistory.id.desc()).limit(limit))).scalars().all()
    return [{"id": r.id, "lang": r.lang, "text": r.text, "action": r.action, "changed_at": r.changed_at.isoformat()} for r in rows]


# ---------------- preview / catalog for the editor ----------------
def render_sample(kind: str, key: str, lang: str, text: str) -> str:
    if kind == "label":
        try:
            return text.format(so="45240", n=3)
        except Exception:  # noqa: BLE001
            return text
    from .replies import ReplyContext, render_text

    ctx = ReplyContext(real_status=SAMPLE["real_status"], so_no=SAMPLE["so_no"], fg_code=SAMPLE["fg_code"], n_items=SAMPLE["n_items"], value=SAMPLE["value"], support=SAMPLE["support"])
    try:
        return render_text(text, lang, ctx)
    except Exception as e:  # noqa: BLE001
        return f"<cannot render: {e}>"


def catalog() -> dict:
    defaults, default_labels = _defaults()
    templates = []
    for spec in TEMPLATE_SPECS.values():
        langs = {}
        for lg in LANGS:
            cur = registry.text(spec.key, lg)
            langs[lg] = {"default": defaults[spec.key][lg], "text": cur, "overridden": registry.is_overridden("template", spec.key, lg)}
        templates.append({"key": spec.key, "title": spec.title, "when": spec.when, "allowed": sorted(spec.allowed), "required": sorted(spec.required),
                          "max_len": spec.max_len, "trilingual": spec.trilingual, "menu": spec.menu, "langs": langs})
    labels = []
    for spec in LABEL_SPECS.values():
        langs = {}
        for lg in LANGS:
            langs[lg] = {"default": default_labels[spec.key][lg], "text": registry.label(spec.key, lg), "overridden": registry.is_overridden("label", spec.key, lg)}
        labels.append({"key": spec.key, "title": spec.title, "when": spec.when, "max_len": spec.max_len, "placeholders": sorted(spec.placeholders),
                       "intent": _LABEL_INTENT.get(spec.key), "langs": langs})
    custom = [c.to_dict() for c in registry.custom.values()]
    return {"templates": templates, "labels": labels, "custom": custom, "sample": SAMPLE, "languages": LANG_NAMES,
            "button_choices": [{"key": k, "label": registry.label(k, "en")} for k in CUSTOM_BUTTON_CHOICES], "loaded_at": registry.loaded_at.isoformat() if registry.loaded_at else None}


def default_label(key: str, lang: str) -> str:
    _, d = _defaults()
    return d[key].get(lang) or d[key]["en"]
