"""
User Model
Basic user representation for account and ownership tracking.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


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
    onboarding_completed: bool = Field(default=False)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
