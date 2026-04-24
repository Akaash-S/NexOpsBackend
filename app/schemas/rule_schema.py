"""
Rule Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class RuleAction(BaseSchema):
    type: str
    params: Optional[Dict[str, Any]] = None


class RuleCondition(BaseSchema):
    field: str
    operator: str
    value: Any


class RuleCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    trigger: str = Field(..., description="Event type: ci.failed | pr.opened | etc.")
    
    # Matching frontend nested structure
    conditions: List[RuleCondition] = Field(default_factory=list)
    actions: List[RuleAction] = Field(default_factory=list)
    
    enabled: bool = Field(default=True, validation_alias="is_active")


class RuleUpdate(BaseSchema):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = Field(None, validation_alias="is_active")
    conditions: Optional[List[RuleCondition]] = None
    actions: Optional[List[RuleAction]] = None


class RuleResponse(BaseSchema):
    id: str
    name: str
    description: Optional[str] = None
    trigger: str = Field(validation_alias="condition_type")
    
    # These will map to JSONB fields in the DB later
    conditions: List[RuleCondition] = Field(default_factory=list, validation_alias="condition_config")
    actions: List[RuleAction] = Field(default_factory=list, validation_alias="action_config")
    
    enabled: bool = Field(validation_alias="is_active")
    execution_count: int = 0
    last_triggered: Optional[datetime] = Field(None, validation_alias="last_triggered_at")
    
    created_at: datetime
    updated_at: datetime
