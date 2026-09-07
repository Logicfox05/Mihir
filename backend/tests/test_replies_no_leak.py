"""Spec 5.5: the outgoing text must never contain any connection_status value from the fixture data."""
import itertools
import uuid

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import MessageLog, OrderCache
from app.services import replies
from app.services.processor import process_payload
from app.services.replies import ReplyContext

PHONES = ["919167861236", "919876543210", "919898012345", "919925001122", "919033445566", "919712345678", "919081726354", "910000000000"]
INPUTS = ["hi", "45231", "45240", "FG-2001", "45250", "FG-3002", "45260", "45270", "PO PO-7777", "yes", "no", "menu", "garbage", "SO 45240 FG-2003"]


@pytest.mark.asyncio
async def test_no_connection_status_ever_leaks(clean_sessions):
    async with session_scope() as db:
        statuses = {r.connection_status for r in (await db.execute(select(OrderCache))).scalars() if r.connection_status}
    assert statuses  # fixture has them
    for phone, text in itertools.product(PHONES, INPUTS):
        async with session_scope() as db:
            await process_payload(db, {"id": f"leak-{uuid.uuid4().hex}", "waId": phone, "type": "text", "text": text})
    async with session_scope() as db:
        rows = (await db.execute(select(MessageLog).where(MessageLog.direction == "out"))).scalars().all()
    outs = [m.text for m in rows] + [m.options for m in rows if m.options]  # menu rows/descriptions are customer-visible too
    assert outs
    for text in outs:
        for cs in statuses:
            assert cs not in text, f"connection_status {cs!r} leaked in {text!r}"
        assert "CONN-" not in text


def test_reply_context_has_no_connection_status_field():
    assert "connection_status" not in ReplyContext.__dataclass_fields__


def test_every_template_renders_in_every_language():
    ctx = ReplyContext(real_status="X", so_no="1", fg_code="FG-1", n_items=2, value="1", support="s")
    for t in replies.TEMPLATES:
        for lang in replies.LANGS:
            out = replies.build(t, ctx, lang)
            assert out and "{" not in out
    assert replies.build("verify_failed", ctx, "en").count("\n\n") == 2  # trilingual stacked
