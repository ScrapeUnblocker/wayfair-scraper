"""Scrape Wayfair through the ScrapeUnblocker API.

>>> from wayfair_scraper import WayfairScraper, SearchQuery
>>> wayfair = WayfairScraper()  # reads SCRAPEUNBLOCKER_KEY
>>> chairs = wayfair.search(SearchQuery("office chair", sort="rating", max_price=300))
>>> chairs[0].price, chairs[0].rating, chairs[0].delivery
>>> sofa = wayfair.product("W009315804")
>>> sofa.specifications["Seating Capacity"], sofa.rating_histogram

See https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos
"""

from __future__ import annotations

__version__ = "0.1.0"

from .errors import NotFoundError, ParseError, WayfairError
from .models import FilterOption, OptionChoice, Product, ProductDetail, Review, SearchPage
from .scraper import WayfairScraper
from .urls import (
    PAGE_SIZE,
    SITES,
    SORTS,
    SearchQuery,
    apply_filters,
    image_url,
    keyword_url,
    page_url,
    product_url,
)

__all__ = [
    "FilterOption",
    "NotFoundError",
    "OptionChoice",
    "PAGE_SIZE",
    "ParseError",
    "Product",
    "ProductDetail",
    "Review",
    "SITES",
    "SORTS",
    "SearchPage",
    "SearchQuery",
    "WayfairError",
    "WayfairScraper",
    "__version__",
    "apply_filters",
    "image_url",
    "keyword_url",
    "page_url",
    "product_url",
]
