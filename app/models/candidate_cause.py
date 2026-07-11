"""
Candidate Cause Model
Represents a potential root cause (event/commit/deployment) scored for an incident.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


class CandidateCause(SQLModel, table=True):
    __tablename__ = "candidate_causes"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    incident_id: str = Field(foreign_key="incidents.id", index=True)
    repo_id: str = Field(foreign_key="repos.id", index=True)
    event_id: Optional[str] = Field(default=None, foreign_key="events.id", nullable=True)
    
    score: float = Field(default=0.0)
    reason: str = Field(max_length=1000)
    
    # NULL/None = pending, True = confirmed, False = rejected
    confirmed: Optional[bool] = Field(default=None, nullable=True)
    confirmed_by: Optional[str] = Field(default=None, foreign_key="users.id", nullable=True)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("incident_id", "event_id", name="uq_candidate_cause_incident_event"),
    )
