from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectResponse,
    RepoValidationRequest, RepoValidationResponse,
    ConfluenceValidationRequest, ConfluenceValidationResponse,
)
import app.services.project_service as svc

router = APIRouter()


# ── Validation endpoints ──────────────────────────────────────────────────────

@router.post("/validate-repo", response_model=RepoValidationResponse)
async def validate_repo(body: RepoValidationRequest):
    """Validate GitHub repo access and return list of branches."""
    return await svc.validate_github_repo(body.url)


@router.post("/validate-confluence", response_model=ConfluenceValidationResponse)
async def validate_confluence(body: ConfluenceValidationRequest):
    """Validate Confluence space access."""
    return await svc.validate_confluence_space(body.url)


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[ProjectResponse])
async def list_projects():
    return await svc.list_projects()


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate, background_tasks: BackgroundTasks):
    project = await svc.create_project(body)
    background_tasks.add_task(
        svc.trigger_onboarding_agent,
        project.id,
        [r.model_dump() for r in body.repos],
        [c.model_dump() for c in (body.confluence_sources or [])],
    )
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str):
    project = await svc.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, body: ProjectUpdate):
    updates = body.model_dump(exclude_none=True)
    project = await svc.update_project(project_id, updates)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str):
    deleted = await svc.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
