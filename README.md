# Promo Pipeline

`promo_pipeline` is a small data pipeline that collects promotional offers from coupon/deal websites and converts them into structured JSON.

It does this in 3 stages:

1. Fetch coupon pages as Markdown using Firecrawl.
2. Extract structured offer data from that Markdown using Groq.
3. Deduplicate overlapping offers across multiple sources for the same provider.

The current configuration is set up for providers like `Myntra` and `Nykaa`, with sources such as `CouponDunia` and `GrabOn`.

## What This Project Produces

The pipeline generates JSON outputs in the `output/` folder:

- `raw_markdown_*.json`
  Raw Markdown scraped from each configured URL.
- `promotions_*.json`
  Final deduplicated structured promotions grouped by provider.

## Project Structure

```text
promo_pipeline/
├── config/
│   └── settings.py
├── fetcher/
│   └── firecrawl_fetcher.py
├── extractor/
│   └── groq_extractor.py
├── deduplicator/
│   └── deduplicator.py
├── output/
├── tests/
├── main.py
├── requirements.txt
└── .env
```

## How It Works

### 1. Configuration

[`config/settings.py`](./config/settings.py) loads:

- `FIRECRAWL_API_KEY`
- `GROQ_API_KEY`
- the Groq model name
- the list of providers and source URLs
- the output directory

### 2. Fetching

[`fetcher/firecrawl_fetcher.py`](./fetcher/firecrawl_fetcher.py) uses Firecrawl to:

- scrape each source URL as Markdown
- scroll the page so lazy-loaded coupon cards appear
- remove common noise such as headers, footers, sidebars, popups, and ads

Output shape:

```json
{
  "url": "https://example.com/page",
  "provider": "Myntra",
  "scraped_date": "2026-04-03",
  "markdown": "..."
}
```

### 3. Extraction

[`extractor/groq_extractor.py`](./extractor/groq_extractor.py) sends the Markdown to Groq and extracts a structured schema for every offer.

It includes fields such as:

- `offer_title`
- `description`
- `brand`
- `category`
- `promo_type`
- `discount_min`
- `discount_max`
- `flat_value`
- `min_purchase`
- `coupon_code`
- `user_type`

### 4. Deduplication

[`deduplicator/deduplicator.py`](./deduplicator/deduplicator.py) merges duplicate offers across multiple sources for the same provider.

Deduplication logic is based on:

- `coupon_code` first
- normalized `offer_title` as fallback

The final output is grouped by provider and includes:

- `provider`
- `scraped_date`
- `source_urls`
- `total_sources`
- `total_offers`
- `offers`

## Requirements

- Python 3
- A Firecrawl API key
- A Groq API key

Install dependencies:

```bash
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file inside `promo_pipeline/`:

```env
FIRECRAWL_API_KEY=your_firecrawl_api_key_here
GROQ_API_KEY=your_groq_api_key_here
```

## How To Run

Run all commands from inside the `promo_pipeline` folder.

### Full Pipeline

This runs fetch + extract + deduplicate.

```bash
python main.py
```

### Fetch Only

This only scrapes Markdown and saves `raw_markdown_*.json`.

```bash
python main.py --fetch-only
```

### Extract Only

This loads an existing `raw_markdown_*.json` file and produces the final `promotions_*.json`.

```bash
python main.py --extract-only output/raw_markdown_2026-03-30_15-54-28.json
```

## Example Flow

1. Configure provider URLs in [`config/settings.py`](./config/settings.py).
2. Add API keys in `.env`.
3. Run:

```bash
python main.py
```

4. Check the generated files in `output/`.

## Notes

- Source URLs are currently hardcoded in `config/settings.py`.
- The pipeline is modular, so fetch, extract, and dedup logic are separated cleanly.
- `tests/test_fetcher.py` currently exists but is empty, so automated test coverage is still minimal.

## Demo Summary

If you need a one-line explanation for a demo:

“This project scrapes coupon pages with Firecrawl, extracts structured promotions using Groq, and merges duplicate offers across multiple sources into a clean provider-level JSON output.”

