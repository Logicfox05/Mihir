"""Go-live checks: is this server actually ready to talk to real customers?

Two entry points over the same rules:
  fatal_problems()  - cheap, no network. Called at start-up; in prod the server refuses to boot.
  run_checks()      - the full list behind the dashboard's "Go live" page, each with the exact fix.

Everything here delegates to the services that already know how to test a connection
(wati.check, order_refresh.test_fetch, customer_sync.test_connection) - nothing is re-implemented,
so the page can never disagree with what the bot really does.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import structlog

from ..config import get_settings

log = structlog.get_logger(__name__)

Status = Literal["pass", "warn", "fail"]

INSECURE_DEFAULTS = {
    "admin_key": "change-me-admin-key",
    "wati_webhook_token": "change-me-webhook-token",
    "support_contact": "[phone/email]",
}
MIN_ADMIN_KEY = 12
MIN_WEBHOOK_TOKEN = 16
DEEP_CHECK_TIMEOUT = 25.0


@dataclass
class Check:
    key: str
    title: str
    status: Status
    detail: str  # what we actually found
    fix: str = ""  # what to do about it (warn / fail only)
    where: str = ""  # where to do it
    group: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "status": self.status, "detail": self.detail,
                "fix": self.fix, "where": self.where, "group": self.group}


# ---------------- start-up guard ----------------
def fatal_problems(s=None) -> list[str]:
    """Configuration that makes a production boot unsafe. [] means safe to start.
    Deliberately no network calls: start-up must not hang because WATI is slow."""
    s = s or get_settings()
    if s.is_dev:
        return []
    problems: list[str] = []
    if s.admin_key == INSECURE_DEFAULTS["admin_key"] or len(s.admin_key) < MIN_ADMIN_KEY:
        problems.append(f"ADMIN_KEY is still the example value or shorter than {MIN_ADMIN_KEY} characters - "
                        "anyone who finds the dashboard could open it. Set a long random value.")
    if s.wati_webhook_token == INSECURE_DEFAULTS["wati_webhook_token"] or len(s.wati_webhook_token) < MIN_WEBHOOK_TOKEN:
        problems.append(f"WATI_WEBHOOK_TOKEN is still the example value or shorter than {MIN_WEBHOOK_TOKEN} characters - "
                        "the webhook is a public URL, so anyone could post fake customer messages. Set a long random value.")
    if s.wati_token and not s.wati_base_url_ok:
        problems.append(s.wati_config_problem)
    if s.support_contact == INSECURE_DEFAULTS["support_contact"] or "XXXX" in s.support_contact:
        problems.append("SUPPORT_CONTACT is still a placeholder, and it is printed to customers in the "
                        "'contact us' and 'could not verify' messages. Set your real number or email.")
    return problems


# ---------------- full readiness ----------------
def _c(checks: list[Check], group: str):
    def add(key, title, status: Status, detail: str, fix: str = "", where: str = "") -> None:
        checks.append(Check(key, title, status, detail, fix, where, group))

    return add


def _security(s, base_url: str) -> list[Check]:
    out: list[Check] = []
    add = _c(out, "Security")
    add("app_mode", "Application mode", "pass" if not s.is_dev else "warn",
        f"APP_MODE={s.app_mode}",
        "Dev mode shows the yellow banner and simulates WhatsApp. Set APP_MODE=prod when you go live." if s.is_dev else "",
        "backend/.env")
    weak_admin = s.admin_key == INSECURE_DEFAULTS["admin_key"] or len(s.admin_key) < MIN_ADMIN_KEY
    add("admin_key", "Dashboard password", "fail" if weak_admin else "pass",
        "still the example value" if s.admin_key == INSECURE_DEFAULTS["admin_key"] else f"{len(s.admin_key)} characters",
        f"Set ADMIN_KEY to a long random value (at least {MIN_ADMIN_KEY} characters)." if weak_admin else "",
        "backend/.env")
    weak_hook = s.wati_webhook_token == INSECURE_DEFAULTS["wati_webhook_token"] or len(s.wati_webhook_token) < MIN_WEBHOOK_TOKEN
    hook_url = f"{base_url.rstrip('/')}/webhook/wati?token={s.wati_webhook_token}" if base_url else "https://<your-domain>/webhook/wati?token=<WATI_WEBHOOK_TOKEN>"
    add("webhook_token", "Webhook token", "fail" if weak_hook else "pass",
        "still the example value" if s.wati_webhook_token == INSECURE_DEFAULTS["wati_webhook_token"] else f"{len(s.wati_webhook_token)} characters",
        (f"Set WATI_WEBHOOK_TOKEN to a long random value (at least {MIN_WEBHOOK_TOKEN} characters), then paste this URL "
         f"into WATI -> Webhooks for 'Message received':\n{hook_url}") if weak_hook
        else f"Webhook URL to use in WATI -> Webhooks (event: Message received):\n{hook_url}",
        "backend/.env, then the WATI portal")
    add("secret_key", "Password encryption key", "pass" if s.secret_key else "warn",
        "SECRET_KEY set in .env" if s.secret_key else "auto-generated file backend/.secret_key",
        "" if s.secret_key else "Fine for one server. Back up backend/.secret_key, or set SECRET_KEY in .env - "
                                "without it, the connection passwords saved in the dashboard must be typed in again.",
        "backend/.env")
    return out


def _whatsapp(s, wati_status: dict | None) -> list[Check]:
    out: list[Check] = []
    add = _c(out, "WhatsApp (WATI)")
    add("wati_token", "WATI token", "pass" if s.wati_token else "fail",
        "set" if s.wati_token else "empty - nothing is sent to WhatsApp",
        "" if s.wati_token else "Copy the API token from WATI -> Settings -> API Docs into WATI_TOKEN.",
        "backend/.env")
    add("wati_base_url", "WATI tenant URL", "pass" if s.wati_base_url_ok else "fail",
        s.wati_base_url,
        "" if s.wati_base_url_ok else "WATI_BASE_URL must end with your own tenant id, e.g. "
                                      "https://live-mt-server.wati.io/123456 (copy it from WATI -> Settings -> API Docs).",
        "backend/.env")
    if wati_status is not None:
        ok = bool(wati_status.get("connected"))
        add("wati_connection", "WATI connection", "pass" if ok else "fail",
            wati_status.get("detail", ""),
            "" if ok else "Fix the token / tenant URL above, then press 'Run the checks again'.",
            "backend/.env")
    bad_support = s.support_contact == INSECURE_DEFAULTS["support_contact"] or "XXXX" in s.support_contact
    add("support_contact", "Support contact", "fail" if bad_support else "pass",
        s.support_contact,
        "Customers are told to contact this. Set SUPPORT_CONTACT to your real number or email." if bad_support else "",
        "backend/.env")
    return out


def _data(s, orders_preview, customers_test, orders_n: int, customers_n: int, stale: bool, conflicts: list[dict], empty_slots: list[str]) -> list[Check]:
    out: list[Check] = []
    add = _c(out, "Order and customer data")
    if orders_preview is not None:
        ok = bool(getattr(orders_preview, "ok", False))
        add("orders_source", "Order table connection", "pass" if ok else "fail",
            f"{getattr(orders_preview, 'source', '')} - {getattr(orders_preview, 'mapped', 0)} rows mapped" if ok
            else str(getattr(orders_preview, "error", "could not read the order table")),
            "" if ok else "Check the source, URL/key and column names, then press 'Test fetch'.",
            "Dashboard -> Data sources")
    add("orders_cached", "Orders loaded", "pass" if orders_n and not stale else ("fail" if not orders_n else "warn"),
        f"{orders_n} rows in the cache" + (" (stale)" if stale and orders_n else ""),
        "No order rows: run 'Refresh orders now'." if not orders_n
        else (f"The cache has not refreshed for over {s.orders_stale_minutes} minutes. Check the order source." if stale else ""),
        "Dashboard -> Data sources")
    if customers_test is not None:
        ok = bool(customers_test.get("ok")) and customers_test.get("accepted", 0) > 0
        add("customers_source", "Customer Excel connection", "pass" if ok else "fail",
            f"{customers_test.get('source', '')} - {customers_test.get('accepted', 0)} usable numbers, {customers_test.get('rejected', 0)} rejected"
            if customers_test.get("ok") else str(customers_test.get("error", "could not read the customer Excel")),
            "" if ok else "Check the file location / Dropbox credentials and the column names.",
            "Dashboard -> Data sources")
    add("customers_imported", "Customers imported", "pass" if customers_n else "fail",
        f"{customers_n} customers",
        "No customers: no one can be verified, so every message gets the 'could not verify' reply. "
        "Run 'Import customers now'." if not customers_n else "",
        "Dashboard -> Data sources")
    add("templates", "Messages and buttons", "fail" if (conflicts or empty_slots) else "pass",
        "; ".join([f"custom reply '{c['title']}' (trigger '{c['trigger']}') blocks the {c['button']} button" for c in conflicts]
                  + [f"'{k}' has no buttons" for k in empty_slots]) or "no conflicts",
        "Rename or remove the trigger word, or add the missing buttons back." if (conflicts or empty_slots) else "",
        "Dashboard -> Messages")
    return out


def _runtime(s, sqlite: bool, jobs: list[dict], queued: int, failed: int, ai_paused: bool, dashboard_built: bool) -> list[Check]:
    out: list[Check] = []
    add = _c(out, "Server")
    add("database", "Database", "warn" if sqlite else "pass",
        "SQLite file" if sqlite else "MySQL",
        "SQLite is fine for one server. Back it up with scripts/backup_db.ps1, or move to MySQL for production." if sqlite else "",
        "backend/.env (DATABASE_URL)")
    names = {j["id"] for j in jobs if j.get("next_run")}
    missing = [j for j in ("customer_sync", "order_refresh") if j not in names]
    add("scheduler", "Background jobs", "fail" if missing else "pass",
        ", ".join(f"{j['id']} next {j['next_run']}" for j in jobs) or "no jobs scheduled",
        f"These jobs are not scheduled: {', '.join(missing)}. Restart the server." if missing else "",
        "server")
    add("queue", "Message queue", "warn" if (queued > 20 or failed) else "pass",
        f"{queued} waiting, {failed} failed",
        "Messages are piling up or failing - open Chat log and check the errors." if (queued > 20 or failed) else "",
        "Dashboard -> Chat log")
    add("voice_notes", "Voice notes", "pass" if (s.voice_notes and s.groq_api_key) else "warn",
        "on" if (s.voice_notes and s.groq_api_key) else ("on, but GROQ_API_KEY is missing" if s.voice_notes else "off"),
        "" if (s.voice_notes and s.groq_api_key) else
        ("Set GROQ_API_KEY or switch voice notes off - right now a voice note gets the 'please type' reply."
         if s.voice_notes else "Customers who send a voice note are asked to type instead. Set GROQ_API_KEY and turn "
                               "voice notes on in Settings -> Conversation to accept them."),
        "Dashboard -> Settings")
    add("openai", "Smart text understanding", "pass" if (s.openai_api_key and not ai_paused) else "warn",
        "on" if (s.openai_api_key and not ai_paused) else ("paused after repeated failures" if s.openai_api_key else "off"),
        "" if (s.openai_api_key and not ai_paused) else
        "Optional. Buttons, order numbers and item codes all work without it; only unusual free text is understood less well.",
        "backend/.env (OPENAI_API_KEY)")
    add("alerts", "Failure alerts", "pass" if s.alert_slack_webhook else "warn",
        "Slack webhook set" if s.alert_slack_webhook else "dashboard only",
        "" if s.alert_slack_webhook else "Set ALERT_SLACK_WEBHOOK to be told about failures without opening the dashboard.",
        "backend/.env")
    add("dashboard_built", "Dashboard build", "pass" if dashboard_built else "warn",
        "built" if dashboard_built else "not built",
        "" if dashboard_built else "Run `npm run build` in the dashboard folder.",
        "dashboard/")
    return out


async def _safe(coro, label: str):
    """Never let one slow or broken connection stop the page from rendering."""
    try:
        return await asyncio.wait_for(coro, timeout=DEEP_CHECK_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        log.warning("readiness_check_failed", check=label, error=str(e))
        return e


async def run_checks(deep: bool = True, base_url: str = "") -> dict:
    """Every go-live check. `deep` also tests the live connections (WATI, orders, customer Excel)."""
    from sqlalchemy import func, select

    from ..db import is_sqlite, session_scope
    from ..jobs import customer_sync, order_refresh, scheduler
    from ..models import InboundQueue
    from ..routers.health import status_payload
    from . import intent, templates
    from .wati import wati

    s = get_settings()
    wati_status = orders_preview = customers_test = None
    if deep:
        wati_status, orders_preview, customers_test = await asyncio.gather(
            _safe(wati.check(), "wati"),
            _safe(order_refresh.test_fetch(), "orders"),
            _safe(customer_sync.test_connection(s), "customers"),
        )
        if isinstance(wati_status, Exception):
            wati_status = {"connected": False, "detail": f"check failed: {wati_status}"}
        if isinstance(orders_preview, Exception):
            orders_preview = None
        if isinstance(customers_test, Exception):
            customers_test = {"ok": False, "error": str(customers_test)}

    health = await status_payload()
    orders_n = await order_refresh.count()
    customers_n = await customer_sync.count()
    async with session_scope() as db:
        queued = await db.scalar(select(func.count()).select_from(InboundQueue).where(InboundQueue.status.in_(("queued", "processing")))) or 0
        failed = await db.scalar(select(func.count()).select_from(InboundQueue).where(InboundQueue.status == "failed")) or 0

    empty_slots = [k for k, slot in templates.BUTTON_SLOTS.items() if slot.min_count and not templates.registry.buttons(k)]
    dashboard_built = (Path(__file__).resolve().parent.parent / "static" / "admin" / "index.html").exists()

    checks = (
        _security(s, base_url)
        + _whatsapp(s, wati_status)
        + _data(s, orders_preview, customers_test, orders_n, customers_n, bool(health.get("orders_stale")),
                templates.audit_custom_conflicts(), empty_slots)
        + _runtime(s, is_sqlite(), scheduler.jobs_info(), int(queued), int(failed), intent.breaker_open(), dashboard_built)
    )
    counts = {st: sum(1 for c in checks if c.status == st) for st in ("pass", "warn", "fail")}
    return {
        "ready": counts["fail"] == 0,
        "mode": s.app_mode,
        "deep": deep,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "checks": [c.to_dict() for c in checks],
    }
