import logging
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn

from insights.agent import InsightsAgentService
from config.settings import CLIENT_BRAND

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title=f"{CLIENT_BRAND} Promotion Intelligence API")

# Initialize the global agent instance so it maintains memory across requests
agent_service = InsightsAgentService()

class ChatHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"
    history: list[ChatHistoryItem] = Field(default_factory=list)

class ChatResponse(BaseModel):
    response: str

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    """
    Passes a natural language question to the LangGraph Agent.
    """
    logger.info(
        "Incoming chat request | session_id=%s | message=%r",
        request.session_id,
        request.message,
    )
    try:
        # Agent execution using LangGraph State mapping
        final_answer = agent_service.generate_response(
            request.message,
            request.session_id,
            history=[item.model_dump() for item in request.history],
        )
        logger.info(
            "Chat request complete | session_id=%s | response_chars=%d",
            request.session_id,
            len(final_answer or ""),
        )
        return ChatResponse(response=final_answer)
    except Exception as e:
        logger.exception(
            "Chat request failed | session_id=%s | error=%s",
            request.session_id,
            e,
        )
        return ChatResponse(response=f"Error accessing insights: {str(e)}")

def run_server():
    """Boots the uvicorn server on port 8000"""
    logger.info("Starting FastAPI server on port 8000")
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)

if __name__ == "__main__":
    run_server()
