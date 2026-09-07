"""Customer sync: SAP B1 Excel (Dropbox or local file) -> normalize -> replace `customers`."""
from __future__ import annotations

import asyncio
import json

import structlog
from sqlalchemy import delete, select

from ..adapters.orders_base import resolve_headers
from ..adapters.parsers import excel_table
from ..config import get_settings
from ..db import session_scope
from ..models import Customer, SyncRun, utcnow
from ..services import alerts
from ..utils.phone import normalize_phone

log = structlog.get_logger(__name__)

_lock = asyncio.Lock()


def _download_dropbox() -> bytes:
    import dropbox

    s = get_settings()
    dbx = dropbox.Dropbox(app_key=s.dropbox_app_key, app_secret=s.dropbox_app_secret, oauth2_refresh_token=s.dropbox_refresh_token)
    _, res = dbx.files_download(s.dropbox_file_path)
    return res.content


def _resolve(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    s = get_settings()
    cmap = {"so_no": s.customers_col_contact, "customer_name": s.customers_col_name, "real_status": s.customers_col_code}
    # reuse the generic resolver: treat contact as "required so_no", name required, code as required real_status
    resolved, warnings, missing = resolve_headers(headers, cmap)
    if missing:
        names = {"so_no": s.customers_col_contact, "customer_name": s.customers_col_name, "real_status": s.customers_col_code}
        raise ValueError("missing column(s): " + ", ".join(names[m] for m in missing) + f". Headers seen: {headers}")
    return {"contact": resolved["so_no"], "name": resolved["customer_name"], "code": resolved["real_status"]}, warnings


def parse_customers(body: bytes) -> tuple[list[Customer], list[dict], list[str], list[str]]:
    """Returns (accepted, rejected_rows, headers, warnings)."""
    raw = excel_table.parse(body)
    headers: list[str] = []
    for r in raw:
        for k in r:
            if k not in headers:
                headers.append(k)
    cols, warnings = _resolve(headers)
    accepted: list[Customer] = []
    rejected: list[dict] = []
    seen: dict[str, str] = {}
    for i, r in enumerate(raw, start=2):  # Excel row number (1 = header)
        raw_contact = r.get(cols["contact"])
        name = r.get(cols["name"])
        code = r.get(cols["code"])
        name_s = None if name is None else str(name)  # EXACT, no strip
        if isinstance(code, float) and code.is_integer():
            code = int(code)
        code_s = None if code is None else str(code).strip()
        pr = normalize_phone(raw_contact)
        if not pr.ok:
            rejected.append({"row": i, "contact": str(raw_contact), "name": name_s, "code": code_s, "reason": f"invalid phone: {pr.reason}"})
            continue
        if not name_s or not name_s.strip():
            rejected.append({"row": i, "contact": str(raw_contact), "name": name_s, "code": code_s, "reason": "empty customer name"})
            continue
        if pr.phone in seen:
            rejected.append({"row": i, "contact": str(raw_contact), "name": name_s, "code": code_s, "reason": f"duplicate phone {pr.phone} (already used by '{seen[pr.phone]}')"})
            continue
        seen[pr.phone] = name_s
        accepted.append(Customer(phone_e164=pr.phone, customer_code=code_s, customer_name=name_s, raw_contact=str(raw_contact)))
    return accepted, rejected, headers, warnings


async def run(file_bytes: bytes | None = None, source_desc: str | None = None) -> SyncRun:
    s = get_settings()
    async with _lock:
        run_row = SyncRun(kind="customers", started_at=utcnow())
        try:
            if file_bytes is None:
                if s.dropbox_configured:
                    file_bytes = await asyncio.to_thread(_download_dropbox)
                    source_desc = f"dropbox {s.dropbox_file_path}"
                else:
                    path = s.resolve_path(s.customers_file_path)
                    file_bytes = await asyncio.to_thread(path.read_bytes)
                    source_desc = f"file {path}"
            run_row.source = source_desc
            accepted, rejected, headers, warnings = await asyncio.to_thread(parse_customers, file_bytes)
            run_row.total_rows = len(accepted) + len(rejected)
            run_row.accepted = len(accepted)
            run_row.rejected = len(rejected)
            run_row.rejected_rows = json.dumps(rejected, ensure_ascii=False)
            run_row.raw_headers = json.dumps(headers, ensure_ascii=False)
            run_row.warnings = json.dumps(warnings, ensure_ascii=False)
            if not accepted:
                raise ValueError("no valid customer rows; keeping existing customers table")
            async with session_scope() as db:
                await db.execute(delete(Customer))
                db.add_all(accepted)
                run_row.ok = True
                run_row.finished_at = utcnow()
                db.add(run_row)
            if rejected:
                await alerts.notify("Customer import: rejected rows", json.dumps(rejected, ensure_ascii=False)[:1500], level="warning")
            log.info("customer_sync_done", accepted=len(accepted), rejected=len(rejected))
        except Exception as e:  # noqa: BLE001
            run_row.ok = False
            run_row.error = str(e)
            run_row.finished_at = utcnow()
            async with session_scope() as db:
                db.add(run_row)
            log.error("customer_sync_failed", error=str(e))
            await alerts.notify("Customer sync failed", str(e))
        return run_row


async def count() -> int:
    from sqlalchemy import func

    async with session_scope() as db:
        return (await db.scalar(select(func.count(Customer.phone_e164)))) or 0
