"""Operational alerts: Slack incoming webhook if configured, always structured log."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import httpx
import structlog

from ..config import get_settings

log = structlog.get_logger(__name__)

recent: deque[dict] = deque(maxlen=100)


async def notify(title: str, detail: str = "", level: str = "error") -> None:
    item = {"title": title, "detail": detail[:2000], "level": level, "at": datetime.now(timezone.utc).isoformat()}
    recent.append(item)
    log.log(40 if level == "error" else 30, "alert", title=title, detail=detail[:500])
    url = get_settings().alert_slack_webhook
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"text": f"[{level.upper()}] {title}\n{detail[:1500]}"})
    except Exception as e:  # noqa: BLE001
        log.warning("alert_delivery_failed", error=str(e))
