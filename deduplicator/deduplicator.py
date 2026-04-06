import re
from collections import defaultdict


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------

def _normalize_title(title: str) -> str:
    """Lowercase + collapse whitespace for fuzzy title comparison."""
    return re.sub(r"\s+", " ", title.lower().strip())


def _merge_offers(base: dict, incoming: dict) -> dict:
    """
    Merges two duplicate offers into one richer record.
    Rules:
    - description : keep the longer one (more detail)
    - all other fields : keep base value if non-null, else take incoming
    """
    merged = dict(base)

    for key, val_incoming in incoming.items():
        val_base = merged.get(key)

        if key == "description":
            # Keep whichever description is longer
            if val_incoming and len(str(val_incoming)) > len(str(val_base or "")):
                merged[key] = val_incoming
        else:
            # Fill in any null field from the incoming record
            if val_base is None and val_incoming is not None:
                merged[key] = val_incoming

    return merged


def _deduplicate_offers(offers: list, provider: str) -> list:
    """
    Deduplicates a flat list of offers from multiple sources.

    Priority:
      1. coupon_code (non-null) — same code = same offer
      2. normalized offer_title (for null-code offers)

    When a duplicate is found, the two records are merged
    (keeping the richer values from both).
    """
    code_index  : dict[str, int] = {}   # coupon_code → result index
    title_index : dict[str, int] = {}   # normalized title → result index
    result      : list           = []
    removed     = 0

    for offer in offers:
        code  = offer.get("coupon_code")
        title = _normalize_title(offer.get("offer_title", ""))

        if code:
            # ── Primary key: coupon_code ────────────────────
            if code in code_index:
                idx         = code_index[code]
                result[idx] = _merge_offers(result[idx], offer)
                removed    += 1
            else:
                code_index[code]   = len(result)
                title_index[title] = len(result)   # also index by title
                result.append(dict(offer))

        else:
            # ── Secondary key: normalized title ────────────
            if title in title_index:
                idx         = title_index[title]
                result[idx] = _merge_offers(result[idx], offer)
                removed    += 1
            else:
                title_index[title] = len(result)
                result.append(dict(offer))

    print(f"  [{provider}] Dedup: {len(offers):>4} raw offers → "
          f"{len(result):>4} unique ({removed} duplicates removed)")

    return result


# -------------------------------------------------------
# Public API
# -------------------------------------------------------

def merge_by_provider(pages: list) -> list:
    """
    Merges per-URL extraction results into one entry per provider,
    deduplicating offers across all sources.

    Input:
        [
            { "source_url": "...", "provider": "Myntra", "scraped_date": "...", "offers": [...] },
            { "source_url": "...", "provider": "Myntra", "scraped_date": "...", "offers": [...] },
            { "source_url": "...", "provider": "Ajio",   "scraped_date": "...", "offers": [...] },
        ]

    Output:
        [
            {
                "provider"     : "Myntra",
                "scraped_date" : "2026-03-30",
                "source_urls"  : ["grabon.in/myntra", "coupondunia.in/myntra", ...],
                "total_sources": 3,
                "total_offers" : 87,
                "offers"       : [ ...87 unique offers... ]
            },
            {
                "provider"     : "Ajio",
                ...
            }
        ]
    """

    # ── Step 1: Group all pages by provider ────────────
    by_provider: dict = defaultdict(lambda: {
        "source_urls"  : [],
        "scraped_date" : "",
        "raw_offers"   : []
    })

    for page in pages:
        provider = page["provider"]
        entry    = by_provider[provider]

        entry["source_urls"].append(page["source_url"])

        if not entry["scraped_date"]:
            entry["scraped_date"] = page.get("scraped_date", "")

        entry["raw_offers"].extend(page.get("offers", []))

    # ── Step 2: Deduplicate per provider ───────────────
    print(f"\n{'='*55}")
    print(f"  DEDUPLICATION")
    print(f"  Providers : {len(by_provider)}")
    print(f"{'='*55}")

    results      = []
    grand_total  = 0

    for provider, data in by_provider.items():
        print(f"\n  [{provider}]")
        unique_offers = _deduplicate_offers(data["raw_offers"], provider)
        grand_total  += len(unique_offers)

        results.append({
            "provider"     : provider,
            "scraped_date" : data["scraped_date"],
            "source_urls"  : data["source_urls"],
            "total_sources": len(data["source_urls"]),
            "total_offers" : len(unique_offers),
            "offers"       : unique_offers
        })

    print(f"\n{'='*55}")
    print(f"  DEDUPLICATION COMPLETE")
    print(f"  Providers     : {len(results)}")
    print(f"  Total unique  : {grand_total} offers")
    print(f"{'='*55}\n")

    return results
