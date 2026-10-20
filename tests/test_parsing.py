from __future__ import annotations

import pytest
from conftest import PRICE_FILTER, fixture_html, listing_html

from wayfair_scraper import ParseError
from wayfair_scraper.parsing import (
    has_listing,
    has_product,
    page_title,
    parse_filters,
    parse_listing,
    parse_pricing,
    parse_product,
    price_filter_id,
    review_date,
)

CATEGORY = fixture_html("category_office_chairs_p2.html")
FILTERED = fixture_html("category_filtered_price_low.html")
CANADA = fixture_html("search_ca_office_chair.html")
PAST_END = fixture_html("category_past_end.html")
PRODUCT = fixture_html("product_W009315804.html")


def test_category_listing_page():
    page = parse_listing(CATEGORY, "https://www.wayfair.com/x")
    assert page.url == "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html?curpage=2"
    assert (page.page, page.page_size, page.total_results) == (2, 48, 20026)
    assert page.total_pages == 418 and page.has_more
    assert page.sort == "recommended"
    assert page.title == "Office Chairs | Office Furniture & Home Office Furniture"
    # the fixture keeps 7 of the page's 48 cards, so it reads as a short page
    assert page.expected == 48 and not page.complete
    assert [p.position for p in page.products] == [1, 2, 3, 4, 5, 7, 13]


def test_card_fields():
    chair = parse_listing(CATEGORY, "u").products[0]
    assert chair.sku == "W116084446"
    assert chair.name.startswith("Upholstered Office Chair Adjustable Height")
    assert chair.url.endswith("-w116084446.html?piid=2037668915")
    assert chair.brand == "George Oliver"
    assert (chair.price, chair.was_price, chair.discount_percent) == (169.99, 369.99, 54)
    assert chair.currency == "USD" and chair.price_label is None
    assert (chair.rating, chair.review_count) == (4.72, 158)
    assert chair.option == "Upholstery Color: Green Chenille" and chair.option_id == 2037668915
    assert chair.options == {"Colors": 6}
    assert chair.flag == "Sale"
    assert (chair.delivery, chair.arrives) == ("FREE 1-Day Delivery", "Get it Tomorrow")
    assert (chair.stock_status, chair.stock_message) == ("IN_STOCK", "130 Left in Stock")
    assert not chair.sponsored and chair.wayfair_verified
    assert (chair.category, chair.category_id) == ("Office Chairs", 478390)
    assert chair.highlights["Product Type"] == "Task Chair"
    assert chair.highlights["Weight Capacity"] == "300 lb."
    assert chair.image.endswith("/4620/462007258/image.jpg")


def test_sponsored_sale_and_deal_cards():
    products = {p.sku: p for p in parse_listing(CATEGORY, "u").products}
    assert products["W010300862"].sponsored
    assert products["AEOI1241"].price_label == "Sale"
    deal = products["W117456599"]
    assert deal.deal == "24 Hour Deal" and deal.deal_ends == "2026-10-21T03:59:00Z"
    assert deal.flag == "24 Hour Preview"
    assert products["W115306316"].stock_message == "Low Stock"


def test_filtered_sorted_listing_and_unit_price():
    page = parse_listing(FILTERED, "u")
    assert page.sort == "price-low" and page.page == 2 and page.total_results == 1692
    assert "/sb2/" in page.url and "-a4576~474790-p88~0~150.html" in page.url
    assert {"filter_id": "4576", "option_id": "474790"} in page.selected_filters
    price = next(f for f in page.selected_filters if f["filter_id"] == "88")
    assert (price["low"], price["high"]) == (0.0, 150.0)
    first, *_, pack = page.products
    assert first.rating is None and first.review_count == 0  # no reviews -> no rating
    assert pack.unit_price == 73.5 and pack.price == 146.99


def test_canadian_search_landed_on_a_category():
    page = parse_listing(CANADA, "https://www.wayfair.ca/keyword.php?keyword=office+chair")
    assert page.url == (
        "https://www.wayfair.ca/furniture/sb0/office-chairs-c478390.html?redir=office+chair&rtype=9"
    )
    chair = page.products[0]
    assert chair.currency == "CAD" and chair.sku == "C005584693"
    assert chair.member_savings == 11.52 and chair.price_label == "Sale"
    assert chair.option == "Upholstery Colour: Black Faux Leather; Frame Colour: Gold"
    assert all(p.sponsored for p in page.products)


def test_page_past_the_end():
    page = parse_listing(PAST_END, "https://www.wayfair.com/x?curpage=3")
    assert page.products == [] and page.total_results == 0
    assert page.complete and not page.has_more
    assert page.selected_filters == [{"filter_id": "86", "option_id": "1944"}]


def test_filters():
    options = parse_filters(CATEGORY, "u")
    refs = {o.ref: o for o in options if o.ref}
    # the first two filters are references to another row on the page
    assert refs["69117:8"].group == "Sale" and refs["160857:580605"].name == "Wayfair Verified"
    assert refs["73316:607854"].group == "Color" and refs["73316:607854"].name == "Cream"
    price = [o for o in options if o.kind == "price"]
    assert price[0].name == "Under $75" and (price[0].low, price[0].high) == (0, 75)
    assert price_filter_id(options) == "88"
    sizes = [o for o in parse_filters(FILTERED, "u") if o.kind == "range"]
    assert all(o.ref is None for o in sizes)
    rating = [o for o in options if o.group == "Customer Rating"]
    assert [o.name for o in rating][:2] == ["5 stars", "4 stars & up"]
    assert parse_filters(PAST_END, "u") == []
    synthetic = parse_filters(listing_html(["W1"], 1, filters=[PRICE_FILTER]), "u")
    assert synthetic[0].name == "Under $75" and price_filter_id(synthetic) == "88"


def test_product_page():
    detail = parse_product(PRODUCT, "https://www.wayfair.com/keyword.php?keyword=W009315804")
    assert detail.sku == "W009315804"
    assert detail.name == 'Perdue 81.5" Velvet Square Arm Futon'
    assert detail.url.endswith("-w009315804.html?piid=1134429065")
    assert (detail.brand, detail.collection) == ("Mercury Row®", "Perdue")
    assert detail.brand_url == "https://www.wayfair.com/brand/bnd/mercury-row-b33808.html"
    assert detail.selected_options == {"Fabric": "Blue Velvet"} and detail.option_id == 1134429065
    assert (detail.price, detail.was_price, detail.discount_percent) == (429.99, 659.99, 35)
    assert (detail.rating, detail.review_count) == (4.41, 25571)
    assert detail.rating_histogram == {"1": 941, "2": 893, "3": 1746, "4": 5043, "5": 16948}
    assert (detail.stock_status, detail.stock_message) == ("IN_STOCK", "22 Left in Stock")
    assert (detail.delivery, detail.arrives) == ("FREE Delivery", "Get it by Tue, Oct 27")
    assert detail.wayfair_verified and len(detail.verified_highlights) == 3
    assert detail.description.startswith("This convertible sofa effortlessly transitions")
    assert detail.features[0].startswith("Seamlessly Transitions for Guests")
    assert detail.specifications["Seating Capacity"] == "3"
    assert detail.dimensions["Overall Dimensions"] == "34'' H X 81.5'' W X 34'' D"
    assert detail.assembly == {"Assembly": "Full Assembly Needed - All Tools Included"}
    assert detail.warranty["Commercial Warranty Length"] == "1 Year"
    assert detail.categories == ["Furniture", "Living Room Furniture", "Futons & Daybeds", "Futons"]
    assert detail.category_id == 1780368
    assert len(detail.options) == 7 and sum(o.selected for o in detail.options) == 1
    blue = next(o for o in detail.options if o.selected)
    assert (
        blue.name == "Blue Velvet" and blue.category == "Fabric" and blue.stock_status == "IN_STOCK"
    )
    assert len(detail.images) == 4 and detail.images[0].endswith("/1947/194742536/image.jpg")
    assert detail.videos[0].endswith(".mp4")
    assert detail.documents[0]["url"].startswith("https://assets.wfcdn.com/dm/document/")
    assert detail.prop65_warning.startswith("This product can expose you")
    review = detail.reviews[0]
    assert (review.review_id, review.rating, review.date) == (183890130, 5, "2026-10-18")
    assert review.author == "Jordan" and review.location == "Springfield, IL"
    assert review.verified_purchase and review.text.startswith("This is what we were looking")


def test_pricing_roles():
    def price(role, amount, label="", suffix=""):
        return {
            "priceVariation": role,
            "label": label,
            "price": {"value": {"amount": amount, "currency": {"code": "CAD"}}, "suffix": suffix},
        }

    out = parse_pricing(
        {
            "allPrices": [
                price("SALE", "80", "Closeout"),
                price("SECONDARY", "20", suffix="per item"),
                price("CONTRAST", "4.5", "Potential Loyalty Savings"),
                price("PREVIOUS", "100"),
            ],
            "standardValuePropInfo": {
                "limitedTimeDeal": {"message": "Flash Deal", "endDate": "2026-11-01T00:00:00Z"}
            },
        }
    )
    assert out == {
        "currency": "CAD",
        "price": 80.0,
        "price_label": "Closeout",
        "unit_price": 20.0,
        "member_savings": 4.5,
        "was_price": 100.0,
        "discount_percent": 20,  # computed when Wayfair shows no "% Off" label
        "deal": "Flash Deal",
        "deal_ends": "2026-11-01T00:00:00Z",
    }
    assert parse_pricing(None) == {}


def test_helpers_and_errors():
    assert has_listing(CATEGORY) and has_listing(PAST_END) and not has_listing(PRODUCT)
    assert has_product(PRODUCT) and not has_product(CATEGORY)
    assert review_date("10/18/2026") == "2026-10-18"
    assert review_date("2026-10-18") == "2026-10-18"
    assert review_date("18 Oct 2026") == "18 Oct 2026" and review_date(None) is None
    assert page_title("<title>Sofas &amp; Couches | Wayfair Canada</title>") == "Sofas & Couches"
    with pytest.raises(ParseError):
        parse_listing("<html>Access denied</html>", "u")
    with pytest.raises(ParseError):
        parse_product(CATEGORY, "u")
    with pytest.raises(ParseError):
        parse_listing(PRODUCT, "u")
