"""Customer-facing text. Section 8 of the spec.

The reply builder receives ONLY {template, real_status, so_no, fg_code, n_items, value, language, support}.
`connection_status` must never reach this module.
"""
from __future__ import annotations

from dataclasses import dataclass

LANGS = ("en", "hi", "gu")

_T: dict[str, dict[str, str]] = {
    "welcome": {
        "en": "Namaste! Please send your SO number to check order status.",
        "hi": "नमस्ते! ऑर्डर स्टेटस जानने के लिए कृपया अपना SO नंबर भेजें।",
        "gu": "નમસ્તે! ઓર્ડર સ્ટેટસ જાણવા માટે કૃપા કરીને તમારો SO નંબર મોકલો.",
    },
    "welcome_list": {
        "en": "Namaste! Select your SO number from the list below to check its status, or type the SO number.",
        "hi": "नमस्ते! स्टेटस जानने के लिए नीचे दी गई सूची से अपना SO नंबर चुनें, या SO नंबर लिखें।",
        "gu": "નમસ્તે! સ્ટેટસ જાણવા માટે નીચેની યાદીમાંથી તમારો SO નંબર પસંદ કરો, અથવા SO નંબર લખો.",
    },
    "welcome_no_orders": {
        "en": "Namaste! We could not find any orders for your account right now. Please send your SO number to check, or contact our team at {support}.",
        "hi": "नमस्ते! अभी आपके खाते में कोई ऑर्डर नहीं मिला। जांचने के लिए कृपया अपना SO नंबर भेजें, या हमारी टीम से {support} पर संपर्क करें।",
        "gu": "નમસ્તે! હાલ તમારા ખાતામાં કોઈ ઓર્ડર મળ્યો નથી. તપાસવા માટે કૃપા કરીને તમારો SO નંબર મોકલો, અથવા અમારી ટીમનો {support} પર સંપર્ક કરો.",
    },
    "ask_so": {
        "en": "Please send your SO number.",
        "hi": "कृपया अपना SO नंबर भेजें।",
        "gu": "કૃપા કરીને તમારો SO નંબર મોકલો.",
    },
    "ask_so_list": {
        "en": "Select your SO number from the list, or type it.",
        "hi": "सूची से अपना SO नंबर चुनें, या लिखें।",
        "gu": "યાદીમાંથી તમારો SO નંબર પસંદ કરો, અથવા લખો.",
    },
    "bye": {
        "en": "Thank you! Message us anytime to check your order status.",
        "hi": "धन्यवाद! अपने ऑर्डर का स्टेटस जानने के लिए कभी भी संदेश भेजें।",
        "gu": "આભાર! તમારા ઓર્ડરનું સ્ટેટસ જાણવા માટે ગમે ત્યારે સંદેશ મોકલો.",
    },
    "ask_fg": {
        "en": "SO {so_no} has {n_items} items. Please send the FG item code.",
        "hi": "SO {so_no} में {n_items} आइटम हैं। कृपया FG आइटम कोड भेजें।",
        "gu": "SO {so_no} માં {n_items} આઇટમ છે. કૃપા કરીને FG આઇટમ કોડ મોકલો.",
    },
    "ask_fg_list": {
        "en": "SO {so_no} has {n_items} items. Select the item from the list, or type the FG item code.",
        "hi": "SO {so_no} में {n_items} आइटम हैं। सूची से आइटम चुनें, या FG आइटम कोड लिखें।",
        "gu": "SO {so_no} માં {n_items} આઇટમ છે. યાદીમાંથી આઇટમ પસંદ કરો, અથવા FG આઇટમ કોડ લખો.",
    },
    "ask_fg_retry": {
        "en": "Item code {fg_code} is not in SO {so_no}. Please send the correct FG item code.",
        "hi": "आइटम कोड {fg_code} SO {so_no} में नहीं है। कृपया सही FG आइटम कोड भेजें।",
        "gu": "આઇટમ કોડ {fg_code} SO {so_no} માં નથી. કૃપા કરીને સાચો FG આઇટમ કોડ મોકલો.",
    },
    "confirm_so": {
        "en": "Did you mean SO number {value}? Reply Yes or send the correct number.",
        "hi": "क्या आपका मतलब SO नंबर {value} है? Yes लिखें या सही नंबर भेजें।",
        "gu": "શું તમારો મતલબ SO નંબર {value} છે? Yes લખો અથવા સાચો નંબર મોકલો.",
    },
    "confirm_po": {
        "en": "Did you mean PO number {value}? Reply Yes or send the correct number.",
        "hi": "क्या आपका मतलब PO नंबर {value} है? Yes लिखें या सही नंबर भेजें।",
        "gu": "શું તમારો મતલબ PO નંબર {value} છે? Yes લખો અથવા સાચો નંબર મોકલો.",
    },
    "confirm_fg": {
        "en": "Did you mean FG item code {value}? Reply Yes or send the correct code.",
        "hi": "क्या आपका मतलब FG आइटम कोड {value} है? Yes लिखें या सही कोड भेजें।",
        "gu": "શું તમારો મતલબ FG આઇટમ કોડ {value} છે? Yes લખો અથવા સાચો કોડ મોકલો.",
    },
    "result": {
        "en": "Real Status for SO {so_no}{item}: {real_status}\n\nSend another SO number to check more, or type \"menu\".",
        "hi": "SO {so_no}{item} का Real Status: {real_status}\n\nऔर जांचने के लिए दूसरा SO नंबर भेजें, या \"menu\" लिखें।",
        "gu": "SO {so_no}{item} નું Real Status: {real_status}\n\nવધુ તપાસવા માટે બીજો SO નંબર મોકલો, અથવા \"menu\" લખો.",
    },
    "not_found": {
        "en": "Sorry, we could not find that SO number / item code under your account. Please check and send it again, or contact our team at {support}.",
        "hi": "क्षमा करें, यह SO नंबर / आइटम कोड आपके खाते में नहीं मिला। कृपया जांच कर दोबारा भेजें, या हमारी टीम से {support} पर संपर्क करें।",
        "gu": "માફ કરશો, આ SO નંબર / આઇટમ કોડ તમારા ખાતામાં મળ્યો નથી. કૃપા કરીને તપાસીને ફરી મોકલો, અથવા અમારી ટીમનો {support} પર સંપર્ક કરો.",
    },
    "verify_failed": {
        "en": "Sorry, we could not verify your details for this number. Please contact our team at {support} and we'll be happy to help.",
        "hi": "क्षमा करें, इस नंबर से आपकी जानकारी सत्यापित नहीं हो सकी। कृपया हमारी टीम से {support} पर संपर्क करें, हम आपकी सहायता करेंगे।",
        "gu": "માફ કરશો, આ નંબર પરથી તમારી વિગતો ચકાસી શકાઈ નથી. કૃપા કરીને અમારી ટીમનો {support} પર સંપર્ક કરો, અમે તમારી મદદ કરીશું.",
    },
    "service_down": {
        "en": "Sorry, our system is temporarily unavailable. Please try again in a few minutes.",
        "hi": "क्षमा करें, हमारा सिस्टम अस्थायी रूप से उपलब्ध नहीं है। कृपया कुछ मिनट बाद पुनः प्रयास करें।",
        "gu": "માફ કરશો, અમારી સિસ્ટમ હાલ પૂરતી ઉપલબ્ધ નથી. કૃપા કરીને થોડી મિનિટ પછી ફરી પ્રયાસ કરો.",
    },
    "rate_limited": {
        "en": "You have sent too many messages. Please wait a few minutes and try again.",
        "hi": "आपने बहुत अधिक संदेश भेजे हैं। कृपया कुछ मिनट प्रतीक्षा करें और पुनः प्रयास करें।",
        "gu": "તમે ઘણા બધા સંદેશા મોકલ્યા છે. કૃપા કરીને થોડી મિનિટ રાહ જુઓ અને ફરી પ્રયાસ કરો.",
    },
}

# These are always sent in all three languages, stacked (spec section 8).
TRILINGUAL = {"verify_failed", "service_down"}

TEMPLATES = tuple(_T.keys())


@dataclass(frozen=True)
class ReplyContext:
    real_status: str | None = None
    so_no: str | None = None
    fg_code: str | None = None
    n_items: int | None = None
    value: str | None = None
    support: str = "[phone/email]"


DEFAULTS = _T  # code defaults; admin overrides come from services.templates.registry


def render_text(text: str, lang: str, ctx: ReplyContext) -> str:
    item = ""
    if ctx.fg_code:
        item = {"en": f", item {ctx.fg_code}", "hi": f", आइटम {ctx.fg_code}", "gu": f", આઇટમ {ctx.fg_code}"}[lang]
    return text.format(
        real_status=ctx.real_status or "",
        so_no=ctx.so_no or "",
        fg_code=ctx.fg_code or "",
        n_items=ctx.n_items if ctx.n_items is not None else "",
        value=ctx.value or "",
        support=ctx.support,
        item=item,
    )


def _render(template: str, lang: str, ctx: ReplyContext) -> str:
    from .templates import registry  # lazy: templates imports DEFAULTS from here

    if template.startswith("custom:"):
        return render_text(registry.custom_text(template[7:], lang), lang, ctx)
    return render_text(registry.text(template, lang), lang, ctx)


def build(template: str, ctx: ReplyContext, language: str = "en") -> str:
    if template not in _T and not template.startswith("custom:"):
        raise KeyError(f"unknown template {template}")
    lang = language if language in LANGS else "en"
    if template in TRILINGUAL:
        return "\n\n".join(_render(template, lg, ctx) for lg in LANGS)
    return _render(template, lang, ctx)
