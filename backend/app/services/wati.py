"""WATI client: session text, interactive reply buttons, interactive list, media download.

Verified against WATI's OpenAPI (docs.wati.io, 2026):
  POST /api/v1/sendSessionMessage/{whatsappNumber}?messageText=...
  POST /api/v1/sendInteractiveButtonsMessage?whatsappNumber=...   body {header?{type:"Text",text}, body, footer?, buttons[{text}]}
  POST /api/v1/sendInteractiveListMessage?whatsappNumber=...      body {header, body, footer, buttonText, sections[{title, rows[{title, description}]}]}
  GET  /api/v1/getMedia?fileName=...
  Responses: {"ok": true} on success, {"ok": false, "result": "<error>"} on failure (HTTP 200 is possible either way).
  Optional (WATI_API_VERSION=v3): POST /api/ext/v3/conversations/messages/interactive  body {target, type, list_message|button_message}

Dry-run (mock) mode when no token: nothing leaves the server; every send is recorded in an
in-memory outbox (shown in the dashboard) and, by the processor, in message_log.
Interactive sends fall back to plain text (with the options listed) if WATI rejects them, so the
customer can always answer by typing.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings
from .menus import BODY_MAX, FOOTER_MAX, HEADER_MAX, Options

log = structlog.get_logger(__name__)

V1_BUTTONS = "/api/v1/sendInteractiveButtonsMessage"
V1_LIST = "/api/v1/sendInteractiveListMessage"
V3_INTERACTIVE = "/api/ext/v3/conversations/messages/interactive"


class WatiError(Exception):
    """Transient (retryable) WATI failure."""


class WatiRejected(Exception):
    """WATI answered but refused the message (4xx or ok=false). Not retried."""


class WatiClient:
    def __init__(self) -> None:
        self.outbox: deque[dict] = deque(maxlen=500)

    # ---- helpers ----
    @property
    def mocked(self) -> bool:
        return get_settings().wati_mocked

    def _headers(self) -> dict[str, str]:
        tok = get_settings().wati_token.strip()
        if tok and not tok.lower().startswith("bearer "):
            tok = f"Bearer {tok}"
        return {"Authorization": tok, "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return get_settings().wati_base_url.rstrip("/") + path

    def _record(self, phone: str, text: str, kind: str = "text", extra: dict | None = None) -> dict:
        item = {"phone": phone, "text": text, "kind": kind, "at": datetime.now(timezone.utc).isoformat(), **(extra or {})}
        self.outbox.append(item)
        return item

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=5), retry=retry_if_exception_type(WatiError), reraise=True)
    async def _post(self, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(self._url(path), headers=self._headers(), params=params, json=json)
        except httpx.HTTPError as e:
            raise WatiError(str(e)) from e
        if r.status_code >= 500 or r.status_code == 429:
            raise WatiError(f"wati {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise WatiRejected(f"wati {r.status_code}: {r.text[:300]}")
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        if isinstance(data, dict) and data.get("ok") is False:
            raise WatiRejected(f"wati ok=false: {data.get('result') or data.get('info') or data.get('message') or data}")
        return data if isinstance(data, dict) else {"raw": data}

    # ---- payload builders (pure; unit-tested) ----
    @staticmethod
    def buttons_payload(body: str, options: Options) -> dict:
        payload: dict = {"body": body[:BODY_MAX], "buttons": [{"text": o.title} for o in options.items[:3]]}
        if options.header:
            payload["header"] = {"type": "Text", "text": options.header[:HEADER_MAX]}
        if options.footer:
            payload["footer"] = options.footer[:FOOTER_MAX]
        return payload

    @staticmethod
    def list_payload(body: str, options: Options) -> dict:
        rows = [{"title": o.title, "description": o.description} for o in options.items[:10]]
        return {
            "header": options.header[:HEADER_MAX],
            "body": body[:BODY_MAX],
            "footer": options.footer[:FOOTER_MAX],
            "buttonText": options.button_text or "Select",
            "sections": [{"title": options.section_title or "Options", "rows": rows}],
        }

    @classmethod
    def v3_payload(cls, phone: str, body: str, options: Options) -> dict:
        """WATI API v3 (/api/ext/v3/conversations/messages/interactive): recipient in the body as `target`."""
        if options.kind == "buttons":
            return {"target": phone, "type": "buttons", "button_message": cls.buttons_payload(body, options)}
        p = cls.list_payload(body, options)
        return {
            "target": phone,
            "type": "list",
            "list_message": {"header": p["header"], "body": p["body"], "footer": p["footer"], "button_text": p["buttonText"], "sections": p["sections"]},
        }

    async def _send_interactive(self, phone: str, body: str, options: Options) -> dict:
        s = get_settings()
        if s.wati_api_version == "v3":
            return await self._post(V3_INTERACTIVE, json=self.v3_payload(phone, body, options))
        path = V1_BUTTONS if options.kind == "buttons" else V1_LIST
        payload = self.buttons_payload(body, options) if options.kind == "buttons" else self.list_payload(body, options)
        return await self._post(path, params={"whatsappNumber": phone}, json=payload)

    # ---- API ----
    async def send_text(self, phone: str, text: str) -> dict:
        if self.mocked:
            log.info("wati_mock_send", phone=phone, text=text)
            return self._record(phone, text)
        data = await self._post(f"/api/v1/sendSessionMessage/{phone}", params={"messageText": text})
        self._record(phone, text, extra={"sent": True})
        return data

    async def send_buttons(self, phone: str, body: str, options: Options) -> dict:
        if self.mocked:
            log.info("wati_mock_send_buttons", phone=phone, text=body, buttons=options.titles())
            return self._record(phone, body, kind="buttons", extra={"options": options.to_dict()})
        try:
            data = await self._send_interactive(phone, body, options)
            self._record(phone, body, kind="buttons", extra={"options": options.to_dict(), "sent": True})
            return data
        except Exception as e:  # noqa: BLE001 - never leave the customer without a way to answer
            log.warning("wati_buttons_failed_fallback_text", error=str(e))
            return await self.send_text(phone, body + "\n\n" + options.as_text())

    async def send_list(self, phone: str, body: str, options: Options) -> dict:
        if self.mocked:
            log.info("wati_mock_send_list", phone=phone, text=body, rows=options.titles())
            return self._record(phone, body, kind="list", extra={"options": options.to_dict()})
        try:
            data = await self._send_interactive(phone, body, options)
            self._record(phone, body, kind="list", extra={"options": options.to_dict(), "sent": True})
            return data
        except Exception as e:  # noqa: BLE001
            log.warning("wati_list_failed_fallback_text", error=str(e))
            return await self.send_text(phone, body + "\n\n" + options.as_text())

    async def send_options(self, phone: str, body: str, options: Options | None) -> dict:
        """Dispatch: buttons / list / plain text."""
        if options is None or not options.items:
            return await self.send_text(phone, body)
        if options.kind == "buttons":
            return await self.send_buttons(phone, body, options)
        return await self.send_list(phone, body, options)

    async def check(self) -> dict:
        """Is the WATI connection usable? Calls a harmless read endpoint to prove the token works.
        Never raises - the dashboard shows whatever comes back."""
        st = get_settings()
        if self.mocked:
            return {"connected": False, "mocked": True, "detail": "No WATI token set - messages are simulated, nothing is sent to WhatsApp.",
                    "base_url": st.wati_base_url, "api_version": st.wati_api_version}
        base = {"mocked": False, "base_url": st.wati_base_url, "api_version": st.wati_api_version}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(self._url("/api/v1/getContacts"), headers=self._headers(), params={"pageSize": 1, "pageNumber": 1})
        except httpx.HTTPError as e:
            return {**base, "connected": False, "detail": f"Cannot reach WATI: {e}"}
        if r.status_code in (401, 403):
            return {**base, "connected": False, "detail": "WATI rejected the token (401/403). Check WATI_TOKEN in .env."}
        if r.status_code == 404:
            return {**base, "connected": False, "detail": "Endpoint not found (404). Check WATI_BASE_URL - it must include your tenant id."}
        if r.status_code >= 400:
            return {**base, "connected": False, "detail": f"WATI returned {r.status_code}: {r.text[:200]}"}
        return {**base, "connected": True, "detail": "Token accepted by WATI. Messages you save here are sent to customers through this connection."}

    async def get_media(self, file_name: str) -> bytes:
        if self.mocked:
            fixture = get_settings().resolve_path("fixtures/voice_sample.ogg")
            return fixture.read_bytes() if fixture.exists() else b""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(self._url("/api/v1/getMedia"), headers=self._headers(), params={"fileName": file_name})
        except httpx.HTTPError as e:
            raise WatiError(str(e)) from e
        if r.status_code != 200:
            raise WatiError(f"getMedia {r.status_code}")
        return r.content


wati = WatiClient()
