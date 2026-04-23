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
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
