from __future__ import annotations

import csv
import io
import json

import pytest
from conftest import fixture_html

from wayfair_scraper.export import render, to_csv, to_table, write
from wayfair_scraper.models import OptionChoice
from wayfair_scraper.parsing import parse_filters, parse_listing, parse_product

CATEGORY = fixture_html("category_office_chairs_p2.html")


@pytest.fixture(scope="module")
def products():
    return parse_listing(CATEGORY, "u").products


@pytest.fixture(scope="module")
def detail():
    return parse_product(fixture_html("product_W009315804.html"), "u")


def test_json_and_jsonl(products):
    data = json.loads(render(products, "json"))
    assert data[0]["sku"] == "W116084446"
    lines = render(products, "jsonl").splitlines()
    assert len(lines) == len(products)
    assert json.loads(lines[1])["brand"] == products[1].brand


def test_csv_flattens_lists_and_dicts(products, detail):
    rows = list(csv.DictReader(io.StringIO(to_csv(products))))
    assert len(rows) == len(products) and rows[0]["discount_percent"] == "54"
    assert rows[3]["was_price"] == "" and rows[0]["sponsored"] == "False"
    assert json.loads(rows[0]["highlights"])["Product Type"] == "Task Chair"
    row = next(csv.DictReader(io.StringIO(to_csv([detail]))))
    assert row["categories"] == "Furniture | Living Room Furniture | Futons & Daybeds | Futons"
    assert json.loads(row["specifications"])["Seating Capacity"] == "3"
    assert json.loads(row["reviews"])[0]["rating"] == 5
    assert json.loads(row["options"])[0]["category"] == "Fabric"
    assert to_csv([]) == ""


def test_tables(products, detail):
    lines = to_table(products).splitlines()
    assert "$169.99" in lines[1] and "$369.99" in lines[1] and "George Oliver" in lines[1]
    assert "[ad]" in lines[6]
    assert "22 Left in Stock" in to_table([detail]).splitlines()[1]
    filters = to_table(parse_filters(CATEGORY, "u")).splitlines()
    assert filters[0].split() == ["group", "filter", "value", "kind"]
    assert to_table(detail.reviews).splitlines()[0].split() == [
        "date",
        "rating",
        "author",
        "review",
    ]
    assert to_table([]) == "(no results)\n"
    with pytest.raises(ValueError):
        to_table([OptionChoice("Fabric", "Blue")])


def test_single_object_and_errors(products, detail, tmp_path):
    assert json.loads(render(detail, "json"))["rating_histogram"]["5"] == 16948
    with pytest.raises(ValueError):
        render(products, "xml")
    path = tmp_path / "chairs.csv"
    write(products, "csv", str(path))
    text = path.read_text(encoding="utf-8")
    assert "W116084446" in text and "\r\n" not in text
    stream = io.StringIO()
    write(products[:1], "jsonl", stream=stream)
    assert json.loads(stream.getvalue())["price"] == 169.99
