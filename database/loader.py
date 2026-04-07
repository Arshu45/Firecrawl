"""
Layer 3 — Database Loader
Idempotent upsert: clean processed offers → PostgreSQL.
Running the pipeline twice for the same date is safe — no duplicate rows.
"""

import logging
from datetime import date

from database.db_client import DBClient

logger = logging.getLogger(__name__)


def _trunc(value: str | None, max_len: int) -> str | None:
    """Silently truncate a string to max_len characters.
    Prevents 'value too long for type character varying' errors
    when the LLM extracts an unexpectedly verbose field value.
    """
    if value is None:
        return None
    return str(value)[:max_len]


def load_promotions(clean_data: dict) -> dict:
    """
    Loads a single provider's clean offers into PostgreSQL.

    Args:
        clean_data: output from processing/post_processor.process_provider()
        {
          "provider"    : str,
          "source_url"  : str,
          "scraped_date": "YYYY-MM-DD",
          "offers"      : [list of offer dicts]
        }

    Returns:
        {"inserted": int, "skipped": int}
    """
    db           = DBClient()
    provider     = clean_data["provider"]
    source_url   = clean_data.get("source_url", "")
    scraped_date = clean_data.get("scraped_date", date.today().isoformat())
    offers       = clean_data.get("offers", [])

    inserted = 0
    skipped  = 0

    try:
        # Step 1: Upsert competitor → get id
        competitor = db.execute_returning(
            """
            INSERT INTO competitors (name, source_url)
            VALUES (%(name)s, %(source_url)s)
            ON CONFLICT (name) DO UPDATE SET source_url = EXCLUDED.source_url
            RETURNING id
            """,
            {"name": _trunc(provider, 100), "source_url": source_url},
        )
        competitor_id = competitor["id"]
        logger.info("[%s] Competitor id=%s", provider, competitor_id)

        # Step 2: Insert each offer (idempotent check)
        for offer in offers:
            existing = db.execute_one(
                """
                SELECT id FROM promotions
                WHERE offer_title = %(title)s
                  AND competitor_id = %(cid)s
                  AND scraped_date  = %(sdate)s
                """,
                {
                    "title" : offer.get("offer_title", ""),
                    "cid"   : competitor_id,
                    "sdate" : scraped_date,
                },
            )

            if existing:
                skipped += 1
                continue

            db.execute_write(
                """
                INSERT INTO promotions (
                    competitor_id, offer_title, description, brand, category,
                    promo_type, discount_min, discount_max, flat_value, min_purchase,
                    coupon_code, user_type, valid_until, source_count,
                    source_url, scraped_date
                ) VALUES (
                    %(competitor_id)s, %(offer_title)s, %(description)s, %(brand)s, %(category)s,
                    %(promo_type)s, %(discount_min)s, %(discount_max)s, %(flat_value)s, %(min_purchase)s,
                    %(coupon_code)s, %(user_type)s, %(valid_until)s, %(source_count)s,
                    %(source_url)s, %(scraped_date)s
                )
                """,
                {
                    "competitor_id": competitor_id,
                    "offer_title"  : offer.get("offer_title"),           # TEXT — no limit
                    "description"  : offer.get("description"),           # TEXT — no limit
                    "brand"        : offer.get("brand"),                 # TEXT — no limit
                    "category"     : _trunc(offer.get("category"),   100),
                    "promo_type"   : _trunc(offer.get("promo_type", "other"), 100),
                    "discount_min" : offer.get("discount_min"),
                    "discount_max" : offer.get("discount_max"),
                    "flat_value"   : offer.get("flat_value"),
                    "min_purchase" : offer.get("min_purchase"),
                    "coupon_code"  : _trunc(offer.get("coupon_code"),  100),
                    "user_type"    : _trunc(offer.get("user_type", "all"), 50),
                    "valid_until"  : offer.get("valid_until"),           # TEXT — no limit
                    "source_count" : offer.get("source_count", 1),
                    "source_url"   : source_url,
                    "scraped_date" : scraped_date,
                },
            )
            inserted += 1

    finally:
        db.close()

    logger.info("[%s] Load complete — inserted:%d skipped:%d", provider, inserted, skipped)
    return {"inserted": inserted, "skipped": skipped}


def load_all(clean_results: list[dict]) -> dict:
    """Load all providers. Returns summary dict."""
    total_inserted = 0
    total_skipped  = 0
    for result in clean_results:
        summary        = load_promotions(result)
        total_inserted += summary["inserted"]
        total_skipped  += summary["skipped"]
    return {"inserted": total_inserted, "skipped": total_skipped}
