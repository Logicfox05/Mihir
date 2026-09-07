"""Direct SQL source when the 'API' is really a database query (MySQL / MSSQL / Postgres)."""
from __future__ import annotations

import asyncio

from sqlalchemy import create_engine, text

from .orders_base import FetchResult


class SqlSource:
    def __init__(self, settings) -> None:
        self.settings = settings

    def describe(self) -> str:
        url = self.settings.orders_sql_url
        safe = url.split("@")[-1] if "@" in url else url
        return f"sql {safe}"

    def _run(self) -> list[dict]:
        s = self.settings
        if not s.orders_sql_url or not s.orders_sql_query:
            raise RuntimeError("ORDERS_SQL_URL / ORDERS_SQL_QUERY not set")
        engine = create_engine(s.orders_sql_url, pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                res = conn.execute(text(s.orders_sql_query))
                cols = list(res.keys())
                return [dict(zip(cols, row)) for row in res.fetchall()]
        finally:
            engine.dispose()

    async def fetch(self) -> FetchResult:
        rows = await asyncio.to_thread(self._run)
        return FetchResult(rows, f"{self.describe()} ({len(rows)} rows)")
