"""Template editor API (X-Admin-Key): conversation messages, menu labels, buttons, custom replies,
plus the live WATI connection status and a test send to a real WhatsApp number."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services import templates as T
from ..services.wati import wati
from ..utils.phone import normalize_phone
from .admin import require_admin

router = APIRouter(prefix="/admin/api/templates", dependencies=[Depends(require_admin)])


class TextsIn(BaseModel):
    texts: dict[str, str] = Field(description="{'en': ..., 'hi': ..., 'gu': ...} - only the languages present are saved")


class PreviewIn(BaseModel):
    kind: str
    key: str
    lang: str
    text: str


class ButtonsIn(BaseModel):
    buttons: list[str]


class TestSendIn(BaseModel):
    kind: str = "template"
    key: str
    lang: str = "en"
    phone: str
    text: str | None = None  # unsaved draft; falls back to the saved text


class CustomIn(BaseModel):
    key: str
    title: str
    triggers: list[str]
    texts: dict[str, str]
    buttons: list[str] = []
    enabled: bool = True


# ---------------- read ----------------
@router.get("")
async def get_catalog():
    return T.catalog()


@router.get("/wati-status")
async def wati_status():
    """Is the dashboard actually wired to WhatsApp right now?"""
    return await wati.check()


@router.post("/reload")
async def reload():
    await T.load_from_db()
    return {"ok": True, "loaded_at": T.registry.loaded_at.isoformat()}


@router.post("/preview")
async def preview(body: PreviewIn):
    if body.kind == "template":
        errors = T.validate_template(body.key, body.lang, body.text)
    elif body.kind == "label":
        errors = T.validate_label(body.key, body.lang, body.text)
    else:
        errors = [] if len(body.text) <= 1024 else ["too long"]
    return {"errors": errors, "rendered": T.render_sample(body.kind, body.key, body.lang, body.text)}


# ---------------- test send (real WhatsApp) ----------------
@router.post("/test-send")
async def test_send(body: TestSendIn):
    """Send this exact message to one WhatsApp number through WATI, with sample values filled in."""
    if body.kind not in ("template", "custom"):
        raise HTTPException(400, "only whole messages can be test-sent (choose a message, not a button label)")
    pr = normalize_phone(body.phone)
    if not pr.ok:
        return {"ok": False, "detail": f"That number is not valid: {pr.reason}. Use 10 digits or 91XXXXXXXXXX."}

    if body.kind == "template":
        if body.key not in T.TEMPLATE_SPECS:
            raise HTTPException(404, f"unknown message '{body.key}'")
        text = body.text if body.text is not None else T.registry.text(body.key, body.lang)
        errors = T.validate_template(body.key, body.lang, text)
        if errors:
            return {"ok": False, "detail": "Fix these first: " + "; ".join(errors)}
        rendered = T.render_sample("template", body.key, body.lang, text)
        options = T.sample_options(body.key, body.lang)
    else:
        reply = T.registry.custom.get(body.key)
        if reply is None:
            raise HTTPException(404, f"unknown custom reply '{body.key}'")
        text = body.text if body.text is not None else T.registry.custom_text(body.key, body.lang)
        rendered = T.render_sample("template", "main_menu", body.lang, text) if "{" in text else text
        from ..services import menus

        options = menus.custom_buttons(reply.buttons, body.lang)

    try:
        await wati.send_options(pr.phone, rendered, options)
    except Exception as e:  # noqa: BLE001 - report, never crash the dashboard
        return {"ok": False, "detail": f"WATI refused the message: {e}", "text": rendered}
    mocked = wati.mocked
    detail = (
        "No WATI token is set, so nothing was sent to WhatsApp. The message is in Data -> outbox exactly as it would go out."
        if mocked
        else f"Sent to {pr.phone} on WhatsApp. Note: WATI can only deliver if that number messaged you in the last 24 hours."
    )
    return {"ok": True, "mocked": mocked, "sent_to": pr.phone, "text": rendered,
            "options": options.to_dict() if options else None, "detail": detail}


# ---------------- write ----------------
@router.put("/buttons/{key}")
async def save_buttons(key: str, body: ButtonsIn):
    errors = await T.save_buttons(key, body.buttons)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "errors": [], "buttons": T.registry.buttons(key)}


@router.put("/{kind}/{key}")
async def save_texts(kind: str, key: str, body: TextsIn):
    if kind not in ("template", "label"):
        raise HTTPException(404, "kind must be template or label")
    specs = T.TEMPLATE_SPECS if kind == "template" else T.LABEL_SPECS
    if key not in specs:
        raise HTTPException(404, f"unknown {kind} '{key}'")
    errors: dict[str, list[str]] = {}
    for lang, text in body.texts.items():
        if lang not in T.LANGS:
            errors[lang] = ["unknown language"]
            continue
        e = T.validate_template(key, lang, text) if kind == "template" else T.validate_label(key, lang, text)
        if e:
            errors[lang] = e
    if errors:
        return {"ok": False, "errors": errors}
    for lang, text in body.texts.items():
        e = await T.save_text(kind, key, lang, text)
        if e:  # a rule that only fails on write (e.g. a cross-label collision created by an earlier language)
            errors[lang] = e
    return {"ok": not errors, "errors": errors}


@router.delete("/{kind}/{key}")
async def reset_to_default(kind: str, key: str):
    if kind == "custom":
        if not await T.delete_custom(key):
            raise HTTPException(404, "no such custom reply")
        return {"ok": True}
    if kind == "buttons":
        slot = T.BUTTON_SLOTS.get(key)
        if slot is None:
            raise HTTPException(404, f"'{key}' has no buttons")
        await T.save_buttons(key, list(slot.default))
        return {"ok": True, "buttons": T.registry.buttons(key)}
    if kind not in ("template", "label"):
        raise HTTPException(404, "kind must be template, label, buttons or custom")
    await T.reset_key(kind, key)
    return {"ok": True}


@router.get("/{kind}/{key}/history")
async def get_history(kind: str, key: str):
    return await T.history(kind, key)


@router.post("/custom")
async def save_custom(body: CustomIn):
    reply = T.CustomReply(key=body.key.strip().lower(), title=body.title, triggers=body.triggers,
                          texts={lg: body.texts.get(lg, "") for lg in T.LANGS}, buttons=body.buttons, enabled=body.enabled)
    errors = await T.save_custom(reply)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "errors": [], "custom": reply.to_dict()}


@router.post("/custom/test")
async def test_custom_match(body: dict):
    """Which custom reply (if any) would fire for this message?"""
    c = T.registry.match_custom(str(body.get("text") or ""))
    return {"match": c.to_dict() if c else None}
