"""Dataclasses for what the scraper returns. Every one has ``to_dict()``."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


def _money(value: float | None) -> str:
    return "-" if value is None else f"${value:,.2f}"


def _short(text: str | None, width: int = 60) -> str:
    text = text or ""
    return text if len(text) <= width else text[: width - 3] + "..."


@dataclass
class Product:
    """One product card from a Wayfair search or category listing.

    ``price`` is the price the card shows (the sale price during a sale) and
    ``was_price`` the struck-through one. ``unit_price`` is set for multi-packs
    ("$39.50 per item"). ``member_savings`` is the extra amount Wayfair Rewards
    members would save, when the card shows it. ``option`` is the variant the card
    shows, e.g. ``"Fabric: Blue Velvet"``, and ``options`` counts the choices
    (``{"Colors": 7}``). ``delivery`` and ``arrives`` are Wayfair's own messages,
    which depend on the delivery location Wayfair infers for the request.
    ``highlights`` are the key specifications category pages show on each card
    (``{"Product Type": "Task Chair", "Weight Capacity": "300 lb."}``).
    """

    position: int
    sku: str
    name: str
    url: str
    brand: str | None = None
    price: float | None = None
    was_price: float | None = None
    discount_percent: int | None = None
    price_label: str | None = None
    unit_price: float | None = None
    member_savings: float | None = None
    deal: str | None = None
    deal_ends: str | None = None
    currency: str = "USD"
    rating: float | None = None
    review_count: int = 0
    option: str | None = None
    option_id: int | None = None
    options: dict[str, int] = field(default_factory=dict)
    flag: str | None = None
    delivery: str | None = None
    arrives: str | None = None
    stock_status: str | None = None
    stock_message: str | None = None
    sponsored: bool = False
    wayfair_verified: bool = False
    category: str | None = None
    category_id: int | None = None
    highlights: dict[str, str] = field(default_factory=dict)
    image: str | None = None

    TABLE_HEADER: ClassVar[tuple[str, ...]] = (
        "#",
        "sku",
        "price",
        "was",
        "rating",
        "reviews",
        "brand",
        "name",
    )

    def table_row(self) -> tuple[Any, ...]:
        return (
            self.position,
            self.sku,
            _money(self.price),
            _money(self.was_price) if self.was_price else "",
            f"{self.rating:.2f}" if self.rating is not None else "-",
            self.review_count,
            _short(self.brand, 24),
            _short(self.name, 60) + (" [ad]" if self.sponsored else ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchPage:
    """One page of a listing: its products plus the totals Wayfair reports.

    ``url`` is the page Wayfair actually served: a keyword search often lands on
    a category (``.../sb0/office-chairs-c478390.html``). ``complete`` is False
    when Wayfair left some cards to be loaded by the browser later (see the
    README); the scraper re-requests such pages.
    """

    url: str
    page: int
    products: list[Product]
    total_results: int
    page_size: int = 48
    sort: str | None = None
    title: str | None = None
    selected_filters: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = True

    @property
    def expected(self) -> int:
        """How many cards this page should hold according to Wayfair's totals."""
        remaining = self.total_results - (self.page - 1) * self.page_size
        return max(0, min(self.page_size, remaining))

    @property
    def total_pages(self) -> int:
        return -(-self.total_results // self.page_size) if self.page_size else 0

    @property
    def has_more(self) -> bool:
        return self.page < self.total_pages and bool(self.products)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_pages"] = self.total_pages
        return data


@dataclass
class FilterOption:
    """A filter value a listing offers, e.g. Brand = Steelcase (``86:1944``).

    Pass ``ref`` to ``--filter`` / ``SearchQuery(filters=[...])``. Price bands
    have ``kind="price"`` with ``low``/``high`` bounds (``high`` is ``None`` for
    "$400 & Above"); their ``filter_id`` is what ``SearchQuery(price_filter=...)``
    takes, though the scraper finds it on its own. Size ranges (inches) have
    ``kind="range"``.
    """

    group: str
    name: str
    filter_id: str
    option_id: str | None = None
    kind: str = "option"
    low: float | None = None
    high: float | None = None
    selected: bool = False

    TABLE_HEADER: ClassVar[tuple[str, ...]] = ("group", "filter", "value", "kind")

    @property
    def ref(self) -> str | None:
        return f"{self.filter_id}:{self.option_id}" if self.option_id is not None else None

    def table_row(self) -> tuple[Any, ...]:
        if self.kind == "price":
            high = _money(self.high) if self.high is not None else ""
            value = (
                f"{self.filter_id} {_money(self.low)}-{high}"
                if high
                else f"{self.filter_id} {_money(self.low)}+"
            )
        elif self.kind == "range":
            value = f"{self.filter_id} {self.low or 0:g}-{self.high or 0:g}"
        else:
            value = self.ref or self.filter_id
        name = self.name + (" (selected)" if self.selected else "")
        return (_short(self.group, 28), value, _short(name, 40), self.kind)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ref"] = self.ref
        return data


@dataclass
class OptionChoice:
    """One choice of a product option (a fabric, a color, a size, ...)."""

    category: str
    name: str
    option_id: int | None = None
    stock_status: str | None = None
    selected: bool = False
    url: str | None = None
    image: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Review:
    """A customer review from a product page. ``date`` is ISO (``YYYY-MM-DD``)."""

    review_id: int | None
    rating: int | None
    date: str | None
    author: str | None
    location: str | None
    text: str
    verified_purchase: bool = False
    options: list[str] = field(default_factory=list)

    TABLE_HEADER: ClassVar[tuple[str, ...]] = ("date", "rating", "author", "review")

    def table_row(self) -> tuple[Any, ...]:
        return (
            self.date or "-",
            self.rating or "-",
            _short(self.author, 20),
            _short(self.text, 70),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductDetail:
    """Everything a Wayfair product page shows for the selected option."""

    sku: str
    name: str
    url: str
    brand: str | None = None
    brand_url: str | None = None
    collection: str | None = None
    option_id: int | None = None
    selected_options: dict[str, str] = field(default_factory=dict)
    price: float | None = None
    was_price: float | None = None
    discount_percent: int | None = None
    price_label: str | None = None
    unit_price: float | None = None
    member_savings: float | None = None
    deal: str | None = None
    deal_ends: str | None = None
    currency: str = "USD"
    rating: float | None = None
    review_count: int = 0
    rating_histogram: dict[str, int] = field(default_factory=dict)
    stock_status: str | None = None
    stock_message: str | None = None
    delivery: str | None = None
    arrives: str | None = None
    wayfair_verified: bool = False
    verified_highlights: list[str] = field(default_factory=list)
    description: str | None = None
    features: list[str] = field(default_factory=list)
    specifications: dict[str, str] = field(default_factory=dict)
    dimensions: dict[str, str] = field(default_factory=dict)
    assembly: dict[str, str] = field(default_factory=dict)
    warranty: dict[str, str] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)
    category_id: int | None = None
    options: list[OptionChoice] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    videos: list[str] = field(default_factory=list)
    documents: list[dict[str, str]] = field(default_factory=list)
    part_number: str | None = None
    prop65_warning: str | None = None
    reviews: list[Review] = field(default_factory=list)

    TABLE_HEADER: ClassVar[tuple[str, ...]] = (
        "sku",
        "price",
        "was",
        "rating",
        "reviews",
        "stock",
        "name",
    )

    def table_row(self) -> tuple[Any, ...]:
        return (
            self.sku,
            _money(self.price),
            _money(self.was_price) if self.was_price else "",
            f"{self.rating:.2f}" if self.rating is not None else "-",
            self.review_count,
            self.stock_message or self.stock_status or "-",
            _short(self.name, 60),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
