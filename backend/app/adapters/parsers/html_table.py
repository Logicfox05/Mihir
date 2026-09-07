from __future__ import annotations

from lxml import html as lhtml


def _cell_text(el) -> str:
    """Cell text. Collapse whitespace only when the cell contains line breaks/tabs (pretty-printed HTML);
    otherwise keep it byte-exact so a trailing space in a customer name survives."""
    t = el.text_content()
    if "\n" in t or "\r" in t or "\t" in t:
        return " ".join(t.split())
    return t


def parse(body: bytes, table_index: int | None = None) -> list[dict]:
    doc = lhtml.fromstring(body)
    tables = doc.xpath("//table")
    if not tables:
        raise ValueError("no <table> found in HTML")
    if table_index is not None:
        table = tables[table_index]
    else:
        table = max(tables, key=lambda t: len(t.xpath(".//tr")))  # biggest table wins
    trs = table.xpath(".//tr")
    if not trs:
        return []
    header_cells = trs[0].xpath("./th|./td")
    header = [_cell_text(c) for c in header_cells]
    out: list[dict] = []
    for tr in trs[1:]:
        cells = tr.xpath("./td|./th")
        if not cells:
            continue
        vals = [_cell_text(c) for c in cells]
        if not any(vals):
            continue
        out.append({header[i]: (vals[i] if i < len(vals) else None) for i in range(len(header))})
    return out
