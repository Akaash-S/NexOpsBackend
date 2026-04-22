"""
Repository Model
Represents a source code repository tracked by NexOps.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String


class Repo(SQLModel, table=True):
    __tablename__ = "repos"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    name: str = Field(index=True, max_length=255)
    platform: str = Field(
        sa_column=Column(String, nullable=False, default="github")
    )  # github | gitlab | bitbucket
    description: Optional[str] = Field(default=None, max_length=500)
    language: Optional[str] = Field(default=None, max_length=50)
    default_branch: str = Field(default="main", max_length=100)

    # Metrics
    last_commit_at: Optional[datetime] = Field(default=None)
    open_issues: int = Field(default=0)
    open_prs: int = Field(default=0)
    stars: int = Field(default=0)
    contributors: int = Field(default=0)
    activity: float = Field(default=50.0)  # 0-100 activity score

    # CI/CD Status
    ci_status: str = Field(default="success")  # success | failed | running | pending

    # Health Intelligence
    health_score: float = Field(default=100.0)
    vulnerabilities: int = Field(default=0)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
