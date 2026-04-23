"""
Alert Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class AlertCreate(BaseSchema):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=2000)
    severity: str = Field(..., pattern="^(low|medium|high|critical)$")
    type: str = Field(
        default="system", 
        pattern="^(security|ci|performance|system|repository|automation)$", 
        alias="category"
    )
    repo_id: str = Field(..., min_length=1)
    event_id: Optional[str] = None


class AlertUpdate(BaseSchema):
    resolved: Optional[bool] = None
    acknowledged: Optional[bool] = None


class AlertResponse(BaseSchema):
    id: str
    title: str
    message: str
    severity: str
    
    # Aliased fields for exact frontend match
    type: str = Field(validation_alias="category")
    repo_id: str
    event_id: Optional[str] = None
    
    resolved: bool
    resolved_at: Optional[datetime] = None
    acknowledged: bool
    
    # Frontend expects 'timestamp' for 'created_at'
    timestamp: datetime = Field(validation_alias="created_at")
