"""
Layer 2 — Processing
Validates, normalises, and deduplicates offers before DB insertion.

Steps:
  1. Field validation  — drop bad records
  2. Category normalisation — using CATEGORY_MAP
  3. Cross-offer deduplication — rapidfuzz fuzzy title matching
  4. Build clean output dict
"""

import json
import logging
import os
from datetime import date, datetime, timezone

from rapidfuzz import fuzz

from config.settings import (
    CATEGORY_MAP, FUZZY_THRESHOLD,
    VALID_PROMO_TYPES, VALID_USER_TYPES,
    OUTPUT_DIR,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ── Step 1: Field Validation ───────────────────────────────────────────────

def _validate_offer(offer: dict) -> dict | None:
    """
    Returns a cleaned offer dict, or None if the offer should be dropped.

    Rules (from spec):
    - Drop if no offer_title
    - Drop if discount_min > 100
    - Drop if discount_max > 100
    - Fix if discount_min > discount_max → swap
    - Default user_type = "all"
    - Default promo_type = "other"
    """
    title = (offer.get("offer_title") or "").strip()
    if not title:
        return None

    cleaned = dict(offer)

    d_min = cleaned.get("discount_min")
    d_max = cleaned.get("discount_max")

    # Drop hallucinated discounts
    if d_min is not None and d_min > 100:
        return None
    if d_max is not None and d_max > 100:
        return None

    # Fix inverted range
    if d_min is not None and d_max is not None and d_min > d_max:
        cleaned["discount_min"], cleaned["discount_max"] = d_max, d_min

    # Defaults
    if not cleaned.get("user_type") or cleaned["user_type"] not in VALID_USER_TYPES:
        cleaned["user_type"] = "all"
    if not cleaned.get("promo_type") or cleaned["promo_type"] not in VALID_PROMO_TYPES:
        cleaned["promo_type"] = "other"

    return cleaned


# ── Step 2: Category Normalisation ────────────────────────────────────────

def _normalise_category(category: str | None) -> str | None:
    """Map raw category strings to canonical names using CATEGORY_MAP."""
    if not category:
        return category
    lower = category.lower().strip()
    return CATEGORY_MAP.get(lower, category)


# ── Step 3: Deduplication ─────────────────────────────────────────────────

def _deduplicate(offers: list[dict], provider: str) -> list[dict]:
    """
    Deduplicates offers using rapidfuzz.fuzz.ratio on title + same discount_min.

    Spec: two offers are duplicates if:
      same provider + fuzzy title match >= FUZZY_THRESHOLD + same discount_min
    Keeps first occurrence, increments source_count.
    """
    results     : list[dict] = []
    total_before = len(offers)

    for offer in offers:
        title_a = (offer.get("offer_title") or "").lower().strip()
        dm_a    = offer.get("discount_min")
        matched = False

        for existing in results:
            title_b = (existing.get("offer_title") or "").lower().strip()
            dm_b    = existing.get("discount_min")

            ratio = fuzz.ratio(title_a, title_b)
            same_discount = (dm_a == dm_b)  # both None counts as same

            if ratio >= FUZZY_THRESHOLD and same_discount:
                existing["source_count"] = existing.get("source_count", 1) + 1
                matched = True
                break

        if not matched:
            offer["source_count"] = offer.get("source_count", 1)
            results.append(offer)

    removed = total_before - len(results)
    logger.info(
        f"[{provider}] Dedup: {total_before} → {len(results)} offers "
        f"({removed} duplicates removed)"
    )
    return results


# ── Public API ─────────────────────────────────────────────────────────────

def process_provider(raw_result: dict) -> dict:
    """
    Runs all processing steps on a single provider's extraction result.

    Args:
        raw_result: { provider, source_url, scraped_at, offers, total_offers }

    Returns:
        {
          "provider"    : str,
          "source_url"  : str,
          "scraped_date": "YYYY-MM-DD",
          "total_raw"   : int,
          "total_clean" : int,
          "dropped"     : int,
          "offers"      : [validated, normalised, deduped offer dicts]
        }
    """
    provider   = raw_result["provider"]
    raw_offers = raw_result.get("offers", [])
    total_raw  = len(raw_offers)

    logger.info(f"[{provider}] Processing {total_raw} raw offers")

    # Step 1: Validate
    validated = []
    for o in raw_offers:
        clean = _validate_offer(o)
        if clean:
            validated.append(clean)

    dropped_validation = total_raw - len(validated)
    logger.info(f"[{provider}] {dropped_validation} dropped in validation")

    # Step 2: Normalise categories
    for o in validated:
        o["category"] = _normalise_category(o.get("category"))

    # Step 3: Deduplicate
    deduped = _deduplicate(validated, provider)

    dropped_total = total_raw - len(deduped)
    scraped_date  = (
        raw_result.get("scraped_at", "")[:10]   # take YYYY-MM-DD from ISO timestamp
        or date.today().isoformat()
    )

    result = {
        "provider"    : provider,
        "source_url"  : raw_result.get("source_url", ""),
        "scraped_date": scraped_date,
        "total_raw"   : total_raw,
        "total_clean" : len(deduped),
        "dropped"     : dropped_total,
        "offers"      : deduped,
    }

    # Save clean output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts       = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"promotions_clean_{provider}_{ts}.json"
    path     = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    logger.info(
        f"[{provider}] Clean output saved → {path} "
        f"({len(deduped)}/{total_raw} offers kept)"
    )

    return result


def process_all(raw_results: list[dict]) -> list[dict]:
    """Run process_provider on every extraction result."""
    return [process_provider(r) for r in raw_results]
