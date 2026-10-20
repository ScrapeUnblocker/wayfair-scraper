"""Build Wayfair listing and product URLs.

Wayfair has two kinds of listing pages:

* **keyword search**: ``/keyword.php?keyword=office+chair``. Wayfair often
  redirects a search to the matching category ("office chair" opens Office
  Chairs), and the page tells us where it landed.
* **category listings**: ``/furniture/sb0/office-chairs-c478390.html``. Filters
  live in the path: ``-a<filter>~<option>`` per selected option and
  ``-p<filter>~<min>~<max>`` for a price range, with ``sbN`` counting them:
  ``/furniture/sb2/office-chairs-c478390-a86~1944-p88~0~600.html``.

Every listing takes ``sortby`` (sort order) and ``curpage`` (page number) in the
query string. Category URLs copied from a browser keep the filters they carry.
Brand and department hub pages (``/brand/bnd/...``, ``/cat/...``) have no product
grid; filter a category by brand instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

SITES = {"us": "https://www.wayfair.com", "ca": "https://www.wayfair.ca"}
#: Wayfair's CDN for product images and documents (manuals, spec sheets).
CDN = "https://assets.wfcdn.com"
CURRENCIES = {"us": "USD", "ca": "CAD"}
_HOSTS = {"www.wayfair.com": "us", "wayfair.com": "us", "www.wayfair.ca": "ca", "wayfair.ca": "ca"}

#: Sort orders, as Wayfair's ``sortby`` values.
SORTS = {"recommended": 1, "price-low": 2, "price-high": 3, "rating": 7}
#: Wayfair's own names for the sort orders (``SearchPage.sort`` uses ours).
SORT_NAMES = {
    "RECOMMENDED": "recommended",
    "PRICE_PER_ITEM_ASC": "price-low",
    "PRICE_PER_ITEM_DESC": "price-high",
    "REVIEW_RATING": "rating",
}
PAGE_SIZE = 48
#: Upper bound Wayfair uses for an open-ended price range.
PRICE_CEILING = 1_000_000

_CATEGORY_PATH = re.compile(
    r"^/(?P<dept>[^/]+)/sb\d+/(?P<slug>[^/]*?)-c(?P<category>\d+)"
    r"(?P<parts>(?:-[ap][0-9a-z.]+(?:~[0-9a-z.]+)+)*)\.html$",
    re.IGNORECASE,
)
_PART = re.compile(r"-([ap])([0-9a-z.]+)((?:~[0-9a-z.]+)+)", re.IGNORECASE)
_SKU = re.compile(r"^[A-Za-z]{1,6}\d{3,12}$")
_PDP_SKU = re.compile(r"-([a-z]{1,6}\d{3,12})\.html$", re.IGNORECASE)


def site_of(url: str) -> str:
    """``us`` or ``ca`` for a wayfair.com / wayfair.ca URL."""
    host = urlsplit(url).netloc.lower()
    if host not in _HOSTS:
        raise ValueError(f"not a wayfair.com or wayfair.ca URL: {url}")
    return _HOSTS[host]


def site_base(site: str) -> str:
    if site not in SITES:
        raise ValueError(f"unknown site {site!r}; choose from: {', '.join(SITES)}")
    return SITES[site]


def is_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


def keyword_url(keywords: str, site: str = "us") -> str:
    return f"{site_base(site)}/keyword.php?keyword={quote_plus(keywords.strip())}"


def with_params(url: str, **params: object) -> str:
    """``url`` with query parameters set (``None`` removes one)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in params]
    query += [(k, str(v)) for k, v in params.items() if v is not None]
    return urlunsplit(parts._replace(query=urlencode(query)))


def is_category_url(url: str) -> bool:
    """True for a filterable category listing (``.../sbN/<slug>-c<id>[...].html``)."""
    return bool(_CATEGORY_PATH.match(urlsplit(url).path))


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def apply_filters(
    url: str,
    filters: list[tuple[str, str]] | tuple[tuple[str, str], ...] = (),
    price: tuple[str, float | None, float | None] | None = None,
) -> str:
    """Add filter options and a price range to a category URL.

    Args:
        url: A category listing URL (it may already carry filters).
        filters: ``(filter id, option id)`` pairs, e.g. ``("86", "1944")`` for
            Brand = Steelcase. ``wayfair-scraper filters`` lists them.
        price: ``(price filter id, min, max)``; either bound may be ``None``.
    """
    if not filters and price is None:
        return url
    parts = urlsplit(url)
    match = _CATEGORY_PATH.match(parts.path)
    if not match:
        raise ValueError(
            "filters and price ranges need a category URL like "
            ".../furniture/sb0/office-chairs-c478390.html (searches that stay on "
            f"keyword results can't take them): {url}"
        )
    attributes: list[str] = []
    price_part = ""
    for kind, ident, values in _PART.findall(match.group("parts")):
        if kind.lower() == "a":
            attributes.append(f"a{ident}{values}")
        else:
            price_part = f"p{ident}{values}"
    for filter_id, option_id in filters:
        part = f"a{filter_id}~{option_id}"
        if part not in attributes:
            attributes.append(part)
    if price is not None:
        filter_id, low, high = price
        price_part = (
            f"p{filter_id}~{_number(low or 0)}~{_number(PRICE_CEILING if high is None else high)}"
        )
    pieces = attributes + ([price_part] if price_part else [])
    path = (
        f"/{match.group('dept')}/sb{len(pieces)}/{match.group('slug')}-c{match.group('category')}"
        + "".join(f"-{piece}" for piece in pieces)
        + ".html"
    )
    return urlunsplit(parts._replace(path=path))


def page_url(url: str, page: int = 1, sort: str | None = None) -> str:
    """``url`` at result page ``page`` (1-based) with an optional sort order."""
    if page < 1:
        raise ValueError("page numbers start at 1")
    params: dict[str, object] = {"curpage": page if page > 1 else None}
    if sort is not None:
        if sort not in SORTS:
            raise ValueError(f"unknown sort {sort!r}; choose from: {', '.join(SORTS)}")
        params["sortby"] = SORTS[sort] if sort != "recommended" else None
    return with_params(url, **params)


def parse_filter(text: str) -> tuple[str, str]:
    """``"86:1944"``, ``"86=1944"`` or ``"86~1944"`` -> ``("86", "1944")``."""
    for separator in (":", "=", "~"):
        if separator in text:
            filter_id, _, option_id = text.partition(separator)
            filter_id, option_id = filter_id.strip(), option_id.strip()
            if filter_id.isdigit() and option_id.isalnum():
                return filter_id, option_id
            break
    raise ValueError(
        f"filters look like FILTER:OPTION with Wayfair's numeric ids, e.g. 86:1944 (got {text!r})"
    )


def product_url(ref: str, site: str = "us") -> str:
    """URL of a product page from a SKU (``W009315804``) or a product URL.

    A SKU is looked up through Wayfair's search, which redirects to the product.
    """
    ref = ref.strip()
    if is_url(ref):
        site_of(ref)
        return ref
    if not _SKU.match(ref):
        raise ValueError(f"expected a Wayfair SKU like W009315804 or a product URL, got {ref!r}")
    return keyword_url(ref.upper(), site)


def sku_from_url(url: str) -> str | None:
    """The SKU at the end of a product URL (``...-w009315804.html`` -> ``W009315804``)."""
    match = _PDP_SKU.search(urlsplit(url).path)
    return match.group(1).upper() if match else None


def clean_product_url(url: str) -> str:
    """A product URL without ad-tracking parameters (keeps the ``piid`` option)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k == "piid"]
    return urlunsplit(parts._replace(query=urlencode(query), fragment=""))


def image_url(image_id: int | str | None, size: int = 800) -> str | None:
    """A JPEG URL on Wayfair's image CDN for an image id from the page data."""
    if not image_id:
        return None
    image_id = str(image_id)
    resize = f"resize-h{size}-w{size}%5Ecompr-r85" if size else "compr-r85"
    return f"{CDN}/im/00000000/{resize}/{image_id[:4]}/{image_id}/image.jpg"


@dataclass
class SearchQuery:
    """What to list: keywords or a listing URL, plus sort, filters and price range.

    Args:
        keywords: Search words (``"office chair"``). Ignored when ``url`` is set.
        url: Any Wayfair listing URL (category, brand, search) from your browser.
        sort: ``recommended``, ``price-low``, ``price-high`` or ``rating``.
        filters: ``"FILTER:OPTION"`` strings or ``(filter, option)`` pairs, e.g.
            ``"86:1944"``; see ``WayfairScraper.filters``. Category listings only.
        min_price / max_price: Wayfair's price filter (category listings only).
        price_filter: The id of that price filter; found automatically if unset.
        site: ``us`` (wayfair.com) or ``ca`` (wayfair.ca); taken from ``url`` if given.
    """

    keywords: str = ""
    url: str | None = None
    sort: str | None = None
    filters: list = field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None
    price_filter: str | None = None
    site: str = "us"

    def __post_init__(self) -> None:
        self.keywords = (self.keywords or "").strip()
        if self.url:
            self.site = site_of(self.url)
        elif self.keywords and is_url(self.keywords):
            self.url, self.keywords = self.keywords, ""
            self.site = site_of(self.url)
        site_base(self.site)
        if not self.url and not self.keywords:
            raise ValueError("give search keywords or a Wayfair listing URL")
        if self.sort is not None and self.sort not in SORTS:
            raise ValueError(f"unknown sort {self.sort!r}; choose from: {', '.join(SORTS)}")
        self.filters = [
            parse_filter(f) if isinstance(f, str) else tuple(map(str, f)) for f in self.filters
        ]
        for value in (self.min_price, self.max_price):
            if value is not None and value < 0:
                raise ValueError("prices cannot be negative")
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price is above max_price")

    @property
    def has_price(self) -> bool:
        return self.min_price is not None or self.max_price is not None

    @property
    def needs_category(self) -> bool:
        """Filters and price ranges can only be applied to a category URL."""
        return bool(self.filters) or self.has_price

    @property
    def start_url(self) -> str:
        return self.url or keyword_url(self.keywords, self.site)

    @property
    def currency(self) -> str:
        return CURRENCIES[self.site]

    def listing_url(self, base: str | None = None) -> str:
        """The listing with this query's filters and price range applied to ``base``."""
        base = base or self.start_url
        price = None
        if self.has_price:
            if not self.price_filter:
                raise ValueError("price_filter is needed to apply a price range")
            price = (self.price_filter, self.min_price, self.max_price)
        return apply_filters(base, self.filters, price)
