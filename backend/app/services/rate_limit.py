"""Per-phone rate limit: max N inbound messages per window (DB-counted, no Redis)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import MessageLog, utcnow


async def check(db: AsyncSession, phone: str) -> tuple[bool, bool]:
    """Returns (allowed, just_exceeded). just_exceeded is True only on the first blocked message."""
    s = get_settings()
    since = utcnow() - timedelta(minutes=s.rate_limit_window_min)
    n = await db.scalar(
        select(func.count(MessageLog.id)).where(
            MessageLog.phone_e164 == phone, MessageLog.direction == "in", MessageLog.created_at >= since
        )
    )
    n = n or 0
    if n <= s.rate_limit_msgs:
        return True, False
    return False, n == s.rate_limit_msgs + 1
