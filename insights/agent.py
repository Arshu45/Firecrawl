import time
import logging
import re
import json
from typing import Any

from langchain_groq import ChatGroq
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain.agents import create_agent

from config.settings import (
    CLIENT_BRAND, 
    GROQ_API_KEY, 
    COMPETITOR_SITES,
    KNOWN_CATEGORIES,
    ANALYSIS_HINTS,
    GROQ_MODEL,
    GROQ_TEMPERATURE
)
from insights.tools import (
    get_active_offers,
    get_category_trends,
    get_recommendation,
    get_top_competitors,
)

logger = logging.getLogger(__name__)


def _truncate(value: Any, limit: int = 500) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


# Built dynamically so switching CLIENT_BRAND or adding competitors in settings.py
# is automatically reflected in the clarification detection logic.
KNOWN_BRANDS = {
    CLIENT_BRAND.lower(),
} | {name.lower() for name in COMPETITOR_SITES.keys()}

BRAND_CANONICAL_MAP = {
    CLIENT_BRAND.lower(): CLIENT_BRAND,
    **{name.lower(): name for name in COMPETITOR_SITES.keys()},
}

CATEGORY_CANONICAL_MAP = {
    "fashion": "Fashion",
    "footwear": "Footwear",
    "beauty": "Beauty",
    "electronics": "Electronics",
    "home": "Home",
    "sports": "Sports",
    "jewellery": "Jewellery",
    "jewelry": "Jewellery",
}


def _normalize_words(query: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]+", query.lower()))


def _is_greeting(query: str) -> bool:
    normalized = query.strip().lower()
    greeting_phrases = {
        "hi", "hello", "hey", "good morning", "good afternoon",
        "good evening", "thanks", "thank you",
    }
    return normalized in greeting_phrases


def _needs_clarification(query: str) -> bool:
    words = _normalize_words(query)
    has_analysis_intent = bool(words & ANALYSIS_HINTS)
    has_context_entity = bool(words & KNOWN_CATEGORIES) or bool(words & KNOWN_BRANDS)
    is_all_category_trend_request = (
        {"category", "categories"} & words
        and {"trend", "trends"} & words
    )
    if is_all_category_trend_request:
        return False
    return has_analysis_intent and not has_context_entity


def _history_to_messages(history: list[dict] | None) -> list[dict]:
    messages = []
    for item in history or []:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    return messages


def _extract_brand(query: str) -> str | None:
    lowered = query.lower()
    for brand_key, brand_name in BRAND_CANONICAL_MAP.items():
        if brand_key in lowered:
            return brand_name
    return None


def _extract_category(query: str) -> str | None:
    words = _normalize_words(query)
    for category_key, category_name in CATEGORY_CANONICAL_MAP.items():
        if category_key in words:
            return category_name
    return None


def _is_recommendation_query(query: str) -> bool:
    words = _normalize_words(query)
    return bool(words & {"recommend", "recommendation", "should", "strategy"})


def _format_recommendation_response(payload: dict) -> str:
    status = payload.get("status")
    if status == "missing_competitor_data":
        return payload.get("recommendation", "No competitor data found for that recommendation.")
    if status == "missing_internal_data":
        recommendation = payload.get("recommendation", "")
        reason = payload.get("reason", "")
        competitor_context = payload.get("competitor_context") or {}
        top_offers = competitor_context.get("top_offers") or []
        examples = ", ".join(
            f"{offer.get('offer_title')} ({offer.get('discount_max') or 'no % value'})"
            for offer in top_offers[:3]
            if offer.get("offer_title")
        )
        parts = [recommendation]
        if reason:
            parts.append(reason)
        if examples:
            parts.append(f"Current {payload.get('competitor')} examples: {examples}.")
        return " ".join(parts)

    competitor = payload.get("competitor")
    category = payload.get("category")
    urgency = str(payload.get("urgency", "")).lower()
    competitor_avg = payload.get("competitor_avg_discount")
    internal_avg = payload.get("internal_avg_discount")
    target_range = payload.get("target_discount_range") or []
    tactic = payload.get("recommended_tactic")
    recommendation = payload.get("recommendation", "")
    reason = payload.get("reason", "")
    tactic_reason = payload.get("tactic_reason", "")
    top_offers = payload.get("competitor_top_offers") or []

    urgency_prefix = {
        "high": "High urgency.",
        "medium": "Medium urgency.",
        "low": "Low urgency.",
    }.get(urgency, "")

    parts = []
    if urgency_prefix:
        parts.append(urgency_prefix)
    parts.append(
        f"{competitor} is currently ahead in {category}: average discount {competitor_avg}% versus {CLIENT_BRAND} at {internal_avg}%."
    )
    parts.append(recommendation)
    if len(target_range) == 2:
        parts.append(
            f"Recommended response range: aim for roughly {target_range[0]}% to {target_range[1]}% effective value in {category}."
        )
    if tactic:
        parts.append(f"Best tactic: {tactic.replace('_', ' ')}.")
    if tactic_reason:
        parts.append(tactic_reason)
    if reason:
        parts.append(reason)
    if top_offers:
        examples = ", ".join(
            f"{offer.get('offer_title')} ({offer.get('discount_max') or 'flat/value-based'})"
            for offer in top_offers[:3]
            if offer.get("offer_title")
        )
        if examples:
            parts.append(f"Competitor examples: {examples}.")
    return " ".join(part for part in parts if part)

class TokenUsageCallback(BaseCallbackHandler):
    """Tracks per-call and cumulative LLM token usage across an agent loop."""
    def __init__(self):
        self.calls: list = []
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.tool_calls: int = 0       
        self.tool_names: list = []     

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        usage = {}
        if response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    msg = getattr(gen, "message", None)
                    if msg:
                        usage_metadata = getattr(msg, "usage_metadata", None)
                        if usage_metadata:
                            usage = {
                                "prompt_tokens": usage_metadata.get("input_tokens", 0),
                                "completion_tokens": usage_metadata.get("output_tokens", 0),
                                "total_tokens": usage_metadata.get("total_tokens", 0),
                            }
                            break
                        response_metadata = getattr(msg, "response_metadata", None)
                        if response_metadata:
                            token_usage = response_metadata.get("token_usage", {})
                            if token_usage:
                                usage = {
                                    "prompt_tokens": token_usage.get("prompt_tokens", 0),
                                    "completion_tokens": token_usage.get("completion_tokens", 0),
                                    "total_tokens": token_usage.get("total_tokens", 0),
                                }
                                break

        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        tt = usage.get("total_tokens", 0) or (pt + ct)
        self.calls.append({"prompt": pt, "completion": ct, "total": tt})
        self.prompt_tokens     += pt
        self.completion_tokens += ct
        self.total_tokens      += tt

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        self.tool_calls += 1
        tool_name = serialized.get("name", "unknown_tool")
        self.tool_names.append(tool_name)
        logger.info(
            "Agent selected tool | tool=%s | input=%s",
            tool_name,
            _truncate(input_str),
        )

    def on_tool_end(self, output: Any, **kwargs) -> None:
        logger.info("Tool returned | output=%s", _truncate(output))

    def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs) -> None:
        logger.info(
            "LLM call starting | prompt_count=%d | prompt_preview=%s",
            len(prompts),
            _truncate(prompts[0]) if prompts else "<no prompt>",
        )

    def token_table(self) -> str:
        header = f"    {'Call':<8} {'Prompt (Input)':>16} {'Completion (Output)':>22} {'Total':>12}"
        sep    = "    " + "-" * 62
        rows   = []
        for i, c in enumerate(self.calls, start=1):
            rows.append(f"    #{i:<7} {c['prompt']:>12} tkns  {c['completion']:>14} tkns  {c['total']:>8} tkns")
        grand = f"    {'TOTAL':<8} {self.prompt_tokens:>12} tkns  {self.completion_tokens:>14} tkns  {self.total_tokens:>8} tkns"
        return "\n".join([header, sep] + rows + [sep, grand])


class InsightsAgentService:
    """Service for LLM agent orchestration with Postgres promotion search tools."""
    
    def __init__(self):
        try:
            self.llm = ChatGroq(
                model=GROQ_MODEL,
                api_key=GROQ_API_KEY,
                temperature=GROQ_TEMPERATURE,
            )
            self.tools = [get_category_trends, get_top_competitors, get_active_offers, get_recommendation]
            
            system_prompt = f"""You are {CLIENT_BRAND}'s Lead Pricing Strategist and Market Intelligence Assistant.
You help the marketing and pricing teams analyze competitor promotions and make strategic decisions.
1. Use the provided tools only for data-backed questions about promotions, discounts, categories, brands, or competitors.
2. If the user is greeting you, greeting back is enough. Do not use tools.
3. If the user asks an analysis question but does not specify a brand or category, ask a short clarifying question. Do not guess. Exception: if they ask for category trends in general, use get_category_trends with no category filter.
4. Never invent a category, brand, offer, or numerical value to make a tool call.
5. Do not mix results from unrelated categories or brands into one recommendation.
6. When the user asks what we should do, what we can do, or asks for a recommendation, always call get_recommendation for the specific competitor and category before answering — even if {CLIENT_BRAND} internal data may be missing. The tool handles missing internal data gracefully and will tell you what to say.
6a. After get_recommendation returns, do not call get_active_offers unless the user explicitly asked to list concrete offers, examples, or more detail about the competitor's offers.
7. When the question is category-specific, always keep tool scope aligned to that category.
8. Use get_active_offers only when the user explicitly asks for exact offers for a specific brand, or when listing examples for that same brand and category.
9. We are "{CLIENT_BRAND}". Discuss internal data as {CLIENT_BRAND}'s promotions.
10. Be specific. Mention exact percentages, rupees, and brand names.
11. Provide actionable insights based on the numerical gaps between us and competitors.
12. When the user asks for more detail, more examples, or a deeper offer listing, request a higher get_active_offers limit instead of repeating the same short summary."""

            self.graph = create_agent(
                model=self.llm,
                tools=self.tools,
                system_prompt=system_prompt,
            )
            
            logger.info(
                "Insights Agent Service initialized successfully | model=%s | tools=%s",
                GROQ_MODEL,
                [tool.name for tool in self.tools],
            )
        except Exception as e:
            logger.error(f"Failed to initialize agent service: {str(e)}")
            self.graph = None

    def generate_response(self, query: str, session_id: str, history: list[dict] | None = None) -> str:
        if not self.graph:
            return "I apologize, but my intelligence engine is currently uninitialized."

        start_total = time.perf_counter()
        
        try:
            t0 = time.perf_counter()
            token_cb = TokenUsageCallback()
            logger.info(
                "Agent run starting | session_id=%s | query=%r | history_items=%d",
                session_id,
                query,
                len(history or []),
            )

            if _is_greeting(query):
                logger.info(
                    "Greeting detected | session_id=%s | bypassing agent/tools",
                    session_id,
                )
                return f"Hello! I can help analyze competitor promotions, category trends, and {CLIENT_BRAND} offers. Ask me about a specific brand or category to get started."

            if _needs_clarification(query):
                logger.info(
                    "Clarification required | session_id=%s | query=%r",
                    session_id,
                    query,
                )
                return f"Which brand or category should I analyze? For example: {CLIENT_BRAND}, Myntra, Nykaa, or a category like Fashion, Beauty, or Electronics."

            if _is_recommendation_query(query):
                competitor = _extract_brand(query)
                category = _extract_category(query)
                if competitor and category and competitor.lower() != CLIENT_BRAND.lower():
                    logger.info(
                        "Deterministic recommendation path selected | session_id=%s | competitor=%s | category=%s",
                        session_id,
                        competitor,
                        category,
                    )
                    token_cb.tool_calls += 1
                    token_cb.tool_names.append(get_recommendation.name)
                    tool_payload = get_recommendation.invoke(
                        {"category": category, "competitor": competitor}
                    )
                    logger.info(
                        "Deterministic recommendation tool returned | payload=%s",
                        _truncate(tool_payload),
                    )
                    parsed_payload = json.loads(tool_payload)
                    final_message = _format_recommendation_response(parsed_payload)
                    logger.info(
                        "Agent final response ready | session_id=%s | response_preview=%s",
                        session_id,
                        _truncate(final_message),
                    )
                    logger.info(f"""
    AGENT EXECUTION REPORT
    
    Session      : {session_id}
    Query        : {query}
    
    ⏱  TIMING BREAKDOWN
    ──────────────────────────────────────────────────────────
    Setup Logic            : {(time.perf_counter() - t0):.4f}s
    Agent Invoke (LLM+Tool): 0.0000s
    🔥 TOTAL TIME          : {(time.perf_counter() - start_total):.4f}s
    
    📊 TOKEN USAGE
    {token_cb.token_table()}
    
    Tool Calls             : {token_cb.tool_calls} ({', '.join(token_cb.tool_names) if token_cb.tool_names else 'none'})
""")
                    return final_message
            
            messages = _history_to_messages(history)
            messages.append({"role": "user", "content": query})
            inputs = {"messages": messages}
            config = {
                "configurable": {"thread_id": session_id},
                "callbacks": [token_cb]
            }
            logger.info(
                "Agent config prepared | thread_id=%s | tools_available=%s",
                session_id,
                [tool.name for tool in self.tools],
            )
            
            t1 = time.perf_counter()
            # Stream or invoke the graph
            result = self.graph.invoke(inputs, config=config)
            t2 = time.perf_counter()
            logger.info("Raw agent result received | keys=%s", list(result.keys()))
            
            final_message = result["messages"][-1].content
            logger.info(
                "Agent final response ready | session_id=%s | response_preview=%s",
                session_id,
                _truncate(final_message),
            )
            
            # Print detailed execution logging exactly as requested
            logger.info(f"""
    AGENT EXECUTION REPORT                          
    
    Session      : {session_id}
    Query        : {query}
    
    ⏱  TIMING BREAKDOWN
    ──────────────────────────────────────────────────────────
    Setup Logic            : {(t1 - t0):.4f}s
    Agent Invoke (LLM+Tool): {(t2 - t1):.4f}s
    🔥 TOTAL TIME          : {(t2 - start_total):.4f}s
    
    📊 TOKEN USAGE
    {token_cb.token_table()}
    
    Tool Calls             : {token_cb.tool_calls} ({', '.join(token_cb.tool_names) if token_cb.tool_names else 'none'})
""")
            return final_message

        except Exception as e:
            logger.error(f"[{session_id}] Agent error: {str(e)}", exc_info=True)
            return f"I encountered an error querying the database: {e}"
