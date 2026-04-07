"""
Master Orchestrator
CLI entry point — run the full promo intelligence pipeline.

Usage:
  python main.py                          # run all providers
  python main.py --providers Myntra Ajio  # specific providers
  python main.py --providers Myntra --skip-db  # dry run (no DB write)
  python main.py --fetch-only             # only fetch markdown
  python main.py --extract-only output/raw_markdown_*.json
"""

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

from config.settings import (
    FIRECRAWL_API_KEY, GROQ_API_KEY, DATABASE_URL,
    COMPETITOR_SITES, OUTPUT_DIR,
)


# ── Validation ─────────────────────────────────────────────────────────────

def _validate_keys(skip_db: bool = False):
    errors = []
    if not FIRECRAWL_API_KEY:
        errors.append("FIRECRAWL_API_KEY not set in .env")
    if not GROQ_API_KEY:
        errors.append("GROQ_API_KEY not set in .env")
    if not skip_db and not DATABASE_URL:
        errors.append("DATABASE_URL not set in .env  (use --skip-db to bypass)")
    if errors:
        print("\n❌ Missing configuration:")
        for e in errors:
            print(f"   • {e}")
        sys.exit(1)


# ── Run modes ──────────────────────────────────────────────────────────────

def run_fetch_only(providers: list[str]):
    """Step 0 only — fetch markdown and save."""
    from ingestion.firecrawl_fetcher import fetch_all
    pages = fetch_all(providers)
    if not pages:
        logger.error("No pages fetched.")
        return {}
    logger.info(f"Fetch complete — {len(pages)} pages")
    return {"pages_fetched": len(pages)}


def run_pipeline(providers: list[str], skip_db: bool = False) -> dict:
    """Full pipeline: fetch → extract → process → (load)."""
    from ingestion.firecrawl_fetcher import fetch_all
    from extraction.groq_extractor   import extract_all
    from processing.post_processor   import process_all

    results = {}

    # ── Step 0: Fetch ──────────────────────────────────
    logger.info(f"Step 0: Fetching {len(providers)} provider(s)")
    pages = fetch_all(providers)
    if not pages:
        logger.error("No pages fetched — aborting.")
        return {"error": "No pages fetched"}

    # ── Step 1: Extract ────────────────────────────────
    logger.info("Step 1: Extracting offers with Groq")
    raw_results = extract_all(pages)
    if not raw_results:
        logger.error("No offers extracted — aborting.")
        return {"error": "No offers extracted"}

    # ── Step 2: Process ────────────────────────────────
    logger.info("Step 2: Processing (validate, normalise, dedup)")
    clean_results = process_all(raw_results)

    # ── Step 3: Load to DB ─────────────────────────────
    if not skip_db:
        logger.info("Step 3: Loading to PostgreSQL")
        from database.loader import load_all
        db_summary = load_all(clean_results)
    else:
        db_summary = {"inserted": 0, "skipped": 0, "note": "DB skipped (--skip-db)"}
        logger.info("Step 3: Skipped (--skip-db)")

    # ── Summary ────────────────────────────────────────
    for r in clean_results:
        results[r["provider"]] = {
            "total_raw"  : r["total_raw"],
            "total_clean": r["total_clean"],
            "dropped"    : r["dropped"],
        }
    results["_db"] = db_summary

    return results


def run_extract_only(raw_file: str, skip_db: bool = False) -> dict:
    """Load saved raw markdown JSON and run extraction + processing + load."""
    if not os.path.exists(raw_file):
        logger.error(f"File not found: {raw_file}")
        return {"error": "File not found"}

    with open(raw_file, encoding="utf-8") as f:
        pages = json.load(f)

    if isinstance(pages, dict):
        pages = [pages]   # single-page file

    from extraction.groq_extractor import extract_all
    from processing.post_processor import process_all

    raw_results   = extract_all(pages)
    clean_results = process_all(raw_results)

    if not skip_db:
        from database.loader import load_all
        db_summary = load_all(clean_results)
    else:
        db_summary = {"inserted": 0, "skipped": 0, "note": "DB skipped"}

    results: dict = {}
    for r in clean_results:
        results[r["provider"]] = {
            "total_raw"  : r["total_raw"],
            "total_clean": r["total_clean"],
            "dropped"    : r["dropped"],
        }
    results["_db"] = db_summary
    return results


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Retail Promotion Intelligence Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch markdown — no extraction, no DB",
    )
    mode.add_argument(
        "--extract-only",
        metavar="RAW_FILE",
        help="Run extraction on an existing raw_markdown_*.json file",
    )

    parser.add_argument(
        "--providers",
        nargs="+",
        default=list(COMPETITOR_SITES.keys()),
        choices=list(COMPETITOR_SITES.keys()),
        metavar="PROVIDER",
        help=f"One or more of: {list(COMPETITOR_SITES.keys())}",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip the database load step (dry run)",
    )

    args = parser.parse_args()

    if args.fetch_only:
        _validate_keys(skip_db=True)
        result = run_fetch_only(args.providers)
    elif args.extract_only:
        _validate_keys(skip_db=args.skip_db)
        result = run_extract_only(args.extract_only, skip_db=args.skip_db)
    else:
        _validate_keys(skip_db=args.skip_db)
        result = run_pipeline(args.providers, skip_db=args.skip_db)

    print("\n" + json.dumps(result, indent=2))
