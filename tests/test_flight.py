from __future__ import annotations

import json

from conftest import fixture_html, flight_page

from wayfair_scraper.flight import Flight, flight_text, split_rows


def test_flight_text_joins_push_chunks():
    html = flight_page({"1": {"a": 1}, "2": ["x", "y"]}, chunks=3)
    assert html.count("self.__next_f.push") == 3
    assert flight_text(html) == '1:{"a":1}\n2:["x","y"]\n'
    assert flight_text("<html>no flight</html>") == ""


def test_split_rows_handles_text_rows_and_skips_imports():
    text_row = '{"t":"Vérifié – ok"}'  # multi-byte characters: length is in bytes
    size = len(text_row.encode("utf-8"))
    flight = (
        '1:I[123,["chunk.js"],"Grid"]\n'
        'HL["/app.css","style"]\n'
        f"2:T{size:x},{text_row}3:" + json.dumps({"after": True}) + "\n"
        "4:null\n"
        "5:not json\n"
    )
    rows = split_rows(flight)
    assert rows["2"] == text_row
    assert rows["3"] == {"after": True}
    assert rows["4"] is None
    assert "1" not in rows and "5" not in rows


def test_resolve_references_and_escapes():
    flight = Flight(
        {
            "a": [["$", "$L1", None, {"data": {"filters": [{"id": 1}, {"id": 2}]}}]],
            "b": {"price": "$$429.99", "missing": "$undefined", "when": "$D2026-10-20"},
            "c": {"ref": "$a:0:props:data:filters:1", "lazy": "$Lb", "gone": "$ff"},
        }
    )
    assert flight.resolve("$a:0:props:data:filters:1") == {"id": 2}
    assert flight.resolve("$$429.99") == "$429.99"
    assert flight.resolve("$Sreact.fragment") == "$Sreact.fragment"
    assert flight.resolve("plain") == "plain"
    assert flight.resolve("$a:0:props:nope:1") is None
    deep = flight.deep(flight.rows["c"])
    assert deep["ref"] == {"id": 2}
    assert deep["lazy"] == {"price": "$429.99", "missing": None, "when": "2026-10-20"}
    assert deep["gone"] is None


def test_objects_walks_rows_in_page_order():
    flight = Flight({"1": [{"n": 1, "child": {"n": 2}}], "2": {"n": 3}})
    assert [o["n"] for o in flight.objects() if "n" in o] == [1, 2, 3]
    assert not Flight({})


def test_real_fixture_decodes():
    flight = Flight.from_html(fixture_html("product_W009315804.html"))
    assert flight
    headers = [
        o for o in flight.objects() if (o.get("block") or {}).get("__typename") == "ListingHeader"
    ]
    assert len(headers) == 1
    # the header's data lives in another row and is reached through a reference
    assert headers[0]["data"] == "$c0:header"
    assert flight.deep(headers[0]["data"])["displayName"].startswith("Perdue")
