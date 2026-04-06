import json
import os
import argparse
from datetime import datetime

from config.settings               import FIRECRAWL_API_KEY, GROQ_API_KEY, GROQ_MODEL, SITES, OUTPUT_DIR
from fetcher.firecrawl_fetcher     import fetch_all_sites
from extractor.groq_extractor      import extract_all_pages
from deduplicator.deduplicator     import merge_by_provider


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _save(data: list, filename: str) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _validate_keys():
    errors = []
    if not FIRECRAWL_API_KEY or FIRECRAWL_API_KEY == "your_firecrawl_api_key_here":
        errors.append("FIRECRAWL_API_KEY not set in .env")
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        errors.append("GROQ_API_KEY not set in .env")
    if errors:
        print("\n❌ Missing API keys:")
        for e in errors:
            print(f"   - {e}")
        return False
    return True


# -------------------------------------------------------
# Run modes
# -------------------------------------------------------

def run_fetch_only():
    """Step 1 only — scrape Markdown, save raw output."""
    if not FIRECRAWL_API_KEY:
        print("❌ FIRECRAWL_API_KEY not set"); return

    pages = fetch_all_sites(SITES, FIRECRAWL_API_KEY)
    if not pages:
        print("❌ No pages fetched."); return

    filename = f"raw_markdown_{_timestamp()}.json"
    path     = _save(pages, filename)
    print(f"✅ Raw Markdown saved → {path}")
    print(f"   ({len(pages)} pages)")


def run_extract_only(raw_file: str):
    """Step 2+3 only — load existing raw Markdown file, run Groq extraction + dedup."""
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set"); return

    if not os.path.exists(raw_file):
        print(f"❌ File not found: {raw_file}"); return

    with open(raw_file, encoding="utf-8") as f:
        pages = json.load(f)

    print(f"📂 Loaded {len(pages)} pages from {raw_file}")

    # ── Step 2: Extract (per URL) ──────────────────────
    raw_offers = extract_all_pages(pages, GROQ_API_KEY, GROQ_MODEL)
    if not raw_offers:
        print("❌ No offers extracted."); return

    # ── Step 3: Deduplicate (merge by provider) ────────
    merged = merge_by_provider(raw_offers)
    out_path = _save(merged, f"promotions_{_timestamp()}.json")
    print(f"✅ Deduplicated offers saved → {out_path}")
    total = sum(p["total_offers"] for p in merged)
    print(f"   {len(merged)} provider(s) | {total} unique offers")


def run_full():
    """Step 1 + Step 2 + Step 3 — scrape, extract, deduplicate."""
    if not _validate_keys():
        return

    # ── Step 1: Fetch ──────────────────────────────────
    pages = fetch_all_sites(SITES, FIRECRAWL_API_KEY)
    if not pages:
        print("❌ No pages fetched. Check API key and URLs."); return

    raw_md_path = _save(pages, f"raw_markdown_{_timestamp()}.json")
    print(f"\n📄 Raw Markdown saved → {raw_md_path}")

    # ── Step 2: Extract (per URL) ──────────────────────
    raw_offers = extract_all_pages(pages, GROQ_API_KEY, GROQ_MODEL)
    if not raw_offers:
        print("❌ No offers extracted."); return

    # ── Step 3: Deduplicate (merge by provider) ────────
    merged   = merge_by_provider(raw_offers)
    out_path = _save(merged, f"promotions_{_timestamp()}.json")
    total    = sum(p["total_offers"] for p in merged)
    print(f"\n🎉 Done! Deduplicated offers saved → {out_path}")
    print(f"   {len(merged)} provider(s) | {total} unique offers")


# -------------------------------------------------------
# Entry point
# -------------------------------------------------------

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Promo Pipeline")
    group  = parser.add_mutually_exclusive_group()

    group.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only run Step 1 (scrape Markdown). Saves raw_markdown_*.json"
    )
    group.add_argument(
        "--extract-only",
        metavar="RAW_FILE",
        help="Only run Step 2 (Groq extraction) on an existing raw_markdown_*.json file"
    )

    args = parser.parse_args()

    if args.fetch_only:
        run_fetch_only()
    elif args.extract_only:
        run_extract_only(args.extract_only)
    else:
        run_full()
