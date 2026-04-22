"""
Alert Schemas
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


class AlertCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=2000)
    severity: str = Field(..., pattern="^(low|medium|high|critical)$")
    type: str = Field(default="system", pattern="^(security|ci|performance|system|repository|automation)$", validation_alias="category")
    repoId: str = Field(..., min_length=1, validation_alias="repo_id")
    event_id: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class AlertUpdate(BaseModel):
    resolved: Optional[bool] = None
    acknowledged: Optional[bool] = None


class AlertResponse(BaseModel):
    id: str
    title: str
    message: str
    severity: str
    type: str = Field(validation_alias="category")
    repoId: str = Field(validation_alias="repo_id")
    eventId: Optional[str] = Field(None, validation_alias="event_id")
    resolved: bool
    resolvedAt: Optional[datetime] = Field(None, validation_alias="resolved_at")
    acknowledged: bool
    timestamp: datetime = Field(validation_alias="created_at")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
