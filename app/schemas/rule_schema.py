"""
Rule Schemas
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime


class RuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    trigger: str = Field(
        ...,
        min_length=1,
        validation_alias="condition_type",
        description="Event type to trigger on: ci.failed | pr.opened | issue.created | deploy.failed",
    )
    conditionConfig: Optional[Dict[str, Any]] = Field(None, validation_alias="condition_config")
    actionType: str = Field(
        ...,
        validation_alias="action_type",
        pattern="^(create_alert|update_repo|notify|escalate)$",
    )
    actionConfig: Optional[Dict[str, Any]] = Field(None, validation_alias="action_config")
    enabled: bool = Field(default=True, validation_alias="is_active")

    model_config = ConfigDict(populate_by_name=True)


class RuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    enabled: Optional[bool] = Field(None, validation_alias="is_active")
    conditionConfig: Optional[Dict[str, Any]] = Field(None, validation_alias="condition_config")
    actionConfig: Optional[Dict[str, Any]] = Field(None, validation_alias="action_config")

    model_config = ConfigDict(populate_by_name=True)


class RuleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    trigger: str = Field(validation_alias="condition_type")
    conditionConfig: Optional[Dict[str, Any]] = Field(None, validation_alias="condition_config")
    actionType: str = Field(validation_alias="action_type")
    actionConfig: Optional[Dict[str, Any]] = Field(None, validation_alias="action_config")
    enabled: bool = Field(validation_alias="is_active")
    executionCount: int = Field(validation_alias="execution_count")
    lastTriggered: Optional[datetime] = Field(None, validation_alias="last_triggered_at")
    createdAt: datetime = Field(validation_alias="created_at")
    updatedAt: datetime = Field(validation_alias="updated_at")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
