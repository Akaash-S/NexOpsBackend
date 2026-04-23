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
    ci_status: Optional[str] = Field(
        default=None, 
        pattern="^(passing|failing|running|pending|unknown)$", 
        alias="status"
    )
    open_issues: Optional[int] = Field(default=None, ge=0, alias="issueCount")
    open_prs: Optional[int] = Field(default=None, ge=0, alias="prCount")
    activity: Optional[float] = Field(default=None, ge=0, le=100)
    vulnerabilities: Optional[int] = Field(default=None, ge=0)
    last_commit_at: Optional[datetime] = Field(default=None, alias="lastCommitAt")


class RepoResponse(BaseSchema):
    id: str
    name: str
    platform: str
    description: Optional[str] = None
    language: Optional[str] = None
    default_branch: str
    last_commit_at: Optional[datetime] = None
    
    # Aliased fields for exact frontend match
    issue_count: int = Field(validation_alias="open_issues")
    pr_count: int = Field(validation_alias="open_prs")
    status: str = Field(validation_alias="ci_status")
    
    stars: int = 0
    forks: int = 0
    contributors: int = 0
    activity: float = 0.0
    health_score: float = 100.0
    vulnerabilities: int = 0
    owner: Optional[str] = None
    
    created_at: datetime
    updated_at: datetime
