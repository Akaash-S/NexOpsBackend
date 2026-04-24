"""
Pipeline Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional, List, Dict, Any
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
    
    # New fields to match frontend requirements
    commit_hash: Optional[str] = None
    environment: str = "staging"
    stages: List[PipelineStage] = Field(default_factory=list)
    
    # Standard timestamps
    created_at: datetime
    updated_at: datetime
