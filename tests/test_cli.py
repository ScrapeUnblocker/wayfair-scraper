from __future__ import annotations

import argparse
import csv
import io
import json

import pytest
from conftest import FakeClient, fixture_html

from wayfair_scraper import WayfairScraper, cli


def parse(*argv: str) -> argparse.Namespace:
    return cli.build_parser().parse_args(list(argv))


def test_search_arguments_build_a_query():
    args = parse(
        "--site", "ca", "--page-retries", "1", "search", "office", "chair",
        "--filter", "86:1944", "--filter", "4576=474790", "--sort", "price-low",
        "--min-price", "50", "--max-price", "299.99", "--price-filter", "88",
        "--pages", "3", "--max", "120", "--no-sponsored",
    )  # fmt: skip
    query = cli.query_from_args(args)
    assert query.keywords == "office chair" and query.site == "ca"
    assert query.filters == [("86", "1944"), ("4576", "474790")]
    assert query.sort == "price-low" and query.price_filter == "88"
    assert (query.min_price, query.max_price) == (50.0, 299.99)
    assert (args.pages, args.max_results, args.page_retries) == (3, 120, 1)
    assert args.no_sponsored and not args.keep_duplicates


def test_defaults():
    args = parse("search", "sofa")
    assert args.site == "us" and args.proxy_country == "auto" and args.retries == 3
    assert args.page_retries == 3 and args.pages == 1 and args.max_results is None
    assert args.format == "json" and args.sort is None and args.filter == []
    url = "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html"
    query = cli.query_from_args(parse("filters", "--url", url))
    assert query.url == url and query.sort is None and query.filters == []


@pytest.mark.parametrize(
    "argv",
    [
        ("search", "sofa", "--sort", "cheapest"),
        ("search", "sofa", "--filter", "brand"),
        ("search", "sofa", "--filter", "86:"),
        ("search", "sofa", "--pages", "0"),
        ("search", "sofa", "--pages", "101"),
        ("search", "sofa", "--min-price", "-5"),
        ("search", "sofa", "--max-price", "cheap"),
        ("--site", "uk", "search", "sofa"),
        ("product",),
    ],
)
def test_bad_arguments_exit(argv):
    with pytest.raises(SystemExit):
        parse(*argv)


@pytest.fixture
def fake_scraper(monkeypatch):
    """Route the CLI to a scraper whose client answers from fixtures."""

    def responder(url, kw):
        if "keyword=W" in url or "/pdp/" in url:
            return fixture_html("product_W009315804.html")
        if "wayfair.ca" in url:
            return fixture_html("search_ca_office_chair.html")
        return fixture_html("category_office_chairs_p2.html")

    client = FakeClient(responder)

    def make(args):
        return WayfairScraper(
            client=client, site=args.site, page_retries=args.page_retries, sleep=lambda s: None
        )

    monkeypatch.setattr(cli, "make_scraper", make)
    return client


def test_main_search_writes_json(fake_scraper, capsys):
    assert cli.main(["--page-retries", "0", "search", "office chair"]) == 0
    out, err = capsys.readouterr()
    data = json.loads(out)
    assert len(data) == 7 and data[0]["sku"] == "W116084446"
    assert data[0]["was_price"] == 369.99 and data[0]["highlights"]["Product Type"]
    assert "7 products, 1 requests" in err
    assert fake_scraper.calls[-1][0] == "https://www.wayfair.com/keyword.php?keyword=office+chair"


def test_main_search_table_and_csv(fake_scraper, capsys, tmp_path):
    assert (
        cli.main(["--page-retries", "0", "search", "chair", "--no-sponsored", "-f", "table"]) == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["#", "sku", "price", "was", "rating", "reviews", "brand", "name"]
    assert "$169.99" in lines[1] and "George Oliver" in lines[1]
    assert "[ad]" not in "\n".join(lines) and len(lines) == 7
    out = tmp_path / "chairs.csv"
    assert cli.main(["--page-retries", "0", "search", "chair", "-f", "csv", "-o", str(out)]) == 0
    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert len(rows) == 7 and rows[0]["price"] == "169.99"
    assert json.loads(rows[0]["options"]) == {"Colors": 6}


def test_main_short_pages_are_retried(fake_scraper, capsys):
    assert cli.main(["search", "office chair", "-f", "jsonl"]) == 0
    assert "7 products, 4 requests" in capsys.readouterr().err  # 1 + 3 page retries


def test_main_product_and_reviews(fake_scraper, capsys):
    assert cli.main(["product", "W009315804"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["sku"] == "W009315804" and data["specifications"]["Seating Capacity"] == "3"
    assert cli.main(["product", "W009315804", "W004441107", "-f", "table"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 3
    assert cli.main(["reviews", "W009315804", "-f", "table"]) == 0
    out, err = capsys.readouterr()
    assert "Jordan" in out and "3 reviews, 1 requests" in err


def test_main_filters_table(fake_scraper, capsys):
    assert cli.main(["filters", "office chair", "-f", "table"]) == 0
    out, err = capsys.readouterr()
    assert "Color" in out and "73316:607854" in out and "Cream" in out
    assert "88 $0.00-$75.00" in out
    assert "office-chairs-c478390.html" in err


def test_main_ca_site(fake_scraper, capsys):
    assert (
        cli.main(["--site", "ca", "--page-retries", "0", "search", "office chair", "--max", "1"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)[0]["currency"] == "CAD"
    assert fake_scraper.calls[-1] == (
        "https://www.wayfair.ca/keyword.php?keyword=office+chair",
        {"proxy_country": "ca"},
    )


def test_main_reports_errors(fake_scraper, capsys):
    assert cli.main(["product", "not-a-sku"]) == 1
    assert "expected a Wayfair SKU" in capsys.readouterr().err
    assert cli.main(["search"]) == 1
    assert "give search keywords" in capsys.readouterr().err
    assert cli.main(["-v", "search", "sofa", "--min-price", "9", "--max-price", "1"]) == 1
    assert "min_price is above max_price" in capsys.readouterr().err
