from typing import Optional, List
from datetime import datetime
from .base import BaseSchema

class IncidentBase(BaseSchema):
    title: str
    description: Optional[str] = None
    severity: str = "medium"
    status: str = "open"
    cluster_id: Optional[str] = None
    root_cause_repo_id: Optional[str] = None
    impact_summary: Optional[str] = None
    affected_users: int = 0
    pd_incident_id: Optional[str] = None

class IncidentCreate(IncidentBase):
    pass

class IncidentResponse(IncidentBase):
    id: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    candidate_causes: List["CandidateCauseResponse"] = []

class CandidateCauseResponse(BaseSchema):
    id: str
    incident_id: str
    repo_id: str
    event_id: Optional[str] = None
    score: float
    reason: str
    confirmed: Optional[bool] = None
    confirmed_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
