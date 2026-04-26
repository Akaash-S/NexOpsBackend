"""
Incident Model
Represents a collection of related alerts that signify a single operational issue.
Tracks the lifecycle from discovery to resolution.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Incident(SQLModel, table=True):
    __tablename__ = "incidents"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    cluster_id: Optional[str] = Field(default=None, foreign_key="clusters.id", index=True)
    
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    
    severity: str = Field(default="medium", index=True)  # low | medium | high | critical
    status: str = Field(default="open", index=True)    # open | investigating | resolved | closed
    
    # Root cause analysis
    root_cause_repo_id: Optional[str] = Field(default=None, foreign_key="repos.id")
    impact_summary: Optional[str] = Field(default=None, max_length=1000)

    # Timestamps
    started_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
