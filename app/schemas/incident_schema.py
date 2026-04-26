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

class IncidentCreate(IncidentBase):
    pass

class IncidentResponse(IncidentBase):
    id: str
    started_at: datetime
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
