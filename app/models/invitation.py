"""
Invitation Model
Tracks pending team invitations.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlmodel import SQLModel, Field


class Invitation(SQLModel, table=True):
    __tablename__ = "invitations"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    email: str = Field(index=True)
    role: str = Field(default="member")
    
    token: str = Field(default_factory=lambda: str(uuid.uuid4()), unique=True)
    status: str = Field(default="pending")  # pending | accepted | expired | revoked
    
    invited_by_id: str = Field(foreign_key="users.id")
    
    expires_at: datetime = Field(
        default_factory=lambda: datetime.utcnow() + timedelta(days=7)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    accepted_at: Optional[datetime] = Field(default=None)
