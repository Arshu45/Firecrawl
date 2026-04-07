"""
Layer 0 — Ingestion
Scrapes a single URL via Firecrawl → returns clean Markdown.

Public API:
    fetch_promotions(url, provider) -> dict
    fetch_all(providers: dict)      -> list[dict]
"""

import json
import os
from datetime import datetime, date

from firecrawl import Firecrawl
from tenacity import retry, stop_after_attempt, wait_fixed, before_log, after_log
import logging

from config.settings import FIRECRAWL_API_KEY, OUTPUT_DIR

logger = logging.getLogger(__name__)


# ── Scroll actions — 12 scrolls × 2s (proven to load all lazy content) ──────
_SCROLL_ACTIONS = []
for _ in range(12):
    _SCROLL_ACTIONS.append({"type": "scroll", "direction": "down"})
    _SCROLL_ACTIONS.append({"type": "wait", "milliseconds": 2000})

_EXCLUDE_TAGS = [
    "nav", "footer", "header",
    "script", "style", "noscript",
    ".sidebar", ".popup", ".modal",
    ".cookie-banner", ".newsletter",
    ".breadcrumb", ".pagination-nav",
    ".social-share", ".related-links",
    "#ad", "#ads", ".advertisement",
]


# ── Core fetch function (with tenacity retry) ─────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    reraise=True,
)
def _scrape_with_retry(url: str, api_key: str) -> str:
    """Calls Firecrawl and returns raw markdown. Retries up to 3× on any error."""
    firecrawl = Firecrawl(api_key=api_key)
    response = firecrawl.scrape(
        url,
        formats            = ["markdown"],
        actions            = _SCROLL_ACTIONS,
        only_main_content  = True,
        exclude_tags       = _EXCLUDE_TAGS,
        timeout            = 120_000,   # 2 min — allows scroll actions to complete
    )
    return response.markdown if hasattr(response, "markdown") else ""


def fetch_promotions(url: str, provider: str) -> dict | None:
    """
    Scrapes a single URL and returns structured raw data.

    Returns:
        {
            "provider"   : str,
            "url"        : str,
            "scraped_at" : ISO 8601 timestamp,
            "scraped_date": "YYYY-MM-DD",
            "markdown"   : str,
            "char_count" : int,
        }
        or None if scrape failed / content too short.
    """
    print(f"\n  [{provider}] Fetching: {url}")

    try:
        markdown = _scrape_with_retry(url, FIRECRAWL_API_KEY)
    except Exception as e:
        print(f"  [{provider}] ❌ Failed after 3 attempts: {e}")
        return None

    if not markdown or len(markdown.strip()) < 200:
        print(f"  [{provider}] ⚠️  Skipped — content too short ({len(markdown)} chars)")
        return None

    print(f"  [{provider}] ✅ {len(markdown):,} chars scraped")

    now = datetime.now()
    return {
        "provider"    : provider,
        "url"         : url,
        "scraped_at"  : now.isoformat(),
        "scraped_date": date.today().isoformat(),
        "markdown"    : markdown,
        "char_count"  : len(markdown),
    }


def fetch_all(providers: dict) -> list:
    """
    Fetches all configured provider URLs.

    Args:
        providers: { "Myntra": "https://...", "Ajio": "https://..." }

    Returns:
        List of page dicts (same shape as fetch_promotions output).
        Also saves each page to output/raw_markdown_{provider}_{timestamp}.json
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = []
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    print(f"\n{'='*55}")
    print(f"  FETCH STARTING — {len(providers)} provider(s)")
    print(f"{'='*55}")

    for provider, url in providers.items():
        page = fetch_promotions(url, provider)
        if not page:
            continue

        # Save raw markdown for this provider
        filename = f"raw_markdown_{provider}_{timestamp}.json"
        out_path = os.path.join(OUTPUT_DIR, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(page, f, indent=2, ensure_ascii=False)
        print(f"  [{provider}] 💾 Saved → {out_path}")

        results.append(page)

    print(f"\n{'='*55}")
    print(f"  FETCH COMPLETE — {len(results)}/{len(providers)} succeeded")
    print(f"{'='*55}\n")

    return results
