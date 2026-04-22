"""
Alert Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AlertCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=2000)
    severity: str = Field(..., pattern="^(low|medium|high|critical)$")
    category: str = Field(default="system", pattern="^(security|ci|performance|system)$")
    repo_id: str = Field(..., min_length=1)
    event_id: Optional[str] = None


class AlertUpdate(BaseModel):
    resolved: Optional[bool] = None
    acknowledged: Optional[bool] = None


class AlertResponse(BaseModel):
    id: str
    title: str
    message: str
    severity: str
    category: str
    repo_id: str
    event_id: Optional[str]
    resolved: bool
    resolved_at: Optional[datetime]
    acknowledged: bool
    created_at: datetime

    model_config = {"from_attributes": True}
