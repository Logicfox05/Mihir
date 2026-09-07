from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select, text

from ..config import get_settings
from ..db import session_scope
from ..models import OrderCache, SyncRun, utcnow

router = APIRouter()


async def status_payload() -> dict:
    s = get_settings()
    db_ok = True
    last_customers = last_orders = None
    orders_fetched = None
    try:
        async with session_scope() as db:
            await db.execute(text("SELECT 1"))
            last_customers = await db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.kind == "customers", SyncRun.ok.is_(True)))
            last_orders = await db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.kind == "orders", SyncRun.ok.is_(True)))
            orders_fetched = await db.scalar(select(func.max(OrderCache.fetched_at)))
    except Exception:  # noqa: BLE001
        db_ok = False
    stale = orders_fetched is None or (utcnow() - orders_fetched) > timedelta(minutes=s.orders_stale_minutes)
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "mode": s.app_mode,
        "wati_mocked": s.wati_mocked,
        "orders_source": s.orders_source,
        "last_customer_sync": last_customers.isoformat() if last_customers else None,
        "last_order_refresh": last_orders.isoformat() if last_orders else None,
        "orders_fetched_at": orders_fetched.isoformat() if orders_fetched else None,
        "orders_stale": stale,
        "time": utcnow().isoformat(),
    }


@router.get("/health")
async def health():
    return await status_payload()
