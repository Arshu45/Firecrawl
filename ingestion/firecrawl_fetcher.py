"""
Layer 0 — Ingestion
Fetches a URL via Firecrawl and returns clean markdown.

fetch_promotions(url, provider) -> dict
  {
    "provider"   : str,
    "url"        : str,
    "scraped_at" : ISO timestamp,
    "markdown"   : str,
    "char_count" : int
  }
"""

import json
import os
from datetime import datetime

from firecrawl import Firecrawl
from tenacity import retry, stop_after_attempt, wait_fixed, RetryError
import logging

from config.settings import FIRECRAWL_API_KEY, OUTPUT_DIR

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def _build_scroll_actions(count: int = 12, wait_ms: int = 1500) -> list:
    """Build a sequence of scroll+wait actions for lazy-loaded pages."""
    actions = []
    for _ in range(count):
        actions.append({"type": "scroll", "direction": "down"})
        actions.append({"type": "wait", "milliseconds": wait_ms})
    return actions


@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def _scrape_with_retry(url: str, api_key: str) -> str:
    """Internal scrape call wrapped in tenacity — 3 attempts, 5s wait."""
    client = Firecrawl(api_key=api_key)
    response = client.scrape(
        url,
        formats           = ["markdown"],
        actions           = _build_scroll_actions(),
        only_main_content = True,
        exclude_tags      = [
            "nav", "footer", "header",
            "script", "style", "noscript",
            ".sidebar", ".popup", ".modal",
            ".cookie-banner", ".newsletter",
            ".breadcrumb", ".pagination-nav",
            ".social-share", ".related-links",
            "#ad", "#ads", ".advertisement",
        ],
        timeout = 30000,   # 30 seconds per spec
    )
    return response.markdown if hasattr(response, "markdown") else ""


def fetch_promotions(url: str, provider: str) -> dict:
    """
    Fetches a single URL and returns structured result.

    Returns dict with provider, url, scraped_at, markdown, char_count.
    Saves raw result to output/raw_markdown_{provider}_{timestamp}.json.
    Raises on failure (caller decides whether to skip or abort).
    """
    logger.info(f"[{provider}] Fetching: {url}")

    try:
        markdown = _scrape_with_retry(url, FIRECRAWL_API_KEY)
    except RetryError as e:
        logger.error(f"[{provider}] Failed after 3 attempts: {e}")
        raise
    except Exception as e:
        logger.error(f"[{provider}] Scrape error: {e}")
        raise

    char_count = len(markdown.strip())
    if char_count < 200:
        logger.warning(f"[{provider}] Content too short ({char_count} chars) — skipping")
        raise ValueError(f"Content too short: {char_count} chars")

    logger.info(f"[{provider}] Retrieved {char_count:,} chars")

    scraped_at = datetime.utcnow().isoformat() + "Z"
    result = {
        "provider"  : provider,
        "url"       : url,
        "scraped_at": scraped_at,
        "markdown"  : markdown,
        "char_count": char_count,
    }

    # Save raw markdown to output/
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"raw_markdown_{provider}_{ts}.json"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info(f"[{provider}] Raw markdown saved → {path}")

    return result


def fetch_all(providers: list[str]) -> list[dict]:
    """
    Fetches all URLs for the given list of provider names.
    Skips providers that fail — logs and continues.

    Returns flat list of fetch results.
    """
    from config.settings import COMPETITOR_SITES

    results = []
    for provider in providers:
        url = COMPETITOR_SITES.get(provider)
        if not url:
            logger.warning(f"No URL configured for provider: {provider}")
            continue
        try:
            result = fetch_promotions(url, provider)
            results.append(result)
        except Exception as e:
            logger.error(f"[{provider}] Skipped due to error: {e}")
            continue

    logger.info(f"Fetch complete: {len(results)}/{len(providers)} providers succeeded")
    return results
