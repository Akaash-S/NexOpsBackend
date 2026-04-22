"""
Event Schemas
Request/Response validation for the Events API — the core ingestion endpoint.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class EventCreate(BaseModel):
    type: str = Field(
        ...,
        min_length=1,
        description="Event type: repo.updated | ci.failed | ci.success | pr.opened | pr.merged | issue.created | deploy.started | deploy.failed",
    )
    repo_id: str = Field(..., min_length=1)
    source: str = Field(default="system")
    payload: Optional[Dict[str, Any]] = Field(default=None, alias="metadata")

    model_config = {"populate_by_name": True}


class EventResponse(BaseModel):
    id: str
    type: str
    repo_id: str
    source: str
    event_data: Optional[Dict[str, Any]] = Field(None, alias="metadata")
    processed: bool
    created_at: datetime

    model_config = {"populate_by_name": True}
