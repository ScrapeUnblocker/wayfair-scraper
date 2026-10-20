"""Decode the React Server Components payload Wayfair embeds in its pages.

Wayfair's storefront is a Next.js app. The data behind a page is not in a single
JSON blob; it is streamed into the HTML as ``self.__next_f.push([1, "..."])``
script chunks that together form an RSC "flight": newline-separated rows such as

    1a:["$","$L1b",null,{"block":{...},"data":{...}}]
    120:T483,{"type":"doc",...}

Rows reference each other with ``"$<row>:<path>"`` strings, and strings that
really start with ``$`` are escaped as ``$$``. :class:`Flight` splits the rows,
parses them and resolves those references so the parsers can read plain dicts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_ROW_ID = re.compile(r"([0-9a-f]+):")
_REF = re.compile(r"^\$[L@]?([0-9a-f]+)((?::[^:]+)*)$")
# React elements are serialized as ["$", type, key, props].
_ELEMENT_FIELDS = {"type": 1, "key": 2, "props": 3}
_MAX_DEPTH = 64


def flight_text(html: str) -> str:
    """The concatenated flight payload of a page ('' when it has none)."""
    return "".join(json.loads(match.group(1)) for match in _PUSH.finditer(html))


def _take_bytes(text: str, start: int, size: int) -> int:
    """Index in ``text`` after ``size`` UTF-8 bytes starting at ``start``."""
    end = start
    remaining = size
    while remaining > 0 and end < len(text):
        remaining -= len(text[end].encode("utf-8", "surrogatepass"))
        end += 1
    return end


def split_rows(text: str) -> dict[str, Any]:
    """Parse a flight into ``{row id: value}``.

    JSON rows become Python values and text rows (``T<hex length>,...``) become
    strings. Rows that are neither (module imports, hints) are skipped.
    """
    rows: dict[str, Any] = {}
    pos = 0
    size = len(text)
    while pos < size:
        match = _ROW_ID.match(text, pos)
        if not match:
            newline = text.find("\n", pos)
            if newline < 0:
                break
            pos = newline + 1
            continue
        row_id, start = match.group(1), match.end()
        if text.startswith("T", start):
            comma = text.find(",", start)
            if comma > start + 1:
                try:
                    length = int(text[start + 1 : comma], 16)
                except ValueError:
                    length = -1
                if length >= 0:
                    end = _take_bytes(text, comma + 1, length)
                    rows[row_id] = text[comma + 1 : end]
                    pos = end
                    continue
        newline = text.find("\n", start)
        end = size if newline < 0 else newline
        raw = text[start:end]
        if raw[:1] in '[{"' or raw[:1].isdigit() or raw in ("null", "true", "false"):
            try:
                rows[row_id] = json.loads(raw)
            except ValueError:
                pass
        pos = end + 1
    return rows


class Flight:
    """The parsed RSC rows of one page, with reference resolution."""

    def __init__(self, rows: dict[str, Any]):
        self.rows = rows

    @classmethod
    def from_html(cls, html: str) -> Flight:
        return cls(split_rows(flight_text(html)))

    def __bool__(self) -> bool:
        return bool(self.rows)

    def resolve(self, value: Any, _depth: int = 0) -> Any:
        """Follow ``"$<row>:<path>"`` references and unescape ``$`` strings."""
        if not isinstance(value, str) or not value.startswith("$") or _depth > _MAX_DEPTH:
            return value
        if value.startswith("$$"):
            return value[1:]
        if value == "$undefined":
            return None
        if value.startswith("$D"):
            return value[2:]
        match = _REF.match(value)
        if not match or match.group(1) not in self.rows:
            return value if not match else None
        node: Any = self.rows[match.group(1)]
        for part in filter(None, match.group(2).split(":")):
            node = self.resolve(node, _depth + 1)
            if isinstance(node, list):
                if node and node[0] == "$" and part in _ELEMENT_FIELDS:
                    index = _ELEMENT_FIELDS[part]
                elif part.isdigit():
                    index = int(part)
                else:
                    return None
                node = node[index] if index < len(node) else None
            elif isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        return self.resolve(node, _depth + 1)

    def deep(self, value: Any, _depth: int = 0) -> Any:
        """``value`` with every nested reference resolved."""
        if _depth > _MAX_DEPTH:
            return value
        value = self.resolve(value)
        if isinstance(value, dict):
            return {key: self.deep(item, _depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [self.deep(item, _depth + 1) for item in value]
        return value

    def objects(self) -> Iterator[dict[str, Any]]:
        """Every dict in every row, depth first, in page order (unresolved)."""
        stack: list[Any] = [self.rows[key] for key in reversed(list(self.rows))]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                yield node
                stack.extend(reversed(list(node.values())))
            elif isinstance(node, list):
                stack.extend(reversed(node))
