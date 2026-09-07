"""Application settings. Every secret and tunable comes from environment / .env."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent

DEFAULT_COLUMN_MAP = {
    "so_no": "SO No",
    "po_no": "PO No",
    "fg_item_code": "FG Item Code",
    "customer_name": "Customer Name",
    "connection_status": "Connection Status",
    "real_status": "Real Status (PPC)",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_mode: Literal["dev", "prod"] = "dev"
    database_url: str = "sqlite+aiosqlite:///./order_bot.db"
    log_level: str = "INFO"

    admin_key: str = "change-me-admin-key"
    support_contact: str = "[phone/email]"

    # WATI
    wati_base_url: str = "https://live-mt-server.wati.io/tenant"
    wati_token: str = ""
    wati_webhook_token: str = "change-me-webhook-token"
    wati_dry_run: bool | None = None  # None = auto (true when token empty)
    wati_api_version: Literal["v1", "v3"] = "v1"  # interactive (list/buttons) endpoints: v1 = documented default, v3 = /api/ext/v3

    # AI
    groq_api_key: str = ""
    groq_stt_model: str = "whisper-large-v3-turbo"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Customers
    dropbox_app_key: str = ""
    dropbox_app_secret: str = ""
    dropbox_refresh_token: str = ""
    dropbox_file_path: str = "/SAP/customers.xlsx"
    customers_file_path: str = "fixtures/customers_dummy.xlsx"
    customers_col_code: str = "Customer Code"
    customers_col_name: str = "Customer Name"
    customers_col_contact: str = "Contact"
    customer_sync_cron: str = "10 6 * * *"

    # Orders source
    orders_source: Literal["file", "http", "sql"] = "file"
    orders_file_path: str = "fixtures/orders_dummy.json"
    orders_api_url: str = ""
    orders_api_method: Literal["GET", "POST"] = "GET"
    orders_api_key: str = ""
    orders_api_key_in: Literal["header", "query", "bearer"] = "header"
    orders_api_key_name: str = "X-API-Key"
    orders_api_body: str = ""
    orders_format: Literal["auto", "json", "csv", "xlsx", "html"] = "auto"
    orders_sheet: str = ""
    orders_sql_url: str = ""
    orders_sql_query: str = ""
    orders_column_map: dict[str, str] = DEFAULT_COLUMN_MAP.copy()
    order_refresh_minutes: int = 5
    orders_stale_minutes: int = 30

    # Session / limits
    session_timeout_min: int = 15
    fg_max_attempts: int = 2
    rate_limit_msgs: int = 20
    rate_limit_window_min: int = 10

    # Alerts
    alert_slack_webhook: str = ""

    @field_validator("wati_dry_run", mode="before")
    @classmethod
    def _empty_bool(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("orders_column_map", mode="before")
    @classmethod
    def _parse_map(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return DEFAULT_COLUMN_MAP.copy()
            return json.loads(v)
        return v

    # ---- derived ----
    @property
    def is_dev(self) -> bool:
        return self.app_mode == "dev"

    @property
    def wati_mocked(self) -> bool:
        if self.wati_dry_run is not None:
            return self.wati_dry_run
        return not self.wati_token

    @property
    def dropbox_configured(self) -> bool:
        return bool(self.dropbox_app_key and self.dropbox_app_secret and self.dropbox_refresh_token)

    def resolve_path(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else BACKEND_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
