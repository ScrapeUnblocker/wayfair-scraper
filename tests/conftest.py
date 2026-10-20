"""Shared test helpers: real (trimmed) Wayfair pages and a fake ScrapeUnblocker client.

The fixtures in ``tests/fixtures/`` are real Wayfair responses cut down to the
parts the parsers read: a few product cards, the pagination, sort and filter
blocks of a listing, and the blocks of one product page, re-encoded as the same
``self.__next_f.push`` flight chunks Wayfair serves. Ad-tracking fields are
dropped and reviewer names replaced. No test calls the API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def flight_page(rows: dict[str, Any], title: str = "Test | Wayfair", chunks: int = 2) -> str:
    """An HTML page carrying ``rows`` as a flight, split over ``chunks`` scripts."""
    text = "".join(
        f"{rid}:{json.dumps(value, separators=(',', ':'))}\n" for rid, value in rows.items()
    )
    size = len(text) // chunks + 1
    scripts = "".join(
        f"<script>self.__next_f.push([1,{json.dumps(text[i : i + size])}])</script>"
        for i in range(0, len(text), size)
    )
    return f"<html><head><title>{title}</title></head><body>{scripts}</body></html>"


def card(sku: str, price: float, index: int = 0, *, sponsored: bool = False) -> dict[str, Any]:
    """A minimal product card the parser accepts."""
    return {
        "__typename": ("Sponsored" if sponsored else "Recommended") + "ListingCollectionItem",
        "url": f"https://www.wayfair.com/furniture/pdp/item-{sku.lower()}.html?piid=1&auctionId=x",
        "index": index,
        "listingVariant": {"listing": {"displayListingId": sku}, "displayName": f"Product {sku}"},
        "blocks": [
            {
                "__typename": "PricingStandard",
                "listingVariant": {
                    "pricing": {
                        "allPrices": [
                            {
                                "priceVariation": "PRIMARY",
                                "price": {
                                    "value": {"amount": str(price), "currency": {"code": "USD"}}
                                },
                            }
                        ]
                    }
                },
            }
        ],
    }


def listing_html(
    skus: list[str],
    total: int,
    *,
    page: int = 1,
    url: str = "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html",
    sort: str = "RECOMMENDED",
    sponsored: tuple[str, ...] = (),
    filters: list[dict[str, Any]] | None = None,
) -> str:
    """A listing page with one card per SKU and Wayfair's totals."""
    rows: dict[str, Any] = {}
    for i, sku in enumerate(skus):
        rows[f"{0x10 + i:x}"] = [
            "$",
            "$L1",
            str(i),
            card(sku, 10.0 + i, i, sponsored=sku in sponsored),
        ]
    rows["a0"] = [
        "$",
        "$L1",
        None,
        {
            "config": {"__typename": "BlockBuilderBrowsePagination"},
            "itemsPerPage": 48,
            "numberOfItems": total,
            "pageNumber": page,
            "requestURL": url,
        },
    ]
    rows["a1"] = ["$", "$L1", None, {"resultCount": total, "selectedSortId": sort}]
    if filters is not None:
        rows["a2"] = [
            "$",
            "$L1",
            None,
            {"config": {"__typename": "BlockBuilderBrowseFilters"}, "data": {"filters": filters}},
        ]
    return flight_page(rows)


PRICE_FILTER = {
    "__typename": "FilterWithNumericRanges",
    "filterId": "88",
    "displayName": "Price Per Item",
    "units": "$$",
    "buckets": [{"displayName": "Under $75", "optionRangeStart": 0, "optionRangeEnd": 75}],
}


class ScrapeTimeoutError(Exception):
    """Same class name as the SDK's timeout error (matched by name)."""


class TargetNotFoundError(Exception):
    """Same class name as the SDK's error for a target that answers 404."""


class AuthenticationError(Exception):
    pass


class FakeClient:
    """Stands in for ``scrapeunblocker.Client``; ``responder(url, kwargs)`` returns HTML.

    A responder may also return an exception instance, which is raised instead.
    """

    def __init__(self, responder: Callable[[str, dict[str, Any]], Any]):
        self.responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_page_source(self, url: str, **kwargs: Any) -> str:
        self.calls.append((url, kwargs))
        result = self.responder(url, kwargs)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def make_scraper():
    """Build a :class:`WayfairScraper` around a :class:`FakeClient` (no sleeping)."""
    from wayfair_scraper import WayfairScraper

    def build(responder, **kwargs):
        client = FakeClient(responder)
        sleeps: list[float] = []
        scraper = WayfairScraper(client=client, sleep=sleeps.append, **kwargs)
        scraper.sleeps = sleeps  # type: ignore[attr-defined]
        return scraper, client

    return build
