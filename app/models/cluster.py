"""
Cluster Model
Middle layer between Workspace and Repository.
Represents a domain/product group (e.g. "Backend Services", "Frontend Platform").
Owns health aggregation, alert grouping, and team ownership.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Cluster(SQLModel, table=True):
    __tablename__ = "clusters"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    name: str = Field(index=True, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    color: str = Field(default="blue", max_length=50)  # blue | purple | red | emerald | orange

    # Ownership
    owner_team_id: Optional[str] = Field(default=None, foreign_key="teams.id", index=True)

    # Aggregated health — recalculated from member repos
    health_score: float = Field(default=100.0)
    ci_status: str = Field(default="passing")   # passing | failing | running | unknown
    alert_critical: int = Field(default=0)
    alert_high: int = Field(default=0)
    alert_total: int = Field(default=0)
    repo_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
