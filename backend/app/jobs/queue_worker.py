"""DB-backed inbound queue worker. No Redis. Survives restarts.

Claim is a single UPDATE that only succeeds for one worker, portable across MySQL and SQLite.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import structlog
from sqlalchemy import select, text, update

from ..config import get_settings
from ..db import session_scope
from ..models import InboundQueue, utcnow
from ..services import alerts
from ..services.processor import process_payload

log = structlog.get_logger(__name__)

wake = asyncio.Event()
_stop = asyncio.Event()
MAX_ATTEMPTS = 3
STUCK_AFTER = timedelta(minutes=5)


async def _claim() -> InboundQueue | None:
    """Take the oldest waiting item. The conditional UPDATE is the lock: only the process whose
    UPDATE actually changed a row owns that id, so two workers can never claim the same message."""
    for _ in range(5):  # a lost race just means someone else took that one; try the next
        async with session_scope() as db:
            row_id = await db.scalar(select(InboundQueue.id).where(InboundQueue.status == "queued").order_by(InboundQueue.id).limit(1))
            if row_id is None:
                return None
            res = await db.execute(
                update(InboundQueue)
                .where(InboundQueue.id == row_id, InboundQueue.status == "queued")
                .values(status="processing", attempts=InboundQueue.attempts + 1, updated_at=utcnow())
            )
            if res.rowcount:
                return await db.get(InboundQueue, row_id)
    return None


async def _process(item: InboundQueue) -> None:
    payload = json.loads(item.payload)
    limit = get_settings().queue_item_timeout_sec
    try:
        # One slow WhatsApp or speech-to-text call must never hold up every other customer behind it.
        async with session_scope() as db:
            await asyncio.wait_for(process_payload(db, payload, message_log_id=item.message_log_id), timeout=limit)
        async with session_scope() as db:
            await db.execute(update(InboundQueue).where(InboundQueue.id == item.id).values(status="done", error=None, updated_at=utcnow()))
    except Exception as e:  # noqa: BLE001
        err = f"timed out after {limit}s" if isinstance(e, asyncio.TimeoutError) else str(e)
        log.error("queue_item_failed", id=item.id, error=err)
        if isinstance(e, asyncio.TimeoutError):
            await alerts.notify_throttled("queue_timeout", "A customer message took too long to handle", err, level="warning")
        async with session_scope() as db:
            status = "failed" if item.attempts >= MAX_ATTEMPTS else "queued"
            await db.execute(update(InboundQueue).where(InboundQueue.id == item.id).values(status=status, error=err[:2000], updated_at=utcnow()))


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
