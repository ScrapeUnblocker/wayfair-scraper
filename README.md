# Wayfair Scraper

[![CI](https://github.com/ScrapeUnblocker/wayfair-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/wayfair-scraper/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Powered by ScrapeUnblocker](https://img.shields.io/badge/powered%20by-ScrapeUnblocker-orange.svg)](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

Scrape **Wayfair** into clean JSON or CSV: search results and category listings with prices, sale and "was" prices, deals, ratings, delivery promises and stock, plus full product pages with specifications, dimensions, every option (color, fabric, size) with its stock status, the rating histogram, the latest reviews, images, videos and manuals. Built for furniture and home-goods price monitoring, assortment research and deal hunting. It ships as a CLI and a Python library and reads wayfair.com (USD) and wayfair.ca (CAD).

**Powered by [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos).** Every page is fetched through the ScrapeUnblocker `getPageSource` API, so you don't deal with blocks, CAPTCHAs or proxies yourself.

```bash
wayfair-scraper search "office chair" --sort rating --max-price 300 -f table
wayfair-scraper search "blue velvet sofa" --pages 3 --no-sponsored -f csv -o sofas.csv
wayfair-scraper product W009315804
wayfair-scraper filters "office chair" -f table
wayfair-scraper --site ca search "sectional sofa" -f table
```

## Features

- **Search results and category listings** (`search`): any keywords, or any category URL pasted from your browser (its filters are kept). Each product has the SKU, name, brand, **price**, **was price and discount percent**, sale / closeout label, per-item price for multi-packs, Wayfair Rewards member savings and limited-time deals (with end time) when shown, star rating and review count, the option the card shows ("Fabric: Blue Velvet") and how many colors/sizes exist, badges ("Sale", "30-Day Low Price", "Bundle & Save"), **delivery promise and arrival estimate** ("FREE 2-Day Delivery", "Get it by Thu, Oct 22"), **stock status and message** ("22 Left in Stock"), sponsored and Wayfair Verified flags, category, key specs (on category pages), image and product URL.
- **Sorting and filters**: Wayfair's four sort orders (recommended, price low/high, customer rating), **price range**, and every other filter a category offers (brand, color, material, features, customer rating, in stock only, sale, ...) by its id. `filters` lists them for any search or category.
- **Smart keyword search**: when Wayfair sends a search to a category ("office chair" opens Office Chairs), the scraper follows it, so filters, price ranges and later pages work on keywords too.
- **Paging**: 48 products per page, as many pages as you ask for. Repeats are dropped (sponsored products can show up again later), and sponsored listings can be left out.
- **Product pages** (`product`): everything above for the selected option, plus brand page and collection, the **1-5 star rating histogram**, description, feature bullets, **specifications**, **dimensions**, assembly and **warranty**, breadcrumb categories, every **option choice with its stock status**, product URL and image, the full image gallery, product videos, manuals and spec sheets (PDF), part number, Prop 65 warning, "Why We Love It" highlights of Wayfair Verified products, and the latest customer reviews (rating, date, reviewer, location, text, verified purchase).
- **wayfair.com and wayfair.ca**: `--site ca` reads the Canadian store, with prices in CAD and requests routed through Canada.
- **Robust**: retries with backoff on timeouts, transient errors and pages that come back without their data, re-requests pages Wayfair served only partly (see below), and raises `NotFoundError` for a product that doesn't exist.
- Output as **JSON, JSON Lines, CSV or a terminal table**; typed dataclasses in Python.

## How it works

Wayfair's storefront is a Next.js app. The data behind a page is streamed into the HTML as React Server Components "flight" chunks (`self.__next_f.push(...)`), and Wayfair builds each page from typed blocks: a product card is a `...ListingCollectionItem` whose blocks hold the name, brand, rating, price, delivery and stock; a product page is a list of blocks such as `PricingFull`, `BlockBuilderSpecificationsDetails` or `BlockBuilderReviewContainer`. The scraper decodes the flight, resolves its internal references and reads those blocks by type name, not by CSS classes. Each page is one request to ScrapeUnblocker's [`getPageSource`](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) endpoint; no browser rendering is needed.

Filters live in Wayfair's category paths (`/furniture/sb2/office-chairs-c478390-a86~1944-p88~0~600.html` is Office Chairs, Brand = Steelcase, $0-$600), and sort order and page number in the query string (`sortby`, `curpage`). The scraper builds those URLs for you.

**Partly rendered pages.** Wayfair sometimes renders only the first 30 of a page's 48 products on the server and leaves the rest for the browser to load. Every page states how many products it should hold, so the scraper notices a short page and asks for it again (up to 3 times by default, `--page-retries`). That means a page can take more than one request; `--page-retries 0` keeps whatever comes back first. `scraper.requests` and the CLI's summary line show how many requests a run made.

**Prices and delivery** are the ones Wayfair shows for the request's location. Requests go through the storefront's own country (US for wayfair.com, Canada for wayfair.ca); delivery dates depend on the delivery area Wayfair infers.

## Install

```bash
git clone https://github.com/ScrapeUnblocker/wayfair-scraper.git
cd wayfair-scraper
python -m pip install .
```

Get an API key at [scrapeunblocker.com](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) and expose it as `SCRAPEUNBLOCKER_KEY` (see `.env.example`):

```bash
export SCRAPEUNBLOCKER_KEY=your_key_here
```

Requires Python 3.9+. The only runtime dependency is the official [`scrapeunblocker`](https://docs.scrapeunblocker.com/sdks/python?utm_source=github&utm_medium=integration&utm_campaign=example-repos) SDK.

## CLI usage

```text
wayfair-scraper [--site us|ca] [--proxy-country auto] [--retries 3] [--page-retries 3] [-v] COMMAND ...

  search   [KEYWORDS] [--url URL] [--sort recommended|price-low|price-high|rating]
           [--filter FILTER:OPTION ...] [--min-price X] [--max-price Y] [--price-filter ID]
           [--pages 1] [--max N] [--no-sponsored] [--keep-duplicates]
  product  SKU_OR_URL [SKU_OR_URL ...]
  reviews  SKU_OR_URL
  filters  [KEYWORDS] [--url URL]

every command: -f json|jsonl|csv|table  -o FILE
```

**Search** with keywords or a listing URL:

```bash
# best-rated office chairs up to $300
wayfair-scraper search "office chair" --sort rating --max-price 300 -f table

# three pages of a search, without ads, to CSV
wayfair-scraper search "blue velvet sofa" --pages 3 --no-sponsored -f csv -o sofas.csv

# a category from your browser, filtered to one brand, cheapest first
wayfair-scraper search --url "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html" \
    --filter 86:1944 --sort price-low

# keywords work with filters too: in-stock Steelcase chairs (Wayfair opens the Office Chairs category)
wayfair-scraper search "office chair" --filter 98091:10 --filter 86:1944 -f table
```

**Find filter ids.** Wayfair identifies each filter option by a pair of numbers. `filters` lists them for a search or category, and tells you which listing Wayfair served:

```console
$ wayfair-scraper filters "office chair" -f table
group              filter                 value              kind
Sale               69117:8                Sale               option
Wayfair Verified   160857:580605          Wayfair Verified   option
Color              73316:607854           Cream              option
...
Price Per Item     88 $0.00-$75.00        Under $75          price
Price Per Item     88 $400.00+            $400 & Above       price
Customer Rating    13109:4                4 stars & up       option
Availability       98091:10               In Stock Only      option
Brand              86:1944                Steelcase          option
...
180 filter options on https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html?redir=office+chair&rtype=9
```

Pass options with `--filter FILTER:OPTION` (repeat it to combine). `--min-price` / `--max-price` use the category's price filter, which the scraper looks up on its own (one extra request; pass `--price-filter 88` to skip it). Filters work on category listings: if a search stays on keyword results instead of opening a category, open a category URL instead. To list one brand, filter a category by its Brand option; Wayfair's brand pages (`/brand/bnd/...`) and department hubs (`/cat/...`) have no product grid to read.

**Products and reviews** take a SKU (the `W...` code at the end of a product URL and in its breadcrumb) or a product URL. A URL with `?piid=...` selects that option, e.g. a color:

```bash
wayfair-scraper product W009315804
wayfair-scraper product W009315804 W004441107 -f csv -o sofas.csv
wayfair-scraper product "https://www.wayfair.com/furniture/pdp/mercury-row-perdue-815-velvet-square-arm-convertible-sofa-w009315804.html?piid=1134429063"
wayfair-scraper reviews W009315804 -f table
wayfair-scraper --site ca product C005584693
```

## Library usage

```python
from wayfair_scraper import SearchQuery, WayfairScraper

wayfair = WayfairScraper()  # reads SCRAPEUNBLOCKER_KEY; WayfairScraper(site="ca") for wayfair.ca

# Keywords only...
chairs = wayfair.search("office chair")

# ...or a full query: sort order, filter options, price range.
query = SearchQuery(
    "office chair",
    sort="rating",
    filters=["98091:10"],  # Availability: In Stock Only
    max_price=300,
)
for chair in wayfair.search(query, max_pages=2, sponsored=False):
    print(chair.price, chair.was_price, chair.rating, chair.delivery, chair.name)

# Any listing URL from your browser
sofas = wayfair.search("https://www.wayfair.com/furniture/sb0/sofas-c413892.html", max_results=100)

# Filter options: [FilterOption(group="Brand", name="Steelcase", filter_id="86", option_id="1944"), ...]
brands = [f for f in wayfair.filters("office chair") if f.group == "Brand"]

# One product page
sofa = wayfair.product("W009315804")
sofa.price, sofa.stock_message, sofa.rating_histogram
sofa.specifications["Seating Capacity"], sofa.dimensions["Overall Dimensions"]
in_stock = [o.name for o in sofa.options if o.stock_status == "IN_STOCK"]
for review in sofa.reviews:
    print(review.date, review.rating, review.text)
```

`WayfairScraper` options: `site` (`us` or `ca`), `proxy_country` (`"auto"` matches the site, `None` lets the API choose), `max_retries`, `backoff`, `page_retries`, `timeout`, or a ready `client`. `scraper.requests` counts the API requests made. `search_page()` returns one page with Wayfair's totals (`total_results`, `total_pages`, `sort`, `selected_filters` and the `url` Wayfair served).

## Example output

`wayfair-scraper search --url "https://www.wayfair.com/furniture/sb0/office-chairs-c478390.html" --max 1` (one product):

```json
[
  {
    "position": 1,
    "sku": "W116084446",
    "name": "Upholstered Office Chair Adjustable Height Desk & Task Chair With Bentwood Chenille Swivel Chair With Metal Frame",
    "url": "https://www.wayfair.com/furniture/pdp/george-oliver-upholstered-office-chair-adjustable-height-desk-task-chair-with-bentwood-boucle-swivel-chair-with-metal-frame-w116084446.html?piid=2037668915",
    "brand": "George Oliver",
    "price": 169.99,
    "was_price": 369.99,
    "discount_percent": 54,
    "price_label": null,
    "unit_price": null,
    "member_savings": null,
    "deal": null,
    "deal_ends": null,
    "currency": "USD",
    "rating": 4.72,
    "review_count": 158,
    "option": "Upholstery Color: Green Chenille",
    "option_id": 2037668915,
    "options": {"Colors": 6},
    "flag": "Sale",
    "delivery": "FREE 1-Day Delivery",
    "arrives": "Get it Tomorrow",
    "stock_status": "IN_STOCK",
    "stock_message": "130 Left in Stock",
    "sponsored": false,
    "wayfair_verified": true,
    "category": "Office Chairs",
    "category_id": 478390,
    "highlights": {
      "Product Type": "Task Chair",
      "Pieces Included": "Wheels / Casters",
      "Removable Components": "Wheels / Casters",
      "Weight Capacity": "300 lb.",
      "Adjustability Features": "Adjustable Height, Tilting, Up / Down, Tilt Lock, Adjustable Tilt Tension",
      "Compatible Floor Type": "Hardwood, Carpet, Marble / Tile, Engineered Wood"
    },
    "image": "https://assets.wfcdn.com/im/00000000/resize-h800-w800%5Ecompr-r85/4620/462007258/image.jpg"
  }
]
```

`wayfair-scraper product W004706126` (lists shortened):

```json
{
  "sku": "W004706126",
  "name": "Belanda 23'' W Modern Velvet Task Chair with Tufted Back",
  "url": "https://www.wayfair.com/furniture/pdp/etta-avenue-teen-belanda-23-w-modern-velvet-task-chair-with-tufted-back-w004706126.html?piid=828792400",
  "brand": "Etta Avenue™ Teen",
  "brand_url": "https://www.wayfair.com/brand/bnd/etta-avenue-teen-b59931.html",
  "collection": null,
  "option_id": 828792400,
  "selected_options": {"Upholstery Color": "Ivory"},
  "price": 136.99,
  "was_price": 279.0,
  "discount_percent": 51,
  "price_label": "Sale",
  "unit_price": null,
  "member_savings": null,
  "deal": null,
  "deal_ends": null,
  "currency": "USD",
  "rating": 4.75,
  "review_count": 1476,
  "rating_histogram": {"1": 15, "2": 26, "3": 43, "4": 145, "5": 1247},
  "stock_status": "IN_STOCK",
  "stock_message": "263 Left in Stock",
  "delivery": "FREE 2-Day Delivery",
  "arrives": "Get it by Thu, Oct 22",
  "wayfair_verified": true,
  "verified_highlights": [
    "What really stands out is the scalloped back along with the vertical tufting for added structure"
  ],
  "description": "This modern task chair brings a sleek, functional design to your home office setup. ...",
  "features": ["Slender metal base provides functional stability across a range of floor types"],
  "specifications": {
    "Product Type": "Task Chair",
    "Frame Material": "Manufactured Wood",
    "Seat Material": "Velvet, Upholstered, Polyester, Solid + Manufactured Wood",
    "Upholstered": "Yes"
  },
  "dimensions": {
    "Seat": "19.5'' H X 21'' W X 18.5'' D",
    "Adjustable Seat Minimum Dimensions": "16.5'' H",
    "Adjustable Seat Maximum Dimensions": "19.5'' H"
  },
  "assembly": {
    "Suggested Number of People for Assembly / Installation": "2",
    "Assembly": "Full Assembly Needed - All Tools Included"
  },
  "warranty": {"Commercial Warranty": "No", "Warranty Length": "30 Days", "Warranty": "Limited Warranty"},
  "categories": ["Furniture", "Office Furniture", "Office Chairs"],
  "category_id": 478390,
  "options": [
    {
      "category": "Upholstery Color",
      "name": "Black",
      "option_id": 828792406,
      "stock_status": "IN_STOCK",
      "selected": false,
      "url": "https://www.wayfair.com/furniture/pdp/etta-avenue-teen-belanda-23-w-modern-velvet-task-chair-with-tufted-back-w004706126.html?piid=828792406",
      "image": "https://assets.wfcdn.com/im/00000000/resize-h800-w800%5Ecompr-r85/2672/267242563/image.jpg"
    }
  ],
  "images": [
    "https://assets.wfcdn.com/im/00000000/resize-h1200-w1200%5Ecompr-r85/2672/267242540/image.jpg",
    "https://assets.wfcdn.com/im/00000000/resize-h1200-w1200%5Ecompr-r85/2672/267242536/image.jpg"
  ],
  "videos": [
    "https://secure.img1-fg.wfcdn.com/dm/video/32aaa698-d163-478e-bc78-ba22940f7731/ofm0165无logo.mp4"
  ],
  "documents": [
    {
      "type": "owner_manual",
      "url": "https://assets.wfcdn.com/dm/document/47098c92-c60a-4bfb-81de-90cf6df0be8b/assembly%20guide%20ofm0165.pdf"
    }
  ],
  "part_number": null,
  "prop65_warning": null,
  "reviews": [
    {
      "review_id": 182873234,
      "rating": 5,
      "date": "2026-10-01",
      "author": "Jordan",
      "location": "Springfield, IL",
      "text": "Love this chair, except for the cheap-looking super shiny gold legs. ...",
      "verified_purchase": true,
      "options": []
    }
  ]
}
```

(The reviewer's name and location are replaced here.)

## Examples

- [`examples/price_watch.py`](examples/price_watch.py) appends today's price, discount, deal and stock of chosen products to a CSV price history (run it daily).
- [`examples/category_deals.py`](examples/category_deals.py) collects the products in a search or category that are marked down by 30% or more, biggest discount first.
- [`examples/product_report.py`](examples/product_report.py) prints a product's rating breakdown and which options are in stock, and saves the full details as JSON.

## Notes

- **Reviews**: `product` and `reviews` return the latest reviews the product page shows (Wayfair loads older ones in the browser), together with the full rating histogram and review count.
- **Searches always return something**: Wayfair falls back to broad results for keywords it can't match, so check `total_results` and the product names when a search looks off.
- **Stores**: wayfair.com and wayfair.ca. Other Wayfair storefronts are not supported.
- Please respect Wayfair's terms of use and scrape at a reasonable pace.

## Project layout

```text
src/wayfair_scraper/
  __init__.py   public API and version
  scraper.py    WayfairScraper: fetching, retries, short-page re-requests, paging
  urls.py       SearchQuery and URL builders (keyword, category filters, sort, pages, SKUs)
  flight.py     decoder for the React Server Components data embedded in pages
  parsing.py    listing cards, filters and product page blocks -> dataclasses
  models.py     Product, SearchPage, FilterOption, ProductDetail, OptionChoice, Review
  export.py     JSON / JSON Lines / CSV / table output
  cli.py        the wayfair-scraper command
examples/       runnable scripts (price history, deals, product report)
tests/          offline tests with trimmed real Wayfair pages (no API calls)
```

## Development

```bash
python -m pip install -e ".[dev]"
make lint    # ruff check + format check
make test    # pytest, fully offline
pre-commit install  # optional: ruff on every commit
```

The tests run against trimmed copies of real Wayfair pages in `tests/fixtures/` and a fake API client, so they need no API key and spend no credits.

## Links

- [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos): web scraping API that handles blocks, CAPTCHAs and proxies
- [Documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos): `getPageSource`, the SDKs and the other endpoints
- [Python SDK](https://docs.scrapeunblocker.com/sdks/python?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

## License

[MIT](LICENSE). Copyright (c) 2026 ScrapeUnblocker.
