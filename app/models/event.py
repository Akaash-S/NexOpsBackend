"""
Event Model
The core entity that drives the entire NexOps automation engine.
Every state change in the system originates from an Event.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON, String, Index


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    type: str = Field(
        sa_column=Column(String, nullable=False, index=True)
    )  # repo.updated | ci.failed | ci.success | pr.opened | pr.merged | issue.created | deploy.started | deploy.failed
    repo_id: str = Field(foreign_key="repos.id", index=True)
    source: str = Field(default="system")  # system | github | gitlab | webhook | manual
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column("payload", JSON, nullable=True),
    )
    message: Optional[str] = Field(default=None, max_length=500)
    severity: str = Field(default="info", max_length=20)  # info | warning | error | critical
    
    # PagerDuty idempotency: stores the PagerDuty event.id to prevent duplicate processing.
    # A partial unique index (on rows where pd_event_id IS NOT NULL) is created via migration.
    pd_event_id: Optional[str] = Field(default=None, max_length=64, nullable=True)

    # PagerDuty incident ID (e.g. Q3OILL557B8681): used to link acknowledged/resolved
    # events back to the original incident. Indexed for fast lookup.
    pd_incident_id: Optional[str] = Field(default=None, max_length=64, nullable=True, index=True)

    processed: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
