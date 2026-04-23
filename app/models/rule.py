"""
Automation Rule Model
Defines condition → action mappings that the automation engine evaluates
when events flow through the system.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON, String


class Rule(SQLModel, table=True):
    __tablename__ = "rules"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)

    # Trigger: what event type starts this rule
    condition_type: str = Field(
        sa_column=Column(String, nullable=False, index=True)
    )  # Event type to match: ci.failed | pr.opened | etc.

    # Advanced Conditions: List of logic gates [{field, operator, value}]
    condition_config: Optional[list] = Field(
        default_factory=list,
        sa_column=Column("condition_config", JSON, nullable=True),
    )

    # Actions: List of results [{type, params}]
    action_config: Optional[list] = Field(
        default_factory=list,
        sa_column=Column("action_config", JSON, nullable=True),
    )

    # State
    is_active: bool = Field(default=True, index=True)
    execution_count: int = Field(default=0)
    last_triggered_at: Optional[datetime] = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
