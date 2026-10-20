from __future__ import annotations

import pytest

from wayfair_scraper.urls import (
    SearchQuery,
    apply_filters,
    clean_product_url,
    image_url,
    is_category_url,
    keyword_url,
    page_url,
    parse_filter,
    product_url,
    site_of,
    sku_from_url,
    with_params,
)

CHAIRS = "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html"


def test_keyword_and_page_urls():
    assert (
        keyword_url(" office chair ") == "https://www.wayfair.com/keyword.php?keyword=office+chair"
    )
    assert keyword_url("sofa", "ca") == "https://www.wayfair.ca/keyword.php?keyword=sofa"
    assert page_url(CHAIRS) == CHAIRS
    assert page_url(CHAIRS, 3, "price-low") == CHAIRS + "?curpage=3&sortby=2"
    assert page_url(CHAIRS + "?sortby=3&curpage=2", 1) == CHAIRS + "?sortby=3"
    assert page_url(CHAIRS + "?sortby=3", 2, "recommended") == CHAIRS + "?curpage=2"
    assert page_url(CHAIRS, 1, "rating").endswith("?sortby=7")
    with pytest.raises(ValueError):
        page_url(CHAIRS, 0)
    with pytest.raises(ValueError):
        page_url(CHAIRS, 1, "cheapest")


def test_with_params_keeps_other_parameters():
    url = "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html?redir=office+chair&rtype=9"
    assert with_params(url, curpage=2) == url + "&curpage=2"
    assert with_params(url + "&curpage=2", curpage=None) == url


def test_apply_filters_writes_wayfair_filter_paths():
    assert apply_filters(CHAIRS) == CHAIRS
    assert (
        apply_filters(CHAIRS, [("86", "1944")])
        == "https://www.wayfair.com/furniture/sb1/office-chairs-c478390-a86~1944.html"
    )
    both = apply_filters(CHAIRS + "?redir=office+chair", [("4576", "474790")], ("88", 0, 150))
    assert both == (
        "https://www.wayfair.com/furniture/sb2/office-chairs-c478390-a4576~474790-p88~0~150.html"
        "?redir=office+chair"
    )
    # existing filters are kept, repeats dropped, the price range replaced
    again = apply_filters(both, [("4576", "474790"), ("86", "1944")], ("88", 99.5, None))
    assert "/sb3/office-chairs-c478390-a4576~474790-a86~1944-p88~99.50~1000000.html" in again
    with pytest.raises(ValueError, match="category URL"):
        apply_filters("https://www.wayfair.com/keyword.php?keyword=sofa", [("86", "1944")])
    with pytest.raises(ValueError):
        apply_filters("https://www.wayfair.com/brand/bnd/mercury-row-b33808.html", [("1", "2")])


def test_is_category_url():
    assert is_category_url(CHAIRS)
    assert is_category_url("https://www.wayfair.ca/furniture/sb1/x-c478390-a86~1944.html?curpage=2")
    assert not is_category_url(
        "https://www.wayfair.com/furniture/cat/office-furniture-c332627.html"
    )
    assert not is_category_url("https://www.wayfair.com/keyword.php?keyword=sofa")


def test_parse_filter_forms():
    assert parse_filter("86:1944") == ("86", "1944")
    assert parse_filter(" 86 = 1944 ") == ("86", "1944")
    assert parse_filter("86~1944") == ("86", "1944")
    for bad in ("brand", "86:", "x:1", "86:19 44"):
        with pytest.raises(ValueError):
            parse_filter(bad)


def test_product_urls_and_skus():
    assert product_url("w009315804") == "https://www.wayfair.com/keyword.php?keyword=W009315804"
    assert product_url("C005584693", "ca").startswith("https://www.wayfair.ca/")
    url = "https://www.wayfair.com/furniture/pdp/mercury-row-perdue-w009315804.html?piid=1134429065"
    assert product_url(url) == url
    for bad in ("not a sku", "https://www.example.com/pdp/x-w1234.html", "12345"):
        with pytest.raises(ValueError):
            product_url(bad)
    assert sku_from_url(url) == "W009315804"
    assert sku_from_url("https://www.wayfair.com/keyword.php?keyword=sofa") is None
    tracked = url + "&auctionId=abc&trackingId=%7B%7D#reviews"
    assert clean_product_url(tracked) == url


def test_image_url_and_site():
    assert image_url(194742536) == (
        "https://assets.wfcdn.com/im/00000000/resize-h800-w800%5Ecompr-r85/1947/194742536/image.jpg"
    )
    assert "resize-h1200-w1200" in image_url("201595491", 1200)
    assert image_url(None) is None
    assert site_of("https://www.wayfair.ca/x") == "ca"
    with pytest.raises(ValueError):
        site_of("https://www.wayfair.co.uk/x")


def test_search_query_validation():
    query = SearchQuery("office chair", sort="rating", filters=["86:1944"], max_price=300)
    assert query.start_url.endswith("keyword=office+chair") and query.currency == "USD"
    assert query.filters == [("86", "1944")] and query.needs_category and query.has_price
    with pytest.raises(ValueError, match="price_filter"):
        query.listing_url(CHAIRS)
    priced = SearchQuery(url=CHAIRS, max_price=300, price_filter="88")
    assert priced.listing_url().endswith("/sb1/office-chairs-c478390-p88~0~300.html")
    from_url = SearchQuery("https://www.wayfair.ca/furniture/sb0/office-chairs-c478390.html")
    assert from_url.url and from_url.site == "ca" and from_url.currency == "CAD"
    assert not SearchQuery("sofa").needs_category
    for kwargs in (
        {},
        {"keywords": "sofa", "sort": "cheapest"},
        {"keywords": "sofa", "min_price": -1},
        {"keywords": "sofa", "min_price": 50, "max_price": 10},
        {"keywords": "sofa", "site": "uk"},
        {"keywords": "sofa", "filters": ["brand"]},
        {"url": "https://www.example.com/sofas"},
    ):
        with pytest.raises(ValueError):
            SearchQuery(**kwargs)
