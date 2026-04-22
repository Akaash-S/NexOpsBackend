"""
Event Model
The core entity that drives the entire NexOps automation engine.
Every state change in the system originates from an Event.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON, String


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    type: str = Field(
        sa_column=Column(String, nullable=False, index=True)
    )  # repo.updated | ci.failed | ci.success | pr.opened | pr.merged | issue.created | deploy.started | deploy.failed
    repo_id: str = Field(foreign_key="repos.id", index=True)
    source: str = Field(default="system")  # system | github | gitlab | webhook | manual
    payload: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column("payload", JSON, nullable=True),
    )
    processed: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
