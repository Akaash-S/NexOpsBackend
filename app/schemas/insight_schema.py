"""
Insight Schemas
Standardized for React frontend compatibility.
"""

from typing import List, Dict, Any, Optional
from .base import BaseSchema


class AlertSummary(BaseSchema):
    active_count: int
    breakdown: Dict[str, int]


class PipelineStats(BaseSchema):
    total: int
    success: int
    failed: int
    running: int
    avg_duration: float


class Recommendation(BaseSchema):
    urgency: str
    title: str
    message: str
    action: str


class InsightFactor(BaseSchema):
    label: str
    value: str
    impact: str


class InsightResponse(BaseSchema):
    repo_id: str
    repo_name: str
    health_score: float
    ci_status: str
    activity: float
    vulnerabilities: int
    alerts: AlertSummary
    pipelines: PipelineStats
    events_24h: int
    recommendation: Recommendation
    factors: List[InsightFactor]
