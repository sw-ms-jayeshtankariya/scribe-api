from sqlalchemy import Column, String, DateTime, Text, JSON, Enum
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime
import enum


class Base(DeclarativeBase):
    pass


class ProjectStatus(str, enum.Enum):
    PENDING = "PENDING"
    SCANNING = "SCANNING"
    READY = "READY"
    ERROR = "ERROR"


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    repos = Column(JSON)             # [{"url": str, "branch": str}]
    jira_url = Column(String)
    confluence_url = Column(String)
    transcript_sources = Column(JSON)
    tech_badges = Column(JSON)       # [{"label": str, "cls": str}]
    status = Column(Enum(ProjectStatus), default=ProjectStatus.PENDING)
    docs_count = Column(String, default="0")
    last_generated = Column(DateTime)
    metadata_summary = Column(JSON)  # agent-extracted summary
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
