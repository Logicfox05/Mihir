"""Template editor API (X-Admin-Key): conversation templates, menu labels, custom keyword replies."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services import templates as T
from .admin import require_admin

router = APIRouter(prefix="/admin/api/templates", dependencies=[Depends(require_admin)])


class TextsIn(BaseModel):
    texts: dict[str, str] = Field(description="{'en': ..., 'hi': ..., 'gu': ...} — only the languages present are saved")


class PreviewIn(BaseModel):
    kind: str
    key: str
    lang: str
    text: str


class CustomIn(BaseModel):
    key: str
    title: str
    triggers: list[str]
    texts: dict[str, str]
    buttons: list[str] = []
    enabled: bool = True


@router.get("")
async def get_catalog():
    return T.catalog()


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
        await T.save_text(kind, key, lang, text)
    return {"ok": True, "errors": {}}


@router.delete("/{kind}/{key}")
async def reset_to_default(kind: str, key: str):
    if kind == "custom":
        if not await T.delete_custom(key):
            raise HTTPException(404, "no such custom reply")
        return {"ok": True}
    if kind not in ("template", "label"):
        raise HTTPException(404, "kind must be template, label or custom")
    await T.reset_key(kind, key)
    return {"ok": True}


@router.get("/{kind}/{key}/history")
async def get_history(kind: str, key: str):
    return await T.history(kind, key)


@router.post("/custom")
async def save_custom(body: CustomIn):
    reply = T.CustomReply(key=body.key.strip().lower(), title=body.title, triggers=body.triggers, texts={lg: body.texts.get(lg, "") for lg in T.LANGS}, buttons=body.buttons, enabled=body.enabled)
    errors = await T.save_custom(reply)
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True, "errors": [], "custom": reply.to_dict()}


@router.post("/custom/test")
async def test_custom_match(body: dict):
    """Which custom reply (if any) would fire for this message?"""
    c = T.registry.match_custom(str(body.get("text") or ""))
    return {"match": c.to_dict() if c else None}
