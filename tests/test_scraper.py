from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import (
    PRICE_FILTER,
    AuthenticationError,
    ScrapeTimeoutError,
    TargetNotFoundError,
    fixture_html,
    listing_html,
)

from wayfair_scraper import NotFoundError, ParseError, SearchQuery

PRODUCT = fixture_html("product_W009315804.html")
CHAIRS = "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html"
SKUS = [f"W{n:09d}" for n in range(1, 101)]


def query_of(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def page_of(url: str) -> int:
    return int(query_of(url).get("curpage", "1"))


def full_pages(total: int = 100, **kwargs):
    """A responder serving complete 48-card pages of a ``total``-product listing."""

    def respond(url, kw):
        page = page_of(url)
        skus = SKUS[(page - 1) * 48 : min(page * 48, total)]
        return listing_html(skus, total, page=page, url=url, **kwargs)

    return respond


def test_retries_transient_errors_with_backoff(make_scraper):
    answers = [ScrapeTimeoutError("slow"), ScrapeTimeoutError("slow"), PRODUCT]
    scraper, client = make_scraper(lambda url, kw: answers.pop(0), backoff=1.5)
    assert scraper.product("W009315804").price == 429.99
    assert len(client.calls) == 3
    assert scraper.sleeps == [1.5, 3.0]
    assert scraper.requests == 3


def test_retries_pages_without_data(make_scraper):
    answers = ["<html><title>Access to this page has been denied</title></html>"]
    responder = full_pages()
    scraper, client = make_scraper(
        lambda url, kw: answers.pop(0) if answers else responder(url, kw)
    )
    assert len(scraper.search(CHAIRS)) == 48
    assert len(client.calls) == 2


def test_gives_up_after_max_retries(make_scraper):
    scraper, client = make_scraper(lambda url, kw: ScrapeTimeoutError("slow"), max_retries=2)
    with pytest.raises(ScrapeTimeoutError):
        scraper.product("W009315804")
    assert len(client.calls) == 3
    scraper, client = make_scraper(lambda url, kw: "<html></html>", max_retries=1)
    with pytest.raises(ParseError):
        scraper.search("office chair")
    assert len(client.calls) == 2


def test_does_not_retry_other_errors(make_scraper):
    scraper, client = make_scraper(lambda url, kw: AuthenticationError("bad key"))
    with pytest.raises(AuthenticationError):
        scraper.product("W009315804")
    assert len(client.calls) == 1


def test_missing_products_are_not_found(make_scraper):
    scraper, client = make_scraper(lambda url, kw: TargetNotFoundError("404"))
    with pytest.raises(NotFoundError):
        scraper.product("https://www.wayfair.com/furniture/pdp/gone-w999999999.html")
    assert len(client.calls) == 1
    # a SKU search that matches nothing returns search results instead of a product
    scraper, client = make_scraper(lambda url, kw: listing_html(["W1"], 1, url=url))
    with pytest.raises(NotFoundError, match="no product 'W999999999'"):
        scraper.product("W999999999")
    assert len(client.calls) == 1


def test_proxy_country_follows_the_site(make_scraper):
    scraper, client = make_scraper(lambda url, kw: PRODUCT)
    scraper.product("W009315804")
    scraper.product("https://www.wayfair.ca/furniture/pdp/x-c005584693.html")
    assert client.calls[0] == (
        "https://www.wayfair.com/keyword.php?keyword=W009315804",
        {"proxy_country": "us"},
    )
    assert client.calls[1][1] == {"proxy_country": "ca"}
    scraper, client = make_scraper(lambda url, kw: PRODUCT, proxy_country=None)
    scraper.product("W009315804")
    assert client.calls[0][1] == {}
    scraper, client = make_scraper(lambda url, kw: PRODUCT, proxy_country="de", site="ca")
    scraper.product("C005584693")
    assert client.calls[0] == (
        "https://www.wayfair.ca/keyword.php?keyword=C005584693",
        {"proxy_country": "de"},
    )


def test_short_pages_are_requested_again(make_scraper):
    answers = [
        listing_html(SKUS[:30], 100, url=CHAIRS),  # 18 cards left to the browser
        listing_html(SKUS[:30], 100, url=CHAIRS),
        listing_html(SKUS[:48], 100, url=CHAIRS),
    ]
    scraper, client = make_scraper(lambda url, kw: answers.pop(0))
    page = scraper.search_page(CHAIRS)
    assert len(page.products) == 48 and page.complete
    assert len(client.calls) == 3 and scraper.sleeps == []


def test_short_pages_are_kept_after_page_retries(make_scraper):
    scraper, client = make_scraper(
        lambda url, kw: listing_html(SKUS[:30], 100, url=CHAIRS), page_retries=1
    )
    page = scraper.search_page(CHAIRS)
    assert len(page.products) == 30 and not page.complete
    assert len(client.calls) == 2
    scraper, client = make_scraper(
        lambda url, kw: listing_html(SKUS[:30], 100, url=CHAIRS), page_retries=0
    )
    assert len(scraper.search(CHAIRS)) == 30 and len(client.calls) == 1
    # the last page of a listing is short by nature and is not asked again
    scraper, client = make_scraper(full_pages(100))
    assert len(scraper.search_page(CHAIRS, 3).products) == 4 and len(client.calls) == 1


def test_search_walks_pages_and_numbers_products(make_scraper):
    scraper, client = make_scraper(full_pages(100))
    products = scraper.search(CHAIRS, max_pages=5)
    assert len(products) == 100 and len(client.calls) == 3  # stops after the last page
    assert [p.position for p in products[:3]] == [1, 2, 3] and products[-1].position == 100
    assert [page_of(url) for url, _ in client.calls] == [1, 2, 3]
    scraper, client = make_scraper(full_pages(100))
    assert len(scraper.search(CHAIRS, max_pages=5, max_results=50)) == 50
    assert len(client.calls) == 2
    with pytest.raises(ValueError):
        scraper.search(CHAIRS, max_pages=0)
    with pytest.raises(ValueError):
        scraper.search(CHAIRS, max_results=0)


def test_search_dedupes_and_drops_sponsored(make_scraper):
    def respond(url, kw):
        page = page_of(url)
        skus = SKUS[:48] if page == 1 else [SKUS[0]] + SKUS[48:60]
        return listing_html(skus, 60, page=page, url=url, sponsored=(SKUS[0], SKUS[1]))

    scraper, _ = make_scraper(respond)
    assert len(scraper.search(CHAIRS, max_pages=2)) == 60
    scraper, _ = make_scraper(respond)
    assert len(scraper.search(CHAIRS, max_pages=2, dedupe=False)) == 61
    scraper, _ = make_scraper(respond)
    products = scraper.search(CHAIRS, max_pages=2, sponsored=False)
    assert len(products) == 58 and not any(p.sponsored for p in products)


def test_keyword_search_follows_its_category(make_scraper):
    landed = CHAIRS + "?redir=office+chair&rtype=9"

    def respond(url, kw):
        if "keyword.php" in url:
            return listing_html(SKUS[:48], 100, url=landed)
        return full_pages(100)(url, kw)

    scraper, client = make_scraper(respond)
    assert len(scraper.search("office chair", max_pages=2)) == 96
    first, second = (url for url, _ in client.calls)
    assert first == "https://www.wayfair.com/keyword.php?keyword=office+chair"
    assert second == landed + "&curpage=2"


def test_search_page_of_a_keyword_search_pages_the_served_listing(make_scraper):
    landed = CHAIRS + "?redir=office+chair&rtype=9"

    def respond(url, kw):
        if "keyword.php" in url:
            return listing_html(SKUS[:30], 100, url=landed)
        return full_pages(100)(url, kw)

    scraper, client = make_scraper(respond)
    page = scraper.search_page(SearchQuery("office chair", sort="price-high"), 2)
    assert page.page == 2 and len(page.products) == 48
    assert [url for url, _ in client.calls] == [
        "https://www.wayfair.com/keyword.php?keyword=office+chair&sortby=3",
        landed + "&curpage=2&sortby=3",
    ]


def test_sort_is_reapplied_when_a_search_lands_on_a_category(make_scraper):
    def respond(url, kw):
        if "keyword.php" in url:  # the redirect dropped the sort order
            return listing_html(SKUS[:48], 100, url=CHAIRS)
        sort = "PRICE_PER_ITEM_ASC" if query_of(url).get("sortby") == "2" else "RECOMMENDED"
        return full_pages(100, sort=sort)(url, kw)

    scraper, client = make_scraper(respond)
    scraper.search(SearchQuery("office chair", sort="price-low"), max_pages=2)
    urls = [url for url, _ in client.calls]
    assert urls == [
        "https://www.wayfair.com/keyword.php?keyword=office+chair&sortby=2",
        CHAIRS + "?sortby=2",
        CHAIRS + "?curpage=2&sortby=2",
    ]


def test_filters_and_price_range_on_a_keyword_search(make_scraper):
    def respond(url, kw):
        if "keyword.php" in url:
            return listing_html(SKUS[:48], 100, url=CHAIRS, filters=[PRICE_FILTER])
        return full_pages(100)(url, kw)

    scraper, client = make_scraper(respond)
    query = SearchQuery("office chair", filters=["86:1944"], max_price=150, sort="rating")
    assert len(scraper.search(query)) == 48
    urls = [url for url, _ in client.calls]
    assert len(urls) == 2  # one request to find the category and its price filter
    assert urls[1] == (
        "https://www.wayfair.com/furniture/sb2/office-chairs-c478390-a86~1944-p88~0~150.html"
        "?sortby=7"
    )
    # with a known price filter on a category URL, no extra request is needed
    scraper, client = make_scraper(full_pages(100))
    scraper.search(SearchQuery(url=CHAIRS, min_price=500, price_filter="88"))
    assert [url for url, _ in client.calls] == [
        "https://www.wayfair.com/furniture/sb1/office-chairs-c478390-p88~500~1000000.html"
    ]


def test_filters_need_a_category(make_scraper):
    keyword = "https://www.wayfair.com/keyword.php?keyword=blue+velvet+sofa"
    scraper, _ = make_scraper(lambda url, kw: listing_html(SKUS[:48], 100, url=keyword))
    with pytest.raises(ValueError, match="kept this search on keyword results"):
        scraper.search(SearchQuery("blue velvet sofa", filters=["86:1944"]))
    scraper, _ = make_scraper(lambda url, kw: listing_html(SKUS[:48], 100, url=CHAIRS))
    with pytest.raises(ValueError, match="no price filter"):
        scraper.search(SearchQuery(url=CHAIRS, max_price=100))


def test_filters_lists_options_of_the_served_listing(make_scraper):
    scraper, client = make_scraper(
        lambda url, kw: listing_html(SKUS[:30], 100, url=CHAIRS, filters=[PRICE_FILTER])
    )
    options = scraper.filters("office chair")
    assert options[0].kind == "price" and scraper.last_filters_url == CHAIRS
    assert len(client.calls) == 1  # a short page is fine for reading filters


def test_reviews_come_from_the_product_page(make_scraper):
    scraper, client = make_scraper(lambda url, kw: PRODUCT)
    reviews = scraper.reviews("W009315804")
    assert len(reviews) == 3 and reviews[0].rating == 5
    assert len(client.calls) == 1
