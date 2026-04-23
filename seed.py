"""
NexOps Seed Script (Aligned with Refactored Models)
Populates the database with realistic sample data.
"""

import asyncio
from datetime import datetime, timedelta
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.repo import Repo
from app.models.event import Event
from app.models.alert import Alert
from app.models.rule import Rule
from app.models.pipeline import Pipeline
from app.models.user import User
from app.models.team import Team
from app.models.workspace import Workspace

engine = create_async_engine(settings.async_database_url, echo=False)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ── Workspace Data ──────────────────────────────────────────────────────
WORKSPACES = [
    {"id": "ws-1", "name": "Frontend Platform", "color": "blue", "description": "Core UI components and micro-frontends"},
    {"id": "ws-2", "name": "Data Infrastructure", "color": "purple", "description": "Pipelines and warehousing"},
    {"id": "ws-3", "name": "Security & Compliance", "color": "red", "description": "Audit logs and threat monitoring"},
]

# ── User & Team Data ─────────────────────────────────────────────────────
USERS = [
    {"full_name": "Akaash S", "email": "akaash@nexops.io", "role": "admin", "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=Akaash"},
    {"full_name": "Sarah Chen", "email": "sarah@nexops.io", "role": "lead", "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=Sarah"},
]

TEAMS = [
    {"name": "Platform Engineering", "description": "Core infrastructure and developer experience", "member_count": 8, "repo_count": 12, "health_score": 94.5},
    {"name": "Security & Compliance", "description": "Threat monitoring and audit readiness", "member_count": 4, "repo_count": 5, "health_score": 88.0},
]

# ── Repository Seed Data ─────────────────────────────────────────────────
REPOS = [
    {
        "id": "repo-001",
        "workspace_id": "ws-1",
        "name": "nexops-frontend",
        "platform": "github",
        "owner": "nexops-io",
        "description": "React frontend for the NexOps DevOps platform",
        "language": "TypeScript",
        "last_commit_at": datetime.utcnow() - timedelta(hours=2),
        "open_issues": 4,
        "open_prs": 2,
        "stars": 128,
        "forks": 12,
        "contributors": 8,
        "activity": 85.0,
        "ci_status": "passing",
        "health_score": 92.0,
    },
    {
        "id": "repo-002",
        "workspace_id": "ws-1",
        "name": "nexops-api",
        "platform": "github",
        "owner": "nexops-io",
        "description": "FastAPI backend engine for NexOps",
        "language": "Python",
        "last_commit_at": datetime.utcnow() - timedelta(hours=1),
        "open_issues": 7,
        "open_prs": 3,
        "stars": 64,
        "forks": 5,
        "contributors": 5,
        "activity": 72.0,
        "ci_status": "passing",
        "health_score": 88.0,
    },
    {
        "id": "repo-003",
        "workspace_id": "ws-2",
        "name": "infra-terraform",
        "platform": "gitlab",
        "owner": "ops-team",
        "description": "Infrastructure-as-code for cloud provisioning",
        "language": "HCL",
        "last_commit_at": datetime.utcnow() - timedelta(days=3),
        "open_issues": 12,
        "open_prs": 0,
        "stars": 22,
        "forks": 45,
        "contributors": 3,
        "activity": 18.0,
        "ci_status": "failing",
        "health_score": 45.0,
        "vulnerabilities": 5,
    },
]

# ── Automation Rules ─────────────────────────────────────────────────────
RULES = [
    {
        "name": "CI Failure Alert",
        "description": "Create a high-severity alert when any CI pipeline fails",
        "condition_type": "ci.failed",
        "condition_config": [], # No extra filters
        "action_config": [
            {
                "type": "create_alert",
                "params": {
                    "severity": "high",
                    "category": "ci",
                    "title": "CI Pipeline Failed",
                    "message": "A CI pipeline has failed. Build is broken — merges are blocked."
                }
            },
            {
                "type": "update_repo",
                "params": {"ci_status": "failing"}
            }
        ],
        "is_active": True,
    },
    {
        "name": "Auto-Resolve on Pass",
        "description": "Mark CI as passing when pipeline succeeds",
        "condition_type": "ci.success",
        "condition_config": [],
        "action_config": [
            {
                "type": "update_repo",
                "params": {"ci_status": "passing"}
            }
        ],
        "is_active": True,
    }
]

# ── Pipelines ────────────────────────────────────────────────────────────
PIPELINES = [
    {
        "repo_id": "repo-001", 
        "name": "Build & Test", 
        "status": "success", 
        "duration": 124.5, 
        "branch": "main", 
        "trigger": "push",
        "environment": "production",
        "commit_hash": "a1b2c3d4e5f6g7h8i9j0",
        "stages": [
            {"name": "Lint", "status": "success", "duration": 12.5},
            {"name": "Test", "status": "success", "duration": 85.0},
            {"name": "Build", "status": "success", "duration": 27.0}
        ]
    },
]

# ── Alerts ───────────────────────────────────────────────────────────────
ALERTS = [
    {
        "title": "Critical vulnerability in lodash@4.17.20",
        "message": "CVE-2021-23337: Prototype pollution in lodash. Upgrade to 4.17.21+.",
        "severity": "critical",
        "category": "security",
        "repo_id": "repo-003",
    },
    {
        "title": "CI Pipeline Failed — infra-terraform",
        "message": "Terraform plan failed due to invalid provider configuration.",
        "severity": "high",
        "category": "ci",
        "repo_id": "repo-003",
    },
]

# ── Events ───────────────────────────────────────────────────────────────
EVENTS = [
    {
        "type": "ci.failed", 
        "repo_id": "repo-003", 
        "source": "gitlab", 
        "message": "CI Pipeline Failed: infra-terraform",
        "severity": "error",
        "payload": {"branch": "main", "error": "provider config invalid"}
    },
]

async def seed():
    """Seed the database with sample data."""
    async with engine.begin() as conn:
        # Drop all tables and recreate to apply model changes
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)

    async with session_factory() as session:
        print("Seeding Workspaces...")
        for data in WORKSPACES: session.add(Workspace(**data))
        await session.commit()

        print("Seeding Users & Teams...")
        for data in USERS: session.add(User(**data))
        for data in TEAMS: session.add(Team(**data))
        await session.commit()

        print("Seeding Repositories...")
        for data in REPOS: session.add(Repo(**data))
        await session.commit()

        print("Seeding Rules...")
        for data in RULES: session.add(Rule(**data))
        await session.commit()

        print("Seeding Pipelines...")
        for data in PIPELINES: session.add(Pipeline(**data))
        await session.commit()

        print("Seeding Alerts...")
        for data in ALERTS: session.add(Alert(**data))
        await session.commit()

        print("Seeding Events...")
        for data in EVENTS: session.add(Event(**data, processed=True))
        await session.commit()

    print("\nSeed complete! NexOps backend is fully aligned and ready.")

if __name__ == "__main__":
    asyncio.run(seed())
