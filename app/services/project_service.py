import os
import re
import uuid
import base64
from datetime import datetime
from typing import Optional

import httpx
from dotenv import load_dotenv

from app.database import get_projects_collection
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse,
    RepoValidationResponse, ConfluenceValidationResponse,
    FeatureItem,
)

load_dotenv()

GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN", "")
JIRA_EMAIL     = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")


# ── helpers ──────────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _atlassian_headers() -> dict:
    creds = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def _parse_github_url(url: str) -> Optional[tuple[str, str]]:
    """Return (owner, repo) or None if not parseable."""
    url = url.strip().rstrip("/").replace(".git", "")
    # https://github.com/owner/repo
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if m:
        return m.group(1), m.group(2)
    # git@github.com:owner/repo
    m = re.match(r"git@github\.com:([^/]+)/([^/]+)", url)
    if m:
        return m.group(1), m.group(2)
    return None


def _parse_confluence_space(url: str) -> Optional[str]:
    """
    Extract space key from URLs like:
      https://org.atlassian.net/wiki/spaces/KEY
      https://org.atlassian.net/wiki/spaces/KEY/overview
    """
    m = re.search(r"/spaces/([A-Z0-9~]+)", url, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _doc_to_response(doc: dict) -> ProjectResponse:
    raw_manifest = doc.get("feature_manifest", [])
    manifest = [FeatureItem(**f) if isinstance(f, dict) else f for f in raw_manifest]
    return ProjectResponse(
        id=doc["_id"],
        name=doc["name"],
        description=doc.get("description"),
        repos=doc.get("repos", []),
        confluence_sources=doc.get("confluence_sources", []),
        jira_url=doc.get("jira_url"),
        tech_badges=doc.get("tech_badges", []),
        status=doc.get("status", "PENDING"),
        docs_count=doc.get("docs_count", 0),
        last_generated=doc.get("last_generated"),
        agent_summary=doc.get("agent_summary"),
        features=doc.get("features", []),
        feature_manifest=manifest,
        created_at=doc["created_at"],
    )


# ── validation ────────────────────────────────────────────────────────────────

async def validate_github_repo(url: str) -> RepoValidationResponse:
    parsed = _parse_github_url(url)
    if not parsed:
        return RepoValidationResponse(valid=False, error="Cannot parse GitHub URL. Expected: https://github.com/owner/repo")

    owner, repo = parsed
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=_gh_headers())
        if r.status_code == 404:
            return RepoValidationResponse(valid=False, error=f"Repository '{owner}/{repo}' not found or no access.")
        if r.status_code == 401:
            return RepoValidationResponse(valid=False, error="GitHub token invalid or expired.")
        if r.status_code != 200:
            return RepoValidationResponse(valid=False, error=f"GitHub returned {r.status_code}.")

        repo_data = r.json()
        default_branch = repo_data.get("default_branch", "main")

        # Fetch branches
        branches_r = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=50",
            headers=_gh_headers(),
        )
        branches = [b["name"] for b in (branches_r.json() if branches_r.status_code == 200 else [])]
        if not branches:
            branches = [default_branch]

        return RepoValidationResponse(
            valid=True,
            branches=branches,
            default_branch=default_branch,
            repo_name=f"{owner}/{repo}",
        )


async def validate_confluence_space(url: str) -> ConfluenceValidationResponse:
    space_key = _parse_confluence_space(url)

    # If no /spaces/ in URL, treat the whole URL as the base and check user access
    if not space_key:
        # Try to validate base Confluence access
        base = url.rstrip("/").split("/wiki")[0] + "/wiki"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/rest/api/user/current", headers=_atlassian_headers())
            if r.status_code == 200:
                return ConfluenceValidationResponse(
                    valid=True, space_key="", space_name="(base access confirmed — add /spaces/KEY to URL for space-level validation)"
                )
            return ConfluenceValidationResponse(valid=False, error="Cannot access Confluence. Check URL or permissions.")

    # Determine base URL
    m = re.match(r"(https?://[^/]+(?:/wiki)?)", url)
    base = m.group(1) if m else url
    if "/wiki" not in base:
        base = base + "/wiki"

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{base}/rest/api/space/{space_key}", headers=_atlassian_headers())
        if r.status_code == 200:
            d = r.json()
            return ConfluenceValidationResponse(
                valid=True,
                space_key=space_key,
                space_name=d.get("name", space_key),
            )
        if r.status_code == 404:
            return ConfluenceValidationResponse(valid=False, error=f"Space '{space_key}' not found.")
        if r.status_code in (401, 403):
            return ConfluenceValidationResponse(valid=False, error="No access to this Confluence space.")
        return ConfluenceValidationResponse(valid=False, error=f"Confluence returned {r.status_code}.")


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def list_projects() -> list[ProjectResponse]:
    col = get_projects_collection()
    docs = await col.find({}).sort("created_at", -1).to_list(length=200)
    return [_doc_to_response(d) for d in docs]


async def get_project(project_id: str) -> Optional[ProjectResponse]:
    col = get_projects_collection()
    doc = await col.find_one({"_id": project_id})
    return _doc_to_response(doc) if doc else None


async def create_project(body: ProjectCreate) -> ProjectResponse:
    col = get_projects_collection()
    project_id = str(uuid.uuid4())[:12]
    doc = {
        "_id": project_id,
        "name": body.name,
        "description": body.description,
        "repos": [r.model_dump() for r in body.repos],
        "confluence_sources": [c.model_dump() for c in (body.confluence_sources or [])],
        "jira_url": body.jira_url,
        "tech_badges": [],
        "status": "PENDING",
        "docs_count": 0,
        "last_generated": None,
        "agent_summary": None,
        "features": [],
        "feature_manifest": [],
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await col.insert_one(doc)
    return _doc_to_response(doc)


async def trigger_generate_agent(project_id: str, session_id: str, depth: str, discovery_mode: str) -> None:
    """Fire Phase 1 (discovery) to scribe-agents."""
    project = await get_project(project_id)
    if not project:
        return
    agents_url = os.getenv("SCRIBE_AGENTS_URL", "http://localhost:8001")
    await update_project(project_id, {"status": "DISCOVERING"})
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{agents_url}/generate", json={
                "project_id": project_id,
                "session_id": session_id,
                "repos": [r.model_dump() for r in project.repos],
                "confluence_sources": [c.model_dump() for c in (project.confluence_sources or [])],
                "jira_url": project.jira_url,
                "depth": depth,
                "discovery_mode": discovery_mode,
            })
    except Exception as e:
        print(f"[WARN] Could not reach scribe-agents /generate: {e}")


async def update_project(project_id: str, updates: dict) -> Optional[ProjectResponse]:
    col = get_projects_collection()
    updates["updated_at"] = datetime.utcnow()
    result = await col.find_one_and_update(
        {"_id": project_id},
        {"$set": updates},
        return_document=True,
    )
    if not result:
        return None

    # When the project transitions to AWAITING_CONFIRMATION, also update
    # the active session so the UI can detect the state correctly.
    new_status = updates.get("status", "")
    if new_status == "AWAITING_CONFIRMATION":
        from app.database import get_sessions_collection
        await get_sessions_collection().update_many(
            {"project_id": project_id, "status": "discovering"},
            {"$set": {"status": "awaiting_confirmation", "updated_at": datetime.utcnow()}},
        )

    return _doc_to_response(result)


async def delete_project(project_id: str) -> bool:
    col = get_projects_collection()
    result = await col.delete_one({"_id": project_id})
    return result.deleted_count > 0


async def trigger_onboarding_agent(project_id: str, repos: list[dict], confluence_sources: list[dict]) -> None:
    """Fire-and-forget: POST to scribe-agents /onboard."""
    agents_url = os.getenv("SCRIBE_AGENTS_URL", "http://localhost:8001")
    await update_project(project_id, {"status": "SCANNING"})
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(f"{agents_url}/onboard", json={
                "project_id": project_id,
                "repos": repos,
                "confluence_sources": confluence_sources,
            })
    except Exception as e:
        print(f"[WARN] Could not reach scribe-agents: {e}")
