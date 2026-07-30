"""
Repository Schemas
Standardized for React frontend compatibility.
"""

from typing import Optional
from datetime import datetime
from pydantic import Field
from .base import BaseSchema


class RepoCreate(BaseSchema):
    name: str = Field(..., min_length=1, max_length=255)
    platform: str = Field(default="github", pattern="^(github|gitlab|bitbucket)$")
    description: Optional[str] = Field(default=None, max_length=500)
    language: Optional[str] = Field(default=None, max_length=50)
    default_branch: str = Field(default="main", max_length=100)


class RepoUpdate(BaseSchema):
    name: Optional[str] = Field(default=None, max_length=255)
    cluster_id: Optional[str] = Field(default=None)
    ci_status: Optional[str] = Field(
        default=None,
        pattern="^(passing|failing|running|pending|unknown)$",
        validation_alias="status"
    )
    open_issues: Optional[int] = Field(default=None, ge=0, validation_alias="issueCount")
    open_prs: Optional[int] = Field(default=None, ge=0, validation_alias="prCount")
    activity: Optional[float] = Field(default=None, ge=0, le=100)
    vulnerabilities: Optional[int] = Field(default=None, ge=0)
    last_commit_at: Optional[datetime] = Field(default=None, validation_alias="lastCommitAt")


class RepoResponse(BaseSchema):
    id: str
    name: str
    platform: str
    description: Optional[str] = None
    language: Optional[str] = None
    default_branch: str
    last_commit_at: Optional[datetime] = None
    workspace_id: Optional[str] = None
    cluster_id: Optional[str] = None
    
    # Map backend names to camelCase fields for frontend
    issue_count: int = Field(default=0, validation_alias="open_issues")
    pr_count: int = Field(default=0, validation_alias="open_prs")
    ci_status: Optional[str] = Field(default="unknown")
    status: str = Field(default="active")
    
    stars: int = 0
    forks: int = 0
    contributors: int = 0
    activity: float = 0.0
    health_score: float = 100.0
    vulnerabilities: int = 0
    owner: Optional[str] = None
    
    created_at: datetime
    updated_at: datetime
