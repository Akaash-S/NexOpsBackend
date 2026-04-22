"""
Repository Schemas
Request/Response validation for the Repos API.
"""

from pydantic import BaseModel, Field, ConfigDict
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
    ci_status: Optional[str] = Field(default=None, pattern="^(passing|failing|running|pending|unknown)$", alias="status")
    open_issues: Optional[int] = Field(default=None, ge=0, alias="issueCount")
    open_prs: Optional[int] = Field(default=None, ge=0, alias="prCount")
    activity: Optional[float] = Field(default=None, ge=0, le=100)
    vulnerabilities: Optional[int] = Field(default=None, ge=0)
    last_commit_at: Optional[datetime] = Field(default=None, alias="lastCommitAt")
    
    model_config = ConfigDict(populate_by_name=True)


class RepoResponse(BaseModel):
    id: str
    name: str
    platform: str
    description: Optional[str]
    language: Optional[str]
    defaultBranch: str = Field(validation_alias="default_branch")
    lastCommitAt: Optional[datetime] = Field(validation_alias="last_commit_at")
    issueCount: int = Field(validation_alias="open_issues")
    prCount: int = Field(validation_alias="open_prs")
    stars: int
    contributors: int
    activity: float
    status: str = Field(validation_alias="ci_status")
    healthScore: float = Field(validation_alias="health_score")
    vulnerabilities: int
    createdAt: datetime = Field(validation_alias="created_at")
    updatedAt: datetime = Field(validation_alias="updated_at")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
