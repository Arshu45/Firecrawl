"""
Layer 6 — Chatbot Engine
Intent routing + tool execution + response generation.
Exactly 2 LLM calls per query. No new LLM logic — routes to existing engines.
"""

import json
import logging

from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import GROQ_API_KEY, GROQ_MODEL, GROQ_TEMPERATURE
from extraction.prompt_templates import INTENT_ROUTER_PROMPT, RESPONSE_PROMPT
from insights.insights_engine import run_insight
from recommendations.recommendation_engine import get_recommendation

logger = logging.getLogger(__name__)


# ── LLM Call helpers ───────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=30), reraise=True)
def _llm(prompt: str, max_tokens: int = 300) -> str:
    client   = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model       = GROQ_MODEL,
        temperature = GROQ_TEMPERATURE,
        max_tokens  = max_tokens,
        messages    = [{"role": "user", "content": prompt}],
    )
    return (response.choices[0].message.content or "").strip()


# ── Step 1: Intent routing (LLM call #1) ──────────────────────────────────

def _route_intent(question: str) -> dict:
    """
    Calls Groq to determine which tool to call and with what params.
    Falls back to answer_direct on any parse error.
    """
    prompt = INTENT_ROUTER_PROMPT.format(question=question)
    try:
        raw  = _llm(prompt, max_tokens=200)
        # Strip markdown code fences
        raw  = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Intent routing failed: {e} — defaulting to answer_direct")
        return {
            "tool"     : "answer_direct",
            "params"   : {},
            "reasoning": "Parse error — defaulted",
        }


# ── Step 2: Tool execution (deterministic) ────────────────────────────────

def _execute_tool(tool: str, params: dict) -> dict:
    """Calls the correct engine function. No LLM involved."""
    try:
        if tool == "search_promotions":
            data = run_insight("recent_offers", {
                "provider": params.get("provider"),
                "category": params.get("category"),
                "days"    : params.get("days", 7),
                "limit"   : 15,
            })
            return {"tool": tool, "result": data}

        elif tool == "get_insights":
            insight_type = "avg_discount_by_category"
            if params.get("category"):
                insight_type = "top_competitors_in_category"
            data = run_insight(insight_type, params)
            return {"tool": tool, "result": data}

        elif tool == "get_recommendation":
            our_discount = params.get("our_discount") or 30.0
            our_margin   = params.get("our_margin")   or 35.0
            category     = params.get("category") or "Fashion"
            data = get_recommendation(category, float(our_discount), float(our_margin))
            return {"tool": tool, "result": data}

        else:  # answer_direct
            return {"tool": "answer_direct", "result": {}}

    except Exception as e:
        logger.error(f"Tool execution error ({tool}): {e}")
        return {"tool": tool, "result": {}, "error": str(e)}


# ── Step 3: Response generation (LLM call #2) ─────────────────────────────

def _generate_response(question: str, tool_output: dict, history: list[dict]) -> str:
    """Formats a natural-language response from tool output data."""
    # Keep last 6 turns to avoid token bloat
    trimmed_history = history[-12:]   # 6 pairs = 12 messages
    history_text    = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}"
        for m in trimmed_history
    )

    prompt = RESPONSE_PROMPT.format(
        history     = history_text or "(no previous messages)",
        question    = question,
        tool_output = json.dumps(tool_output, indent=2, default=str),
    )

    return _llm(prompt, max_tokens=400)


# ── Public API ─────────────────────────────────────────────────────────────

def chat(question: str, history: list[dict]) -> dict:
    """
    Main chat function. Exactly 2 LLM calls.

    Args:
        question: user's current question
        history:  list of {"role": "user"|"assistant", "content": str}

    Returns:
        {"response": str, "tool_used": str, "data": dict}
    """
    # LLM call #1 — route intent
    routing     = _route_intent(question)
    tool        = routing.get("tool", "answer_direct")
    tool_params = routing.get("params", {})

    logger.info(f"Routed to tool={tool} | reasoning={routing.get('reasoning', '')}")

    # Deterministic tool execution
    tool_result = _execute_tool(tool, tool_params)

    # LLM call #2 — generate response
    response_text = _generate_response(question, tool_result, history)

    return {
        "response" : response_text,
        "tool_used": tool,
        "data"     : tool_result.get("result", {}),
    }
