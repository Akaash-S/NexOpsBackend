"""
Workspace Model
Represents a first-class tenant workspace in NexOps.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    # GUARD: Identity and workspace-name fields (User.full_name, Workspace.name) must NEVER be modified
    # except in direct response to an explicit user-facing request or admin action — NEVER as an inferred
    # "correction" during unrelated troubleshooting work. Workspace name is set at creation and preserved.
    name: str = Field(max_length=255)
    color: str = Field(default="blue")
    description: Optional[str] = Field(default=None, max_length=500)
    provider: str = Field(default="custom")
    status: str = Field(default="connected")
    show_extended_navigation: bool = Field(default=False)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
