"""
Scoring Weight Recalibration Model
Stores auditable history of correlation scoring weight recalibrations per workspace.
"""

import uuid
from datetime import datetime
from sqlmodel import SQLModel, Field


class ScoringWeightRecalibration(SQLModel, table=True):
    __tablename__ = "scoring_weight_recalibrations"

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    workspace_id: str = Field(foreign_key="workspaces.id", index=True)

    # JSON string encoding of the computed weights dict
    weights: str = Field(max_length=2000)

    # Number of ledger decisions used to compute recalibration
    sample_size: int = Field(default=0)

    # JSON string encoding of the previous weights dict
    previous_weights: str = Field(max_length=2000)

    # Trigger type: e.g. "manual", "scheduled"
    trigger_type: str = Field(default="manual", max_length=50)

    created_at: datetime = Field(default_factory=datetime.utcnow)
