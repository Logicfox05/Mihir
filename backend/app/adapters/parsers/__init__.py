"""Table parsers: any of JSON / CSV / XLSX / HTML -> list[dict] keyed by header."""
from __future__ import annotations

from . import csv_table, excel_table, html_table, json_table

FORMATS = ("json", "csv", "xlsx", "html")


def detect_format(content_type: str | None, name: str | None, body: bytes) -> str:
    ct = (content_type or "").lower()
    if "json" in ct:
        return "json"
    if "spreadsheetml" in ct or "ms-excel" in ct or "octet-stream" in ct and (name or "").lower().endswith((".xlsx", ".xls")):
        return "xlsx"
    if "csv" in ct or "tab-separated" in ct:
        return "csv"
    if "html" in ct:
        return "html"
    n = (name or "").lower().split("?")[0]
    for ext, fmt in ((".json", "json"), (".xlsx", "xlsx"), (".xls", "xlsx"), (".csv", "csv"), (".tsv", "csv"), (".html", "html"), (".htm", "html")):
        if n.endswith(ext):
            return fmt
    head = body[:2048].lstrip()
    if head.startswith(b"PK"):
        return "xlsx"
    if head.startswith(b"\xd0\xcf\x11\xe0"):  # legacy .xls OLE header
        return "xlsx"
    if head[:1] in (b"{", b"["):
        return "json"
    low = head.lower()
    if b"<table" in low or b"<html" in low or b"<!doctype" in low:
        return "html"
    return "csv"


def parse(body: bytes, fmt: str, sheet: str | None = None) -> list[dict]:
    if fmt == "json":
        return json_table.parse(body)
    if fmt == "csv":
        return csv_table.parse(body)
    if fmt == "xlsx":
        return excel_table.parse(body, sheet=sheet)
    if fmt == "html":
        return html_table.parse(body)
    raise ValueError(f"unsupported format {fmt}")
