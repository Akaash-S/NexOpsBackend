"""
Repository Schemas
Request/Response validation for the Repos API.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class RepoCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    platform: str = Field(default="github", pattern="^(github|gitlab|bitbucket)$")
    description: Optional[str] = Field(default=None, max_length=500)
    language: Optional[str] = Field(default=None, max_length=50)
    default_branch: str = Field(default="main", max_length=100)


class RepoUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    ci_status: Optional[str] = Field(default=None, pattern="^(success|failed|running|pending)$")
    open_issues: Optional[int] = Field(default=None, ge=0)
    open_prs: Optional[int] = Field(default=None, ge=0)
    activity: Optional[float] = Field(default=None, ge=0, le=100)
    vulnerabilities: Optional[int] = Field(default=None, ge=0)
    last_commit_at: Optional[datetime] = None


class RepoResponse(BaseModel):
    id: str
    name: str
    platform: str
    description: Optional[str]
    language: Optional[str]
    default_branch: str
    last_commit_at: Optional[datetime]
    open_issues: int
    open_prs: int
    stars: int
    contributors: int
    activity: float
    ci_status: str
    health_score: float
    vulnerabilities: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
