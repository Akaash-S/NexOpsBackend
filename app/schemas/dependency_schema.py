"""
Dependency Schemas
"""

from typing import Optional
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class DependencyCreate(BaseSchema):
    source_repo_id: str
    target_repo_id: str
    label: str = Field(default="depends on", max_length=100)
    type: str = Field(default="api", max_length=50)


class DependencyResponse(BaseSchema):
    id: str
    source_repo_id: str
    target_repo_id: str
    label: str
    type: str
    created_at: datetime


class TopologyNode(BaseSchema):
    """A repo node enriched with live health data for the graph."""
    id: str
    name: str
    platform: str
    language: Optional[str] = None
    health_score: float
    ci_status: str
    open_issues: int
    vulnerabilities: int
    activity: float
    owner: Optional[str] = None


class TopologyEdge(BaseSchema):
    """A dependency edge between two repos."""
    id: str
    source: str   # source_repo_id
    target: str   # target_repo_id
    label: str
    # True when the source repo is currently failing — used for cascade highlight
    is_broken: bool = False


class TopologyResponse(BaseSchema):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
