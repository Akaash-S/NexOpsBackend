"""
Workspace Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional, List
from pydantic import Field
from .base import BaseSchema


class WorkspaceBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    color: str = Field(default="blue")
    description: Optional[str] = None


class WorkspaceCreate(WorkspaceBase):
    pass


class WorkspaceUpdate(BaseSchema):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class WorkspaceResponse(WorkspaceBase):
    id: str
    repo_count: int = 0
    health_score: float = 100.0
