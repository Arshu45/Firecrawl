"""
Layer 5 — Recommendation Engine
Two-layer approach: deterministic rules first, LLM explains second.
"""

import json
import logging
import re

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import GROQ_API_KEY, GROQ_MODEL, GROQ_TEMPERATURE
from database.db_client import DBClient
from extraction.prompt_templates import RECOMMENDATION_PROMPT

logger = logging.getLogger(__name__)


# ── Rule Engine (deterministic) ────────────────────────────────────────────

def get_rule_decision(market_avg: float, our_discount: float, our_margin: float) -> dict:
    """
    Pure function — no LLM, no DB.
    Returns action, urgency, label, suggested_discount, margin_impact.
    """
    gap = market_avg - our_discount

    if gap > 20:
        action  = "URGENT_MATCH"
        urgency = "high"
        label   = "Urgent: Match market within 48 hours"
    elif gap > 10:
        action  = "BUNDLE_OFFER"
        urgency = "medium"
        label   = "Consider a bundle offer to stay competitive"
    elif gap > 0:
        action  = "MONITOR"
        urgency = "low"
        label   = "Monitor — within acceptable range"
    else:
        action  = "HOLD"
        urgency = "none"
        label   = "We are competitive — maintain position"

    if action == "URGENT_MATCH":
        suggested_discount = market_avg
    elif action == "BUNDLE_OFFER":
        suggested_discount = our_discount + (gap * 0.6)
    else:
        suggested_discount = our_discount

    margin_impact = our_margin - (suggested_discount - our_discount)

    return {
        "action"             : action,
        "urgency"            : urgency,
        "label"              : label,
        "gap"                : round(gap, 1),
        "suggested_discount" : round(suggested_discount, 1),
        "margin_impact"      : round(margin_impact, 1),
    }


# ── Market data fetch ──────────────────────────────────────────────────────

def _fetch_market_data(category: str) -> dict:
    """
    Fetches avg market discount and top competitor for a category from DB.
    Returns defaults if no data found.
    """
    db = DBClient()
    try:
        row = db.execute_one(
            """
            SELECT
                c.name AS top_competitor,
                ROUND(AVG(COALESCE(p.discount_max, p.discount_min))::numeric, 1) AS avg_discount,
                COUNT(*) AS offer_count
            FROM promotions p
            JOIN competitors c ON c.id = p.competitor_id
            WHERE p.category    = %(category)s
              AND p.scraped_date >= CURRENT_DATE - 7
              AND (p.discount_max IS NOT NULL OR p.discount_min IS NOT NULL)
            GROUP BY c.name
            ORDER BY avg_discount DESC
            LIMIT 1
            """,
            {"category": category},
        )
    finally:
        db.close()

    if row:
        return {
            "top_competitor": row["top_competitor"],
            "top_discount"  : float(row["avg_discount"] or 0),
            "market_avg"    : float(row["avg_discount"] or 0),
            "offer_count"   : row["offer_count"],
        }

    # No data yet — return neutral defaults
    return {
        "top_competitor": "N/A",
        "top_discount"  : 0.0,
        "market_avg"    : 0.0,
        "offer_count"   : 0,
    }


# ── LLM Explanation ────────────────────────────────────────────────────────

def _parse_llm_sections(text: str) -> dict:
    """Parse SITUATION / RECOMMENDATION / REASONING from LLM output."""
    sections = {"situation": "", "recommendation": "", "reasoning": ""}
    pattern  = re.compile(
        r"SITUATION:\s*(.*?)(?=RECOMMENDATION:|$)"
        r"|RECOMMENDATION:\s*(.*?)(?=REASONING:|$)"
        r"|REASONING:\s*(.*?)$",
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        if m.group(1) is not None:
            sections["situation"]      = m.group(1).strip()
        elif m.group(2) is not None:
            sections["recommendation"] = m.group(2).strip()
        elif m.group(3) is not None:
            sections["reasoning"]      = m.group(3).strip()
    return sections


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=30), reraise=True)
def _call_llm(prompt: str) -> str:
    client   = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model       = GROQ_MODEL,
        temperature = GROQ_TEMPERATURE,
        max_tokens  = 300,
        messages    = [{"role": "user", "content": prompt}],
    )
    return (response.choices[0].message.content or "").strip()


# ── Public API ─────────────────────────────────────────────────────────────

def get_recommendation(category: str, our_discount: float, our_margin: float) -> dict:
    """
    1. Fetch market data for category from DB (top competitor + avg discount)
    2. Run deterministic rule engine
    3. Generate LLM explanation
    Returns full recommendation dict.
    """
    market_data = _fetch_market_data(category)
    rule        = get_rule_decision(
        market_data["market_avg"], our_discount, our_margin
    )

    prompt = RECOMMENDATION_PROMPT.format(
        category        = category,
        top_competitor  = market_data["top_competitor"],
        top_discount    = market_data["top_discount"],
        market_avg      = market_data["market_avg"],
        our_discount    = our_discount,
        our_margin      = our_margin,
        rule_label      = rule["label"],
    )

    try:
        llm_text = _call_llm(prompt)
        explanation = _parse_llm_sections(llm_text)
    except Exception as e:
        logger.warning(f"LLM explanation failed: {e}")
        explanation = {
            "situation"     : "Market data retrieved.",
            "recommendation": rule["label"],
            "reasoning"     : "Based on rule engine analysis.",
        }

    return {
        "category"    : category,
        "market_data" : market_data,
        "rule"        : rule,
        "explanation" : explanation,
    }
