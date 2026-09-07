import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import session_scope
from app.jobs import queue_worker
from app.main import app
from app.models import InboundQueue, MessageLog

HOOK = "/webhook/wati?token=test-hook"


@pytest.mark.asyncio
async def test_token_required():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/webhook/wati?token=wrong", json={"waId": "1", "text": "hi"})
        assert r.status_code == 401
        r = await c.post("/webhook/wati", json={"waId": "1", "text": "hi"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_enqueue_and_dedup(clean_sessions):
    mid = f"wamid-{uuid.uuid4().hex}"
    payload = {"id": mid, "waId": "919167861236", "type": "text", "text": "45231", "eventType": "message", "owner": False}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(HOOK, json=payload)
        assert r.status_code == 200 and r.json()["status"] == "queued"
        r = await c.post(HOOK, json=payload)  # WATI retry
        assert r.status_code == 200 and r.json()["status"] == "duplicate"
        r = await c.post(HOOK, json={**payload, "id": "x", "owner": True})
        assert r.json()["status"] == "ignored"
    async with session_scope() as db:
        q = (await db.execute(select(InboundQueue).where(InboundQueue.status == "queued"))).scalars().all()
        assert len(q) == 1
        # drain the queue exactly like the worker does
        item = await queue_worker._claim()
    assert item is not None
    await queue_worker._process(item)
    async with session_scope() as db:
        done = await db.get(InboundQueue, item.id)
        assert done.status == "done", done.error
        out = (await db.execute(select(MessageLog).where(MessageLog.direction == "out"))).scalars().all()
        assert out and "In Production" in out[-1].text
        inbound = (await db.execute(select(MessageLog).where(MessageLog.wati_msg_id == mid))).scalar_one()
        assert inbound.outcome == "status_delivered" and inbound.step_after == "DONE"


@pytest.mark.asyncio
async def test_admin_key_and_simulate(clean_sessions):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/admin/api/overview")
        assert r.status_code == 401
        r = await c.get("/admin/api/overview", headers={"X-Admin-Key": "test-admin"})
        assert r.status_code == 200 and r.json()["counts"]["customers"] == 8
        r = await c.get("/health")
        assert r.status_code == 200 and r.json()["db"] is True
