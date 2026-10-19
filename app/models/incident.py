"""
Incident Model
Represents a collection of related alerts that signify a single operational issue.
Tracks the lifecycle from discovery to resolution.
"""

import uuid
from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


class Incident(SQLModel, table=True):
    __tablename__ = "incidents"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    cluster_id: Optional[str] = Field(default=None, index=True)
    
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    
    severity: str = Field(default="medium", index=True)  # low | medium | high | critical
    status: str = Field(default="open", index=True)    # open | investigating | resolved | closed
    
    # Root cause analysis
    root_cause_repo_id: Optional[str] = Field(default=None, foreign_key="repos.id")
    impacted_repos: List[str] = Field(default=[], sa_column=Column(JSON))
    impact_summary: Optional[str] = Field(default=None, max_length=1000)
    affected_users: int = Field(default=0)

    # PagerDuty incident ID (e.g. Q3OILL557B8681): direct FK lookup for webhook resolve/ack.
    pd_incident_id: Optional[str] = Field(default=None, max_length=64, nullable=True, index=True)

    # Timestamps
    started_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
