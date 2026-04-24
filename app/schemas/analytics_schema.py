"""
Analytics Schemas
"""

from typing import List
from .base import BaseSchema

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
