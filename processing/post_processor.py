"""
Layer 2 — Processing / Post-Processor
Makes extraction output trustworthy before DB insertion.

Steps performed in order:
  1. Field Validation  — drop bad records, fix swapped discounts, apply defaults
  2. Category Normalisation — map synonyms to canonical category names (CATEGORY_MAP)
  3. Cross-offer Deduplication — rapidfuzz fuzzy title match (>= FUZZY_THRESHOLD)
  4. Output shaping — return clean summary dict + save promotions_clean_{provider}_{ts}.json

Public API:
    process(raw_result: dict) -> dict
    process_all(raw_results: list) -> list[dict]
"""

import json
import os
import logging
import datetime as dt
from copy import deepcopy

from rapidfuzz import fuzz

from config.settings import (
    CATEGORY_MAP, FUZZY_THRESHOLD, OUTPUT_DIR,
    VALID_PROMO_TYPES, VALID_USER_TYPES,
)

logger = logging.getLogger(__name__)


# ── Step 1: Field Validation ───────────────────────────────────────────────────

def _validate_offer(offer: dict, idx: int, provider: str) -> dict | None:
    """
    Validates and sanitises a single offer dict.
    Returns cleaned offer or None if it should be dropped.
    """
    # Drop if no offer_title
    title = (offer.get("offer_title") or "").strip()
    if not title:
        logger.warning(f"[{provider}] offer[{idx}] dropped — missing offer_title")
        return None

    cleaned = deepcopy(offer)
    cleaned["offer_title"] = title

    # Numeric fields — cast to float, drop offer if clearly hallucinated
    for field in ("discount_min", "discount_max", "flat_value", "min_purchase"):
        val = cleaned.get(field)
        if val is not None:
            try:
                cleaned[field] = float(val)
            except (TypeError, ValueError):
                cleaned[field] = None

    d_min = cleaned.get("discount_min")
    d_max = cleaned.get("discount_max")

    # Drop if discount > 100 (hallucination)
    if d_min is not None and d_min > 100:
        logger.warning(f"[{provider}] offer[{idx}] dropped — discount_min={d_min} > 100")
        return None
    if d_max is not None and d_max > 100:
        logger.warning(f"[{provider}] offer[{idx}] dropped — discount_max={d_max} > 100")
        return None

    # Fix swapped min/max
    if d_min is not None and d_max is not None and d_min > d_max:
        logger.info(f"[{provider}] offer[{idx}] — swapping discount_min/max ({d_min} ↔ {d_max})")
        cleaned["discount_min"], cleaned["discount_max"] = d_max, d_min

    # Defaults
    if not cleaned.get("user_type") or cleaned["user_type"] not in VALID_USER_TYPES:
        cleaned["user_type"] = "all"
    if not cleaned.get("promo_type") or cleaned["promo_type"] not in VALID_PROMO_TYPES:
        cleaned["promo_type"] = "other"

    return cleaned


def _validate_all(offers: list, provider: str) -> tuple[list, int]:
    """Returns (valid_offers, dropped_count)."""
    valid   = []
    dropped = 0
    for i, offer in enumerate(offers):
        result = _validate_offer(offer, i, provider)
        if result is not None:
            valid.append(result)
        else:
            dropped += 1
    return valid, dropped


# ── Step 2: Category Normalisation ────────────────────────────────────────────

def _normalise_category(category: str | None) -> str | None:
    """Maps synonyms to canonical category names using CATEGORY_MAP (case-insensitive)."""
    if not category:
        return category
    key = category.lower().strip()
    return CATEGORY_MAP.get(key, category)


def _normalise_categories(offers: list) -> list:
    for offer in offers:
        offer["category"] = _normalise_category(offer.get("category"))
    return offers


# ── Step 3: Fuzzy Deduplication ───────────────────────────────────────────────

def _deduplicate(offers: list, provider: str) -> tuple[list, int]:
    """
    Deduplicates offers using:
      Priority 1: exact coupon_code match (non-null)
      Priority 2: rapidfuzz title ratio >= FUZZY_THRESHOLD + same discount_min

    When duplicate found: merge richer fields into existing record, increment source_count.
    Returns (unique_offers, removed_count).
    """
    code_index  : dict[str, int] = {}   # coupon_code → result index
    result      : list           = []
    removed     = 0

    def _merge(base: dict, incoming: dict) -> dict:
        """Keep richer values from both records."""
        merged = deepcopy(base)
        merged["source_count"] = merged.get("source_count", 1) + 1
        for key, val in incoming.items():
            base_val = merged.get(key)
            if key == "description":
                if val and len(str(val)) > len(str(base_val or "")):
                    merged[key] = val
            elif base_val is None and val is not None:
                merged[key] = val
        return merged

    for offer in offers:
        if "source_count" not in offer:
            offer["source_count"] = 1

        code  = offer.get("coupon_code")
        title = (offer.get("offer_title") or "").lower().strip()
        d_min = offer.get("discount_min")

        # ── Primary key: coupon_code ──────────────────────
        if code:
            if code in code_index:
                idx         = code_index[code]
                result[idx] = _merge(result[idx], offer)
                removed    += 1
                continue
            else:
                code_index[code] = len(result)
                result.append(deepcopy(offer))
                continue

        # ── Secondary key: fuzzy title + same discount_min ─
        matched = False
        for idx, existing in enumerate(result):
            existing_title = (existing.get("offer_title") or "").lower().strip()
            existing_d_min = existing.get("discount_min")

            ratio = fuzz.ratio(title, existing_title)
            if ratio >= FUZZY_THRESHOLD and d_min == existing_d_min:
                result[idx] = _merge(result[idx], offer)
                removed    += 1
                matched = True
                break

        if not matched:
            result.append(deepcopy(offer))

    print(f"  [{provider}] Dedup: {len(offers):>4} → {len(result):>4} unique "
          f"({removed} duplicates removed, fuzzy threshold: {FUZZY_THRESHOLD}%)")
    return result, removed


# ── Step 4: Output shaping ────────────────────────────────────────────────────

def process(raw_result: dict) -> dict:
    """
    Runs all 3 processing steps on a single provider's raw extraction output.

    Args:
        raw_result: { source_url, provider, scraped_date, offers: [...] }

    Returns:
        {
            "provider"    : str,
            "source_url"  : str,
            "scraped_date": str,
            "total_raw"   : int,
            "total_clean" : int,
            "dropped"     : int,
            "offers"      : [list of clean validated offers],
        }
    """
    provider     = raw_result["provider"]
    source_url   = raw_result.get("source_url", "")
    scraped_date = raw_result.get("scraped_date", "")
    raw_offers   = raw_result.get("offers", [])
    total_raw    = len(raw_offers)

    print(f"\n  [{provider}] Processing {total_raw} raw offers...")

    # Step 1: Validate
    valid_offers, dropped = _validate_all(raw_offers, provider)
    print(f"  [{provider}] Validation: {total_raw} raw → {len(valid_offers)} valid, {dropped} dropped")

    # Step 2: Normalise categories
    valid_offers = _normalise_categories(valid_offers)

    # Step 3: Deduplicate
    clean_offers, dupes_removed = _deduplicate(valid_offers, provider)
    dropped += dupes_removed   # count dedup removals in dropped total

    print(f"  [{provider}] ✅ Final: {len(clean_offers)} clean offers "
          f"(from {total_raw} raw, {dropped} total removed)")

    return {
        "provider"    : provider,
        "source_url"  : source_url,
        "scraped_date": scraped_date,
        "total_raw"   : total_raw,
        "total_clean" : len(clean_offers),
        "dropped"     : dropped,
        "offers"      : clean_offers,
    }


def process_all(raw_results: list) -> list:
    """
    Processes all provider results and saves clean JSON per provider.

    Args:
        raw_results: list from extraction.extract_all()

    Returns:
        list of clean provider dicts (same as process() output)
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    results   = []

    print(f"\n{'='*55}")
    print(f"  POST-PROCESSING — {len(raw_results)} provider(s)")
    print(f"{'='*55}")

    for raw in raw_results:
        clean = process(raw)
        results.append(clean)

        # Save clean output per provider
        provider = clean["provider"]
        filename = f"promotions_clean_{provider}_{timestamp}.json"
        out_path = os.path.join(OUTPUT_DIR, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)
        print(f"  [{provider}] 💾 Clean saved → {out_path}")

    grand_total = sum(r["total_clean"] for r in results)
    grand_raw   = sum(r["total_raw"]   for r in results)
    print(f"\n{'='*55}")
    print(f"  PROCESSING COMPLETE — {grand_raw} raw → {grand_total} clean offers")
    print(f"{'='*55}\n")

    return results
