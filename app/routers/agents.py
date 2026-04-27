from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    project_id: str
    query: str
    session_id: str | None = None


@router.post("/chat")
async def doc_chat(body: ChatRequest):
    """Proxy to scribe-agents Doc Assistant."""
    return {
        "answer": "Placeholder — scribe-agents will handle this query via RAG.",
        "confidence": 0.0,
        "sources": [],
        "session_id": body.session_id or "new-session",
    }


@router.get("/status")
async def agents_status():
    return {
        "onboarding_agent": "idle",
        "doc_assistant_agent": "idle",
        "generation_agent": "idle",
    }
