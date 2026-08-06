"""
User Model
Basic user representation for account and ownership tracking.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, JSON


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    email: str = Field(index=True, unique=True, max_length=255)
    full_name: str = Field(max_length=255)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    role: str = Field(default="member")  # admin | lead | member
    
    github_access_token: Optional[str] = Field(default=None)
    github_last_synced_at: Optional[datetime] = Field(default=None)  # Timestamp of last successful GitHub sync
    pagerduty_access_token: Optional[str] = Field(default=None)
    pagerduty_webhook_secret: Optional[str] = Field(default=None)
    pagerduty_webhook_subscription_id: Optional[str] = Field(default=None)
    email_verified: bool = Field(default=False)
    onboarding_completed: bool = Field(default=False)
    preferences: Optional[dict] = Field(
        default_factory=dict,
        sa_column=Column("preferences", JSON, nullable=True)
    )
    workspace_id: Optional[str] = Field(default=None, foreign_key="workspaces.id", index=True)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
