"""
Pipeline Model
Represents CI/CD pipeline runs associated with repositories.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String


class Pipeline(SQLModel, table=True):
    __tablename__ = "pipelines"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    repo_id: str = Field(foreign_key="repos.id", index=True)
    name: str = Field(default="default", max_length=255)
    branch: str = Field(default="main", max_length=100)

    # Execution
    status: str = Field(
        sa_column=Column(String, nullable=False, index=True)
    )  # success | failed | running | cancelled | pending
    duration: Optional[float] = Field(default=None)  # seconds
    trigger: str = Field(default="push")  # push | pr | manual | schedule

    # Metadata
    commit_sha: Optional[str] = Field(default=None, max_length=40)
    commit_message: Optional[str] = Field(default=None, max_length=500)
    triggered_by: Optional[str] = Field(default=None, max_length=100)

    # Timestamps
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
