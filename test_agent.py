"""Agent service for LLM-powered product search and recommendations."""

import os
import logging
import json
import re
import time
from typing import Optional
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_classic.agents import create_react_agent, AgentExecutor
from langchain_classic.memory.buffer_window import ConversationBufferWindowMemory
from langsmith import Client

from src.agents.tools.product_search_tool import create_product_search_tool
from src.application.services.product_search_service import ProductSearchService
from src.infrastructure.llm.groq_client import get_groq_client
from src.infrastructure.prompts.prompts_loader import get_prompt
from src.config.settings import settings
from src.config.logger import get_logger

from src.application.services.agent_prompt_builder import (
    derive_output_fields,
    build_final_answer_schema,
)
from src.config.csv_schema_loader import get_attribute_schema

load_dotenv()
logger = get_logger(__name__)

class TokenUsageCallback(BaseCallbackHandler):
    """Tracks per-call and cumulative LLM token usage across an agent loop."""

    def __init__(self):
        self.calls: list = []
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.tool_calls: int = 0       
        self.tool_names: list = []     

    @property
    def llm_calls(self) -> int:
        return len(self.calls)

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

    def on_llm_start(self, serialized: dict, prompts: list, **kwargs) -> None:
        """Log the full prompt sent to the LLM on each call."""
        call_num = len(self.calls) + 1
        # for i, prompt in enumerate(prompts):
            # logger.info(
            #     f"\n{'='*60}\n"
            #     f"🔷 REACT PROMPT  (LLM call #{call_num}, message {i+1})\n"
            #     f"{'='*60}\n"
            #     f"{prompt}\n"
            #     f"{'='*60}"
            # )

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        self.tool_calls += 1
        self.tool_names.append(serialized.get("name", "unknown_tool"))  

    def token_table(self) -> str:
        """Return a formatted per-call breakdown + grand total."""
        header = f"    {'Call':<8} {'Prompt (Input)':>16} {'Completion (Output)':>22} {'Total':>12}"
        sep    = "    " + "-" * 62
        rows   = []
        for i, c in enumerate(self.calls, start=1):
            rows.append(
                f"    #{i:<7} {c['prompt']:>12} tkns  {c['completion']:>14} tkns  {c['total']:>8} tkns"
            )
        grand = (
            f"    {'TOTAL':<8} {self.prompt_tokens:>12} tkns  "
            f"{self.completion_tokens:>14} tkns  {self.total_tokens:>8} tkns"
        )
        return "\n".join([header, sep] + rows + [sep, grand])

    def summary(self) -> str:
        """One-line summary for quick scanning."""
        return (
            f"LLM Calls={self.llm_calls} | "
            f"Prompt={self.prompt_tokens} | "
            f"Completion={self.completion_tokens} | "
            f"Total={self.total_tokens}"
        )

class AgentService:
    """Service for LLM agent orchestration with product search tool."""
    
    def __init__(self, product_service: ProductSearchService):
        """Initialize agent service with LLM and product search tool.
        
        Args:
            product_service: ProductSearchService instance (required)
        """
        if not product_service:
            raise ValueError("ProductSearchService is required for AgentService")
        
        try:
            # Configure Groq LLM
            self.llm = ChatGroq(
                model=settings.agent_model,
                groq_api_key=settings.groq_api_key,
                temperature=0,
            )
            
            # Additional Groq client for JSON extraction tasks
            self.groq_client = get_groq_client()
            
            #CSV_HEADERS = load_csv_headers(settings.csv_file_path)

            # Create product search tool
            self.product_search_tool = create_product_search_tool(product_service)
            tools = [self.product_search_tool]
            
            logger.info("Product search tool added to agent")
            
            # Pull ReAct prompt template
            try:
                client = Client()
                self.prompt = client.pull_prompt("hwchase17/react")
            except Exception as e:
                logger.warning(f"Could not pull prompt from LangSmith: {e}. Using default.")
                self.prompt = None
            
            # Store executors and memories per session
            self.sessions = {}
            self.memories = {}
            
            # Save components for dynamic executor creation
            self.tools = tools
            
            logger.info("Agent service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize agent service: {str(e)}")
            self.llm = None
            self.tools = []
    
    def get_executor(self, session_id: str) -> AgentExecutor:
        """
        Get or create an AgentExecutor for a specific session.
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            AgentExecutor instance
        """
        if session_id in self.sessions:
            return self.sessions[session_id]
        
        # Create memory for session
        memory = ConversationBufferWindowMemory(
            k=5,
            return_messages=False,  # ReAct prompt expects string history
            output_key="output",
            memory_key="chat_history"
        )
        self.memories[session_id] = memory
        
        # Fetch ReAct prompt from dynamic loader
        template = get_prompt("REACT_AGENT_PROMPT")

        #Build agent prompt variables
        CATALOG_NAME = os.getenv("COLLECTION_NAME")

        ATTRIBUTE_SCHEMA = get_attribute_schema(CATALOG_NAME)

        DOCUMENT_COLUMNS = {
            col.strip().lower()
            for col in os.getenv("DOCUMENT_COLUMNS", "").split(",")
            if col.strip()
        }

        OUTPUT_FIELDS = derive_output_fields(
            attribute_schema=ATTRIBUTE_SCHEMA,
            document_columns=DOCUMENT_COLUMNS,
        )

        FINAL_ANSWER_SCHEMA = build_final_answer_schema(OUTPUT_FIELDS)

        react_prompt = PromptTemplate.from_template(template, 
            partial_variables={
                "final_answer_schema": FINAL_ANSWER_SCHEMA
            })

        # Create agent
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=react_prompt,
        )
        
        # Create executor
        executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=memory,
            max_iterations=10,
            verbose=True,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
            output_key="output"
        )
        
        self.sessions[session_id] = executor
        return executor

    def create_session(self) -> str:
        """
        Create and initialize a new session with a unique UUID.
        
        Returns:
            The new session ID
        """
        import uuid
        session_id = str(uuid.uuid4())
        # Lazy initialization will happen on first use, or we can force it here
        self.get_executor(session_id)
        logger.info(f"Explicitly created new session: {session_id}")
        return session_id

    def get_all_sessions(self) -> list:
        """Get list of all active session IDs."""
        return list(self.sessions.keys())

    def reset_session(self, session_id: str) -> bool:
        """
        Reset/Clear a specific session.
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            True if session was found and reset, False otherwise
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            if session_id in self.memories:
                del self.memories[session_id]
            logger.info(f"Session {session_id} reset successfully")
            return True
        return False

    def get_session_history(self, session_id: str) -> list:
        """
        Get chat history for a specific session.
        
        Args:
            session_id: Unique session identifier
            
        Returns:
            List of messages in the history
        """
        if session_id in self.memories:
            memory = self.memories[session_id]
            # Convert memory buffer to list of dicts
            messages = []
            for msg in memory.chat_memory.messages:
                messages.append({
                    "type": msg.type,
                    "content": msg.content
                })
            return messages
        return []

    def generate_response(self, query: str, session_id: str) -> dict:
        """
        Generate chatbot response using LLM agent with session memory.
        
        Args:
            query: User search query
            session_id: Unique session identifier
            
        Returns:
            Dictionary with response_text and found_products
        """
        if not self.llm:
            return {"response_text": self._get_fallback_response(query), "products": []}

        start_total = time.perf_counter()

        try:
            # --- Executor ---
            t0 = time.perf_counter()
            executor = self.get_executor(session_id)
            t1 = time.perf_counter()

            # --- Token callback (MUST be created here and passed to invoke) ---
            token_cb = TokenUsageCallback()  

            # --- Agent Invoke ---
            result = executor.invoke(
                {"input": query},
                config={"callbacks": [token_cb]} 
            )
            t2 = time.perf_counter()

            output = result.get("output", "")
            t3 = time.perf_counter()

            if not output:
                logger.warning(f"[{session_id}] Agent returned empty output.")
                return {"response_text": self._get_fallback_response(query), "products": []}

            # Strip "Final Answer:" prefix if present
            if output.lstrip().startswith("Final Answer:"):
                output = output.split("Final Answer:", 1)[1].strip()

            try:
                parsed = json.loads(output)
                t4 = time.perf_counter()

                logger.info(f"""
    AGENT EXECUTION REPORT                          
    
    Session      : {session_id}
    Query        : {query}
    
    ⏱  TIMING BREAKDOWN
    ──────────────────────────────────────────────────────────
    Executor Init          : {(t1 - t0):.4f}s
    Agent Invoke (LLM+Tool): {(t2 - t1):.4f}s
    Output Extraction      : {(t3 - t2):.4f}s
    JSON Parse             : {(t4 - t3):.4f}s
    🔥 TOTAL TIME          : {(t4 - start_total):.4f}s
    
    📊 TOKEN USAGE
    {token_cb.token_table()}
    
    Tool Calls             : {token_cb.tool_calls} ({', '.join(token_cb.tool_names) if token_cb.tool_names else 'none'})
    
    """)
                return {
                    "response_text": parsed.get("response_text", ""),
                    "products": parsed.get("products", [])
                }

            except json.JSONDecodeError:
                logger.warning(f"[{session_id}] Agent returned non-JSON output: {output[:200]}")
                return {"response_text": output, "products": []}

        except Exception as e:
            logger.error(f"[{session_id}] Agent error: {str(e)}", exc_info=True)
            return {"response_text": self._get_fallback_response(query), "products": []}
    
    def generate_follow_ups(self, query: str, response_text: str) -> list:
        """
        Generate dynamic follow-up questions using LLM.

        Returns an empty list for simple greetings / chitchat.
        For product-related queries, asks the LLM for 2-3 attribute-focused
        follow-up questions (color, size, price range, style).

        Args:
            query: Original user query
            response_text: LLM generated response

        Returns:
            List of follow-up question strings (may be empty)
        """
        # Short-circuit for greetings — no LLM call, no follow-up questions
        _GREETING = re.compile(
            r"^\s*(hi+|hello+|hey+|howdy|greetings|good\s*(morning|afternoon|evening|day)|"
            r"how are you|what'?s up|sup|thanks?|thank you|bye|goodbye|ok|okay|sure|cool|great)"
            r"\s*[!?.]*\s*$",
            re.IGNORECASE,
        )
        if _GREETING.match(query.strip()):
            logger.info("Greeting detected – returning empty follow-ups")
            return []

        try:
            # Inject the real user query into the prompt template
            system_prompt_template = get_prompt("GENERATE_FOLLOW_UP_PROMPT")
            system_prompt = system_prompt_template.replace("{user_query}", query)
            CATALOG_NAME = os.getenv("COLLECTION_NAME")
            ATTRIBUTE_SCHEMA = get_attribute_schema(CATALOG_NAME)
            # Read excluded keys from env (comma-separated) — configurable per deployment
            _exclude_env = os.getenv("FOLLOWUP_EXCLUDE_ATTRIBUTES", "")
            _EXCLUDE = {k.strip() for k in _exclude_env.split(",") if k.strip()}
            attribute_keys = [
                k for k in (ATTRIBUTE_SCHEMA.keys() if isinstance(ATTRIBUTE_SCHEMA, dict) else [])
                if k not in _EXCLUDE
            ]
            system_prompt = system_prompt.replace(
                "{attribute_schema}", json.dumps(attribute_keys)
            )

            user_input = f"Agent Response: {response_text}"
            # logger.info(
            #     f"\n{'='*60}\n"
            #     f"🔶 FOLLOW UP PROMPT  (system)\n"
            #     f"{'='*60}\n"
            #     f"{system_prompt}\n"
            #     f"{'='*60}\n"
            #     f"🔶 FOLLOW-UP USER MESSAGE\n"
            #     f"{'-'*60}\n"
            #     f"{user_input}\n"
            #     f"{'='*60}"
            # )
            result = self.groq_client.extract_json(
                system_prompt=system_prompt,
                user_query=user_input
            )
            # Ensure we always return a list
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.warning(f"Failed to generate dynamic follow-ups: {e}")
            return []
    
    def _get_fallback_response(self, query: str) -> str:
        """
        Generate fallback response when LLM fails.
        
        Args:
            query: User search query
            
        Returns:
            Fallback response text
        """
        return (
            f"I apologize, but I'm having trouble processing your query: '{query}'. "
            "Please try again or rephrase your question."
        )