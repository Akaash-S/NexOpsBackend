"""
Cluster Schemas
"""

from typing import Optional, List
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class ClusterCreate(BaseSchema):
    workspace_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    color: str = Field(default="blue")
    owner_team_id: Optional[str] = None


class ClusterUpdate(BaseSchema):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    owner_team_id: Optional[str] = None


class ClusterResponse(BaseSchema):
    id: str
    workspace_id: str
    name: str
    description: Optional[str] = None
    color: str
    owner_team_id: Optional[str] = None

    # Aggregated intelligence
    health_score: float
    ci_status: str
    alert_critical: int
    alert_high: int
    alert_total: int
    repo_count: int

    created_at: datetime
    updated_at: datetime


class ClusterAlertSummary(BaseSchema):
    """Alert breakdown grouped by cluster — used on the alerts/security page."""
    cluster_id: str
    cluster_name: str
    cluster_color: str
    critical: int
    high: int
    medium: int
    low: int
    total: int
