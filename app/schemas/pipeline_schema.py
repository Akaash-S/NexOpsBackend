"""
Pipeline Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional, List
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class PipelineStage(BaseSchema):
    name: str
    status: str
    duration: Optional[float] = None


class PipelineResponse(BaseSchema):
    id: str
    repo_id: str
    name: str
    status: str
    branch: str
    trigger: str
    duration: Optional[float] = None
    commit_hash: Optional[str] = None
    environment: str = "staging"
    stages: List[PipelineStage] = Field(default_factory=list)

    # Frontend expects startedAt, map from created_at
    started_at: datetime = Field(validation_alias="created_at")
    updated_at: datetime
