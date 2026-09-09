"""Operational alerts: Slack incoming webhook if configured, always structured log."""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

import httpx
import structlog

from ..config import get_settings

log = structlog.get_logger(__name__)

recent: deque[dict] = deque(maxlen=100)
_last_sent: dict[str, float] = {}


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


async def notify_throttled(key: str, title: str, detail: str = "", level: str = "error", min_interval_s: int = 300) -> bool:
    """At most one alert per `key` per interval. An outage sends one message per customer otherwise,
    which buries the alert it is trying to raise. Returns True when the alert was actually sent."""
    now = time.monotonic()
    last = _last_sent.get(key)
    if last is not None and now - last < min_interval_s:
        return False
    _last_sent[key] = now
    await notify(title, detail, level)
    return True


def reset_throttle() -> None:
    """Tests only: forget when each key last fired."""
    _last_sent.clear()
