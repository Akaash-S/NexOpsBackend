"""
Event Schemas
Request/Response validation for the Events API — the core ingestion endpoint.
"""

from pydantic import BaseModel, Field, ConfigDict, computed_field
from typing import Optional, Dict, Any
from datetime import datetime


class EventCreate(BaseModel):
    type: str = Field(
        ...,
        min_length=1,
        description="Event type: repo.updated | ci.failed | ci.success | pr.opened | pr.merged | issue.created | deploy.started | deploy.failed",
    )
    repoId: str = Field(..., min_length=1, validation_alias="repo_id")
    source: str = Field(default="system")
    
    # Input can be 'payload' or 'metadata'
    payload: Optional[Dict[str, Any]] = Field(default=None, validation_alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class EventResponse(BaseModel):
    id: str
    type: str
    repoId: str = Field(validation_alias="repo_id")
    source: str
    
    # Map internal 'payload' to frontend 'payload'
    payload: Optional[Dict[str, Any]] = Field(None, validation_alias="payload")
    processed: bool
    timestamp: datetime = Field(validation_alias="created_at")

    @computed_field(alias="metadata")
    @property
    def event_metadata(self) -> Optional[Dict[str, Any]]:
        """Keep supporting 'metadata' for compatibility."""
        return self.payload

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
