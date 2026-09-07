"""DB-backed inbound queue worker. No Redis. Survives restarts.

Claim is a single UPDATE that only succeeds for one worker, portable across MySQL and SQLite.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import structlog
from sqlalchemy import select, text, update

from ..db import session_scope
from ..models import InboundQueue, utcnow
from ..services.processor import process_payload

log = structlog.get_logger(__name__)

wake = asyncio.Event()
_stop = asyncio.Event()
MAX_ATTEMPTS = 3
STUCK_AFTER = timedelta(minutes=5)

_CLAIM = text(
    "UPDATE inbound_queue SET status='processing', attempts=attempts+1, updated_at=:now "
    "WHERE status='queued' AND id = (SELECT id FROM (SELECT id FROM inbound_queue WHERE status='queued' ORDER BY id LIMIT 1) AS t)"
)


async def _claim() -> InboundQueue | None:
    async with session_scope() as db:
        res = await db.execute(_CLAIM, {"now": utcnow()})
        if not res.rowcount:
            return None
        # the row we just claimed: most recently updated 'processing' row
        row = (
            await db.execute(select(InboundQueue).where(InboundQueue.status == "processing").order_by(InboundQueue.updated_at.desc(), InboundQueue.id.desc()).limit(1))
        ).scalar_one_or_none()
        return row


async def _process(item: InboundQueue) -> None:
    payload = json.loads(item.payload)
    try:
        async with session_scope() as db:
            await process_payload(db, payload, message_log_id=item.message_log_id)
        async with session_scope() as db:
            await db.execute(update(InboundQueue).where(InboundQueue.id == item.id).values(status="done", error=None, updated_at=utcnow()))
    except Exception as e:  # noqa: BLE001
        log.error("queue_item_failed", id=item.id, error=str(e))
        async with session_scope() as db:
            status = "failed" if item.attempts >= MAX_ATTEMPTS else "queued"
            await db.execute(update(InboundQueue).where(InboundQueue.id == item.id).values(status=status, error=str(e)[:2000], updated_at=utcnow()))


async def _recover_stuck() -> None:
    cutoff = utcnow() - STUCK_AFTER
    async with session_scope() as db:
        await db.execute(
            update(InboundQueue)
            .where(InboundQueue.status == "processing", InboundQueue.updated_at < cutoff, InboundQueue.attempts < MAX_ATTEMPTS)
            .values(status="queued", updated_at=utcnow())
        )
        await db.execute(
            update(InboundQueue)
            .where(InboundQueue.status == "processing", InboundQueue.updated_at < cutoff, InboundQueue.attempts >= MAX_ATTEMPTS)
            .values(status="failed", error="stuck in processing", updated_at=utcnow())
        )


async def run_forever() -> None:
    log.info("queue_worker_started")
    await _recover_stuck()
    last_recover = utcnow()
    while not _stop.is_set():
        try:
            item = await _claim()
            if item is None:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                wake.clear()
                if utcnow() - last_recover > timedelta(minutes=1):
                    await _recover_stuck()
                    last_recover = utcnow()
                continue
            await _process(item)
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            log.error("queue_worker_loop_error", error=str(e))
            await asyncio.sleep(1)
    log.info("queue_worker_stopped")


def stop() -> None:
    _stop.set()
    wake.set()


async def wait_for(queue_id: int, timeout: float = 15.0) -> InboundQueue | None:
    """Poll until the item is done/failed (used by the simulator)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with session_scope() as db:
            item = await db.get(InboundQueue, queue_id)
            if item and item.status in ("done", "failed"):
                return item
        await asyncio.sleep(0.15)
    return None
