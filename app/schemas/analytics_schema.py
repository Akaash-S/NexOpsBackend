"""
Analytics Schemas
"""

from typing import List, Optional
from .base import BaseSchema
from .repo_schema import RepoResponse
from .alert_schema import AlertResponse
from .cluster_schema import ClusterResponse

class DashboardStats(BaseSchema):
    avg_health: float
    success_rate: float
    vulnerability_index: int
    infrastructure_load: float

class ActivityPoint(BaseSchema):
    name: str
    commits: int
    issues: int
    deployed: int

class ActivityResponse(BaseSchema):
    data: List[ActivityPoint]

class DashboardSummary(BaseSchema):
    """Combined dashboard data to reduce API calls"""
    stats: DashboardStats
    repos: List[RepoResponse]
    alerts: List[AlertResponse]
    clusters: List[ClusterResponse]
