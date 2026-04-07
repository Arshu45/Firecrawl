"""
Master Orchestrator — Promotion Intelligence Pipeline

Usage:
    python main.py                           # Run full pipeline (all providers)
    python main.py --providers Myntra Nykaa  # Specific providers
    python main.py --providers Myntra --skip-db  # Skip DB load (Layers 0-2 only)
    python main.py --extract-only output/raw_markdown_Myntra_*.json  # Re-run Layer 1-3
    python main.py --load-only output/promotions_clean_Myntra_*.json # Re-run Layer 3 only
"""

import json
import os
import argparse
import logging
from datetime import datetime

from config.settings import COMPETITOR_SITES, OUTPUT_DIR
from ingestion.firecrawl_fetcher import fetch_promotions, fetch_all
from extraction.groq_extractor   import extract_from_page, extract_all
from processing.post_processor   import process, process_all
from database.loader             import load_promotions, load_all

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def _save(data, filename: str) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _validate_keys(skip_db: bool = False) -> bool:
    from config.settings import FIRECRAWL_API_KEY, GROQ_API_KEY, DATABASE_URL
    errors = []
    if not FIRECRAWL_API_KEY:
        errors.append("FIRECRAWL_API_KEY not set in .env")
    if not GROQ_API_KEY:
        errors.append("GROQ_API_KEY not set in .env")
    if not skip_db and not DATABASE_URL:
        errors.append("DATABASE_URL not set in .env (use --skip-db to bypass)")
    if errors:
        print("\n❌ Missing configuration:")
        for e in errors:
            print(f"   - {e}")
        return False
    return True


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_pipeline(providers: list[str], skip_db: bool = False) -> dict:
    """
    Runs the full pipeline for the specified providers.

    Layer 0 → Layer 1 → Layer 2 → [Layer 3 if not skip_db]

    Returns dict: { provider: { total_raw, total_clean, dropped, inserted, skipped } }
    """
    if not _validate_keys(skip_db):
        return {}

    # Filter to only known providers
    sites_to_run = {
        p: url for p, url in COMPETITOR_SITES.items()
        if p in providers
    }
    unknown = [p for p in providers if p not in COMPETITOR_SITES]
    if unknown:
        print(f"⚠️  Unknown providers (ignored): {unknown}")
        print(f"   Valid options: {list(COMPETITOR_SITES.keys())}")

    if not sites_to_run:
        print("❌ No valid providers to run."); return {}

    print(f"\n🚀 Pipeline starting — providers: {list(sites_to_run.keys())}")
    print(f"   skip-db: {skip_db}")

    summary = {}

    # ── Layer 0: Fetch ─────────────────────────────────
    pages = fetch_all(sites_to_run)
    if not pages:
        print("❌ Fetch failed — no pages returned."); return {}

    # ── Layer 1: Extract ───────────────────────────────
    raw_results = extract_all(pages)
    if not raw_results:
        print("❌ Extraction failed — no offers from any page."); return {}

    # ── Layer 2: Process ───────────────────────────────
    clean_results = process_all(raw_results)

    # ── Layer 3: Load to DB ────────────────────────────
    for clean in clean_results:
        provider = clean["provider"]
        entry = {
            "total_raw"  : clean["total_raw"],
            "total_clean": clean["total_clean"],
            "dropped"    : clean["dropped"],
            "inserted"   : 0,
            "skipped"    : 0,
        }

        if not skip_db:
            try:
                from database.loader import load_promotions
                db_result        = load_promotions(clean)
                entry["inserted"] = db_result.get("inserted", 0)
                entry["skipped"]  = db_result.get("skipped", 0)
                print(f"  [{provider}] DB: {entry['inserted']} inserted, {entry['skipped']} skipped")
            except ImportError:
                print(f"  [{provider}] ⚠️  database.loader not yet built — skipping DB load")
            except Exception as e:
                print(f"  [{provider}] ❌ DB load failed: {e}")
        else:
            print(f"  [{provider}] ⏭  DB load skipped (--skip-db)")

        summary[provider] = entry

    # ── Final summary ──────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'='*55}")
    for provider, s in summary.items():
        print(f"  [{provider}]")
        print(f"    Raw offers   : {s['total_raw']}")
        print(f"    Clean offers : {s['total_clean']}")
        print(f"    Dropped      : {s['dropped']}")
        if not skip_db:
            print(f"    DB inserted  : {s['inserted']}")
            print(f"    DB skipped   : {s['skipped']}")
    print(f"{'='*55}\n")

    return summary


def run_extract_only(raw_file: str, skip_db: bool = False):
    """Re-run extraction + processing on a previously saved raw_markdown JSON file."""
    from config.settings import GROQ_API_KEY
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY not set"); return

    if not os.path.exists(raw_file):
        print(f"❌ File not found: {raw_file}"); return

    with open(raw_file, encoding="utf-8") as f:
        page = json.load(f)

    print(f"\n📂 Loaded page from {raw_file}")
    print(f"   Provider : {page.get('provider')}")
    print(f"   Chars    : {page.get('char_count', len(page.get('markdown', ''))):,}")

    # Layer 1
    raw_result = extract_from_page(page)
    if not raw_result:
        print("❌ No offers extracted."); return

    # Layer 2
    clean = process(raw_result)
    ts    = _timestamp()
    provider = clean["provider"]
    out_path = _save(clean, f"promotions_clean_{provider}_{ts}.json")
    print(f"\n✅ Clean output → {out_path}")
    print(f"   {clean['total_clean']} clean offers from {clean['total_raw']} raw")

    # Layer 3
    if not skip_db:
        try:
            from database.loader import load_promotions
            db_result = load_promotions(clean)
            print(f"  [{provider}] DB load complete: {db_result['inserted']} inserted, {db_result['skipped']} skipped")
        except Exception as e:
            print(f"  [{provider}] ❌ DB load failed: {e}")
    else:
        print(f"  [{provider}] ⏭  DB load skipped (--skip-db)")

def run_load_only(clean_file: str):
    """Re-run database load on a previously saved clean JSON file."""
    if not os.path.exists(clean_file):
        print(f"❌ File not found: {clean_file}"); return

    with open(clean_file, encoding="utf-8") as f:
        clean_data = json.load(f)

    print(f"\n📂 Loaded clean data from {clean_file}")
    
    try:
        from database.loader import load_promotions
        result = load_promotions(clean_data)
        print(f"  ✅ DB load complete: {result['inserted']} inserted, {result['skipped']} skipped")
    except ImportError:
        print("  ⚠️  database.loader not found")
    except Exception as e:
        print(f"  ❌ DB load failed: {e}")



# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Promotion Intelligence Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available providers: {list(COMPETITOR_SITES.keys())}"
    )

    parser.add_argument(
        "--providers",
        nargs   = "+",
        default = list(COMPETITOR_SITES.keys()),
        help    = "Provider names to run (default: all)"
    )
    parser.add_argument(
        "--skip-db",
        action  = "store_true",
        help    = "Skip database load (run Layers 0-2 only)"
    )
    parser.add_argument(
        "--extract-only",
        metavar = "RAW_FILE",
        help    = "Re-run extraction (+ DB load) on an existing raw_markdown_*.json file"
    )
    parser.add_argument(
        "--load-only",
        metavar = "CLEAN_FILE",
        help    = "Run database load on an existing promotions_clean_*.json file"
    )

    args = parser.parse_args()

    if args.load_only:
        run_load_only(args.load_only)
    elif args.extract_only:
        run_extract_only(args.extract_only, skip_db=args.skip_db)
    else:
        result = run_pipeline(args.providers, skip_db=args.skip_db)
        if result:
            print(json.dumps(result, indent=2))
