"""
Workspace Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class WorkspaceBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    color: str = Field(default="blue")
    description: Optional[str] = None
    provider: str = Field(default="custom")
    status: str = Field(default="connected")
    show_extended_navigation: bool = Field(default=False)


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseSchema):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    status: Optional[str] = None
    access_token: Optional[str] = None
    show_extended_navigation: Optional[bool] = None


class WorkspaceResponse(WorkspaceBase):
    id: str
    repo_count: int = 0
    health_score: float = 100.0
    last_synced_at: Optional[datetime] = None
