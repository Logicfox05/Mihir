"""Local file source (any format). Default in dev; also handy for manual drops."""
from __future__ import annotations

import asyncio

from .orders_base import FetchResult
from .parsers import detect_format, parse


class FileSource:
    def __init__(self, settings, path: str | None = None) -> None:
        self.settings = settings
        self.path = settings.resolve_path(path or settings.orders_file_path)

    def describe(self) -> str:
        return f"file {self.path}"

    async def fetch(self) -> FetchResult:
        body = await asyncio.to_thread(self.path.read_bytes)
        fmt = self.settings.orders_format
        if fmt == "auto":
            fmt = detect_format(None, self.path.name, body)
        rows = await asyncio.to_thread(parse, body, fmt, self.settings.orders_sheet or None)
        return FetchResult(rows, f"{self.describe()} ({fmt})")
