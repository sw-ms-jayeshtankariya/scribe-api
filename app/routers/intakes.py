"""
Intakes router — manages customer-reported issues from Zammad (or any ticketing system).

Endpoints:
  POST /webhook          — Zammad webhook receiver (creates intake + triggers analyzer)
  POST /simulate         — Manual intake creation for testing
  GET  /project/:id      — List intakes for a project
  GET  /:intake_id       — Get single intake with analysis
  PATCH /:intake_id      — Update intake status/analysis (called by scribe-agents)
  GET  /:intake_id/stream — SSE stream for real-time analyzer progress
"""

import os
import uuid
import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.database import get_db

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class IntakeWebhook(BaseModel):
    """Zammad webhook payload (simplified)."""
    ticket_id: str | int
    title: str
    description: str
    reporter: str = "Unknown"
    severity: str = "MEDIUM"
    project_id: str  # mapped from Zammad group/tag → Scribe project
    guid: Optional[str] = None


class IntakeSimulate(BaseModel):
    """Manual intake for testing without Zammad."""
    project_id: str
    title: str
    description: str
    reporter: str = "Test User"
    severity: str = "MEDIUM"
    guid: Optional[str] = None


class IntakeUpdate(BaseModel):
    status: Optional[str] = None
    analysis: Optional[dict] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _col():
    return get_db()["intakes"]


def _events_col():
    return get_db()["intake_events"]


# In-memory SSE queues for intake events
_sse_queues: dict[str, asyncio.Queue] = {}


def _get_queue(intake_id: str) -> asyncio.Queue:
    if intake_id not in _sse_queues:
        _sse_queues[intake_id] = asyncio.Queue(maxsize=500)
    return _sse_queues[intake_id]


# ── Webhook (Zammad → Scribe) ────────────────────────────────────────────────

@router.post("/webhook", status_code=202)
async def receive_webhook(body: IntakeWebhook, background_tasks: BackgroundTasks):
    """
    Zammad fires this webhook when a new ticket is created or updated.
    We store the intake and trigger the analyzer agent.
    """
    intake_id = f"intake_{str(uuid.uuid4())[:8]}"
    session_id = f"intake_sess_{intake_id}"

    doc = {
        "_id": intake_id,
        "project_id": body.project_id,
        "ticket_id": str(body.ticket_id),
        "title": body.title,
        "description": body.description,
        "reporter": body.reporter,
        "severity": body.severity,
        "guid": body.guid,
        "status": "PENDING",
        "session_id": session_id,
        "analysis": None,
        "created_at": datetime.utcnow(),
    }
    await _col().insert_one(doc)

    # Trigger analyzer agent
    background_tasks.add_task(_trigger_analyzer, intake_id, body, session_id)

    return {"intake_id": intake_id, "session_id": session_id, "message": "Intake received. Analysis starting."}


# ── Manual simulate (for testing) ─────────────────────────────────────────────

@router.post("/simulate", status_code=202)
async def simulate_intake(body: IntakeSimulate, background_tasks: BackgroundTasks):
    """Create a test intake without Zammad. Triggers the same analyzer pipeline."""
    intake_id = f"intake_{str(uuid.uuid4())[:8]}"
    session_id = f"intake_sess_{intake_id}"

    doc = {
        "_id": intake_id,
        "project_id": body.project_id,
        "ticket_id": f"SIM-{intake_id[-4:]}",
        "title": body.title,
        "description": body.description,
        "reporter": body.reporter,
        "severity": body.severity,
        "guid": body.guid,
        "status": "PENDING",
        "session_id": session_id,
        "analysis": None,
        "created_at": datetime.utcnow(),
    }
    await _col().insert_one(doc)

    webhook = IntakeWebhook(
        ticket_id=doc["ticket_id"],
        title=body.title,
        description=body.description,
        reporter=body.reporter,
        severity=body.severity,
        project_id=body.project_id,
        guid=body.guid,
    )
    background_tasks.add_task(_trigger_analyzer, intake_id, webhook, session_id)

    return {"intake_id": intake_id, "session_id": session_id, "message": "Simulated intake created. Analysis starting."}


async def _trigger_analyzer(intake_id: str, body: IntakeWebhook, session_id: str):
    """Fire the analyzer agent on scribe-agents."""
    import httpx

    agents_url = os.getenv("SCRIBE_AGENTS_URL", "http://localhost:8001")
    api_url = os.getenv("SCRIBE_API_URL", "http://localhost:8000")

    # Update status to ANALYZING
    await _col().update_one({"_id": intake_id}, {"$set": {"status": "ANALYZING"}})

    # Fetch project repos for code inspection
    repos = []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{api_url}/api/v1/projects/{body.project_id}")
            if r.status_code == 200:
                repos = r.json().get("repos", [])
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{agents_url}/analyze-intake", json={
                "intake_id": intake_id,
                "project_id": body.project_id,
                "session_id": session_id,
                "title": body.title,
                "description": body.description,
                "reporter": body.reporter,
                "severity": body.severity,
                "guid": body.guid,
                "repos": repos,
            })
    except Exception as e:
        print(f"[WARN] Could not reach scribe-agents /analyze-intake: {e}")
        await _col().update_one({"_id": intake_id}, {"$set": {"status": "FAILED"}})


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/project/{project_id}")
async def list_project_intakes(project_id: str):
    """List all intakes for a project, newest first."""
    docs = await _col().find({"project_id": project_id}).sort("created_at", -1).to_list(length=100)
    return [{**d, "id": d.pop("_id")} for d in docs]


@router.get("/{intake_id}")
async def get_intake(intake_id: str):
    doc = await _col().find_one({"_id": intake_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Intake not found")
    return {**doc, "id": doc.pop("_id")}


@router.patch("/{intake_id}")
async def update_intake(intake_id: str, body: IntakeUpdate):
    """Called by scribe-agents to update status and analysis results."""
    updates = {}
    if body.status:
        updates["status"] = body.status
    if body.analysis is not None:
        updates["analysis"] = body.analysis
    if not updates:
        return {"ok": True}

    updates["updated_at"] = datetime.utcnow()
    result = await _col().find_one_and_update(
        {"_id": intake_id},
        {"$set": updates},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Intake not found")

    # Push to SSE queue if anyone is listening
    q = _get_queue(intake_id)
    if not q.full():
        try:
            q.put_nowait({"type": "status_change", "status": updates.get("status", ""), "analysis": updates.get("analysis")})
        except Exception:
            pass

    return {"ok": True, "intake_id": intake_id}


# ── SSE stream for intake analysis progress ──────────────────────────────────

@router.get("/{intake_id}/stream")
async def stream_intake_events(intake_id: str, request: Request):
    """SSE endpoint — streams analyzer agent events for an intake."""
    # The analyzer agent emits events to the session SSE queue (via event_bus)
    # which is on the sessions collection. We proxy from there.
    doc = await _col().find_one({"_id": intake_id})
    if not doc:
        async def _not_found():
            yield f"data: {json.dumps({'type': 'error', 'message': 'Intake not found'})}\n\n"
        return StreamingResponse(_not_found(), media_type="text/event-stream")

    session_id = doc.get("session_id", "")

    async def _event_generator():
        # Replay past events
        async for ev in _events_col().find({"session_id": session_id}).sort("timestamp", 1):
            ev.pop("_id", None)
            yield f"data: {json.dumps(ev, default=str)}\n\n"

        # Also replay from the main agent_events collection
        from app.database import get_events_collection
        async for ev in get_events_collection().find({"session_id": session_id}).sort("timestamp", 1):
            ev.pop("_id", None)
            yield f"data: {json.dumps(ev, default=str)}\n\n"

        # Check if already terminal
        current = await _col().find_one({"_id": intake_id})
        if current and current.get("status") in ("ANALYZED", "FAILED"):
            yield f"data: {json.dumps({'type': 'completed', 'status': current['status'], 'analysis': current.get('analysis')}, default=str)}\n\n"
            return

        # Stream live updates
        q = _get_queue(intake_id)
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(event, default=str)}\n\n"
                if event.get("type") in ("completed", "error", "status_change") and event.get("status") in ("ANALYZED", "FAILED"):
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
