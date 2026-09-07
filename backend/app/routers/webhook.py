"""POST /webhook/wati — validate token, dedup, enqueue, return 200 fast."""
from __future__ import annotations

import hmac
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..jobs import queue_worker
from ..models import InboundQueue, MessageLog
from ..services.processor import extract_message

log = structlog.get_logger(__name__)
router = APIRouter()

IGNORED_EVENTS = {"sentMessageDELIVERED", "sentMessageREAD", "sentMessageREPLIED", "templateMessageSent", "sessionMessageSent", "message_sent"}


async def enqueue(db: AsyncSession, payload: dict) -> dict:
    """Shared by the webhook and the simulator. Returns {"status": ..., "queue_id": ...}."""
    if payload.get("owner") is True or payload.get("eventType") in IGNORED_EVENTS:
        return {"status": "ignored", "reason": "not a customer message"}
    phone, msg_type, text, media = extract_message(payload)
    if not phone:
        return {"status": "ignored", "reason": "no waId"}
    msg_id = str(payload.get("id") or payload.get("whatsappMessageId") or "").strip() or None

    row = MessageLog(wati_msg_id=msg_id, phone_e164=phone, direction="in", msg_type=msg_type, text=text if msg_type == "text" else (text or media))
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        log.info("webhook_duplicate", wati_msg_id=msg_id, phone_e164=phone)
        return {"status": "duplicate", "wati_msg_id": msg_id}
    q = InboundQueue(message_log_id=row.id, phone_e164=phone, payload=json.dumps(payload, ensure_ascii=False))
    db.add(q)
    await db.commit()
    queue_worker.wake.set()
    return {"status": "queued", "queue_id": q.id, "message_log_id": row.id}


@router.post("/webhook/wati")
async def wati_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    s = get_settings()
    token = request.query_params.get("token", "")
    if not s.wati_webhook_token or not hmac.compare_digest(token, s.wati_webhook_token):
        raise HTTPException(status_code=401, detail="bad token")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="expected object")
    result = await enqueue(db, payload)
    return {"ok": True, **result}
