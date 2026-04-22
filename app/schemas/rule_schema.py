"""
Rule Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class RuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    condition_type: str = Field(
        ...,
        min_length=1,
        description="Event type to trigger on: ci.failed | pr.opened | issue.created | deploy.failed",
    )
    condition_config: Optional[Dict[str, Any]] = None
    action_type: str = Field(
        ...,
        pattern="^(create_alert|update_repo|notify|escalate)$",
    )
    action_config: Optional[Dict[str, Any]] = None
    is_active: bool = Field(default=True)


class RuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None
    condition_config: Optional[Dict[str, Any]] = None
    action_config: Optional[Dict[str, Any]] = None


class RuleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    condition_type: str
    condition_config: Optional[Dict[str, Any]]
    action_type: str
    action_config: Optional[Dict[str, Any]]
    is_active: bool
    execution_count: int
    last_triggered_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
