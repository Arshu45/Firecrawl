"""
Layer 4 — Insights Engine
Fixed parameterised SQL queries + LLM narration via Groq.
No dynamic SQL generation from user input — ever.
"""

import json
import logging
from decimal import Decimal
from datetime import date, datetime

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import GROQ_API_KEY, GROQ_MODEL, GROQ_TEMPERATURE
from database.db_client import DBClient
from extraction.prompt_templates import NARRATION_PROMPT

logger = logging.getLogger(__name__)


# ── JSON serialisation helper ──────────────────────────────────────────────

class _DecimalEncoder(json.JSONEncoder):
    """Handles PostgreSQL NUMERIC (Decimal) and date/datetime objects."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def _to_json(data) -> str:
    return json.dumps(data, indent=2, cls=_DecimalEncoder)


# ── 5 Fixed SQL query functions ────────────────────────────────────────────

def avg_discount_by_category(days: int = 7) -> list[dict]:
    """Returns avg discount and offer count per category over last N days."""
    db = DBClient()
    try:
        return db.execute(
            """
            SELECT
                p.category,
                ROUND(AVG(COALESCE(p.discount_max, p.discount_min))::numeric, 1) AS avg_discount,
                COUNT(*) AS offer_count
            FROM promotions p
            WHERE p.scraped_date >= CURRENT_DATE - %(days)s
              AND (p.discount_max IS NOT NULL OR p.discount_min IS NOT NULL)
              AND p.category IS NOT NULL
            GROUP BY p.category
            ORDER BY avg_discount DESC
            """,
            {"days": days},
        )
    finally:
        db.close()


def top_competitors_in_category(category: str, days: int = 7) -> list[dict]:
    """Returns top 5 competitors by avg discount in a given category."""
    db = DBClient()
    try:
        return db.execute(
            """
            SELECT
                c.name AS competitor,
                ROUND(AVG(COALESCE(p.discount_max, p.discount_min))::numeric, 1) AS avg_discount,
                COUNT(*) AS offer_count
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE p.category    = %(category)s
              AND p.scraped_date >= CURRENT_DATE - %(days)s
              AND (p.discount_max IS NOT NULL OR p.discount_min IS NOT NULL)
            GROUP BY c.name
            ORDER BY avg_discount DESC
            LIMIT 5
            """,
            {"category": category, "days": days},
        )
    finally:
        db.close()


def coupon_availability_by_provider(days: int = 7) -> list[dict]:
    """Returns % of offers that carry a coupon code, per competitor."""
    db = DBClient()
    try:
        return db.execute(
            """
            SELECT
                c.name AS competitor,
                COUNT(*) FILTER (WHERE p.coupon_code IS NOT NULL) AS with_coupon,
                COUNT(*) AS total,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE p.coupon_code IS NOT NULL) / COUNT(*),
                    1
                ) AS pct
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE p.scraped_date >= CURRENT_DATE - %(days)s
            GROUP BY c.name
            ORDER BY pct DESC
            """,
            {"days": days},
        )
    finally:
        db.close()


def user_type_targeting(days: int = 7) -> list[dict]:
    """Returns offer count breakdown by competitor × user_type."""
    db = DBClient()
    try:
        return db.execute(
            """
            SELECT
                c.name AS competitor,
                p.user_type,
                COUNT(*) AS count
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE p.scraped_date >= CURRENT_DATE - %(days)s
            GROUP BY c.name, p.user_type
            ORDER BY c.name, count DESC
            """,
            {"days": days},
        )
    finally:
        db.close()


def recent_offers(
    provider: str | None = None,
    category: str | None = None,
    days: int = 7,
    limit: int = 20,
) -> list[dict]:
    """
    Filterable offer list for the promotions table screen.
    WHERE clause built from non-None params — values are parameterised, never interpolated.
    """
    db     = DBClient()
    where  = ["p.scraped_date >= CURRENT_DATE - %(days)s"]
    params: dict = {"days": days, "limit": limit}

    if provider:
        where.append("c.name = %(provider)s")
        params["provider"] = provider
    if category:
        where.append("p.category = %(category)s")
        params["category"] = category

    where_sql = " AND ".join(where)

    try:
        return db.execute(
            f"""
            SELECT
                p.offer_title, p.brand, p.category, p.promo_type,
                p.discount_min, p.discount_max, p.flat_value, p.coupon_code,
                p.user_type, p.valid_until, p.scraped_date,
                c.name AS competitor
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE {where_sql}
            ORDER BY p.scraped_date DESC, p.discount_max DESC NULLS LAST
            LIMIT %(limit)s
            """,
            params,
        )
    finally:
        db.close()


# ── LLM Narration ──────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=30), reraise=True)
def generate_narrative(query_name: str, data: list[dict], context: dict) -> str:
    """Calls Groq to produce a 3-sentence plain-language summary of query results."""
    client  = Groq(api_key=GROQ_API_KEY)
    prompt  = NARRATION_PROMPT.format(
        context=context.get("description", query_name),
        data=_to_json(data),
    )
    response = client.chat.completions.create(
        model       = GROQ_MODEL,
        temperature = GROQ_TEMPERATURE,
        max_tokens  = 200,
        messages    = [{"role": "user", "content": prompt}],
    )
    return (response.choices[0].message.content or "").strip()


# ── Public router ──────────────────────────────────────────────────────────

def run_insight(insight_type: str, params: dict) -> dict:
    """
    Routes to the correct query function, appends LLM narrative.

    insight_type options:
      avg_discount_by_category | top_competitors_in_category |
      coupon_availability | user_type_targeting | recent_offers

    Returns: {"data": list, "narrative": str, "insight_type": str}
    """
    days     = params.get("days", 7)
    category = params.get("category")
    provider = params.get("provider")
    limit    = params.get("limit", 20)

    if insight_type == "avg_discount_by_category":
        data    = avg_discount_by_category(days)
        context = {"description": f"average discounts by category over the last {days} days"}

    elif insight_type == "top_competitors_in_category":
        if not category:
            raise ValueError("category is required for top_competitors_in_category")
        data    = top_competitors_in_category(category, days)
        context = {"description": f"top competitors in {category} over the last {days} days"}

    elif insight_type == "coupon_availability":
        data    = coupon_availability_by_provider(days)
        context = {"description": f"coupon code availability by provider over the last {days} days"}

    elif insight_type == "user_type_targeting":
        data    = user_type_targeting(days)
        context = {"description": f"new vs existing user targeting over the last {days} days"}

    elif insight_type == "recent_offers":
        data    = recent_offers(provider, category, days, limit)
        context = {"description": "recent promotional offers"}

    else:
        raise ValueError(f"Unknown insight_type: {insight_type}")

    try:
        narrative = generate_narrative(insight_type, data, context)
    except Exception as e:
        logger.warning(f"Narration failed: {e}")
        narrative = "Narrative unavailable."

    return {
        "data"         : data,
        "narrative"    : narrative,
        "insight_type" : insight_type,
    }
