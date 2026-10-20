"""Turn Wayfair pages into the dataclasses in :mod:`models`.

Wayfair builds every page from "blocks". On listings, each product card is a
``...ListingCollectionItem`` object whose ``blocks`` hold the name, brand,
rating, price, delivery and stock pieces of the card. On product pages, each
section is a block with a ``block.__typename`` (``PricingFull``,
``BlockBuilderSpecificationsDetails``, ...) and its ``data``. The parsers find
those objects in the page's flight data (see :mod:`flight`) by type name, so they
do not depend on CSS classes or on where a block sits in the layout.
"""

from __future__ import annotations

import html as htmllib
import re
from datetime import datetime
from typing import Any

from .errors import ParseError
from .flight import Flight
from .models import (
    FilterOption,
    OptionChoice,
    Product,
    ProductDetail,
    Review,
    SearchPage,
)
from .urls import CDN, PAGE_SIZE, SORT_NAMES, clean_product_url, image_url, sku_from_url

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_PERCENT = re.compile(r"(\d+)\s*%")


# -- small helpers ---------------------------------------------------------------


def _get(node: Any, *path: Any) -> Any:
    for key in path:
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list) and isinstance(key, int):
            node = node[key] if -len(node) <= key < len(node) else None
        else:
            return None
    return node


def _find(node: Any, key: str) -> Any:
    """The first non-empty value of ``key`` anywhere under ``node`` (depth first)."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            value = current.get(key)
            if value not in (None, "", [], {}):
                return value
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def _flight(html: str) -> Flight:
    flight = Flight.from_html(html)
    if not flight:
        raise ParseError("the page has no Wayfair page data (blocked or not a Wayfair page?)")
    return flight


def page_title(html: str) -> str | None:
    match = _TITLE.search(html)
    if not match:
        return None
    title = " ".join(htmllib.unescape(match.group(1)).split())
    return re.sub(r"\s*\|\s*Wayfair.*$", "", title) or None


def has_listing(html: str) -> bool:
    """Listing pages (even past the last page) carry Wayfair's result count."""
    return "self.__next_f" in html and "resultCount" in html


def has_product(html: str) -> bool:
    return "self.__next_f" in html and "ListingHeader" in html


# -- prices ----------------------------------------------------------------------


def parse_pricing(pricing: Any, value_prop: Any = None) -> dict[str, Any]:
    """Price fields from a Wayfair ``pricing`` object (cards and product pages).

    ``allPrices`` lists the prices a card displays by role: ``PRIMARY`` (or
    ``SALE`` with a "Sale"/"Closeout" label) is the price, ``PREVIOUS`` the
    struck-through one, ``SECONDARY`` with an "per item" suffix the unit price of
    a multi-pack and ``CONTRAST`` the potential Wayfair Rewards member savings.
    """
    out: dict[str, Any] = {}
    for entry in _get(pricing, "allPrices") or []:
        if not isinstance(entry, dict):
            continue
        price = entry.get("price") or {}
        amount = _float(_get(price, "value", "amount"))
        currency = _get(price, "value", "currency", "code")
        if currency:
            out.setdefault("currency", currency)
        role = entry.get("priceVariation")
        if role in ("PRIMARY", "SALE") and "price" not in out:
            out["price"] = amount
            if role == "SALE":
                out["price_label"] = entry.get("label") or "Sale"
        elif role == "PREVIOUS":
            out["was_price"] = amount
        elif role == "SECONDARY" and "item" in (price.get("suffix") or ""):
            out["unit_price"] = amount
        elif role == "CONTRAST":
            out["member_savings"] = amount
    info = value_prop or _get(pricing, "standardValuePropInfo") or {}
    label = _get(info, "pricingInfo", "savingsPercentageLabel", "message") or _get(
        pricing, "percentageOffMessage"
    )
    match = _PERCENT.search(label or "")
    if match:
        out["discount_percent"] = int(match.group(1))
    elif out.get("price") and out.get("was_price") and out["was_price"] > out["price"]:
        out["discount_percent"] = round((1 - out["price"] / out["was_price"]) * 100)
    deal = _get(info, "limitedTimeDeal") or _get(pricing, "limitedTimeDeal") or {}
    if isinstance(deal, dict) and deal.get("message"):
        out["deal"] = deal["message"]
        out["deal_ends"] = deal.get("endDate")
    return out


# -- listings --------------------------------------------------------------------


def _is_card(node: dict[str, Any]) -> bool:
    kind = node.get("__typename")
    return (
        isinstance(kind, str)
        and kind.endswith("ListingCollectionItem")
        and not kind.startswith("Display")  # sponsored-brand banners above the grid
        and "blocks" in node
    )


def _blocks(card: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for block in card.get("blocks") or []:
        if isinstance(block, dict) and isinstance(block.get("__typename"), str):
            found.setdefault(block["__typename"], block)
    return found


def _selected_choices(selections: Any) -> list[tuple[str | None, str]]:
    pairs = []
    for selection in selections or []:
        for choice in _get(selection, "selectedChoices") or []:
            name = _get(choice, "name")
            if name:
                pairs.append((_get(choice, "choiceCategory", "name"), name))
    return pairs


def parse_card(card: dict[str, Any], currency: str = "USD") -> Product | None:
    """One product card (with references already resolved)."""
    blocks = _blocks(card)
    variant = card.get("listingVariant") or {}
    sku = _get(variant, "listing", "displayListingId") or _find(card, "displayListingId")
    if not sku:
        return None
    image_block = blocks.get("ListingCardImageCarousel") or blocks.get("ListingCardImage") or {}
    image_variant = image_block.get("listingVariant") or {}
    name = (
        _get(blocks, "ListingCardName", "listingVariant", "displayName")
        or variant.get("displayName")
        or image_variant.get("displayName")
        or ""
    )
    reviews = _get(blocks, "ListingCardReviewStars", "listingVariant", "listing", "reviews") or {}
    review_count = _int(reviews.get("totalCount")) or 0
    price_block = blocks.get("PricingStandard") or blocks.get("ListingPricing") or {}
    prices = parse_pricing(_get(price_block, "listingVariant", "pricing"))
    choices = _selected_choices(
        _get(blocks, "ListingCardSelectedChoices", "listingVariant", "selections")
    )
    option = "; ".join(f"{group}: {name}" if group else name for group, name in choices) or None
    available = _get(blocks, "ListingCardAvailableChoices", "listingVariant") or {}
    options = {
        preview["name"]: _int(preview.get("count")) or 0
        for preview in _get(available, "listing", "choicePreview") or []
        if isinstance(preview, dict) and preview.get("name")
    }
    if not options and _get(available, "visualChoicesPreview", "count"):
        options = {"Options": _int(_get(available, "visualChoicesPreview", "count")) or 0}
    delivery = _get(
        blocks,
        "ShippingWidget",
        "listingOrBasket",
        "fulfillment",
        "defaultDeliveryOptionInformation",
    )
    highlights = {}
    for edge in (
        _get(
            blocks,
            "ListingCardSpecifications",
            "listingVariant",
            "specificationHighlights",
            "edges",
        )
        or []
    ):
        key, value = _text(_get(edge, "node", "key")), _text(_get(edge, "node", "value"))
        if key and value:
            highlights[key] = value
    primary_class = _find(card, "primaryClass") or {}
    url = card.get("url") or variant.get("listingUrl") or ""
    return Product(
        position=(_int(card.get("index")) or 0) + 1,
        sku=str(sku),
        name=_text(name) or "",
        url=clean_product_url(url) if url else "",
        brand=_get(
            blocks, "ListingCardManufacturer", "listingVariant", "listing", "manufacturer", "name"
        ),
        price=prices.get("price"),
        was_price=prices.get("was_price"),
        discount_percent=prices.get("discount_percent"),
        price_label=prices.get("price_label"),
        unit_price=prices.get("unit_price"),
        member_savings=prices.get("member_savings"),
        deal=prices.get("deal"),
        deal_ends=prices.get("deal_ends"),
        currency=prices.get("currency") or currency,
        rating=_float(reviews.get("averageRating")) if review_count else None,
        review_count=review_count,
        option=option,
        option_id=_int(_get(variant, "selections", 0, "selectedChoices", 0, "displayId")),
        options=options,
        flag=_get(image_variant, "flag", "flagText"),
        delivery=_get(delivery, "deliveryPromiseMessage", "text"),
        arrives=_get(delivery, "estimatedArrivalMessages", "estimatedArrivalMessage"),
        stock_status=_find(card, "stockStatus"),
        stock_message=_get(
            blocks,
            "BasicInventoryWidget",
            "listingVariant",
            "fulfillment",
            "shortInventoryStatusMessage",
        ),
        sponsored=str(card.get("__typename", "")).startswith("Sponsored"),
        wayfair_verified=bool(variant.get("isBestValue") or image_variant.get("isBestValue")),
        category=_get(primary_class, "category", "displayName"),
        category_id=_int(_get(primary_class, "category", "categoryId")),
        highlights=highlights,
        image=image_url(_find(image_variant, "imageId")),
    )


def _selected_filters(raw: Any) -> list[dict[str, Any]]:
    out = []
    for item in raw or []:
        if not isinstance(item, dict) or not item.get("filterId"):
            continue
        entry: dict[str, Any] = {"filter_id": str(item["filterId"])}
        if item.get("optionId") is not None:
            entry["option_id"] = str(item["optionId"])
        if item.get("optionRangeStart") is not None or item.get("optionRangeEnd") is not None:
            entry["low"] = _float(item.get("optionRangeStart"))
            entry["high"] = _float(item.get("optionRangeEnd"))
        out.append(entry)
    return out


def parse_listing(html: str, url: str, *, page: int = 1, currency: str = "USD") -> SearchPage:
    """A search or category listing page."""
    flight = _flight(html)
    cards: dict[Any, Product] = {}
    pagination: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    for node in flight.objects():
        if _is_card(node):
            product = parse_card(flight.deep(node), currency)
            if product is not None:
                cards.setdefault(node.get("index", len(cards)), product)
        elif _get(node, "config", "__typename") == "BlockBuilderBrowsePagination":
            pagination = pagination or node
        elif "selectedSortId" in node and "resultCount" in node:
            summary = summary or node
    if not pagination and not summary:
        raise ParseError(
            f"no Wayfair product grid on {url} (brand and department hub pages have none; "
            "open a category such as .../furniture/sb0/office-chairs-c478390.html and "
            "filter it by brand)"
        )
    products = sorted(cards.values(), key=lambda product: product.position)
    total = _int(pagination.get("numberOfItems"))
    if total is None:
        total = _int(summary.get("resultCount")) or 0
    sort_id = summary.get("selectedSortId")
    result = SearchPage(
        url=flight.resolve(pagination.get("requestURL")) or url,
        page=_int(pagination.get("pageNumber")) or page,
        products=products,
        total_results=total,
        page_size=_int(pagination.get("itemsPerPage")) or PAGE_SIZE,
        sort=SORT_NAMES.get(sort_id, sort_id.lower() if isinstance(sort_id, str) else None),
        title=page_title(html),
        selected_filters=_selected_filters(flight.deep(summary.get("selectedFilters"))),
    )
    result.complete = len(products) >= result.expected
    return result


# -- filters ---------------------------------------------------------------------


def _filter_options(node: dict[str, Any], group: str) -> list[FilterOption]:
    kind = node.get("__typename")
    name = _text(node.get("displayName")) or ""
    label = f"{group} / {name}" if group and name and name != group else (name or group)
    filter_id = str(node.get("filterId") or "")
    out: list[FilterOption] = []

    def option(choice: dict[str, Any]) -> FilterOption:
        option_id = str(choice.get("filterOptionId"))
        text = _text(choice.get("displayName")) or ""
        if not text or text.startswith("&"):  # ratings: "" (5 stars) or "& up"
            text = (
                f"{option_id} stars {text}" if "rating" in label.lower() else f"{option_id} {text}"
            )
        return FilterOption(
            group=label,
            name=text.strip(),
            filter_id=filter_id,
            option_id=option_id,
            selected=bool(choice.get("isSelected")),
        )

    if kind == "FilterFeatured" and isinstance(node.get("option"), dict):
        out.append(option(node["option"]))
    for choice in node.get("options") or []:
        if isinstance(choice, dict) and choice.get("filterOptionId") is not None:
            out.append(option(choice))
    if kind == "FilterWithNumericRanges":
        units = _text(node.get("units"))
        buckets = [b for b in node.get("buckets") or [] if isinstance(b, dict)]
        span = node.get("range") or {}
        for bucket in buckets or [span]:
            low = _float(bucket.get("optionRangeStart", bucket.get("minValue")))
            high = _float(bucket.get("optionRangeEnd", bucket.get("maxValue")))
            if bucket is span:
                low, high = _float(span.get("minValue")), _float(span.get("maxValue"))
            out.append(
                FilterOption(
                    group=label,
                    name=_text(bucket.get("displayName"))
                    or (f"range ({units})" if units else "range"),
                    filter_id=filter_id,
                    kind="price" if units == "$" or "rice" in label else "range",
                    low=low,
                    high=high,
                    selected=bool(bucket.get("isSelected")),
                )
            )
    for sub in node.get("subSections") or []:
        if isinstance(sub, dict):
            out.extend(_filter_options(sub, label))
    return out


def parse_filters(html: str, url: str) -> list[FilterOption]:
    """Every filter option a listing offers (brands, colors, price bands, ...)."""
    flight = _flight(html)
    for node in flight.objects():
        if _get(node, "config", "__typename") == "BlockBuilderBrowseFilters" and "data" in node:
            filters = flight.deep(_get(node, "data", "filters")) or []
            out: list[FilterOption] = []
            for item in filters:
                if isinstance(item, dict):
                    out.extend(_filter_options(item, ""))
            return out
    if has_listing(html):
        return []
    raise ParseError(f"no Wayfair filters on {url}")


def price_filter_id(filters: list[FilterOption]) -> str | None:
    """The id of a listing's price filter (``88`` on most categories)."""
    for item in filters:
        if item.kind == "price" and item.filter_id.isdigit():
            return item.filter_id
    return None


# -- product pages ---------------------------------------------------------------


def _page_blocks(flight: Flight) -> dict[str, dict[str, Any]]:
    """``{block type: {"data": ..., "variables": ...}}`` for a product page."""
    found: dict[str, dict[str, Any]] = {}
    for node in flight.objects():
        kind = _get(node, "block", "__typename")
        if isinstance(kind, str) and "data" in node and kind not in found:
            found[kind] = {
                "data": flight.deep(node["data"]) or {},
                "variables": flight.deep(node.get("variables")) or {},
            }
    return found


def _specs(groups: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in groups or []:
        for item in _get(group, "items") or []:
            key, value = _text(_get(item, "key")), _text(_get(item, "value"))
            if key and value is not None:
                out[key] = value
            for child in _get(item, "children") or []:
                child_key, child_value = _text(_get(child, "key")), _text(_get(child, "value"))
                if child_key and child_value is not None:
                    out[child_key] = child_value
    return out


def review_date(text: Any) -> str | None:
    """``"10/18/2026"`` -> ``"2026-10-18"`` (other formats are returned unchanged)."""
    if not isinstance(text, str) or not text:
        return None
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return text


def parse_reviews(container: Any) -> list[Review]:
    reviews = []
    for edge in _get(container, "reviewslist", "reviews", "edges") or []:
        node = _get(edge, "node") or {}
        if not isinstance(node, dict) or not node.get("body") and not node.get("rating"):
            continue
        reviews.append(
            Review(
                review_id=_int(node.get("reviewId")),
                rating=_int(node.get("rating")),
                date=review_date(node.get("formattedDate")),
                author=_text(node.get("reviewerGivenName")),
                location=_text(node.get("reviewerLocation")),
                text=(node.get("body") or "").strip(),
                verified_purchase=node.get("badge") == "Verified Purchase",
                options=[
                    name
                    for name in (_get(choice, "name") for choice in node.get("choices") or [])
                    if name
                ],
            )
        )
    return reviews


def _options(container: Any) -> list[OptionChoice]:
    out = []
    for category in _get(container, "choiceCategories") or []:
        group = _get(category, "name") or "Option"
        selected = _get(category, "selectedVariantChoice", "choice", "displayId")
        for edge in _get(category, "variantChoices", "edges") or []:
            node = _get(edge, "node") or {}
            choice = node.get("choice") or {}
            option_id = _int(choice.get("displayId"))
            variant = node.get("selectableVariant") or {}
            url = variant.get("listingUrl")
            out.append(
                OptionChoice(
                    category=group,
                    name=_text(choice.get("name")) or "",
                    option_id=option_id,
                    stock_status=_get(variant, "fulfillmentv2", "stockStatus"),
                    selected=option_id is not None and option_id == _int(selected),
                    url=clean_product_url(url) if url else None,
                    image=image_url(_get(variant, "leadImageEntity", "imageId")),
                )
            )
    return out


def parse_product(html: str, url: str, *, currency: str = "USD") -> ProductDetail:
    """A product page: price, stock, specifications, options, images and reviews."""
    flight = _flight(html)
    blocks = _page_blocks(flight)
    header = _get(blocks, "ListingHeader", "data")
    if not header:
        raise ParseError(f"no Wayfair product on {url}")
    listing = header.get("listing") or {}
    pricing_data = _get(blocks, "PricingFull", "data") or {}
    pricing = pricing_data.get("pricing") or {}
    prices = parse_pricing(pricing, pricing.get("fullComplexValuePropInfo"))
    if not prices.get("deal") and isinstance(pricing_data.get("limitedTimeDeal"), dict):
        prices["deal"] = pricing_data["limitedTimeDeal"].get("message")
        prices["deal_ends"] = pricing_data["limitedTimeDeal"].get("endDate")
    reviews_block = _get(blocks, "BlockBuilderReviewContainer", "data") or {}
    histogram = {
        str(entry.get("rating")): _int(entry.get("totalCount")) or 0
        for entry in _get(reviews_block, "reviewsHistogram", "reviews", "ratingHistogram") or []
        if isinstance(entry, dict) and entry.get("rating") is not None
    }
    fulfillment = (
        _get(
            blocks,
            "BlockBuilderShippingWidgetCardAndOverlay",
            "data",
            "node",
            "listingOrBasket",
            "fulfillment",
        )
        or {}
    )
    delivery = fulfillment.get("defaultDeliveryOptionInformation") or {}
    choices = _get(blocks, "MarketplaceListingChoicesContainer", "data") or {}
    variables = _get(blocks, "BlockBuilderReviewContainer", "variables") or {}
    media = _get(blocks, "BlockBuilderMediaTrayGrid", "data", "media", "edges") or []
    images, videos = [], []
    for edge in media:
        node = _get(edge, "node") or {}
        if node.get("videoId") is not None or node.get("__typename") == "Video":
            source = next(
                (s.get("url") for s in node.get("sources") or [] if isinstance(s, dict)), None
            )
            if source:
                videos.append(source)
        elif node.get("imageId"):
            images.append(image_url(node["imageId"], 1200))
    documents = []
    for doc in (
        _get(blocks, "BlockBuilderMarketplaceListingDocuments", "data", "listing", "documents")
        or []
    ):
        link = _get(doc, "url")
        if link:
            documents.append(
                {
                    "type": str(_get(doc, "documentType") or "").lower(),
                    "url": link if link.startswith("http") else f"{CDN}{link}",
                }
            )
    breadcrumbs = _get(blocks, "BlockBuilderBreadcrumbs", "data") or []
    categories = [
        crumb["text"]
        for crumb in breadcrumbs
        if isinstance(crumb, dict) and crumb.get("categoryId") and crumb.get("text")
    ]
    category_ids = [_int(c.get("categoryId")) for c in breadcrumbs if isinstance(c, dict)]
    category_ids = [c for c in category_ids if c]
    verified = _get(blocks, "BlockBuilderVerifiedModule", "data") or {}
    review_count = _int(_get(listing, "reviews", "totalCount")) or 0
    selected = {
        str(_get(category, "name")): str(_get(category, "selectedVariantChoice", "choice", "name"))
        for category in choices.get("choiceCategories") or []
        if _get(category, "selectedVariantChoice", "choice", "name")
    }
    listing_url = header.get("listingUrl") or url
    sku = (
        _get(choices, "listing", "displayListingId")
        or variables.get("sku")
        or sku_from_url(listing_url)
        or ""
    )
    return ProductDetail(
        sku=str(sku),
        name=_text(header.get("displayName")) or "",
        url=clean_product_url(listing_url),
        brand=_get(listing, "manufacturer", "name"),
        brand_url=_get(listing, "manufacturer", "url"),
        collection=_get(listing, "manufacturerCollection", "collectionName"),
        option_id=_int(_get(choices, "selections", 0, "selectedChoices", 0, "displayId")),
        selected_options=selected,
        price=prices.get("price"),
        was_price=prices.get("was_price"),
        discount_percent=prices.get("discount_percent"),
        price_label=prices.get("price_label"),
        unit_price=prices.get("unit_price"),
        member_savings=prices.get("member_savings"),
        deal=prices.get("deal"),
        deal_ends=prices.get("deal_ends"),
        currency=prices.get("currency") or currency,
        rating=_float(_get(listing, "reviews", "averageRating")) if review_count else None,
        review_count=review_count,
        rating_histogram=histogram,
        stock_status=fulfillment.get("stockStatus"),
        stock_message=_text(fulfillment.get("detailedInventoryStatusMessage")),
        delivery=_get(delivery, "deliveryPromiseMessage", "text"),
        arrives=_get(delivery, "estimatedArrivalMessages", "estimatedArrivalMessage"),
        wayfair_verified=bool(header.get("isBestValue") or verified.get("isBestValue")),
        verified_highlights=[
            b
            for b in _get(verified, "verifiedValueProp", "bulletListSection", "bullets") or []
            if b
        ],
        description=_text(_get(blocks, "BlockBuilderRomanceCopy", "data", "marketingCopy")),
        features=[
            f
            for f in _get(blocks, "BlockBuilderFeatureBullets", "data", "featureBullets") or []
            if f
        ],
        specifications=_specs(
            _get(blocks, "BlockBuilderSpecificationsDetails", "data", "specifications_details")
        ),
        dimensions=_specs(
            _get(blocks, "BlockBuilderStructuredDimensions", "data", "structuredDimensions")
        ),
        assembly=_specs(
            _get(blocks, "BlockBuilderSpecificationsAssembly", "data", "specifications_assembly")
        ),
        warranty=_specs(
            _get(blocks, "BlockBuilderSpecificationsWarranty", "data", "specifications_warranties")
        ),
        categories=categories,
        category_id=category_ids[-1] if category_ids else None,
        options=_options(choices),
        images=images,
        videos=videos,
        documents=documents,
        part_number=_text(header.get("partNumber") or pricing_data.get("partNumber")),
        prop65_warning=_text(
            _get(blocks, "BlockBuilderProposition65Block", "data", "exposureWarning")
        ),
        reviews=parse_reviews(reviews_block),
    )
