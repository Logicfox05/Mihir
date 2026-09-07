"""HTTP source: endpoint + API key, body is a table in any format."""
from __future__ import annotations

import asyncio
import json

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .orders_base import FetchResult
from .parsers import detect_format, parse


class OrdersApiError(Exception):
    pass


class HttpSource:
    def __init__(self, settings) -> None:
        self.settings = settings

    def describe(self) -> str:
        return f"http {self.settings.orders_api_method} {self.settings.orders_api_url}"

    def _auth(self) -> tuple[dict, dict]:
        s = self.settings
        headers: dict[str, str] = {"Accept": "application/json, text/csv, text/html, */*"}
        params: dict[str, str] = {}
        if s.orders_api_key:
            if s.orders_api_key_in == "bearer":
                headers["Authorization"] = f"Bearer {s.orders_api_key}"
            elif s.orders_api_key_in == "query":
                params[s.orders_api_key_name or "apikey"] = s.orders_api_key
            else:
                headers[s.orders_api_key_name or "X-API-Key"] = s.orders_api_key
        return headers, params

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), retry=retry_if_exception_type(OrdersApiError), reraise=True)
    async def _download(self) -> tuple[bytes, str | None]:
        s = self.settings
        if not s.orders_api_url:
            raise RuntimeError("ORDERS_API_URL is empty")
        headers, params = self._auth()
        body_arg: dict = {}
        if s.orders_api_method == "POST" and s.orders_api_body:
            try:
                body_arg = {"json": json.loads(s.orders_api_body)}
            except ValueError:
                body_arg = {"content": s.orders_api_body}
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                r = await client.request(s.orders_api_method, s.orders_api_url, headers=headers, params=params, **body_arg)
        except httpx.HTTPError as e:
            raise OrdersApiError(str(e)) from e
        if r.status_code >= 500 or r.status_code == 429:
            raise OrdersApiError(f"orders api {r.status_code}")
        if r.status_code >= 400:
            raise RuntimeError(f"orders api {r.status_code}: {r.text[:300]}")
        return r.content, r.headers.get("content-type")

    async def fetch(self) -> FetchResult:
        body, ctype = await self._download()
        fmt = self.settings.orders_format
        if fmt == "auto":
            fmt = detect_format(ctype, self.settings.orders_api_url, body)
        rows = await asyncio.to_thread(parse, body, fmt, self.settings.orders_sheet or None)
        return FetchResult(rows, f"{self.describe()} ({fmt}, {len(body)} bytes)")
