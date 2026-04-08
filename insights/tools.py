import json
import logging

from langchain_core.tools import tool

from database.db_client import DBClient
from config.settings import (
    CLIENT_BRAND,
    DEFAULT_ACTIVE_OFFERS_LIMIT,
    DEFAULT_TOP_COMPETITORS_LIMIT,
    TOOL_SUMMARY_TOP_OFFERS,
)

logger = logging.getLogger(__name__)


def _truncate(value, limit: int = 500) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


def _normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    category = category.strip().title()
    return category or None


def _serialize_payload(payload: dict) -> str:
    return json.dumps(payload, default=str)


def _top_offer_examples(rows: list[dict], limit: int = TOOL_SUMMARY_TOP_OFFERS) -> list[dict]:
    examples = []
    for row in rows[:limit]:
        examples.append(
            {
                "offer_title": row.get("offer_title"),
                "category": row.get("category"),
                "promo_type": row.get("promo_type"),
                "discount_max": row.get("discount_max"),
                "valid_until": row.get("valid_until"),
            }
        )
    return examples


@tool
def get_category_trends(category: str | None = None) -> str:
    """
    Returns discount trends for a specific category, or for all categories when category is omitted.
    """
    category = _normalize_category(category)
    logger.info("Tool get_category_trends called | category=%s", category)

    with DBClient() as db:
        if category is None:
            competitor_rows = db.execute(
                """
                SELECT
                    p.category,
                    c.name AS brand,
                    ROUND(AVG(p.discount_max), 2) AS avg_discount,
                    COUNT(p.id) AS active_offers
                FROM promotions p
                JOIN competitors c ON p.competitor_id = c.id
                WHERE p.category IS NOT NULL
                  AND p.discount_max IS NOT NULL
                GROUP BY p.category, c.name
                ORDER BY p.category, avg_discount DESC NULLS LAST
                """
            )
            internal_rows = db.execute(
                """
                SELECT
                    category,
                    %s AS brand,
                    ROUND(AVG(discount_max), 2) AS avg_discount,
                    COUNT(*) AS active_offers
                FROM internal_promotions
                WHERE category IS NOT NULL
                  AND valid_until >= CURRENT_DATE::text
                  AND discount_max IS NOT NULL
                GROUP BY category
                ORDER BY category
                """,
                (CLIENT_BRAND,),
            )
            rows = competitor_rows + internal_rows
        else:
            rows = db.execute(
                """
                SELECT 
                    %s as brand, 
                    ROUND(AVG(discount_max), 2) as avg_discount, 
                    COUNT(*) as active_offers
                FROM internal_promotions
                WHERE category = %s AND valid_until >= CURRENT_DATE::text AND discount_max IS NOT NULL
                
                UNION ALL
                
                SELECT 
                    c.name as brand, 
                    ROUND(AVG(p.discount_max), 2) as avg_discount, 
                    COUNT(p.id) as active_offers
                FROM promotions p
                JOIN competitors c ON p.competitor_id = c.id
                WHERE p.category = %s AND p.discount_max IS NOT NULL
                GROUP BY c.name
                """,
                (CLIENT_BRAND, category, category),
            )
    logger.info(
        "Tool get_category_trends DB rows fetched | category=%s | row_count=%d | preview=%s",
        category,
        len(rows),
        _truncate(rows),
    )
    
    if not rows:
        if category is None:
            return "No category trend data found."
        return f"No active promotional data found for category: {category}."

    if category is None:
        grouped = {}
        for row in rows:
            row_category = row.get("category")
            if not row_category:
                continue
            grouped.setdefault(row_category, []).append(
                {
                    "brand": row.get("brand"),
                    "avg_discount": row.get("avg_discount"),
                    "active_offers": row.get("active_offers"),
                }
            )
        payload = {
            "scope": "all_categories",
            "category_count": len(grouped),
            "categories": [
                {"category": category_name, "brands": brand_rows}
                for category_name, brand_rows in sorted(grouped.items())
            ],
        }
    else:
        payload = {
            "scope": "single_category",
            "category": category,
            "brands": [
                {
                    "brand": row.get("brand"),
                    "avg_discount": row.get("avg_discount"),
                    "active_offers": row.get("active_offers"),
                }
                for row in rows
            ],
        }

    result = _serialize_payload(payload)
    logger.info("Tool get_category_trends returning | payload=%s", _truncate(result))
    return result


@tool
def get_top_competitors(category: str, limit: int = DEFAULT_TOP_COMPETITORS_LIMIT) -> str:
    """
    Use this only when a specific category is explicitly known from the user request.
    Returns which competitors are giving the deepest discounts in that exact category.
    """
    category = category.strip().title()
    logger.info("Tool get_top_competitors called | category=%s | limit=%s", category, limit)
    query = """
    SELECT 
        c.name as competitor, 
        MAX(p.discount_max) as deepest_discount,
        ROUND(AVG(p.discount_max), 2) as avg_discount
    FROM promotions p
    JOIN competitors c ON p.competitor_id = c.id
    WHERE p.category = %s AND p.discount_max IS NOT NULL
    GROUP BY c.name
    ORDER BY deepest_discount DESC
    LIMIT %s
    """
    
    with DBClient() as db:
        rows = db.execute(query, (category, limit))
    logger.info(
        "Tool get_top_competitors DB rows fetched | category=%s | row_count=%d | preview=%s",
        category,
        len(rows),
        _truncate(rows),
    )
    
    if not rows:
        return f"No competitor discounts found for category: {category}."

    payload = {
        "category": category,
        "competitor_count": len(rows),
        "competitors": [
            {
                "competitor": row.get("competitor"),
                "deepest_discount": row.get("deepest_discount"),
                "avg_discount": row.get("avg_discount"),
            }
            for row in rows
        ],
    }
    result = _serialize_payload(payload)
    logger.info("Tool get_top_competitors returning | payload=%s", _truncate(result))
    return result


@tool
def get_active_offers(
    brand: str,
    category: str | None = None,
    limit: int = DEFAULT_ACTIVE_OFFERS_LIMIT,
) -> str:
    """
    Use this only when the user explicitly asks for the exact offers of a specific brand.
    When the user asks about a category-specific question, always pass the category too.
    """
    brand = brand.strip()
    category = _normalize_category(category)
    logger.info(
        "Tool get_active_offers called | brand=%s | category=%s | limit=%s",
        brand,
        category,
        limit,
    )
    
    if brand.lower() == CLIENT_BRAND.lower():
        query = """
        SELECT offer_title, category, promo_type, discount_max, valid_until
        FROM internal_promotions
        WHERE valid_until >= CURRENT_DATE::text
          AND (%s IS NULL OR category = %s)
        ORDER BY discount_max DESC NULLS LAST
        LIMIT %s
        """
        params = (category, category, limit)
    else:
        query = """
        SELECT p.offer_title, p.category, p.promo_type, p.discount_max
        FROM promotions p
        JOIN competitors c ON p.competitor_id = c.id
        WHERE c.name ILIKE %s
          AND (%s IS NULL OR p.category = %s)
        ORDER BY p.discount_max DESC NULLS LAST
        LIMIT %s
        """
        params = (brand, category, category, limit)
        
    with DBClient() as db:
        rows = db.execute(query, params)
    logger.info(
        "Tool get_active_offers DB rows fetched | brand=%s | row_count=%d | preview=%s",
        brand,
        len(rows),
        _truncate(rows),
    )
        
    if not rows:
        return f"No active offers found for brand: {brand}."

    discounts = [float(row["discount_max"]) for row in rows if row.get("discount_max") is not None]
    payload = {
        "brand": brand,
        "category": category,
        "returned_offer_count": len(rows),
        "avg_discount": round(sum(discounts) / len(discounts), 2) if discounts else None,
        "max_discount": max(discounts) if discounts else None,
        "top_offers": _top_offer_examples(rows),
    }
    result = _serialize_payload(payload)
    logger.info("Tool get_active_offers returning | payload=%s", _truncate(result))
    return result


@tool
def get_recommendation(category: str, competitor: str) -> str:
    """
    Use this when the user asks what Westside should do against a competitor in a specific category.
    This is a deterministic recommendation tool, not freeform LLM advice.
    """
    category = _normalize_category(category)
    competitor = competitor.strip()
    logger.info(
        "Tool get_recommendation called | category=%s | competitor=%s",
        category,
        competitor,
    )

    query = """
    WITH competitor_stats AS (
        SELECT
            c.name AS competitor,
            ROUND(AVG(p.discount_max), 2) AS competitor_avg_discount,
            MAX(p.discount_max) AS competitor_deepest_discount,
            COUNT(*) AS competitor_offer_count
        FROM promotions p
        JOIN competitors c ON p.competitor_id = c.id
        WHERE c.name ILIKE %s
          AND p.category = %s
          AND p.discount_max IS NOT NULL
        GROUP BY c.name
    ),
    internal_stats AS (
        SELECT
            ROUND(AVG(discount_max), 2) AS internal_avg_discount,
            MAX(discount_max) AS internal_deepest_discount,
            COUNT(*) AS internal_offer_count
        FROM internal_promotions
        WHERE category = %s
          AND valid_until >= CURRENT_DATE::text
          AND discount_max IS NOT NULL
    )
    SELECT
        %s AS client_brand,
        cs.competitor,
        cs.competitor_avg_discount,
        cs.competitor_deepest_discount,
        cs.competitor_offer_count,
        ist.internal_avg_discount,
        ist.internal_deepest_discount,
        ist.internal_offer_count
    FROM competitor_stats cs
    CROSS JOIN internal_stats ist
    """

    with DBClient() as db:
        row = db.execute_one(query, (competitor, category, category, CLIENT_BRAND))

    logger.info("Tool get_recommendation DB row fetched | row=%s", _truncate(row))

    if not row:
        result = {
            "status": "missing_competitor_data",
            "category": category,
            "competitor": competitor,
            "recommendation": f"No competitor data found for {competitor} in {category}.",
            "reason": "There is no category-level competitor data to compare yet.",
        }
        payload = _serialize_payload(result)
        logger.info("Tool get_recommendation returning | payload=%s", _truncate(payload))
        return payload

    competitor_avg = float(row["competitor_avg_discount"]) if row["competitor_avg_discount"] is not None else None
    competitor_deepest = float(row["competitor_deepest_discount"]) if row["competitor_deepest_discount"] is not None else None
    internal_avg = float(row["internal_avg_discount"]) if row["internal_avg_discount"] is not None else None
    internal_deepest = float(row["internal_deepest_discount"]) if row["internal_deepest_discount"] is not None else None
    internal_offer_count = int(row["internal_offer_count"] or 0)

    if internal_offer_count == 0 or internal_avg is None:
        result = {
            "status": "missing_internal_data",
            "category": category,
            "competitor": competitor,
            "recommendation": f"Populate {CLIENT_BRAND}'s internal promotions for {category} before making a pricing move.",
            "reason": f"{CLIENT_BRAND} has no active comparable offers in {category}, so any recommendation would be one-sided.",
            "urgency": "high",
        }
        payload = _serialize_payload(result)
        logger.info("Tool get_recommendation returning | payload=%s", _truncate(payload))
        return payload

    avg_gap = round((competitor_avg or 0) - internal_avg, 2)
    deepest_gap = round((competitor_deepest or 0) - (internal_deepest or 0), 2)

    if avg_gap >= 15 or deepest_gap >= 20:
        urgency = "high"
        action = "Close most of the gap quickly, but prefer a targeted category push or bundle over a blanket sitewide discount."
    elif avg_gap >= 5 or deepest_gap >= 10:
        urgency = "medium"
        action = "Partially narrow the gap with a measured discount or bundle, then monitor competitor moves."
    else:
        urgency = "low"
        action = "Do not aggressively match. Keep pricing steady and differentiate with bundles, merchandising, or limited-time offers."

    result = {
        "status": "ok",
        "client_brand": CLIENT_BRAND,
        "category": category,
        "competitor": competitor,
        "competitor_avg_discount": competitor_avg,
        "competitor_deepest_discount": competitor_deepest,
        "internal_avg_discount": internal_avg,
        "internal_deepest_discount": internal_deepest,
        "avg_gap": avg_gap,
        "deepest_gap": deepest_gap,
        "urgency": urgency,
        "recommendation": action,
        "reason": f"{competitor} is ahead of {CLIENT_BRAND} by {avg_gap}% on average discount and {deepest_gap}% at the deepest discount point in {category}.",
    }
    payload = _serialize_payload(result)
    logger.info("Tool get_recommendation returning | payload=%s", _truncate(payload))
    return payload
