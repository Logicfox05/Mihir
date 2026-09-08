"""Data connections (X-Admin-Key): where the PPC order table and the SAP customer Excel come from.

Everything here is stored in the database and applied immediately - no .env edit, no restart.
Passwords are encrypted at rest and never sent back to the browser.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import DEFAULT_COLUMN_MAP, get_settings
from ..jobs import customer_sync, order_refresh, scheduler
from ..services import settings_store as store
from .admin import require_admin

router = APIRouter(prefix="/admin/api/connections", dependencies=[Depends(require_admin)])


class ValuesIn(BaseModel):
    values: dict = {}


class ResetIn(BaseModel):
    keys: list[str] = []


@router.get("")
async def get_connections():
    s = get_settings()
    return {
        "fields": await store.public_view(),
        "column_fields": list(DEFAULT_COLUMN_MAP),
        "required_columns": ["so_no", "customer_name", "real_status"],
        "customers_source_effective": s.customers_source_effective,
        "last_orders_preview": order_refresh.last_preview.to_dict() if order_refresh.last_preview else None,
        "jobs": scheduler.jobs_info(),
        "env_note": "Values shown here come from the dashboard if saved, otherwise from the .env file.",
    }


@router.put("")
async def save_connections(body: ValuesIn):
    errors = await store.save(body.values)
    if errors:
        return {"ok": False, "errors": errors}
    scheduler.reschedule()
    return {"ok": True, "errors": {}, "fields": await store.public_view(), "jobs": scheduler.jobs_info()}


@router.post("/reset")
async def reset_connections(body: ResetIn):
    await store.reset(body.keys or None)
    scheduler.reschedule()
    return {"ok": True, "fields": await store.public_view()}


@router.post("/orders/test")
async def test_orders(body: ValuesIn):
    """Try the order connection with the values currently in the form (nothing is saved)."""
    try:
        draft = store.draft_settings(body.values)
    except ValueError as e:
        return {"ok": False, "error": str(e), "headers": [], "sample": [], "total_raw": 0, "mapped": 0}
    return (await order_refresh.test_fetch(draft)).to_dict()


@router.post("/customers/test")
async def test_customers(body: ValuesIn):
    """Try the customer Excel connection with the values currently in the form (nothing is saved)."""
    try:
        draft = store.draft_settings(body.values)
    except ValueError as e:
        return {"ok": False, "error": str(e), "headers": [], "sample": [], "accepted": 0, "rejected": 0, "rejected_rows": []}
    return await customer_sync.test_connection(draft)
