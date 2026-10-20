"""Watch Wayfair product prices: append today's price and stock to a CSV history.

Run it once a day (cron, Task Scheduler, a GitHub Action) and the CSV grows into
a price history you can chart or alert on. Pass SKUs (the "W..." code on every
product page) or product URLs; a URL with ``?piid=`` tracks that exact option.

    python examples/price_watch.py W009315804 W004441107 --history sofas.csv
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timezone

from wayfair_scraper import NotFoundError, WayfairScraper

COLUMNS = [
    "checked_at",
    "sku",
    "name",
    "option",
    "price",
    "was_price",
    "discount_percent",
    "deal",
    "stock_message",
    "delivery",
    "url",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("products", nargs="+", metavar="SKU_OR_URL")
    parser.add_argument("--history", default="wayfair_prices.csv")
    parser.add_argument("--site", default="us", choices=["us", "ca"])
    args = parser.parse_args()

    wayfair = WayfairScraper(site=args.site)  # reads SCRAPEUNBLOCKER_KEY
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_file = not os.path.exists(args.history)
    with open(args.history, "a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for ref in args.products:
            try:
                item = wayfair.product(ref)
            except NotFoundError:
                print(f"{ref}: not on Wayfair any more")
                continue
            option = ", ".join(f"{k}: {v}" for k, v in item.selected_options.items())
            writer.writerow({**item.to_dict(), "option": option, "checked_at": checked_at})
            was = f" (was ${item.was_price:,.2f})" if item.was_price else ""
            stock = item.stock_message or "-"
            print(f"{item.sku}  ${item.price or 0:,.2f}{was}  {stock}  {item.name}")
    print(f"appended to {args.history}")


if __name__ == "__main__":
    main()
