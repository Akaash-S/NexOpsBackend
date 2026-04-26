"""
Dependency Model
Represents a directed dependency edge between two repositories.
source_repo_id → target_repo_id means source depends on target.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, String


class Dependency(SQLModel, table=True):
    __tablename__ = "dependencies"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    # The repo that has the dependency
    source_repo_id: str = Field(foreign_key="repos.id", index=True)
    # The repo being depended on
    target_repo_id: str = Field(foreign_key="repos.id", index=True)

    # type: hard | soft | api | library
    type: str = Field(default="api", max_length=50, index=True)

    # Human-readable label shown on the edge
    label: str = Field(default="depends on", max_length=100)

    created_at: datetime = Field(default_factory=datetime.utcnow)
