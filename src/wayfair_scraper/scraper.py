"""Scrape Wayfair through the ScrapeUnblocker ``getPageSource`` API.

:class:`WayfairScraper` builds Wayfair URLs, fetches the pages through
ScrapeUnblocker and parses them into the dataclasses in :mod:`models`.

* Listing and product pages are server-rendered with their data embedded, so
  every page is one plain ``getPageSource`` request; no browser rendering.
* Wayfair sometimes renders only the first 30 of a page's 48 cards on the server
  and leaves the rest to the browser. The page still reports how many cards it
  should hold, so a short page is requested again (``page_retries`` times).
* A keyword search that Wayfair redirects to a category ("office chair" ->
  Office Chairs) is followed to that category, so its filters, price range and
  later pages work like on any category URL.
* Timeouts, transient API errors and pages that come back without their data are
  retried with doubling backoff. A product that does not exist raises
  :class:`NotFoundError`.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any, Callable

from .errors import NotFoundError, ParseError
from .models import FilterOption, Product, ProductDetail, Review, SearchPage
from .parsing import (
    has_listing,
    has_product,
    parse_filters,
    parse_listing,
    parse_product,
    price_filter_id,
)
from .urls import (
    CURRENCIES,
    SearchQuery,
    is_category_url,
    page_url,
    product_url,
    site_base,
    site_of,
    with_params,
)

_TRANSIENT_NAMES = (
    "UpstreamOutageError",
    "RateLimitError",
    "ScrapeTimeoutError",
    "BlockedError",
    "ServerError",
    "ConnectionError",
)
_NOT_FOUND_NAMES = ("TargetNotFoundError", "NotFoundError")

#: Proxy country per storefront, used when ``proxy_country="auto"``.
SITE_COUNTRY = {"us": "us", "ca": "ca"}

log = logging.getLogger(__name__)


def _is_named(error: BaseException, *names: str) -> bool:
    return any(cls.__name__ in names for cls in type(error).__mro__)


def _query(query: SearchQuery | str, site: str) -> SearchQuery:
    if isinstance(query, SearchQuery):
        return query
    return SearchQuery(keywords=query, site=site)


def _listing_base(url: str) -> str:
    """A served listing URL without its page number and sort order."""
    return with_params(url, curpage=None, sortby=None)


class WayfairScraper:
    """Read Wayfair search results, category listings and product pages.

    Args:
        api_key: Your ScrapeUnblocker API key. Defaults to the
            ``SCRAPEUNBLOCKER_KEY`` environment variable (read by the SDK).
        client: A ready ``scrapeunblocker.Client`` (or anything with a compatible
            ``get_page_source``); handy for tests.
        site: Default storefront, ``us`` (wayfair.com) or ``ca`` (wayfair.ca).
        proxy_country: Country to route requests through. ``"auto"`` (default)
            matches the storefront so prices and delivery messages are the ones
            local shoppers see. ``None`` lets the API choose.
        max_retries: Extra attempts for a request that fails transiently.
        backoff: Seconds before the first retry; doubles on each retry.
        page_retries: Extra requests for a listing page that came back with
            fewer cards than Wayfair says it holds. ``0`` keeps partial pages.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any = None,
        site: str = "us",
        proxy_country: str | None = "auto",
        max_retries: int = 3,
        backoff: float = 2.0,
        page_retries: int = 3,
        timeout: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        site_base(site)
        if client is None:
            from scrapeunblocker import Client

            client = Client(api_key=api_key, timeout=timeout)
        self.client = client
        self.site = site
        self.proxy_country = proxy_country or None
        self.max_retries = max_retries
        self.backoff = backoff
        self.page_retries = page_retries
        self.sleep = sleep
        #: Number of API requests made so far (each page fetch is one request).
        self.requests = 0
        #: The listing ``filters()`` last read (a search may land on a category).
        self.last_filters_url: str | None = None

    # -- fetching -------------------------------------------------------------

    def _country(self, url: str) -> str | None:
        if self.proxy_country == "auto":
            return SITE_COUNTRY[site_of(url)]
        return self.proxy_country

    def fetch(self, url: str, *, check: Callable[[str], bool] | None = None) -> str:
        """The HTML of ``url``, retried on transient failures.

        ``check`` tells a complete page from an empty or challenge page (which is
        retried like a transient error).
        """
        kwargs: dict[str, Any] = {}
        country = self._country(url)
        if country:
            kwargs["proxy_country"] = country
        attempt = 0
        while True:
            self.requests += 1
            try:
                html = self.client.get_page_source(url, **kwargs)
                if not isinstance(html, str) or (check is not None and not check(html)):
                    raise ParseError(f"the page came back without its data: {url}")
                return html
            except Exception as exc:
                if _is_named(exc, *_NOT_FOUND_NAMES):
                    raise NotFoundError(f"Wayfair has no page at {url}") from exc
                retryable = isinstance(exc, ParseError) or _is_named(exc, *_TRANSIENT_NAMES)
                if not retryable or attempt >= self.max_retries:
                    raise
                log.info("retrying %s after %s", url, type(exc).__name__)
                self.sleep(self.backoff * (2**attempt))
                attempt += 1

    def _listing(self, url: str, page: int, *, complete: bool = True) -> tuple[SearchPage, str]:
        """Fetch and parse one listing page, asking again while it is short."""
        currency = CURRENCIES[site_of(url)]
        attempt = 0
        while True:
            html = self.fetch(url, check=has_listing)
            result = parse_listing(html, url, page=page, currency=currency)
            if result.complete or not complete or attempt >= self.page_retries:
                if not result.complete and complete:
                    log.warning(
                        "page %d kept %d of %d cards after %d tries: %s",
                        page,
                        len(result.products),
                        result.expected,
                        attempt + 1,
                        url,
                    )
                return result, html
            attempt += 1
            log.info(
                "page %d came back with %d of %d cards; asking again",
                page,
                len(result.products),
                result.expected,
            )

    def _resolve(self, query: SearchQuery) -> tuple[SearchQuery, str]:
        """The query with a known price filter, and the listing URL to page through."""
        base = query.start_url
        if not query.needs_category:
            return query, base
        first_html = None
        if not is_category_url(base):
            first, first_html = self._listing(page_url(base, 1), 1, complete=False)
            served = _listing_base(first.url)
            if not is_category_url(served):
                raise ValueError(
                    "Wayfair kept this search on keyword results, so filters and a price "
                    "range can't be applied. Open a category instead, e.g. --url "
                    "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html "
                    "(run `filters` to see where a search lands)"
                )
            base = served
        if query.has_price and not query.price_filter:
            if first_html is None:
                _, first_html = self._listing(page_url(base, 1), 1, complete=False)
            found = price_filter_id(parse_filters(first_html, base))
            if not found:
                raise ValueError(f"this listing has no price filter: {base}")
            query = dataclasses.replace(query, price_filter=found)
        return query, query.listing_url(base)

    # -- listings -------------------------------------------------------------

    def search_page(self, query: SearchQuery | str, page: int = 1) -> SearchPage:
        """One result page of a search or category listing.

        For a later page of a keyword search, page 1 is read first to learn which
        listing Wayfair serves for the keywords (one extra request).
        """
        query, base = self._resolve(_query(query, self.site))
        if page > 1 and not is_category_url(base):
            first, _ = self._listing(page_url(base, 1, query.sort), 1, complete=False)
            base = _listing_base(first.url)
        result, _ = self._listing(page_url(base, page, query.sort), page)
        return result

    def search(
        self,
        query: SearchQuery | str,
        *,
        max_results: int | None = None,
        max_pages: int = 1,
        sponsored: bool = True,
        dedupe: bool = True,
    ) -> list[Product]:
        """Products of a search or listing, in Wayfair's order, numbered from 1.

        Args:
            query: Keywords (``"office chair"``), a listing URL, or a
                :class:`SearchQuery` with sort order, filters and price range.
            max_results: Stop once this many products are collected.
            max_pages: Read at most this many result pages (48 products each).
            sponsored: Keep the sponsored listings Wayfair mixes into results.
            dedupe: Keep each SKU once (sponsored products can show up again on
                a later page).
        """
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if max_results is not None and max_results < 1:
            raise ValueError("max_results must be at least 1")
        query, base = self._resolve(_query(query, self.site))
        products: list[Product] = []
        seen: set[str] = set()
        for number in range(1, max_pages + 1):
            url = page_url(base, number, query.sort)
            page, _ = self._listing(url, number)
            if number == 1:
                served = _listing_base(page.url)
                if served != _listing_base(url):
                    # A keyword search landed on a category: page through that.
                    base = served
                    if query.sort and page.sort != query.sort:
                        page, _ = self._listing(page_url(base, 1, query.sort), 1)
            for product in page.products:
                if not sponsored and product.sponsored:
                    continue
                if dedupe and product.sku in seen:
                    continue
                seen.add(product.sku)
                products.append(product)
            if max_results is not None and len(products) >= max_results:
                break
            if not page.has_more:
                break
        products = products[:max_results] if max_results is not None else products
        for position, product in enumerate(products, 1):
            product.position = position
        return products

    def filters(self, query: SearchQuery | str) -> list[FilterOption]:
        """The filter options a listing offers (brands, colors, price bands, ...).

        Pass an option's ``ref`` (``"86:1944"``) in ``SearchQuery(filters=[...])``.
        Filters apply to category listings; see :attr:`last_filters_url` for the
        page Wayfair served.
        """
        query = _query(query, self.site)
        page, html = self._listing(page_url(query.start_url, 1), 1, complete=False)
        self.last_filters_url = _listing_base(page.url)
        return parse_filters(html, page.url)

    # -- product pages --------------------------------------------------------

    def product(self, ref: str, *, site: str | None = None) -> ProductDetail:
        """A product page: price, stock, delivery, specifications, options,
        images and the latest reviews.

        ``ref`` is a SKU (``W009315804``) or a product URL (a ``?piid=`` in the
        URL selects that option, e.g. a color).
        """
        url = product_url(ref, site or self.site)
        site = site_of(url)
        html = self.fetch(url, check=lambda page: has_product(page) or has_listing(page))
        if not has_product(html):
            raise NotFoundError(f"Wayfair has no product {ref!r}")
        return parse_product(html, url, currency=CURRENCIES[site])

    def reviews(self, ref: str, *, site: str | None = None) -> list[Review]:
        """The latest customer reviews a product page shows."""
        return self.product(ref, site=site).reviews
