"""
Candidate Cause Feedback Log Model
Immutable append-only ledger recording every confirm/reject decision.
"""

import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class CandidateCauseFeedbackLog(SQLModel, table=True):
    __tablename__ = "candidate_cause_feedback_logs"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)
    candidate_cause_id: str = Field(foreign_key="candidate_causes.id", index=True)
    incident_id: str = Field(foreign_key="incidents.id", index=True)
    repo_id: str = Field(foreign_key="repos.id", index=True)
    event_id: Optional[str] = Field(default=None, foreign_key="events.id", nullable=True)

    confirmed: bool = Field(nullable=False)
    confirmed_by: Optional[str] = Field(default=None, foreign_key="users.id", nullable=True)
    score_at_time: float = Field(default=0.0)
    reasons_at_time: str = Field(max_length=1000, default="")

    created_at: datetime = Field(default_factory=datetime.utcnow)
