"""Write results as JSON, JSON Lines, CSV or a terminal table."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from typing import Any, TextIO

FORMATS = ("json", "jsonl", "csv", "table")


def as_dict(item: Any) -> dict[str, Any]:
    return item.to_dict() if hasattr(item, "to_dict") else dict(item)


def _cell(value: Any) -> Any:
    """A CSV-friendly value: lists of plain values joined with `` | ``, the rest as JSON."""
    if isinstance(value, (list, tuple)):
        if all(not isinstance(v, (dict, list)) for v in value):
            return " | ".join(str(v) for v in value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return value


def to_json(items: Sequence[Any] | Any) -> str:
    data = [as_dict(i) for i in items] if isinstance(items, (list, tuple)) else as_dict(items)
    return json.dumps(data, ensure_ascii=False, indent=2)


def to_jsonl(items: Iterable[Any]) -> str:
    return "".join(json.dumps(as_dict(i), ensure_ascii=False) + "\n" for i in items)


def to_csv(items: Iterable[Any]) -> str:
    rows = [as_dict(i) for i in items]
    if not rows:
        return ""
    columns: list[str] = []
    for row in rows:
        columns.extend(k for k in row if k not in columns)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _cell(row.get(k)) for k in columns})
    return buffer.getvalue()


def to_table(items: Iterable[Any]) -> str:
    """A compact, human-readable table (columns depend on the kind of result)."""
    items = list(items)
    if not items:
        return "(no results)\n"
    header = getattr(items[0], "TABLE_HEADER", ())
    if not header:
        raise ValueError(f"no table layout for {type(items[0]).__name__}; use json or csv")
    rows = [tuple(header)] + [tuple(str(c) for c in item.table_row()) for item in items]
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    return "\n".join(lines) + "\n"


def render(items: Sequence[Any] | Any, fmt: str = "json") -> str:
    if fmt == "json":
        return to_json(items) + "\n"
    many = items if isinstance(items, (list, tuple)) else [items]
    if fmt == "jsonl":
        return to_jsonl(many)
    if fmt == "csv":
        return to_csv(many)
    if fmt == "table":
        return to_table(many)
    raise ValueError(f"unknown format {fmt!r}; choose from: {', '.join(FORMATS)}")


def write(
    items: Sequence[Any] | Any,
    fmt: str = "json",
    path: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Render ``items`` and write them to ``path`` (UTF-8) or ``stream``."""
    text = render(items, fmt)
    if path:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return
    if stream is None:
        import sys

        stream = sys.stdout
    stream.write(text)
