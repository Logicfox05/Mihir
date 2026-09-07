"""Conversation flows through the full processor with the mocked WATI client."""
import uuid

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import MessageLog, Session
from app.services.processor import process_payload
from app.services.wati import wati

SHREE = "919167861236"  # SO 45231 (1 FG), 45232
MEHTA = "919876543210"  # SO 45240 (3 FG)
GUJ = "919898012345"  # SO 45250 (2 FG)
PATEL = "919925001122"  # SO 45260 name mismatch (trailing space)
ROYAL = "919712345678"  # SO 45280 via PO-7777
ANAND = "919081726354"  # no orders
UNKNOWN = "910000000000"


async def say(phone: str, text: str | None = None, *, audio: bool = False) -> str:
    payload = {"id": f"t-{uuid.uuid4().hex}", "waId": phone, "type": "audio" if audio else "text", "text": text, "data": "x.ogg" if audio else None}
    async with session_scope() as db:
        r = await process_payload(db, payload)
    return r.reply_text or ""


async def step_of(phone: str) -> str:
    async with session_scope() as db:
        s = await db.get(Session, phone)
        return s.step if s else "NONE"


@pytest.mark.asyncio
async def test_greeting_then_single_fg(clean_sessions):
    r = await say(SHREE, "hi")
    assert "SO number" in r and await step_of(SHREE) == "AWAIT_SO"
    r = await say(SHREE, "45231")
    assert "In Production" in r and "45231" in r and await step_of(SHREE) == "DONE"
    # DONE accepts another SO directly
    r = await say(SHREE, "SO 45232")
    assert "Dispatched" in r


@pytest.mark.asyncio
async def test_multi_fg_flow(clean_sessions):
    r = await say(MEHTA, "SO no 45240")
    assert "3 items" in r and await step_of(MEHTA) == "AWAIT_FG"
    r = await say(MEHTA, "FG-2002")
    assert "Printing" in r and "FG-2002" in r and await step_of(MEHTA) == "DONE"


@pytest.mark.asyncio
async def test_wrong_fg_twice_then_apology(clean_sessions):
    await say(GUJ, "45250")
    assert await step_of(GUJ) == "AWAIT_FG"
    r = await say(GUJ, "FG-9999")
    assert "not in SO 45250" in r and await step_of(GUJ) == "AWAIT_FG"
    r = await say(GUJ, "FG-8888")
    assert "could not find" in r and await step_of(GUJ) == "AWAIT_SO"


@pytest.mark.asyncio
async def test_fg_given_with_so_in_one_message(clean_sessions):
    r = await say(GUJ, "SO 45250 FG-3002")
    assert "Slitting" in r


@pytest.mark.asyncio
async def test_po_lookup(clean_sessions):
    r = await say(ROYAL, "PO PO-7777")
    assert "Delivered" in r and "45280" in r


@pytest.mark.asyncio
async def test_not_found_and_menu(clean_sessions):
    r = await say(ANAND, "45231")  # exists but belongs to Shree -> mismatch -> verify failed (trilingual)
    assert "could not verify" in r and "क्षमा" in r and "માફ" in r
    r = await say(ANAND, "12345")
    assert "could not find" in r
    r = await say(ANAND, "menu")
    assert "SO number" in r


@pytest.mark.asyncio
async def test_unknown_phone_verify_failed(clean_sessions):
    r = await say(UNKNOWN, "hi")
    assert "could not verify" in r and "support@test" in r


@pytest.mark.asyncio
async def test_mismatch_logged_and_verify_failed(clean_sessions):
    r = await say(PATEL, "45260")
    assert "could not verify" in r


@pytest.mark.asyncio
async def test_voice_confirm_yes_and_no(clean_sessions):
    await say(SHREE, "hi")
    r = await say(SHREE, audio=True)  # fixture transcript: "my SO number is 45231"
    assert "Did you mean SO number 45231" in r and await step_of(SHREE) == "CONFIRM"
    r = await say(SHREE, "no")
    assert "SO number" in r and await step_of(SHREE) == "AWAIT_SO"
    r = await say(SHREE, audio=True)
    r = await say(SHREE, "yes")
    assert "In Production" in r and await step_of(SHREE) == "DONE"


@pytest.mark.asyncio
async def test_voice_confirm_replaced_by_typed_number(clean_sessions):
    r = await say(SHREE, audio=True)
    assert "45231" in r
    r = await say(SHREE, "45232")
    assert "Dispatched" in r


@pytest.mark.asyncio
async def test_hindi_reply_language(clean_sessions):
    r = await say(SHREE, "नमस्ते")
    assert "SO" in r and "नमस्ते" in r
    r = await say(SHREE, "SO नंबर 45231")
    assert "In Production" in r and "Real Status" in r and "का" in r


@pytest.mark.asyncio
async def test_outgoing_logged_and_outbox(clean_sessions):
    n0 = len(wati.outbox)
    await say(SHREE, "45231")
    assert len(wati.outbox) == n0 + 1 and wati.outbox[-1]["phone"] == SHREE
    async with session_scope() as db:
        rows = (await db.execute(select(MessageLog).where(MessageLog.direction == "out"))).scalars().all()
    assert rows and rows[-1].outcome == "status_delivered"
