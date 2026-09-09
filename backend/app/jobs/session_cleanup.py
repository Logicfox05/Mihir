"""Reset sessions idle longer than SESSION_TIMEOUT_MIN."""
from __future__ import annotations

from datetime import timedelta

import structlog
from sqlalchemy import update

from ..config import get_settings
from ..db import session_scope
from ..models import Session, utcnow

log = structlog.get_logger(__name__)


async def run() -> int:
    cutoff = utcnow() - timedelta(minutes=get_settings().session_timeout_min)
    async with session_scope() as db:
        res = await db.execute(
            update(Session)
            .where(Session.updated_at < cutoff, Session.step != "START")
            .values(step="START", so_no=None, po_no=None, fg_code=None, pending_value=None, pending_kind=None, attempts=0, lang_chosen=False)
        )
        n = res.rowcount or 0
    if n:
        log.info("sessions_reset", count=n)
    return n
