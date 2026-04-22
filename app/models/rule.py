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

    # Condition: what triggers this rule
    condition_type: str = Field(
        sa_column=Column(String, nullable=False, index=True)
    )  # Event type to match: ci.failed | pr.opened | issue.created | deploy.failed | etc.
    condition_config: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column("condition_config", JSON, nullable=True),
    )  # Additional filters: { "severity": "critical", "repo_id": "specific-repo" }

    # Action: what happens when triggered
    action_type: str = Field(
        sa_column=Column(String, nullable=False)
    )  # create_alert | update_repo | notify | escalate
    action_config: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column("action_config", JSON, nullable=True),
    )  # Action parameters: { "severity": "high", "message_template": "..." }

    # State
    is_active: bool = Field(default=True, index=True)
    execution_count: int = Field(default=0)
    last_triggered_at: Optional[datetime] = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
