from typing import Optional
from datetime import datetime
from .base import BaseSchema

class DeploymentBase(BaseSchema):
    repo_id: str
    environment: str = "staging"
    status: str = "pending"
    deployed_by: Optional[str] = None
    commit_hash: Optional[str] = None
    changelog: Optional[str] = None
    risk_score: float = 0.0
    risk_basis: str = ""

class DeploymentCreate(DeploymentBase):
    pass

class DeploymentResponse(DeploymentBase):
    id: str
    deployed_at: datetime
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
