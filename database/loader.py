"""
Layer 3 — Database Loader
Loads clean processed offers into PostgreSQL.

Idempotent: running the pipeline twice for the same date will NOT
create duplicate rows. Uniqueness is enforced by checking
(offer_title, competitor_id, scraped_date) before insert.

Public API:
    load_promotions(clean_data: dict) -> {"inserted": int, "skipped": int}
    load_all(clean_results: list)     -> {"total_inserted": int, "total_skipped": int}
"""

import datetime as dt
import logging
from database.db_client import DBClient

logger = logging.getLogger(__name__)


_NULL_LIKE = {"", "null", "none", "n/a", "na", "-", "--"}


def _clean_scalar(value):
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in _NULL_LIKE:
            return None
        return stripped
    return value


def _coerce_date(value):
    value = _clean_scalar(value)
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            logger.warning("Could not coerce valid_until to date: %r", value)
            return None
    return None


def _prepare_offer_for_db(offer: dict, source_url: str, scraped_date: str) -> dict:
    prepared = {key: _clean_scalar(val) for key, val in offer.items()}
    prepared["source_url"] = _clean_scalar(source_url)
    prepared["scraped_date"] = _coerce_date(scraped_date) or scraped_date
    prepared["valid_until"] = _coerce_date(prepared.get("valid_until"))
    return prepared


# ── Upsert competitor ──────────────────────────────────────────────────────────

def _get_or_create_competitor(db: DBClient, name: str, source_url: str) -> int:
    """
    Ensures the competitor row exists and returns its id.
    Uses INSERT ... ON CONFLICT DO NOTHING to stay idempotent.
    """
    # Try insert first (idempotent)
    db.execute_write(
        """
        INSERT INTO competitors (name, source_url)
        VALUES (%s, %s)
        ON CONFLICT (name) DO NOTHING
        """,
        (name, source_url),
    )

    # Fetch the id (works whether just inserted or already existed)
    row = db.execute_one(
        "SELECT id FROM competitors WHERE name = %s",
        (name,),
    )
    return row["id"]


# ── Insert single offer ────────────────────────────────────────────────────────

def _insert_offer(db: DBClient, offer: dict, competitor_id: int, scraped_date: str) -> bool:
    """
    Inserts one offer. Returns True if inserted, False if skipped (duplicate).
    Duplicate check: same offer_title + competitor_id + scraped_date.
    """
    # Check for existing row
    existing = db.execute_one(
        """
        SELECT id FROM promotions
        WHERE offer_title    = %s
          AND competitor_id  = %s
          AND scraped_date   = %s
        LIMIT 1
        """,
        (offer.get("offer_title"), competitor_id, scraped_date),
    )

    if existing:
        return False  # already loaded — skip

    db.execute_write(
        """
        INSERT INTO promotions (
            competitor_id, offer_title, description, brand, category,
            promo_type, discount_min, discount_max, flat_value,
            min_purchase, coupon_code, user_type, valid_until,
            source_count, source_url, scraped_date
        ) VALUES (
            %(competitor_id)s, %(offer_title)s, %(description)s, %(brand)s, %(category)s,
            %(promo_type)s, %(discount_min)s, %(discount_max)s, %(flat_value)s,
            %(min_purchase)s, %(coupon_code)s, %(user_type)s, %(valid_until)s,
            %(source_count)s, %(source_url)s, %(scraped_date)s
        )
        """,
        {
            "competitor_id": competitor_id,
            "offer_title"  : _clean_scalar(offer.get("offer_title")),
            "description"  : _clean_scalar(offer.get("description")),
            "brand"        : _clean_scalar(offer.get("brand")),
            "category"     : _clean_scalar(offer.get("category")),
            "promo_type"   : _clean_scalar(offer.get("promo_type", "other")),
            "discount_min" : offer.get("discount_min"),
            "discount_max" : offer.get("discount_max"),
            "flat_value"   : offer.get("flat_value"),
            "min_purchase" : offer.get("min_purchase"),
            "coupon_code"  : _clean_scalar(offer.get("coupon_code")),
            "user_type"    : _clean_scalar(offer.get("user_type", "all")),
            "valid_until"  : _coerce_date(offer.get("valid_until")),
            "source_count" : offer.get("source_count", 1),
            "source_url"   : _clean_scalar(offer.get("source_url")),
            "scraped_date" : _coerce_date(scraped_date) or scraped_date,
        },
    )
    return True


# ── Public API ─────────────────────────────────────────────────────────────────

def load_promotions(clean_data: dict) -> dict:
    """
    Loads all clean offers from one provider into the database.

    Args:
        clean_data: output from processing.post_processor.process()
            { provider, source_url, scraped_date, total_raw, total_clean, dropped, offers }

    Returns:
        { "inserted": int, "skipped": int }
    """
    provider      = clean_data["provider"]
    source_url    = clean_data.get("source_url", "")
    scraped_date  = clean_data.get("scraped_date", "")
    offers        = clean_data.get("offers", [])

    inserted = 0
    skipped  = 0

    print(f"\n  [{provider}] Loading {len(offers)} offers into DB...")

    db = DBClient()
    try:
        competitor_id = _get_or_create_competitor(db, provider, source_url)
        logger.info(f"[{provider}] competitor_id={competitor_id}")

        for offer in offers:
            # Attach source_url to offer for storage
            offer_with_url = _prepare_offer_for_db(offer, source_url=source_url, scraped_date=scraped_date)
            was_inserted = _insert_offer(db, offer_with_url, competitor_id, scraped_date)
            if was_inserted:
                inserted += 1
            else:
                skipped += 1

    except Exception as e:
        logger.error(f"[{provider}] DB load failed: {e}")
        raise
    finally:
        db.close()

    print(f"  [{provider}] ✅ DB load complete — {inserted} inserted, {skipped} skipped")
    return {"inserted": inserted, "skipped": skipped}


def load_all(clean_results: list) -> dict:
    """
    Loads all providers' clean results into the database.

    Args:
        clean_results: list from processing.post_processor.process_all()

    Returns:
        { "total_inserted": int, "total_skipped": int, "by_provider": { provider: {...} } }
    """
    total_inserted = 0
    total_skipped  = 0
    by_provider    = {}

    print(f"\n{'='*55}")
    print(f"  DB LOAD STARTING — {len(clean_results)} provider(s)")
    print(f"{'='*55}")

    for clean in clean_results:
        provider = clean["provider"]
        try:
            result = load_promotions(clean)
            by_provider[provider]  = result
            total_inserted        += result["inserted"]
            total_skipped         += result["skipped"]
        except Exception as e:
            by_provider[provider] = {"inserted": 0, "skipped": 0, "error": str(e)}
            print(f"  [{provider}] ❌ Load failed: {e}")

    print(f"\n{'='*55}")
    print(f"  DB LOAD COMPLETE")
    print(f"  Total inserted : {total_inserted}")
    print(f"  Total skipped  : {total_skipped}")
    print(f"{'='*55}\n")

    return {
        "total_inserted": total_inserted,
        "total_skipped" : total_skipped,
        "by_provider"   : by_provider,
    }


# ── Internal Store Data Load ───────────────────────────────────────────────────

def load_internal_promotions(internal_offers: list[dict]) -> dict:
    """
    Loads transformed MySQL promotions into the internal_promotions table.
    Uses internal_promo_id for idempotency (UPSERT/ON CONFLICT DO UPDATE).
    """
    inserted = 0
    updated  = 0
    skipped  = 0

    print(f"\n  [Internal Sync] Loading {len(internal_offers)} offers into DB...")

    db = DBClient()
    try:
        for offer in internal_offers:
            promo_id = offer.get("internal_promo_id")
            if not promo_id:
                logger.warning("Skipping internal offer without internal_promo_id")
                skipped += 1
                continue

            # We use an UPSERT (ON CONFLICT) so running sync twice updates any changes.
            db.execute_write(
                """
                INSERT INTO internal_promotions (
                    internal_promo_id, offer_title, description, brand, category,
                    promo_type, discount_min, discount_max, flat_value,
                    min_purchase, coupon_code, user_type, valid_until,
                    source_count, source_url, scraped_date
                ) VALUES (
                    %(internal_promo_id)s, %(offer_title)s, %(description)s, %(brand)s, %(category)s,
                    %(promo_type)s, %(discount_min)s, %(discount_max)s, %(flat_value)s,
                    %(min_purchase)s, %(coupon_code)s, %(user_type)s, %(valid_until)s,
                    %(source_count)s, %(source_url)s, %(scraped_date)s
                )
                ON CONFLICT (internal_promo_id) DO UPDATE SET
                    offer_title  = EXCLUDED.offer_title,
                    description  = EXCLUDED.description,
                    brand        = EXCLUDED.brand,
                    category     = EXCLUDED.category,
                    promo_type   = EXCLUDED.promo_type,
                    discount_min = EXCLUDED.discount_min,
                    discount_max = EXCLUDED.discount_max,
                    flat_value   = EXCLUDED.flat_value,
                    min_purchase = EXCLUDED.min_purchase,
                    coupon_code  = EXCLUDED.coupon_code,
                    user_type    = EXCLUDED.user_type,
                    valid_until  = EXCLUDED.valid_until,
                    scraped_date = EXCLUDED.scraped_date;
                """,
                {
                    **offer,
                    "offer_title": _clean_scalar(offer.get("offer_title")),
                    "description": _clean_scalar(offer.get("description")),
                    "brand": _clean_scalar(offer.get("brand")),
                    "category": _clean_scalar(offer.get("category")),
                    "promo_type": _clean_scalar(offer.get("promo_type")),
                    "coupon_code": _clean_scalar(offer.get("coupon_code")),
                    "user_type": _clean_scalar(offer.get("user_type")),
                    "source_url": _clean_scalar(offer.get("source_url")),
                    "valid_until": _coerce_date(offer.get("valid_until")),
                    "scraped_date": _coerce_date(offer.get("scraped_date")) or offer.get("scraped_date"),
                }
            )
            inserted += 1  # Technically this counts both inserts and updates

    except Exception as e:
        logger.error(f"[Internal Sync] DB load failed: {e}")
        raise
    finally:
        db.close()

    print(f"  [Internal Sync] ✅ DB load complete — {inserted} records upserted")
    return {"upserted": inserted, "skipped": skipped}
