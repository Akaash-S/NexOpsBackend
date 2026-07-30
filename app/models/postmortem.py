"""
Postmortem Model
Stores the structured postmortem document for a resolved incident.
One postmortem per incident. Fields are editable and auto-saved.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, Text


class Postmortem(SQLModel, table=True):
    __tablename__ = "postmortems"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    incident_id: str = Field(foreign_key="incidents.id", unique=True, index=True)
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)

    # Authored by
    author_id: Optional[str] = Field(default=None, foreign_key="users.id")

    # Postmortem sections — all optional, filled progressively
    summary: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
    )
    timeline: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="Chronological event log in plain text or Markdown",
    )
    root_cause: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
    )
    contributing_factors: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
    )
    impact: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="Customer and business impact description",
    )
    action_items: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="Corrective and preventive action items",
    )
    lessons_learned: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
    )

    # Status: draft | published
    status: str = Field(default="draft", index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
