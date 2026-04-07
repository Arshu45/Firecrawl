import time
import logging
import re
from typing import Any

from langchain_groq import ChatGroq
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

from config.settings import GROQ_API_KEY
from insights.tools import get_category_trends, get_top_competitors, get_active_offers

logger = logging.getLogger(__name__)


def _truncate(value: Any, limit: int = 500) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} chars]"


KNOWN_CATEGORIES = {
    "fashion", "footwear", "beauty", "electronics",
    "home", "sports", "jewellery", "jewelry",
}
KNOWN_BRANDS = {
    "westside", "myntra", "nykaa", "ajio", "flipkart",
}
ANALYSIS_HINTS = {
    "trend", "trends", "discount", "discounts", "offer", "offers",
    "competitor", "competitors", "category", "categories", "pricing",
    "price", "market", "strategy", "recommend", "recommendation",
    "promotions", "promotion", "analyze", "analysis", "compare",
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
    return has_analysis_intent and not has_context_entity

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
                model="llama-3.3-70b-versatile",
                api_key=GROQ_API_KEY,
                temperature=0.0,
            )
            self.tools = [get_category_trends, get_top_competitors, get_active_offers]
            
            system_prompt = """You are Westside's Lead Pricing Strategist and Market Intelligence Assistant.
You help the marketing and pricing teams analyze competitor promotions and make strategic decisions.
1. Use the provided tools only for data-backed questions about promotions, discounts, categories, brands, or competitors.
2. If the user is greeting you, greeting back is enough. Do not use tools.
3. If the user asks an analysis question but does not specify a brand or category, ask a short clarifying question. Do not guess.
4. Never invent a category, brand, offer, or numerical value to make a tool call.
5. Do not mix results from unrelated categories or brands into one recommendation.
6. Use get_active_offers only when the user explicitly asks for exact offers for a specific brand, or when listing examples for that same brand.
2. We are "Westside". Discuss internal data as Westside's promotions.
3. Be specific. Mention exact percentages, rupees, and brand names.
4. Provide actionable insights based on the numerical gaps between us and competitors."""

            # Using Langchain create_agent with LangGraph MemorySaver
            self.memory = MemorySaver()
            self.graph = create_agent(
                model=self.llm,
                tools=self.tools,
                system_prompt=system_prompt,
                checkpointer=self.memory
            )
            
            logger.info(
                "Insights Agent Service initialized successfully | model=%s | tools=%s",
                "llama-3.3-70b-versatile",
                [tool.name for tool in self.tools],
            )
        except Exception as e:
            logger.error(f"Failed to initialize agent service: {str(e)}")
            self.graph = None

    def generate_response(self, query: str, session_id: str) -> str:
        if not self.graph:
            return "I apologize, but my intelligence engine is currently uninitialized."

        start_total = time.perf_counter()
        
        try:
            t0 = time.perf_counter()
            token_cb = TokenUsageCallback()
            logger.info(
                "Agent run starting | session_id=%s | query=%r",
                session_id,
                query,
            )

            if _is_greeting(query):
                logger.info(
                    "Greeting detected | session_id=%s | bypassing agent/tools",
                    session_id,
                )
                return "Hello! I can help analyze competitor promotions, category trends, and Westside offers. Ask me about a specific brand or category to get started."

            if _needs_clarification(query):
                logger.info(
                    "Clarification required | session_id=%s | query=%r",
                    session_id,
                    query,
                )
                return "Which brand or category should I analyze? For example: Westside, Myntra, Nykaa, or a category like Fashion, Beauty, or Electronics."
            
            inputs = {"messages": [{"role": "user", "content": query}]}
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
