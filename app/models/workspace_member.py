"""
WorkspaceMember Model
Links users to workspaces with specific roles.
"""

import uuid
from datetime import datetime
from sqlmodel import SQLModel, Field


class WorkspaceMember(SQLModel, table=True):
    __tablename__ = "workspace_members"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    
    role: str = Field(default="member")  # admin | lead | member
    
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
