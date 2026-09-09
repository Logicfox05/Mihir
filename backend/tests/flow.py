"""Helpers that drive the conversation through the full processor (mocked WATI)."""
from __future__ import annotations

import uuid

from app.db import session_scope
from app.models import Session
from app.services.processor import ProcessResult, process_payload

SHREE = "919167861236"  # SO 45231 (1 FG), 45232 (1 FG)
MEHTA = "919876543210"  # SO 45240 (3 FG)
GUJ = "919898012345"  # SO 45250 (2 FG)
PATEL = "919925001122"  # SO 45260 name mismatch (trailing space)
ROYAL = "919712345678"  # SO 45280 via PO-7777
ANAND = "919081726354"  # no orders
UNKNOWN = "910000000000"

LANG_BUTTONS = ["English", "हिंदी", "ગુજરાતી"]
MENU_BUTTONS = {"en": ["Order status", "Change language", "Contact us"],
                "hi": ["ऑर्डर स्टेटस", "भाषा बदलें", "संपर्क करें"],
                "gu": ["ઓર્ડર સ્ટેટસ", "ભાષા બદલો", "સંપર્ક કરો"]}


async def send(phone: str, text: str | None = None, *, audio: bool = False, tap: bool = False) -> ProcessResult:
    payload: dict = {"id": f"t-{uuid.uuid4().hex}", "waId": phone, "type": "text", "text": text}
    if audio:
        payload.update(type="audio", text=None, data="x.ogg")
    elif tap:
        payload.update(type="interactive", buttonReply={"text": text})
    async with session_scope() as db:
        return await process_payload(db, payload)


async def say(phone: str, text: str | None = None, *, audio: bool = False) -> str:
    return (await send(phone, text, audio=audio)).reply_text or ""


async def tap(phone: str, title: str) -> ProcessResult:
    return await send(phone, title, tap=True)


def titles(r: ProcessResult) -> list[str]:
    return [i["title"] for i in r.options["items"]] if r.options else []


async def step_of(phone: str) -> str:
    async with session_scope() as db:
        s = await db.get(Session, phone)
        return s.step if s else "NONE"


async def open_menu(phone: str, language: str = "English") -> ProcessResult:
    """First contact: greeting + language question, then tap a language -> main menu."""
    r = await send(phone, "hi")
    assert r.outcome == "ask_language", r
    r = await tap(phone, language)
    assert r.outcome == "menu", r
    return r
