import time
import logging
import re
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
    GROQ_TEMPERATURE,
    MAX_HISTORY_TURNS,
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


# Built dynamically — adding a competitor to COMPETITOR_SITES or changing
# CLIENT_BRAND in settings.py is automatically reflected here.
KNOWN_BRANDS = {
    CLIENT_BRAND.lower(),
} | {name.lower() for name in COMPETITOR_SITES.keys()}


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

    # General overview requests are self-contained — no clarification needed
    general_overviews = {"all", "everything", "overall", "market", "overview"}
    if words & general_overviews:
        return False

    # Category trends with no specific entity — self-contained
    is_all_category_trend_request = (
        {"category", "categories"} & words
        and {"trend", "trends"} & words
    )
    if is_all_category_trend_request:
        return False

    # Known brand or category present — self-contained
    # KNOWN_CATEGORIES is pulled from settings so adding categories there
    # automatically expands coverage here
    known_categories_lower = {c.lower() for c in KNOWN_CATEGORIES}
    has_context_entity = bool(words & known_categories_lower) or bool(words & KNOWN_BRANDS)
    if has_context_entity:
        return False

    # Has analysis intent but no entity → needs clarification
    return bool(words & ANALYSIS_HINTS)


def _history_to_messages(history: list[dict] | None) -> list[dict]:
    messages = []
    for item in history or []:
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    return messages


def _build_clarification_response() -> str:
    competitor_examples = ", ".join(list(COMPETITOR_SITES.keys())[:3])
    category_examples = ", ".join(list(KNOWN_CATEGORIES)[:3])
    return (
        f"Which brand or category should I analyze? "
        f"For example: {CLIENT_BRAND}, {competitor_examples}, "
        f"or a category like {category_examples}."
    )


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
        self.prompt_tokens += pt
        self.completion_tokens += ct
        self.total_tokens += tt

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
        sep = "    " + "-" * 62
        rows = []
        for i, c in enumerate(self.calls, start=1):
            rows.append(
                f"    #{i:<7} {c['prompt']:>12} tkns  {c['completion']:>14} tkns  {c['total']:>8} tkns"
            )
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
            self.tools = [
                get_category_trends,
                get_top_competitors,
                get_active_offers,
                get_recommendation,
            ]

            # Build competitor list dynamically from settings
            competitor_list = ", ".join(COMPETITOR_SITES.keys())
            category_list = ", ".join(KNOWN_CATEGORIES)

            system_prompt = f"""You are {CLIENT_BRAND}'s Lead Pricing Strategist and Market Intelligence Assistant.
You help the marketing and pricing teams analyze competitor promotions and make strategic decisions.

KNOWN COMPETITORS: {competitor_list}
KNOWN CATEGORIES: {category_list}

--- TOOL SELECTION RULES ---

OBSERVATION QUESTIONS (what is happening):
- Trigger words: "what is X doing", "show me", "list", "what offers", "what are they running", "how is the market", "trends", "overview"
- Use: get_category_trends OR get_active_offers
- Do NOT call get_recommendation for observation questions

STRATEGY QUESTIONS (what we should do):
- Trigger words: "what should we do", "how do we respond", "what can we do", "recommend", "strategy", "how do we compete", "what's our move", "respond to"
- Use: get_recommendation FIRST, then stop
- Do NOT call get_active_offers or get_category_trends unless the user also asked for examples

LISTING QUESTIONS (show me specific offers):
- Trigger words: "show me", "list", "give me examples", "concrete offers", "what are they running"
- Use: get_active_offers ONLY
- Lead your response with the actual offer list
- Do NOT call get_recommendation for listing questions

OVERVIEW QUESTIONS (trends across categories):
- Trigger words: "category trends", "all categories", "overview", "what's happening"
- Use: get_category_trends with no category filter
- Call it ONCE and stop — do not follow up with get_active_offers or get_recommendation per category
- One overview question = exactly one tool call

--- HARD LIMITS ---
1. Never make more than 2 tool calls in a single response unless the user explicitly asks for a multi-part analysis in the same message.
2. Never invent a category, brand, offer, or numerical value to make a tool call.
3. Do not mix results from unrelated categories or brands into one recommendation.
4. When the question is category-specific, keep every tool call scoped to that category only.
5. If the user says "For all" or "all categories" after a trends question, call get_category_trends with no category filter — do not repeat the last brand/category query.

--- RESPONSE RULES ---
- We are "{CLIENT_BRAND}". Refer to internal data as {CLIENT_BRAND}'s promotions.
- Be specific. Use exact percentages and brand names.
- For strategy responses: lead with urgency, then recommendation, then reasoning.
- For listing responses: lead with the actual offers, then a brief summary.
- For overview responses: summarise the trends clearly by category.
- For normal answers, do not over-compress into a one-line summary. A standard answer should usually be 3 to 6 sentences.
- For observation responses, include: offer count or activity level, average/deepest discount, promo mix when available, and 2 to 4 concrete offer examples.
- For strategy responses, include: urgency, recommended action, target response range if available, why that tactic fits the competitor pattern, and 2 to 3 supporting facts.
- If the user asks for more detail, examples, explanation, or rationale, give a richer answer rather than repeating the short summary."""

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

    def generate_response(
        self,
        query: str,
        session_id: str,
        history: list[dict] | None = None,
    ) -> str:
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

            # --- Pre-checks: only for clear non-agent cases ---

            if _is_greeting(query):
                logger.info(
                    "Greeting detected | session_id=%s | bypassing agent/tools",
                    session_id,
                )
                return (
                    f"Hello! I can help analyze competitor promotions, "
                    f"category trends, and {CLIENT_BRAND} offers. "
                    f"Ask me about a specific brand or category to get started."
                )

            if _needs_clarification(query):
                logger.info(
                    "Clarification required | session_id=%s | query=%r",
                    session_id,
                    query,
                )
                return _build_clarification_response()

            # --- Agent path: history-aware, all routing done by LLM ---

            # Cap history to last MAX_HISTORY_TURNS turns to control token growth.
            # Each "turn" is one user message + one assistant message = 2 items.
            messages = _history_to_messages(history)[-(MAX_HISTORY_TURNS * 2):]
            messages.append({"role": "user", "content": query})

            inputs = {"messages": messages}
            config = {
                "configurable": {"thread_id": session_id},
                "callbacks": [token_cb],
            }

            logger.info(
                "Agent config prepared | thread_id=%s | tools_available=%s | history_turns=%d",
                session_id,
                [tool.name for tool in self.tools],
                len(messages) - 1,  # exclude current query
            )

            t1 = time.perf_counter()
            result = self.graph.invoke(inputs, config=config)
            t2 = time.perf_counter()

            logger.info("Raw agent result received | keys=%s", list(result.keys()))

            final_message = result["messages"][-1].content

            logger.info(
                "Agent final response ready | session_id=%s | response_preview=%s",
                session_id,
                _truncate(final_message),
            )

            logger.info(f"""
    AGENT EXECUTION REPORT                          
    
    Session      : {session_id}
    Query        : {query}
    History Turns: {(len(messages) - 1) // 2}
    
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
