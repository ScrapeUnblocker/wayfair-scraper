"""Find the deepest discounts in a Wayfair category and save them as CSV.

Reads a few result pages of a search or category (optionally capped by price),
keeps the products marked down by at least --min-discount percent and writes them
sorted by discount, biggest first. Sponsored listings are left out.

    python examples/category_deals.py "office chair" --max-price 250 --pages 3
    python examples/category_deals.py https://www.wayfair.com/furniture/sb0/sofas-c413892.html
"""

from __future__ import annotations

import argparse

from wayfair_scraper import SearchQuery, WayfairScraper
from wayfair_scraper.export import write


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("listing", help="search words or a Wayfair category URL")
    parser.add_argument("--max-price", type=float)
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--min-discount", type=int, default=30, help="percent")
    parser.add_argument("--output", default="wayfair_deals.csv")
    args = parser.parse_args()

    wayfair = WayfairScraper()  # reads SCRAPEUNBLOCKER_KEY
    query = SearchQuery(args.listing, max_price=args.max_price)
    products = wayfair.search(query, max_pages=args.pages, sponsored=False)
    deals = sorted(
        (p for p in products if (p.discount_percent or 0) >= args.min_discount),
        key=lambda p: p.discount_percent or 0,
        reverse=True,
    )
    write(deals, "csv", args.output)
    print(
        f"{len(deals)} of {len(products)} products are {args.min_discount}%+ off -> {args.output}"
    )
    for p in deals[:10]:
        price = f"${p.price:,.2f} (was ${p.was_price:,.2f})"
        print(f"{p.discount_percent:>3}% off  {price}  {p.name[:60]}")
    print(f"{wayfair.requests} requests")


if __name__ == "__main__":
    main()
