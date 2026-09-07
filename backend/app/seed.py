"""python -m app.seed  -> create tables, import dummy customers + orders, print test pairs."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from .config import get_settings
from .db import dispose_db, init_db, session_scope
from .jobs import customer_sync, order_refresh
from .logging_setup import setup_logging
from .models import Customer, OrderCache


async def main() -> None:
    setup_logging()
    s = get_settings()
    print(f"mode={s.app_mode}  db={s.database_url}  orders_source={s.orders_source}  wati_mocked={s.wati_mocked}")
    await init_db()
    c = await customer_sync.run()
    print(f"customers: ok={c.ok} total={c.total_rows} accepted={c.accepted} rejected={c.rejected} {c.error or ''}")
    if c.rejected_rows and c.rejected_rows != "[]":
        print("  rejected:", c.rejected_rows)
    o = await order_refresh.run()
    print(f"orders:    ok={o.ok} total={o.total_rows} accepted={o.accepted} {o.error or ''}")
    async with session_scope() as db:
        customers = (await db.execute(select(Customer).order_by(Customer.customer_code))).scalars().all()
        orders = (await db.execute(select(OrderCache).order_by(OrderCache.so_no, OrderCache.fg_item_code))).scalars().all()
    print("\nTest pairs (phone -> SO numbers whose API name matches byte-exactly):")
    for cu in customers:
        sos = sorted({r.so_no for r in orders if r.customer_name == cu.customer_name})
        near = sorted({r.so_no for r in orders if r.customer_name != cu.customer_name and r.customer_name.strip().casefold() == cu.customer_name.strip().casefold()})
        extra = f"   (mismatch-only SOs: {', '.join(near)})" if near else ""
        print(f"  {cu.phone_e164}  {cu.customer_name!r:32} -> {', '.join(sos) or '-'}{extra}")
    print("\nOrders:")
    for r in orders:
        print(f"  SO {r.so_no:8} PO {r.po_no or '-':9} FG {r.fg_item_code or '-':8} {r.customer_name!r:32} real_status={r.real_status!r}")
    await dispose_db()


if __name__ == "__main__":
    asyncio.run(main())
