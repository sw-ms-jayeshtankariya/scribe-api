import asyncio
import uuid
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.database import get_sessions_collection, get_events_collection
import app.services.project_service as project_svc

router = APIRouter()

# In-memory SSE queues: session_id → asyncio.Queue
_sse_queues: dict[str, asyncio.Queue] = {}


# ── Request / Response models ─────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    project_id: str
    depth: str = "standard"        # overview | standard | detailed
    discovery_mode: str = "auto"   # auto | jira-first | code-first


class ConfirmFeaturesRequest(BaseModel):
    features: list[dict]           # confirmed (possibly edited) feature manifest
    user_message: str = ""         # free-text instructions — agent applies them to the feature list


class UserMessageRequest(BaseModel):
    message: str


class IngestEventRequest(BaseModel):
    """Called by scribe-agents to push live events into the SSE queue."""
    type: str
    agent: str
    feature: Optional[str] = None
    round: int = 0
    message: str
    timestamp: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _create_session(project_id: str, depth: str, discovery_mode: str) -> str:
    session_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{project_id[:6]}"
    doc = {
        "_id": session_id,
        "project_id": project_id,
        "depth": depth,
        "discovery_mode": discovery_mode,
        "status": "discovering",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await get_sessions_collection().insert_one(doc)
    return session_id


async def _update_session(session_id: str, updates: dict):
    updates["updated_at"] = datetime.utcnow()
    await get_sessions_collection().find_one_and_update(
        {"_id": session_id}, {"$set": updates}
    )


def _get_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _sse_queues:
        _sse_queues[session_id] = asyncio.Queue(maxsize=500)
    return _sse_queues[session_id]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate", status_code=202)
async def trigger_generation(body: GenerateRequest, background_tasks: BackgroundTasks):
    """Start Phase 1 — feature discovery."""
    session_id = await _create_session(body.project_id, body.depth, body.discovery_mode)
    background_tasks.add_task(
        project_svc.trigger_generate_agent,
        body.project_id,
        session_id,
        body.depth,
        body.discovery_mode,
    )
    return {"session_id": session_id, "project_id": body.project_id, "depth": body.depth}


@router.post("/{session_id}/confirm-features", status_code=202)
async def confirm_features(session_id: str, body: ConfirmFeaturesRequest, background_tasks: BackgroundTasks):
    """
    User confirms the feature manifest (with optional free-text instructions).
    If user_message is provided it is forwarded to scribe-agents which uses Claude
    to apply the intent (merge, skip, rename, re-focus) before running Phase 2.
    """
    session = await get_sessions_collection().find_one({"_id": session_id})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    project_id = session["project_id"]

    # Store the user message as an event so it appears in the session log
    if body.user_message.strip():
        evt = {
            "_id": str(uuid.uuid4()),
            "session_id": session_id,
            "type": "user_message",
            "agent": "user",
            "message": body.user_message,
            "feature": None, "round": 0,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await get_events_collection().insert_one(evt)
        q = _get_queue(session_id)
        if not q.full():
            await q.put({k: v for k, v in evt.items() if k != "_id"})

    await project_svc.update_project(project_id, {"status": "GENERATING"})
    await _update_session(session_id, {"status": "generating", "user_instruction": body.user_message})

    import os
    agents_url = os.getenv("SCRIBE_AGENTS_URL", "http://localhost:8001")
    background_tasks.add_task(_fire_phase2, agents_url, project_id, session_id, body.features, session, body.user_message)

    return {"message": "Phase 2 generation started.", "session_id": session_id}


async def _fire_phase2(agents_url: str, project_id: str, session_id: str, features: list, session: dict, user_instruction: str = ""):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{agents_url}/generate-phase2", json={
                "project_id": project_id,
                "session_id": session_id,
                "features": features,
                "depth": session.get("depth", "standard"),
                "discovery_mode": session.get("discovery_mode", "auto"),
                "user_instruction": user_instruction,
            })
    except Exception as e:
        print(f"[WARN] Could not reach scribe-agents /generate-phase2: {e}")


@router.post("/{session_id}/events")
async def ingest_event(session_id: str, body: IngestEventRequest):
    """Scribe-agents POSTs events here — we store + push to SSE queue."""
    event = {
        "session_id": session_id,
        "type": body.type,
        "agent": body.agent,
        "feature": body.feature,
        "round": body.round,
        "message": body.message,
        "timestamp": body.timestamp or datetime.utcnow().isoformat(),
    }
    # Persist to MongoDB
    await get_events_collection().insert_one({**event, "_id": str(uuid.uuid4())})
    # Push to SSE queue
    q = _get_queue(session_id)
    if not q.full():
        await q.put(event)
    return {"ok": True}


@router.post("/{session_id}/message")
async def send_user_message(session_id: str, body: UserMessageRequest):
    """User sends a free-text message to guide the agent mid-session."""
    event = {
        "_id": str(uuid.uuid4()),
        "session_id": session_id,
        "type": "user_message",
        "agent": "user",
        "message": body.message,
        "feature": None,
        "round": 0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await get_events_collection().insert_one(event)
    await get_sessions_collection().find_one_and_update(
        {"_id": session_id},
        {"$push": {"user_messages": {"message": body.message, "timestamp": event["timestamp"]}}},
    )
    q = _get_queue(session_id)
    if not q.full():
        await q.put({k: v for k, v in event.items() if k != "_id"})
    return {"ok": True}


@router.get("/{session_id}/stream")
async def stream_events(session_id: str, request: Request):
    """SSE endpoint — browser connects here to receive live agent events."""
    async def event_generator():
        # Replay past events from MongoDB first
        async for doc in get_events_collection().find({"session_id": session_id}).sort("timestamp", 1):
            doc.pop("_id", None)
            yield f"data: {json.dumps(doc)}\n\n"

        # Then stream new events from queue
        q = _get_queue(session_id)
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("completed", "error"):
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/project/{project_id}")
async def get_project_sessions(project_id: str):
    """List all generation sessions for a project."""
    docs = await get_sessions_collection().find(
        {"project_id": project_id}
    ).sort("created_at", -1).to_list(length=50)
    for d in docs:
        d["id"] = d.pop("_id")
    return docs
