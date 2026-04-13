import json
import logging

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from pydantic import BaseModel

from database.db_client import DBClient
from config.settings import (
    CLIENT_BRAND,
    DEFAULT_ACTIVE_OFFERS_LIMIT,
    DEFAULT_TOP_COMPETITORS_LIMIT,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_TEMPERATURE,
    TOOL_SUMMARY_TOP_OFFERS,
)

logger = logging.getLogger(__name__)


class RecommendationExplanation(BaseModel):
    situation: str
    action: str
    why: str


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
                "description": row.get("description"),
                "category": row.get("category"),
                "promo_type": row.get("promo_type"),
                "discount_max": row.get("discount_max"),
                "valid_until": row.get("valid_until"),
            }
        )
    return examples


def _example_limit(requested_limit: int | None = None) -> int:
    if requested_limit is None:
        return max(TOOL_SUMMARY_TOP_OFFERS, 5)
    return max(TOOL_SUMMARY_TOP_OFFERS, min(requested_limit, 5))


def _promo_type_breakdown(rows: list[dict]) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for row in rows:
        promo_type = row.get("promo_type") or "other"
        breakdown[promo_type] = breakdown.get(promo_type, 0) + 1
    return breakdown


def _coerce_float(value):
    if value is None:
        return None
    return float(value)


def _format_offer_examples(rows: list[dict]) -> str:
    if not rows:
        return "No offer examples available."

    lines = []
    for row in rows[:_example_limit()]:
        title = row.get("offer_title") or "Untitled offer"
        description = row.get("description") or "No description"
        promo_type = row.get("promo_type") or "other"
        discount = row.get("discount_max")
        discount_text = f"{discount}%" if discount is not None else "unknown discount"
        lines.append(
            f"- {title} | {description} | promo_type={promo_type} | discount_max={discount_text}"
        )
    return "\n".join(lines)


def _generate_why_explanation(
    *,
    category: str,
    competitor: str,
    competitor_avg: float | None,
    competitor_deepest: float | None,
    competitor_active_offer_count: int,
    competitor_breakdown: dict[str, int],
    competitor_top_offers: list[dict],
    internal_avg: float | None,
    internal_deepest: float | None,
    internal_active_offer_count: int,
    internal_breakdown: dict[str, int],
    internal_top_offers: list[dict],
    avg_gap: float,
    deepest_gap: float,
) -> RecommendationExplanation:
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=GROQ_TEMPERATURE,
    )
    structured_llm = llm.with_structured_output(RecommendationExplanation)
    competitor_breakdown_text = json.dumps(competitor_breakdown, default=str)
    internal_breakdown_text = json.dumps(internal_breakdown, default=str)
    competitor_offers_text = _format_offer_examples(competitor_top_offers)
    internal_offers_text = _format_offer_examples(internal_top_offers)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    f"You are {CLIENT_BRAND}'s pricing strategist. "
                    "Return exactly three concise fields: situation, action, and why. "
                    "Situation must summarize competitor activity and the exact gap versus us. "
                    "Action must recommend a specific offer construct, discount range when justified, "
                    "and timeframe. "
                    "Why must be exactly one sentence and reference the competitor's actual promo mix. "
                    "Do not use markdown bullets or labels in the field values."
                ),
            ),
            (
                "human",
                (
                    "Use this evidence to create the recommendation explanation.\n\n"
                    "Category: {category}\n"
                    "Competitor: {competitor}\n"
                    "Client brand: {client_brand}\n\n"
                    "Competitor avg discount: {competitor_avg}\n"
                    "Competitor deepest discount: {competitor_deepest}\n"
                    "Competitor active offer count: {competitor_active_offer_count}\n"
                    "Competitor promo type breakdown: {competitor_breakdown_text}\n"
                    "Competitor top offers:\n{competitor_offers_text}\n\n"
                    "{client_brand} avg discount: {internal_avg}\n"
                    "{client_brand} deepest discount: {internal_deepest}\n"
                    "{client_brand} active offer count: {internal_active_offer_count}\n"
                    "{client_brand} promo type breakdown: {internal_breakdown_text}\n"
                    "{client_brand} top offers:\n{internal_offers_text}\n\n"
                    "Average discount gap: {avg_gap}\n"
                    "Deepest discount gap: {deepest_gap}\n"
                ),
            ),
        ]
    )
    return structured_llm.invoke(
        prompt.invoke(
            {
                "category": category,
                "competitor": competitor,
                "client_brand": CLIENT_BRAND,
                "competitor_avg": competitor_avg,
                "competitor_deepest": competitor_deepest,
                "competitor_active_offer_count": competitor_active_offer_count,
                "competitor_breakdown_text": competitor_breakdown_text,
                "competitor_offers_text": competitor_offers_text,
                "internal_avg": internal_avg,
                "internal_deepest": internal_deepest,
                "internal_active_offer_count": internal_active_offer_count,
                "internal_breakdown_text": internal_breakdown_text,
                "internal_offers_text": internal_offers_text,
                "avg_gap": avg_gap,
                "deepest_gap": deepest_gap,
            }
        )
    )


def _generate_market_why_explanation(
    *,
    category: str,
    competitor_summary_text: str,
    competitor_offer_examples_text: str,
    internal_avg: float | None,
    internal_deepest: float | None,
    internal_active_offer_count: int,
    internal_breakdown: dict[str, int],
    internal_top_offers: list[dict],
    common_promo_types: list[str],
    avg_competitor_discount: float | None,
    deepest_competitor_discount: float | None,
) -> RecommendationExplanation:
    llm = ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=GROQ_TEMPERATURE,
    )
    structured_llm = llm.with_structured_output(RecommendationExplanation)
    internal_breakdown_text = json.dumps(internal_breakdown, default=str)
    internal_offers_text = _format_offer_examples(internal_top_offers)
    common_promo_types_text = ", ".join(common_promo_types) if common_promo_types else "none identified"
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    f"You are {CLIENT_BRAND}'s pricing strategist. "
                    "Return exactly three concise fields: situation, action, and why. "
                    "Situation must summarize what multiple competitors are doing in the category and how that compares to us. "
                    "Action must recommend one accumulated response for the category, with a concrete offer construct and timeframe. "
                    "Why must be exactly one sentence and reference the common competitor promo pattern. "
                    "Do not use markdown bullets or labels in the field values."
                ),
            ),
            (
                "human",
                (
                    "Create one market-wide strategy recommendation from this evidence.\n\n"
                    "Category: {category}\n"
                    "Client brand: {client_brand}\n"
                    "Competitor summary:\n{competitor_summary_text}\n\n"
                    "Competitor offer examples:\n{competitor_offer_examples_text}\n\n"
                    "Common competitor promo types: {common_promo_types_text}\n"
                    "Average competitor discount across brands: {avg_competitor_discount}\n"
                    "Deepest competitor discount across brands: {deepest_competitor_discount}\n\n"
                    "{client_brand} avg discount: {internal_avg}\n"
                    "{client_brand} deepest discount: {internal_deepest}\n"
                    "{client_brand} active offer count: {internal_active_offer_count}\n"
                    "{client_brand} promo type breakdown: {internal_breakdown_text}\n"
                    "{client_brand} top offers:\n{internal_offers_text}\n"
                ),
            ),
        ]
    )
    return structured_llm.invoke(
        prompt.invoke(
            {
                "category": category,
                "client_brand": CLIENT_BRAND,
                "competitor_summary_text": competitor_summary_text,
                "competitor_offer_examples_text": competitor_offer_examples_text,
                "common_promo_types_text": common_promo_types_text,
                "avg_competitor_discount": avg_competitor_discount,
                "deepest_competitor_discount": deepest_competitor_discount,
                "internal_avg": internal_avg,
                "internal_deepest": internal_deepest,
                "internal_active_offer_count": internal_active_offer_count,
                "internal_breakdown_text": internal_breakdown_text,
                "internal_offers_text": internal_offers_text,
            }
        )
    )


@tool
def get_category_trends(category: str | None = None) -> str:
    """
    Use this for OBSERVATION questions about market trends and category overviews.

    Call with no category when the user asks for an overall market view.
    Call with a specific category when the user asks about one category only.

    Trigger phrases: "what's happening in", "category trends", "how is the market",
    "overview", "what's the average discount", "compare across categories",
    "all categories", "for all".

    IMPORTANT: After this tool returns, stop. Do not call get_active_offers or
    get_recommendation per category unless the user explicitly asks for more detail
    in the same message.

    Do NOT use this for strategy questions — use get_recommendation for those.
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
                  AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
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
                  AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
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
                WHERE category = %s
                  AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
                  AND discount_max IS NOT NULL
                
                UNION ALL
                
                SELECT 
                    c.name as brand, 
                    ROUND(AVG(p.discount_max), 2) as avg_discount, 
                    COUNT(p.id) as active_offers
                FROM promotions p
                JOIN competitors c ON p.competitor_id = c.id
                WHERE p.category = %s
                  AND p.discount_max IS NOT NULL
                  AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
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
    Use this when the user wants to know which competitors are most aggressive
    in a specific category.

    Trigger phrases: "who is leading in", "top competitors in", "most aggressive in",
    "deepest discounts in", "who is ahead in".

    Requires a specific category. Do not call without one.
    Do NOT use this for strategy questions — use get_recommendation for those.
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
    WHERE p.category = %s
      AND p.discount_max IS NOT NULL
      AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
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
    Use this when the user wants to SEE or LIST specific offers from a brand.

    Trigger phrases: "show me", "list", "what offers", "give me examples",
    "what are they running", "show concrete offers", "active offers".

    Always pass category when the question is category-specific.
    Do NOT call this for strategy questions — use get_recommendation instead.
    Do NOT call this automatically after get_category_trends or get_recommendation
    unless the user explicitly asked for offer examples.

    When this tool is called, your response MUST lead with the actual offer list.
    Do not replace the offer list with a recommendation summary.
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
        SELECT offer_title, description, category, promo_type, discount_max, valid_until
        FROM internal_promotions
        WHERE (valid_until IS NULL OR valid_until >= CURRENT_DATE)
          AND (%s IS NULL OR category = %s)
        ORDER BY discount_max DESC NULLS LAST
        LIMIT %s
        """
        params = (category, category, limit)
    else:
        query = """
        SELECT p.offer_title, p.description, p.category, p.promo_type, p.discount_max, p.valid_until
        FROM promotions p
        JOIN competitors c ON p.competitor_id = c.id
        WHERE c.name ILIKE %s
          AND (%s IS NULL OR p.category = %s)
          AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
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
        if category:
            return f"No active offers found for brand: {brand} in {category}."
        return f"No active offers found for brand: {brand}."

    discounts = [
        float(row["discount_max"])
        for row in rows
        if row.get("discount_max") is not None
    ]
    payload = {
        "brand": brand,
        "category": category,
        "returned_offer_count": len(rows),
        "avg_discount": round(sum(discounts) / len(discounts), 2) if discounts else None,
        "max_discount": max(discounts) if discounts else None,
        "promo_type_breakdown": _promo_type_breakdown(rows),
        "top_offers": _top_offer_examples(rows, limit=_example_limit(limit)),
    }
    result = _serialize_payload(payload)
    logger.info("Tool get_active_offers returning | payload=%s", _truncate(result))
    return result


@tool
def get_recommendation(category: str, competitor: str) -> str:
    """
    Use this ONLY for STRATEGY questions — when the user wants to know how
    to respond to a competitor or what action to take.

    Trigger phrases: "what should we do", "how do we respond", "what can we do",
    "recommend a response", "give me a strategy", "how do we compete",
    "what's our move", "respond to", "counter", "react to".

    Always call this before giving any strategic advice.
    Requires both competitor name and category.

    Do NOT call this for observation questions ("what is X doing") —
    use get_active_offers or get_category_trends for those.
    Do NOT call this automatically after get_category_trends.

    This tool returns structured evidence only. It does not generate the final
    strategy text. The LLM should synthesize the recommendation from the facts.
    """
    category = _normalize_category(category)
    competitor = competitor.strip()
    logger.info(
        "Tool get_recommendation called | category=%s | competitor=%s",
        category,
        competitor,
    )

    stats_query = """
    WITH competitor_stats AS (
        SELECT
            c.name AS competitor,
            ROUND(AVG(p.discount_max), 2) AS competitor_avg_discount,
            MAX(p.discount_max) AS competitor_deepest_discount,
            COUNT(*) AS competitor_quantified_offer_count
        FROM promotions p
        JOIN competitors c ON p.competitor_id = c.id
        WHERE c.name ILIKE %s
          AND p.category = %s
          AND p.discount_max IS NOT NULL
          AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
        GROUP BY c.name
    ),
    internal_stats AS (
        SELECT
            ROUND(AVG(discount_max), 2) AS internal_avg_discount,
            MAX(discount_max) AS internal_deepest_discount,
            COUNT(*) AS internal_offer_count
        FROM internal_promotions
        WHERE category = %s
          AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
          AND discount_max IS NOT NULL
    )
    SELECT
        %s AS client_brand,
        cs.competitor,
        cs.competitor_avg_discount,
        cs.competitor_deepest_discount,
        cs.competitor_quantified_offer_count,
        ist.internal_avg_discount,
        ist.internal_deepest_discount,
        ist.internal_offer_count
    FROM competitor_stats cs
    CROSS JOIN internal_stats ist
    """

    with DBClient() as db:
        row = db.execute_one(
            stats_query, (competitor, category, category, CLIENT_BRAND)
        )
        competitor_offer_rows = db.execute(
            """
            SELECT p.offer_title, p.description, p.category, p.promo_type, p.discount_max, p.flat_value, p.valid_until
            FROM promotions p
            JOIN competitors c ON p.competitor_id = c.id
            WHERE c.name ILIKE %s
              AND p.category = %s
              AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
            ORDER BY p.discount_max DESC NULLS LAST, p.flat_value DESC NULLS LAST, p.offer_title
            LIMIT %s
            """,
            (competitor, category, DEFAULT_ACTIVE_OFFERS_LIMIT),
        )
        internal_offer_rows = db.execute(
            """
            SELECT offer_title, description, category, promo_type, discount_max, flat_value, valid_until
            FROM internal_promotions
            WHERE category = %s
              AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
            ORDER BY discount_max DESC NULLS LAST, flat_value DESC NULLS LAST, offer_title
            LIMIT %s
            """,
            (category, DEFAULT_ACTIVE_OFFERS_LIMIT),
        )

    logger.info("Tool get_recommendation DB row fetched | row=%s", _truncate(row))

    if not row:
        result = {
            "status": "missing_competitor_data",
            "category": category,
            "competitor": competitor,
            "reason": "There is no category-level competitor data to compare yet.",
        }
        payload = _serialize_payload(result)
        logger.info("Tool get_recommendation returning | payload=%s", _truncate(payload))
        return payload

    competitor_avg = _coerce_float(row["competitor_avg_discount"])
    competitor_deepest = _coerce_float(row["competitor_deepest_discount"])
    internal_avg = _coerce_float(row["internal_avg_discount"])
    internal_deepest = _coerce_float(row["internal_deepest_discount"])
    internal_offer_count = int(row["internal_offer_count"] or 0)
    competitor_quantified_offer_count = int(row["competitor_quantified_offer_count"] or 0)
    competitor_active_offer_count = len(competitor_offer_rows)
    internal_active_offer_count = len(internal_offer_rows)
    competitor_breakdown = _promo_type_breakdown(competitor_offer_rows)
    internal_breakdown = _promo_type_breakdown(internal_offer_rows)

    if internal_offer_count == 0 or internal_avg is None:
        result = {
            "status": "missing_internal_data",
            "category": category,
            "competitor": competitor,
            "reason": (
                f"{CLIENT_BRAND} has no active comparable offers in {category}, "
                f"so any recommendation would be one-sided."
            ),
            "client_brand": CLIENT_BRAND,
            "competitor_context": {
                "active_offer_count": competitor_active_offer_count,
                "quantified_offer_count": competitor_quantified_offer_count,
                "avg_discount": competitor_avg,
                "deepest_discount": competitor_deepest,
                "promo_type_breakdown": competitor_breakdown,
                "top_offers": _top_offer_examples(competitor_offer_rows, limit=_example_limit()),
            },
        }
        payload = _serialize_payload(result)
        logger.info("Tool get_recommendation returning | payload=%s", _truncate(payload))
        return payload

    avg_gap = round((competitor_avg or 0) - internal_avg, 2)
    deepest_gap = round((competitor_deepest or 0) - (internal_deepest or 0), 2)
    competitor_top_offers = _top_offer_examples(competitor_offer_rows, limit=_example_limit())
    internal_top_offers = _top_offer_examples(internal_offer_rows, limit=_example_limit())
    explanation = _generate_why_explanation(
        category=category,
        competitor=competitor,
        competitor_avg=competitor_avg,
        competitor_deepest=competitor_deepest,
        competitor_active_offer_count=competitor_active_offer_count,
        competitor_breakdown=competitor_breakdown,
        competitor_top_offers=competitor_top_offers,
        internal_avg=internal_avg,
        internal_deepest=internal_deepest,
        internal_active_offer_count=internal_active_offer_count,
        internal_breakdown=internal_breakdown,
        internal_top_offers=internal_top_offers,
        avg_gap=avg_gap,
        deepest_gap=deepest_gap,
    )

    result = {
        "status": "ok",
        "client_brand": CLIENT_BRAND,
        "category": category,
        "competitor": competitor,
        "competitor_avg_discount": competitor_avg,
        "competitor_deepest_discount": competitor_deepest,
        "competitor_active_offer_count": competitor_active_offer_count,
        "competitor_quantified_offer_count": competitor_quantified_offer_count,
        "competitor_promo_type_breakdown": competitor_breakdown,
        "competitor_top_offers": competitor_top_offers,
        "internal_avg_discount": internal_avg,
        "internal_deepest_discount": internal_deepest,
        "internal_active_offer_count": internal_active_offer_count,
        "internal_promo_type_breakdown": internal_breakdown,
        "internal_top_offers": internal_top_offers,
        "avg_gap": avg_gap,
        "deepest_gap": deepest_gap,
        "situation_line": explanation.situation,
        "action_line": explanation.action,
        "why_line": explanation.why,
        "reason": (
            f"{competitor} is ahead of {CLIENT_BRAND} by {avg_gap}% on average discount "
            f"and {deepest_gap}% at the deepest discount point in {category}."
        ),
    }
    payload = _serialize_payload(result)
    logger.info("Tool get_recommendation returning | payload=%s", _truncate(payload))
    return payload


@tool
def get_competitor_market_recommendation(category: str) -> str:
    """
    Use this for category-level strategy questions about all competitors together.

    Trigger phrases: "our competitors", "competitors doing in", "what are competitors doing",
    "what is the market doing and what can we do", "against competitors", "all competitors".

    Requires a specific category. This tool returns an accumulated market view and
    one category-wide recommendation for the client brand.
    """
    category = _normalize_category(category)
    logger.info("Tool get_competitor_market_recommendation called | category=%s", category)

    with DBClient() as db:
        competitor_stats_rows = db.execute(
            """
            SELECT
                c.name AS competitor,
                ROUND(AVG(p.discount_max), 2) AS avg_discount,
                MAX(p.discount_max) AS deepest_discount,
                COUNT(*) AS active_offers
            FROM promotions p
            JOIN competitors c ON p.competitor_id = c.id
            WHERE p.category = %s
              AND p.discount_max IS NOT NULL
              AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
            GROUP BY c.name
            ORDER BY avg_discount DESC NULLS LAST, deepest_discount DESC NULLS LAST
            """,
            (category,),
        )
        competitor_offer_rows = db.execute(
            """
            SELECT
                c.name AS competitor,
                p.offer_title,
                p.description,
                p.category,
                p.promo_type,
                p.discount_max,
                p.flat_value,
                p.valid_until
            FROM promotions p
            JOIN competitors c ON p.competitor_id = c.id
            WHERE p.category = %s
              AND (p.valid_until IS NULL OR p.valid_until >= CURRENT_DATE)
            ORDER BY c.name, p.discount_max DESC NULLS LAST, p.flat_value DESC NULLS LAST, p.offer_title
            """,
            (category,),
        )
        internal_row = db.execute_one(
            """
            SELECT
                ROUND(AVG(discount_max), 2) AS avg_discount,
                MAX(discount_max) AS deepest_discount,
                COUNT(*) AS active_offers
            FROM internal_promotions
            WHERE category = %s
              AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
              AND discount_max IS NOT NULL
            """,
            (category,),
        )
        internal_offer_rows = db.execute(
            """
            SELECT
                offer_title,
                description,
                category,
                promo_type,
                discount_max,
                flat_value,
                valid_until
            FROM internal_promotions
            WHERE category = %s
              AND (valid_until IS NULL OR valid_until >= CURRENT_DATE)
            ORDER BY discount_max DESC NULLS LAST, flat_value DESC NULLS LAST, offer_title
            LIMIT %s
            """,
            (category, DEFAULT_ACTIVE_OFFERS_LIMIT),
        )

    logger.info(
        "Tool get_competitor_market_recommendation DB rows fetched | category=%s | competitors=%d | competitor_offer_rows=%d",
        category,
        len(competitor_stats_rows),
        len(competitor_offer_rows),
    )

    if not competitor_stats_rows:
        result = {
            "status": "missing_competitor_data",
            "category": category,
            "reason": f"No competitor data found for category: {category}.",
        }
        payload = _serialize_payload(result)
        logger.info(
            "Tool get_competitor_market_recommendation returning | payload=%s",
            _truncate(payload),
        )
        return payload

    internal_avg = _coerce_float((internal_row or {}).get("avg_discount"))
    internal_deepest = _coerce_float((internal_row or {}).get("deepest_discount"))
    internal_active_offer_count = int((internal_row or {}).get("active_offers") or 0)
    internal_breakdown = _promo_type_breakdown(internal_offer_rows)
    internal_top_offers = _top_offer_examples(internal_offer_rows, limit=_example_limit())

    if internal_avg is None:
        result = {
            "status": "missing_internal_data",
            "category": category,
            "client_brand": CLIENT_BRAND,
            "reason": (
                f"{CLIENT_BRAND} has no active comparable offers in {category}, "
                "so a market-wide response cannot be benchmarked properly."
            ),
            "competitors": competitor_stats_rows,
        }
        payload = _serialize_payload(result)
        logger.info(
            "Tool get_competitor_market_recommendation returning | payload=%s",
            _truncate(payload),
        )
        return payload

    offers_by_competitor: dict[str, list[dict]] = {}
    aggregate_breakdown: dict[str, int] = {}
    for row in competitor_offer_rows:
        competitor_name = row.get("competitor") or "Unknown"
        offers_by_competitor.setdefault(competitor_name, []).append(row)
        promo_type = row.get("promo_type") or "other"
        aggregate_breakdown[promo_type] = aggregate_breakdown.get(promo_type, 0) + 1

    competitors = []
    summary_lines = []
    example_lines = []
    avg_values = []
    deepest_values = []
    for stats_row in competitor_stats_rows:
        competitor_name = stats_row.get("competitor")
        avg_discount = _coerce_float(stats_row.get("avg_discount"))
        deepest_discount = _coerce_float(stats_row.get("deepest_discount"))
        active_offers = int(stats_row.get("active_offers") or 0)
        competitor_rows = offers_by_competitor.get(competitor_name, [])
        breakdown = _promo_type_breakdown(competitor_rows)
        top_offers = _top_offer_examples(competitor_rows, limit=_example_limit())
        avg_gap = round((avg_discount or 0) - internal_avg, 2)
        deepest_gap = round((deepest_discount or 0) - (internal_deepest or 0), 2)
        competitors.append(
            {
                "competitor": competitor_name,
                "avg_discount": avg_discount,
                "deepest_discount": deepest_discount,
                "active_offers": active_offers,
                "avg_gap_vs_client": avg_gap,
                "deepest_gap_vs_client": deepest_gap,
                "promo_type_breakdown": breakdown,
                "top_offers": top_offers,
            }
        )
        summary_lines.append(
            f"- {competitor_name}: avg_discount={avg_discount}, deepest_discount={deepest_discount}, "
            f"active_offers={active_offers}, avg_gap_vs_{CLIENT_BRAND}={avg_gap}, deepest_gap_vs_{CLIENT_BRAND}={deepest_gap}, "
            f"promo_mix={json.dumps(breakdown, default=str)}"
        )
        for offer in top_offers:
            title = offer.get("offer_title") or "Untitled offer"
            description = offer.get("description") or "No description"
            promo_type = offer.get("promo_type") or "other"
            discount_max = offer.get("discount_max")
            example_lines.append(
                f"- {competitor_name}: {title} | {description} | promo_type={promo_type} | discount_max={discount_max}"
            )
        if avg_discount is not None:
            avg_values.append(avg_discount)
        if deepest_discount is not None:
            deepest_values.append(deepest_discount)

    common_promo_types = [
        promo_type
        for promo_type, count in sorted(
            aggregate_breakdown.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if count > 0
    ][:3]
    avg_competitor_discount = round(sum(avg_values) / len(avg_values), 2) if avg_values else None
    deepest_competitor_discount = max(deepest_values) if deepest_values else None
    explanation = _generate_market_why_explanation(
        category=category,
        competitor_summary_text="\n".join(summary_lines),
        competitor_offer_examples_text="\n".join(example_lines) or "No examples available.",
        internal_avg=internal_avg,
        internal_deepest=internal_deepest,
        internal_active_offer_count=internal_active_offer_count,
        internal_breakdown=internal_breakdown,
        internal_top_offers=internal_top_offers,
        common_promo_types=common_promo_types,
        avg_competitor_discount=avg_competitor_discount,
        deepest_competitor_discount=deepest_competitor_discount,
    )

    result = {
        "status": "ok",
        "scope": "all_competitors_in_category",
        "client_brand": CLIENT_BRAND,
        "category": category,
        "competitor_count": len(competitors),
        "competitors": competitors,
        "avg_competitor_discount": avg_competitor_discount,
        "deepest_competitor_discount": deepest_competitor_discount,
        "common_promo_types": common_promo_types,
        "internal_avg_discount": internal_avg,
        "internal_deepest_discount": internal_deepest,
        "internal_active_offer_count": internal_active_offer_count,
        "internal_promo_type_breakdown": internal_breakdown,
        "internal_top_offers": internal_top_offers,
        "situation_line": explanation.situation,
        "action_line": explanation.action,
        "why_line": explanation.why,
    }
    payload = _serialize_payload(result)
    logger.info(
        "Tool get_competitor_market_recommendation returning | payload=%s",
        _truncate(payload),
    )
    return payload
