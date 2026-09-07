from __future__ import annotations

import csv
import io


def _decode(body: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def parse(body: bytes) -> list[dict]:
    text = _decode(body)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader]
    # drop fully empty leading rows
    while rows and not any(c.strip() for c in rows[0]):
        rows.pop(0)
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out: list[dict] = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        out.append({header[i]: (r[i] if i < len(r) else None) for i in range(len(header))})
    return out
