import uuid
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import get_db

router = APIRouter()


class DocumentCreate(BaseModel):
    project_id: str
    session_id: str
    feature: str
    content: str
    depth: str = "standard"
    generated_at: Optional[str] = None


class DocumentEdit(BaseModel):
    content: str


class DocumentResponse(BaseModel):
    id: str
    project_id: str
    session_id: str
    feature: str
    content: str
    depth: str
    approved: bool = False
    generated_at: Optional[str] = None
    versions: list[dict] = []


def _col():
    return get_db()["documents"]


@router.post("/", response_model=DocumentResponse, status_code=201)
async def create_document(body: DocumentCreate):
    """Called by scribe-agents orchestrator to save an approved document."""
    doc_id = str(uuid.uuid4())[:12]
    doc = {
        "_id": doc_id,
        "project_id": body.project_id,
        "session_id": body.session_id,
        "feature": body.feature,
        "content": body.content,
        "depth": body.depth,
        "approved": False,
        "versions": [],
        "generated_at": body.generated_at or datetime.utcnow().isoformat(),
    }
    await _col().insert_one(doc)
    return {**doc, "id": doc_id}


@router.get("/project/{project_id}", response_model=list[DocumentResponse])
async def list_project_docs(project_id: str):
    docs = await _col().find({"project_id": project_id}).sort("generated_at", -1).to_list(length=100)
    return [{**d, "id": d.pop("_id")} for d in docs]


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_doc(doc_id: str):
    doc = await _col().find_one({"_id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {**doc, "id": doc.pop("_id")}


@router.patch("/{doc_id}")
async def save_doc_edit(doc_id: str, body: DocumentEdit):
    """Save edited content — pushes current content into versions history."""
    doc = await _col().find_one({"_id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    versions = doc.get("versions", [])
    versions.append({
        "content": doc["content"],
        "saved_at": doc.get("generated_at", datetime.utcnow().isoformat()),
    })
    await _col().update_one(
        {"_id": doc_id},
        {"$set": {"content": body.content, "versions": versions}},
    )
    updated = await _col().find_one({"_id": doc_id})
    return {**updated, "id": updated.pop("_id")}


@router.post("/{doc_id}/reset")
async def reset_doc_edit(doc_id: str):
    """Restore the most recent previous version."""
    doc = await _col().find_one({"_id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    versions = doc.get("versions", [])
    if not versions:
        raise HTTPException(status_code=400, detail="No previous version to restore")
    prev = versions.pop()
    await _col().update_one(
        {"_id": doc_id},
        {"$set": {"content": prev["content"], "versions": versions}},
    )
    updated = await _col().find_one({"_id": doc_id})
    return {**updated, "id": updated.pop("_id")}


@router.patch("/{doc_id}/approve")
async def approve_doc(doc_id: str):
    from fastapi import BackgroundTasks as _BG
    doc = await _col().find_one({"_id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    await _col().update_one(
        {"_id": doc_id},
        {"$set": {"approved": True, "ingestion_status": "pending"}},
    )

    # Fire-and-forget: trigger vector DB ingestion on scribe-agents
    import httpx, os
    agents_url = os.getenv("SCRIBE_AGENTS_URL", "http://localhost:8001")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{agents_url}/ingest", json={
                "project_id": doc["project_id"],
                "doc_id": doc_id,
                "feature": doc.get("feature", ""),
                "content": doc["content"],
            })
    except Exception as e:
        print(f"[WARN] Could not trigger ingestion for {doc_id}: {e}")

    return {"message": "Document approved. Ingestion started.", "doc_id": doc_id}


@router.get("/{doc_id}/ingestion-status")
async def get_ingestion_status(doc_id: str):
    """Poll endpoint for ingestion progress."""
    doc = await _col().find_one({"_id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "doc_id": doc_id,
        "ingestion_status": doc.get("ingestion_status", "none"),
        "chunks_count": doc.get("chunks_count", 0),
    }


@router.patch("/{doc_id}/ingestion-status")
async def update_ingestion_status(doc_id: str, body: dict):
    """Called by scribe-agents to update ingestion progress."""
    updates = {}
    if "ingestion_status" in body:
        updates["ingestion_status"] = body["ingestion_status"]
    if "chunks_count" in body:
        updates["chunks_count"] = body["chunks_count"]
    if not updates:
        return {"ok": True}
    result = await _col().find_one_and_update(
        {"_id": doc_id},
        {"$set": updates},
        return_document=True,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True, "doc_id": doc_id}
