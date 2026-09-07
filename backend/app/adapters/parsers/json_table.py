from __future__ import annotations

import json

_LIST_KEYS = ("data", "rows", "result", "results", "items", "value", "records", "table", "Table", "orders", "d")


def _rows_from_list(lst: list) -> list[dict]:
    if not lst:
        return []
    if all(isinstance(x, dict) for x in lst):
        return [dict(x) for x in lst]
    if all(isinstance(x, (list, tuple)) for x in lst):
        header = [str(h) for h in lst[0]]
        return [dict(zip(header, row)) for row in lst[1:]]
    raise ValueError("JSON list is neither objects nor rows")


def parse(body: bytes) -> list[dict]:
    text = body.decode("utf-8-sig")
    data = json.loads(text)
    if isinstance(data, list):
        return _rows_from_list(data)
    if isinstance(data, dict):
        for k in _LIST_KEYS:
            v = data.get(k)
            if isinstance(v, list):
                return _rows_from_list(v)
            if isinstance(v, dict):  # e.g. {"d": {"results": [...]}}
                for k2 in _LIST_KEYS:
                    if isinstance(v.get(k2), list):
                        return _rows_from_list(v[k2])
        # column-oriented {"SO No": [...], "PO No": [...]}
        if data and all(isinstance(v, list) for v in data.values()):
            cols = list(data.keys())
            n = max(len(v) for v in data.values())
            return [{c: (data[c][i] if i < len(data[c]) else None) for c in cols} for i in range(n)]
        # any single list value
        lists = [v for v in data.values() if isinstance(v, list)]
        if len(lists) == 1:
            return _rows_from_list(lists[0])
    raise ValueError("could not find a table in JSON")
