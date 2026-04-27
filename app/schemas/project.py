from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class RepoConfig(BaseModel):
    url: str
    branch: str = "main"


class TechBadge(BaseModel):
    label: str
    cls: str


class ConfluenceSource(BaseModel):
    url: str
    space_key: str
    space_name: str


class FeatureItem(BaseModel):
    """One entry in the discovered feature manifest."""
    feature: str
    description: str = ""
    repos: list[str] = []
    key_files: list[str] = []
    jira_epics: list[str] = []


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    repos: list[RepoConfig]
    confluence_sources: Optional[list[ConfluenceSource]] = []
    jira_url: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    repos: Optional[list[RepoConfig]] = None
    confluence_sources: Optional[list[ConfluenceSource]] = None
    jira_url: Optional[str] = None
    tech_badges: Optional[list[TechBadge]] = None
    status: Optional[str] = None
    agent_summary: Optional[str] = None
    features: Optional[list[str]] = None
    feature_manifest: Optional[list[FeatureItem]] = None
    docs_count: Optional[int] = None
    last_generated: Optional[datetime] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    repos: list[RepoConfig]
    confluence_sources: Optional[list[ConfluenceSource]] = []
    jira_url: Optional[str] = None
    tech_badges: Optional[list[TechBadge]] = []
    status: str
    docs_count: int = 0
    last_generated: Optional[datetime] = None
    agent_summary: Optional[str] = None
    features: Optional[list[str]] = []
    feature_manifest: Optional[list[FeatureItem]] = []
    created_at: datetime


class RepoValidationRequest(BaseModel):
    url: str


class RepoValidationResponse(BaseModel):
    valid: bool
    branches: list[str] = []
    default_branch: str = "main"
    repo_name: str = ""
    error: Optional[str] = None


class ConfluenceValidationRequest(BaseModel):
    url: str


class ConfluenceValidationResponse(BaseModel):
    valid: bool
    space_key: str = ""
    space_name: str = ""
    error: Optional[str] = None
