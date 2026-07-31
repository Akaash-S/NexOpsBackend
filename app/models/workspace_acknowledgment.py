"""
Workspace Acknowledgment Model
Records workspace acceptance of Terms of Service and Privacy Notice before connecting integrations.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class WorkspaceAcknowledgment(SQLModel, table=True):
    __tablename__ = "workspace_acknowledgments"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True, unique=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    terms_version: str = Field(default="v1.0", max_length=50)
    acknowledged_at: datetime = Field(default_factory=datetime.utcnow)
