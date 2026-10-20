"""``wayfair-scraper`` command line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any

from . import __version__
from .export import FORMATS, write
from .urls import SITES, SORTS, SearchQuery, parse_filter

EXAMPLES = """\
examples:
  wayfair-scraper search "office chair" -f table
  wayfair-scraper search "office chair" --sort rating --max-price 300 --pages 2 -f csv -o chairs.csv
  wayfair-scraper search "blue velvet sofa" --sort price-low --no-sponsored --max 20 -f table
  wayfair-scraper search --url "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html" \\
      --filter 86:1944 --sort price-high
  wayfair-scraper filters "office chair" -f table
  wayfair-scraper product W009315804
  wayfair-scraper product W009315804 W004441107 -f csv -o sofas.csv
  wayfair-scraper reviews W009315804 -f table
  wayfair-scraper --site ca search "office chair" -f table
"""


def filter_ref(text: str) -> tuple[str, str]:
    try:
        return parse_filter(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def bounded(low: int, high: int):
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return value

    return parse


def money(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a price: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError("prices cannot be negative")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wayfair-scraper",
        description=(
            "Scrape Wayfair search results, category listings and product "
            "pages into JSON/CSV via the ScrapeUnblocker API."
        ),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--site",
        default="us",
        choices=list(SITES),
        help="storefront: us = wayfair.com, ca = wayfair.ca (default: us)",
    )
    parser.add_argument(
        "--proxy-country",
        default="auto",
        help="route requests through this country (default: auto = the site's country; "
        '"" lets the API choose)',
    )
    parser.add_argument("--retries", type=int, default=3, help="retries per request (default 3)")
    parser.add_argument(
        "--page-retries",
        type=int,
        default=3,
        help="extra requests for a listing page that comes back short (default 3, 0 = off)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log retries to stderr")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search results or a category listing")
    _listing_args(search)
    search.add_argument("--sort", choices=list(SORTS), help="default: Wayfair's recommended order")
    search.add_argument(
        "--filter",
        type=filter_ref,
        action="append",
        default=[],
        metavar="FILTER:OPTION",
        help="a filter option from `filters`, e.g. 86:1944 (category listings); repeatable",
    )
    search.add_argument("--min-price", type=money, help="Wayfair's price filter, lower end")
    search.add_argument("--max-price", type=money, help="Wayfair's price filter, upper end")
    search.add_argument(
        "--price-filter", metavar="ID", help="id of the price filter (found automatically)"
    )
    search.add_argument(
        "--pages", type=bounded(1, 100), default=1, help="result pages to read (default 1)"
    )
    search.add_argument(
        "--max", type=bounded(1, 10000), dest="max_results", help="stop after this many products"
    )
    search.add_argument("--no-sponsored", action="store_true", help="drop the sponsored listings")
    search.add_argument(
        "--keep-duplicates", action="store_true", help="keep repeats of the same SKU"
    )
    _output_args(search)

    product = sub.add_parser("product", help="full details of one or more products")
    product.add_argument(
        "items", nargs="+", metavar="SKU_OR_URL", help="e.g. W009315804 or a product URL"
    )
    _output_args(product)

    reviews = sub.add_parser("reviews", help="the latest customer reviews on a product page")
    reviews.add_argument("item", metavar="SKU_OR_URL")
    _output_args(reviews)

    filters = sub.add_parser("filters", help="filter options (FILTER:OPTION ids) a listing offers")
    _listing_args(filters)
    _output_args(filters)
    return parser


def _listing_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("keywords", nargs="*", help='search words, e.g. "office chair"')
    parser.add_argument("--url", help="a Wayfair listing URL copied from your browser")


def _output_args(parser: argparse.ArgumentParser, default: str = "json") -> None:
    parser.add_argument("-f", "--format", default=default, choices=FORMATS)
    parser.add_argument("-o", "--output", help="write to this file instead of stdout")


def query_from_args(args: argparse.Namespace) -> SearchQuery:
    return SearchQuery(
        keywords=" ".join(args.keywords),
        url=args.url,
        sort=getattr(args, "sort", None),
        filters=list(getattr(args, "filter", [])),
        min_price=getattr(args, "min_price", None),
        max_price=getattr(args, "max_price", None),
        price_filter=getattr(args, "price_filter", None),
        site=args.site,
    )


def make_scraper(args: argparse.Namespace):
    from .scraper import WayfairScraper

    return WayfairScraper(
        site=args.site,
        proxy_country=args.proxy_country or None,
        max_retries=args.retries,
        page_retries=args.page_retries,
    )


def _emit(items: Any, args: argparse.Namespace) -> None:
    write(items, args.format, args.output)


def run(args: argparse.Namespace) -> int:
    scraper = make_scraper(args)
    if args.command == "search":
        products = scraper.search(
            query_from_args(args),
            max_results=args.max_results,
            max_pages=args.pages,
            sponsored=not args.no_sponsored,
            dedupe=not args.keep_duplicates,
        )
        _emit(products, args)
        print(f"{len(products)} products, {scraper.requests} requests", file=sys.stderr)
    elif args.command == "product":
        details = [scraper.product(item) for item in args.items]
        _emit(details[0] if len(details) == 1 and args.format == "json" else details, args)
    elif args.command == "reviews":
        found = scraper.reviews(args.item)
        _emit(found, args)
        print(f"{len(found)} reviews, {scraper.requests} requests", file=sys.stderr)
    elif args.command == "filters":
        options = scraper.filters(query_from_args(args))
        _emit(options, args)
        print(f"{len(options)} filter options on {scraper.last_filters_url}", file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.verbose:
        logging.basicConfig(format="%(levelname)s %(message)s")
        logging.getLogger("wayfair_scraper").setLevel(logging.INFO)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - report any failure as one clean line
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
