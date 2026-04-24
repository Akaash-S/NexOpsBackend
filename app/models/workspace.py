"""
Workspace Model
Organizes repositories into logical groups (e.g., Frontend Platform, Data Infra).
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
    name: str = Field(index=True, max_length=255)
    color: str = Field(default="blue", max_length=50) # blue | purple | red | green
    description: Optional[str] = Field(default=None, max_length=500)
    
    # Integration metadata
    provider: str = Field(default="custom", max_length=50) # github | gitlab | bitbucket | custom
    status: str = Field(default="connected", max_length=50) # connected | disconnected | error
    access_token: Optional[str] = Field(default=None, max_length=500)
    refresh_token: Optional[str] = Field(default=None, max_length=500)
    last_synced_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
