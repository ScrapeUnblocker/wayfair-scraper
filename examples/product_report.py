"""Summarize one Wayfair product: rating breakdown, options in stock, key specs.

Prints a short report and saves the full product page data as JSON.

    python examples/product_report.py W009315804
"""

from __future__ import annotations

import argparse

from wayfair_scraper import WayfairScraper
from wayfair_scraper.export import write


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("product", metavar="SKU_OR_URL")
    parser.add_argument("--output", help="JSON file (default: <sku>.json)")
    args = parser.parse_args()

    item = WayfairScraper().product(args.product)  # reads SCRAPEUNBLOCKER_KEY
    print(f"{item.name}  ({item.sku}, {item.brand})")
    print(
        f"${item.price:,.2f} {item.currency}"
        + (f", was ${item.was_price:,.2f}" if item.was_price else "")
    )
    delivery = " ".join(filter(None, [item.delivery, item.arrives]))
    print(f"{item.stock_message or item.stock_status}; {delivery}")

    total = sum(item.rating_histogram.values())
    print(f"\nRating {item.rating} from {item.review_count:,} reviews")
    for stars in ("5", "4", "3", "2", "1"):
        count = item.rating_histogram.get(stars, 0)
        share = count / total if total else 0
        print(f"  {stars} stars  {'#' * round(share * 40):<40} {share:5.1%}")

    in_stock = [o for o in item.options if o.stock_status == "IN_STOCK"]
    print(f"\n{len(in_stock)} of {len(item.options)} options in stock")
    for option in item.options:
        mark = "*" if option.selected else " "
        print(f" {mark} {option.category}: {option.name} [{option.stock_status or '?'}]")

    for key in ("Overall Dimensions", "Overall Product Weight"):
        if key in item.dimensions:
            print(f"{key}: {item.dimensions[key]}")

    output = args.output or f"{item.sku}.json"
    write(item, "json", output)
    print(f"\nfull details -> {output}")


if __name__ == "__main__":
    main()
