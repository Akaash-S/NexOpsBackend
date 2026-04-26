"""
Deployment Model
Tracks specific software releases across different environments.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Deployment(SQLModel, table=True):
    __tablename__ = "deployments"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    repo_id: str = Field(foreign_key="repos.id", index=True)
    
    version: str = Field(max_length=100)
    environment: str = Field(default="staging", index=True)  # production | staging | preview
    
    status: str = Field(default="pending", index=True) # pending | running | success | failed | rolled_back
    
    deployed_by: Optional[str] = Field(default=None, max_length=100)
    
    # Metadata
    commit_hash: Optional[str] = Field(default=None, max_length=40)
    changelog: Optional[str] = Field(default=None, max_length=2000)
    
    # Timestamps
    deployed_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
