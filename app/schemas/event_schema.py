"""
Event Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class EventCreate(BaseSchema):
    type: str
    repo_id: Optional[str] = None
    source: str = "system"
    payload: Optional[Dict[str, Any]] = None


class EventResponse(BaseSchema):
    id: str
    type: str
    repo_id: Optional[str] = None
    source: str
    payload: Optional[Dict[str, Any]] = None
    processed: bool
    
    # New fields for frontend display
    message: Optional[str] = None
    severity: Optional[str] = "info"
    
    # Frontend expects 'timestamp' for 'created_at'
    timestamp: datetime = Field(validation_alias="created_at")
