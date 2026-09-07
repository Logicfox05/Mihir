"""Intent + entity extraction.

Primary: OpenAI gpt-4o-mini (JSON mode). Fallback (and always run first): regex.
The customer's message is the ONLY input. No customer / order data is ever sent.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings

log = structlog.get_logger(__name__)

Intent = Literal["check_status", "greeting", "confirm_yes", "confirm_no", "menu", "bye", "other"]


@dataclass
class Parsed:
    intent: Intent = "other"
    so_no: str | None = None
    po_no: str | None = None
    fg_code: str | None = None
    bare_codes: list[str] = field(default_factory=list)  # tokens with no SO/PO/FG prefix
    language: str | None = None  # None = undetermined (code-only message) -> keep the session's language
    source: str = "regex"
    raw_text: str = ""


# ---------------- regex layer ----------------
# a code must contain a digit within its first 4 characters (rejects words like NUMBER / CODE)
_CODE = r"((?=[A-Z\-/]{0,3}\d)[A-Z0-9][A-Z0-9\-/]{2,})"
# filler between the keyword and the code: "SO number is 45231", "so no: 45231", "SO - 45231", "PO nambar 7781"
_FILL = r"[\s.:#=]*(?:no\.?|number|num|nambar|nmbr|code|नंबर|नम्बर|क्रमांक|कोड|નંબર|કોડ)?[\s.:#=]*(?:is|hai|che|hoy|है|છે|=|:)?[\s.:#=]*"
# glued tokens keep their prefix: "PO-7781", "FG-2003", "SO45231", "FG 2003"
_GLUED = re.compile(r"\b((SO|PO|FG)[-/ ]?\d[A-Z0-9\-/]*)\b", re.I)
_SO = re.compile(r"\b(?:so|s\.o\.?|sales\s*order)\b" + _FILL + _CODE, re.I)
_PO = re.compile(r"\b(?:po|p\.o\.?|purchase\s*order)\b" + _FILL + _CODE, re.I)
_FG = re.compile(r"\b(?:fg|f\.g\.?|item\s*code|item)\b" + _FILL + _CODE, re.I)
_BARE = re.compile(r"\b([A-Z]{0,3}-?\d{3,}[A-Z0-9\-/]*)\b", re.I)
# NOTE: `\b` does not work after Devanagari/Gujarati vowel signs (they are combining marks, not \w),
# so word endings are checked with an explicit lookahead instead.
_END = r"(?=$|[\s.,!?।])"
_YES = re.compile(r"^\s*(yes|y|yeah|yep|ok|okay|correct|right|haan|ha|han|hanji|ji|sahi|barabar|हाँ|हां|हा|जी|सही|હા|હાં|બરાબર|સાચું)" + _END, re.I)
_NO = re.compile(r"^\s*(no|n|nope|nah|wrong|nahi|nahin|nai|galat|नहीं|नही|गलत|ના|નહીં|ખોટું)" + _END, re.I)
_GREET = re.compile(r"^\s*(hi|hello|hey|hii+|namaste|namaskar|नमस्ते|नमस्कार|હેલો|નમસ્તે|hlo|good\s*(morning|evening|afternoon)|start)" + _END, re.I)
# "menu" also covers the button labels that re-open the SO list (see menus.LABELS)
_MENU = re.compile(
    r"^\s*(menu|main\s*menu|start\s*over|restart|reset|मेनू|मुख्य\s*मेनू|મેનુ|મુખ્ય\s*મેનુ"
    r"|check\s*another\s*so|another\s*so|another|show\s*my\s*orders|my\s*orders|orders|order\s*list"
    r"|दूसरा\s*so\s*देखें|दूसरा\s*so|मेरे\s*ऑर्डर\s*दिखाएं|मेरे\s*ऑर्डर"
    r"|બીજો\s*so\s*જુઓ|બીજો\s*so|મારા\s*ઓર્ડર\s*બતાવો|મારા\s*ઓર્ડર)[\s.!]*$",
    re.I,
)
_BYE = re.compile(r"^\s*(done|thanks?|thank\s*you|thx|ty|bye|ok\s*thanks|ok\s*bye|हो\s*गया|धन्यवाद|शुक्रिया|થઈ\s*ગયું|આભાર)[\s.!]*$", re.I)


def _norm_code(c: str) -> str:
    c = c.strip().upper().rstrip(".,;:")
    c = re.sub(r"^(SO|PO|FG)\s+", r"\1-", c)
    return c


def _strip_so(c: str) -> str:
    """SO numbers are stored without a prefix; 'SO-45231' -> '45231'."""
    return re.sub(r"^SO[-/ ]?", "", c, flags=re.I)


_CODE_WORDS = re.compile(r"\b(?:so|po|fg|no|number|num|code|item|id|s\.o\.?|p\.o\.?|f\.g\.?)\b|[A-Z]{0,3}[-/ ]?\d[A-Z0-9\-/]*", re.I)


def detect_language(text: str) -> str | None:
    """gu / hi by script; en if there are real Latin words; None for code-only messages
    (e.g. a tapped list row "SO 45240") so the session keeps its language."""
    if re.search(r"[઀-૿]", text):
        return "gu"
    if re.search(r"[ऀ-ॿ]", text):
        return "hi"
    rest = _CODE_WORDS.sub(" ", text)
    if re.search(r"[A-Za-z]{2,}", rest):
        return "en"
    return None


def label_intent(text: str) -> Intent | None:
    """If the message equals one of the current menu button labels (any language, as edited in the
    template editor), return the intent that button stands for. Tapped buttons come back as their title."""
    from .templates import LABEL_INTENTS, norm_trigger, registry  # lazy: templates imports from here

    n = norm_trigger(text)
    if not n:
        return None
    for key, intent in LABEL_INTENTS.items():
        for lang in ("en", "hi", "gu"):
            try:
                if norm_trigger(registry.label(key, lang)) == n:
                    return intent  # type: ignore[return-value]
            except KeyError:
                continue
    return None


def regex_parse(text: str, use_labels: bool = True) -> Parsed:
    p = Parsed(raw_text=text, language=detect_language(text), source="regex")
    t = text.strip()
    if not t:
        return p
    if use_labels:
        li = label_intent(t)
        if li:
            p.intent = li
            return p
    if _MENU.match(t):
        p.intent = "menu"
        return p
    if _BYE.match(t):
        p.intent = "bye"
        return p
    # 1. glued tokens first (PO-7781, FG-2003, SO45231) so their prefix survives
    glued_spans: list[tuple[int, int]] = []
    for m in _GLUED.finditer(t):
        kind = m.group(2).upper()
        code = _norm_code(m.group(1))
        if kind == "SO" and not p.so_no:
            p.so_no = _strip_so(code)
        elif kind == "PO" and not p.po_no:
            p.po_no = code
        elif kind == "FG" and not p.fg_code:
            p.fg_code = code
        else:
            continue
        glued_spans.append(m.span())

    def _free(m: re.Match) -> bool:
        return not any(a <= m.start(1) < b for a, b in glued_spans)

    # 2. keyword + separate code ("SO number is 45231", "item code 2003")
    m = _SO.search(t)
    if m and not p.so_no and _free(m):
        p.so_no = _strip_so(_norm_code(m.group(1)))
    m = _PO.search(t)
    if m and not p.po_no and _free(m):
        p.po_no = _norm_code(m.group(1))
    m = _FG.search(t)
    if m and not p.fg_code and _free(m):
        p.fg_code = _norm_code(m.group(1))

    # 3. bare tokens (context decides SO vs FG in the state machine)
    consumed = {p.so_no, p.po_no, p.fg_code}
    for m in _BARE.finditer(t):
        if any(a <= m.start() < b for a, b in glued_spans):
            continue
        code = _norm_code(m.group(1))
        if code in consumed or code in p.bare_codes:
            continue
        # skip tokens that are the tail of an already-extracted code (e.g. "7781" inside "PO-7781")
        if any(c and c.endswith(code) for c in consumed):
            continue
        p.bare_codes.append(code)

    if p.so_no or p.po_no or p.fg_code or p.bare_codes:
        p.intent = "check_status"
    elif _YES.match(t):
        p.intent = "confirm_yes"
    elif _NO.match(t):
        p.intent = "confirm_no"
    elif _GREET.match(t):
        p.intent = "greeting"
    else:
        p.intent = "other"
    return p


# ---------------- OpenAI layer ----------------
_SYSTEM = (
    "You extract order lookup details from a WhatsApp message sent by a customer of a packaging company. "
    "Return ONLY a JSON object with keys: intent, so_no, po_no, fg_code, language. "
    "intent is one of: check_status, greeting, confirm_yes, confirm_no, menu, bye, other. "
    "menu = the customer wants to see / pick from their orders again (menu, another SO, my orders). bye = done/thanks/bye. "
    "so_no = sales order number if explicitly given as SO (string or null). "
    "po_no = purchase order number if explicitly given as PO (string or null). "
    "fg_code = FG item code if given (string or null). "
    "If the message contains just a number/code with no prefix, put it in so_no unless it clearly looks like an item code (e.g. starts with FG). "
    "language is en, hi or gu based on the language the customer wrote in (romanized Hindi/Gujarati count as hi/gu). "
    "Never invent values."
)


class OpenAIError(Exception):
    pass


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4), retry=retry_if_exception_type(OpenAIError), reraise=True)
async def _call_openai(text: str) -> dict:
    s = get_settings()
    body = {
        "model": s.openai_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": text}],
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {s.openai_api_key}"},
                json=body,
            )
    except httpx.HTTPError as e:
        raise OpenAIError(str(e)) from e
    if r.status_code >= 500 or r.status_code == 429:
        raise OpenAIError(f"openai {r.status_code}")
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return json.loads(content)


async def parse(text: str) -> Parsed:
    """Regex first (never fails), then overlay OpenAI if configured and successful."""
    p = regex_parse(text)
    s = get_settings()
    if not s.openai_api_key:
        return p
    try:
        data = await _call_openai(text)
    except Exception as e:  # noqa: BLE001 - bot must work without OpenAI
        log.warning("openai_intent_failed", error=str(e))
        return p
    try:
        intent = data.get("intent")
        if intent in ("check_status", "greeting", "confirm_yes", "confirm_no", "menu", "bye", "other"):
            p.intent = intent
        for k in ("so_no", "po_no", "fg_code"):
            v = data.get(k)
            if v and str(v).strip():
                code = _norm_code(str(v))
                setattr(p, k, _strip_so(code) if k == "so_no" else code)
        lang = data.get("language")
        # A code-only message carries no language signal; only accept an Indic verdict for it.
        if lang in ("hi", "gu") or (lang == "en" and p.language is not None):
            p.language = lang
        # A code the model classified explicitly should no longer count as bare
        p.bare_codes = [c for c in p.bare_codes if c not in {p.so_no, p.po_no, p.fg_code}]
        if p.so_no or p.po_no or p.fg_code:
            p.intent = "check_status"
        p.source = "openai"
    except Exception as e:  # noqa: BLE001
        log.warning("openai_intent_bad_payload", error=str(e))
    return p
