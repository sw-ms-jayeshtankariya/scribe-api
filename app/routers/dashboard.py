"""
Dashboard router — aggregates real data from MongoDB collections
for the admin dashboard: projects, sessions, documents, intakes, events.
"""

from fastapi import APIRouter
from typing import Optional
from datetime import date, datetime, timedelta

from app.database import (
    get_projects_collection, get_sessions_collection,
    get_events_collection, get_db,
)

router = APIRouter()


def _date_filter(from_date: Optional[date], to_date: Optional[date]) -> dict:
    """Build a MongoDB date filter from optional from/to dates."""
    f: dict = {}
    if from_date:
        f["$gte"] = datetime.combine(from_date, datetime.min.time())
    if to_date:
        f["$lte"] = datetime.combine(to_date, datetime.max.time())
    return {"created_at": f} if f else {}


@router.get("/stats")
async def get_stats(from_date: Optional[date] = None, to_date: Optional[date] = None):
    """Summary stats: total projects, sessions, documents, intakes."""
    projects_col = get_projects_collection()
    sessions_col = get_sessions_collection()
    docs_col = get_db()["documents"]
    intakes_col = get_db()["intakes"]
    events_col = get_events_collection()

    date_q = _date_filter(from_date, to_date)

    total_projects = await projects_col.count_documents({})
    total_sessions = await sessions_col.count_documents(date_q or {})
    total_docs = await docs_col.count_documents({})
    approved_docs = await docs_col.count_documents({"approved": True})
    total_intakes = await intakes_col.count_documents(date_q or {})
    total_events = await events_col.count_documents(date_q or {})

    # Count unique queries from doc assistant (user_message events)
    total_queries = await events_col.count_documents(
        {**date_q, "type": "user_message"} if date_q else {"type": "user_message"}
    )

    return {
        "total_projects": total_projects,
        "total_sessions": total_sessions,
        "total_documents": total_docs,
        "approved_documents": approved_docs,
        "total_intakes": total_intakes,
        "total_events": total_events,
        "total_queries": total_queries,
    }


@router.get("/projects-summary")
async def projects_summary():
    """Per-project summary: name, status, docs count, sessions count, intakes count."""
    projects_col = get_projects_collection()
    sessions_col = get_sessions_collection()
    docs_col = get_db()["documents"]
    intakes_col = get_db()["intakes"]

    projects = await projects_col.find({}).sort("created_at", -1).to_list(length=50)
    result = []

    for p in projects:
        pid = p["_id"]
        sessions_count = await sessions_col.count_documents({"project_id": pid})
        docs_count = await docs_col.count_documents({"project_id": pid})
        approved_count = await docs_col.count_documents({"project_id": pid, "approved": True})
        intakes_count = await intakes_col.count_documents({"project_id": pid})

        result.append({
            "project_id": pid,
            "name": p.get("name", "Unknown"),
            "status": p.get("status", "PENDING"),
            "tech_badges": p.get("tech_badges", []),
            "sessions": sessions_count,
            "documents": docs_count,
            "approved": approved_count,
            "intakes": intakes_count,
            "features_count": len(p.get("features", [])),
            "created_at": p.get("created_at"),
        })

    return result


@router.get("/recent-sessions")
async def recent_sessions(limit: int = 10):
    """Recent generation sessions with status and metadata."""
    sessions_col = get_sessions_collection()
    projects_col = get_projects_collection()

    sessions = await sessions_col.find({}).sort("created_at", -1).to_list(length=limit)
    result = []

    # Build project name lookup
    project_ids = list(set(s.get("project_id", "") for s in sessions))
    projects = await projects_col.find({"_id": {"$in": project_ids}}).to_list(length=50)
    name_map = {p["_id"]: p.get("name", "Unknown") for p in projects}

    for s in sessions:
        result.append({
            "id": s["_id"],
            "project": name_map.get(s.get("project_id", ""), "Unknown"),
            "project_id": s.get("project_id", ""),
            "depth": s.get("depth", "standard"),
            "status": s.get("status", "unknown"),
            "created_at": s.get("created_at"),
        })

    return result


@router.get("/recent-intakes")
async def recent_intakes(limit: int = 10):
    """Recent customer intakes with analysis status."""
    intakes_col = get_db()["intakes"]
    projects_col = get_projects_collection()

    intakes = await intakes_col.find({}).sort("created_at", -1).to_list(length=limit)

    project_ids = list(set(i.get("project_id", "") for i in intakes))
    projects = await projects_col.find({"_id": {"$in": project_ids}}).to_list(length=50)
    name_map = {p["_id"]: p.get("name", "Unknown") for p in projects}

    result = []
    for i in intakes:
        analysis = i.get("analysis", {}) or {}
        result.append({
            "id": i["_id"],
            "project": name_map.get(i.get("project_id", ""), "Unknown"),
            "title": i.get("title", ""),
            "severity": i.get("severity", "MEDIUM"),
            "status": i.get("status", "PENDING"),
            "reporter": i.get("reporter", ""),
            "code_fix_needed": analysis.get("code_fix_needed", False),
            "created_at": i.get("created_at"),
        })

    return result


@router.get("/agent-activity")
async def agent_activity():
    """Aggregate agent event counts by agent name."""
    events_col = get_events_collection()

    pipeline = [
        {"$group": {
            "_id": "$agent",
            "events": {"$sum": 1},
            "latest": {"$max": "$timestamp"},
        }},
        {"$sort": {"events": -1}},
    ]
    cursor = events_col.aggregate(pipeline)
    results = await cursor.to_list(length=50)

    return [
        {
            "agent": r["_id"] or "unknown",
            "events": r["events"],
            "latest": r.get("latest"),
        }
        for r in results
    ]


@router.get("/events-timeline")
async def events_timeline(days: int = 14):
    """Event counts per day for the last N days."""
    events_col = get_events_collection()
    since = datetime.utcnow() - timedelta(days=days)

    pipeline = [
        {"$match": {"timestamp": {"$gte": since.isoformat()}}},
        {"$addFields": {
            "day": {"$substr": ["$timestamp", 0, 10]},
        }},
        {"$group": {"_id": "$day", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]

    try:
        cursor = events_col.aggregate(pipeline)
        results = await cursor.to_list(length=days + 1)
        return [{"date": r["_id"], "count": r["count"]} for r in results]
    except Exception:
        return []
