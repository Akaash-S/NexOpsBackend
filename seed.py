"""
NexOps Seed Script
Populates the database with realistic sample data to mirror
the frontend's mockData.ts — ensuring instant frontend integration.

Usage: python seed.py
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.repo import Repo
from app.models.event import Event
from app.models.alert import Alert
from app.models.rule import Rule
from app.models.pipeline import Pipeline


engine = create_async_engine(settings.async_database_url, echo=False)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ── Repository Seed Data ─────────────────────────────────────────────────
REPOS = [
    {
        "id": "repo-001",
        "name": "nexops-frontend",
        "platform": "github",
        "description": "React frontend for the NexOps DevOps platform",
        "language": "TypeScript",
        "default_branch": "main",
        "last_commit_at": datetime.utcnow() - timedelta(hours=2),
        "open_issues": 4,
        "open_prs": 2,
        "stars": 128,
        "contributors": 8,
        "activity": 85.0,
        "ci_status": "success",
        "health_score": 92.0,
        "vulnerabilities": 0,
    },
    {
        "id": "repo-002",
        "name": "nexops-api",
        "platform": "github",
        "description": "FastAPI backend engine for NexOps",
        "language": "Python",
        "default_branch": "main",
        "last_commit_at": datetime.utcnow() - timedelta(hours=1),
        "open_issues": 7,
        "open_prs": 3,
        "stars": 64,
        "contributors": 5,
        "activity": 72.0,
        "ci_status": "success",
        "health_score": 88.0,
        "vulnerabilities": 1,
    },
    {
        "id": "repo-003",
        "name": "infra-terraform",
        "platform": "gitlab",
        "description": "Infrastructure-as-code for cloud provisioning",
        "language": "HCL",
        "default_branch": "main",
        "last_commit_at": datetime.utcnow() - timedelta(days=3),
        "open_issues": 12,
        "open_prs": 0,
        "stars": 22,
        "contributors": 3,
        "activity": 18.0,
        "ci_status": "failed",
        "health_score": 45.0,
        "vulnerabilities": 5,
    },
    {
        "id": "repo-004",
        "name": "auth-service",
        "platform": "github",
        "description": "OAuth2 / SSO authentication microservice",
        "language": "Go",
        "default_branch": "main",
        "last_commit_at": datetime.utcnow() - timedelta(hours=6),
        "open_issues": 2,
        "open_prs": 1,
        "stars": 45,
        "contributors": 4,
        "activity": 61.0,
        "ci_status": "success",
        "health_score": 78.0,
        "vulnerabilities": 2,
    },
    {
        "id": "repo-005",
        "name": "data-pipeline",
        "platform": "github",
        "description": "ETL pipelines for analytics and reporting",
        "language": "Python",
        "default_branch": "develop",
        "last_commit_at": datetime.utcnow() - timedelta(days=1),
        "open_issues": 9,
        "open_prs": 4,
        "stars": 31,
        "contributors": 6,
        "activity": 55.0,
        "ci_status": "running",
        "health_score": 65.0,
        "vulnerabilities": 3,
    },
    {
        "id": "repo-006",
        "name": "mobile-app",
        "platform": "github",
        "description": "React Native mobile application",
        "language": "TypeScript",
        "default_branch": "main",
        "last_commit_at": datetime.utcnow() - timedelta(hours=12),
        "open_issues": 15,
        "open_prs": 5,
        "stars": 89,
        "contributors": 7,
        "activity": 78.0,
        "ci_status": "success",
        "health_score": 71.0,
        "vulnerabilities": 4,
    },
]


# ── Automation Rules ─────────────────────────────────────────────────────
RULES = [
    {
        "id": "rule-001",
        "name": "CI Failure Alert",
        "description": "Create a high-severity alert when any CI pipeline fails",
        "condition_type": "ci.failed",
        "action_type": "create_alert",
        "action_config": {
            "severity": "high",
            "category": "ci",
            "title": "🔴 CI Pipeline Failed",
            "message": "A CI pipeline has failed. Build is broken — merges are blocked.",
        },
        "is_active": True,
    },
    {
        "id": "rule-002",
        "name": "Deploy Failure Escalation",
        "description": "Escalate to critical when a deployment fails",
        "condition_type": "deploy.failed",
        "action_type": "escalate",
        "is_active": True,
    },
    {
        "id": "rule-003",
        "name": "Issue Tracker",
        "description": "Track new issues and update repo counters",
        "condition_type": "issue.created",
        "action_type": "create_alert",
        "action_config": {
            "severity": "low",
            "category": "system",
            "title": "New Issue Opened",
            "message": "A new issue has been created on this repository.",
        },
        "is_active": True,
    },
    {
        "id": "rule-004",
        "name": "PR Merge Notifier",
        "description": "Log PR merge activity for velocity tracking",
        "condition_type": "pr.merged",
        "action_type": "update_repo",
        "action_config": {"last_commit_at": None},  # Will be set dynamically
        "is_active": True,
    },
]


# ── Pipelines ────────────────────────────────────────────────────────────
PIPELINES = [
    {"repo_id": "repo-001", "name": "Build & Test", "status": "success", "duration": 124.5, "branch": "main", "trigger": "push"},
    {"repo_id": "repo-001", "name": "Build & Test", "status": "success", "duration": 118.2, "branch": "main", "trigger": "push"},
    {"repo_id": "repo-002", "name": "pytest", "status": "success", "duration": 87.3, "branch": "main", "trigger": "push"},
    {"repo_id": "repo-002", "name": "pytest", "status": "failed", "duration": 45.1, "branch": "feature/auth", "trigger": "pr"},
    {"repo_id": "repo-003", "name": "terraform plan", "status": "failed", "duration": 34.8, "branch": "main", "trigger": "push"},
    {"repo_id": "repo-003", "name": "terraform plan", "status": "failed", "duration": 28.0, "branch": "main", "trigger": "push"},
    {"repo_id": "repo-004", "name": "Go Build", "status": "success", "duration": 56.2, "branch": "main", "trigger": "push"},
    {"repo_id": "repo-005", "name": "ETL Tests", "status": "running", "duration": None, "branch": "develop", "trigger": "push"},
    {"repo_id": "repo-006", "name": "RN Build", "status": "success", "duration": 245.7, "branch": "main", "trigger": "push"},
    {"repo_id": "repo-006", "name": "E2E Tests", "status": "success", "duration": 312.4, "branch": "main", "trigger": "push"},
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
    {
        "title": "High memory usage detected",
        "message": "Auth service pod exceeding 85% memory threshold in production.",
        "severity": "high",
        "category": "performance",
        "repo_id": "repo-004",
    },
    {
        "title": "Dependency outdated: axios@0.21.0",
        "message": "Known security issue in axios < 0.21.1. Recommend upgrading.",
        "severity": "medium",
        "category": "security",
        "repo_id": "repo-006",
    },
    {
        "title": "Stale branch cleanup needed",
        "message": "12 branches older than 30 days detected. Consider cleanup.",
        "severity": "low",
        "category": "system",
        "repo_id": "repo-005",
    },
]


# ── Events ───────────────────────────────────────────────────────────────
EVENTS = [
    {"type": "ci.success", "repo_id": "repo-001", "source": "github", "metadata_": {"branch": "main", "commit": "a1b2c3d"}},
    {"type": "pr.opened", "repo_id": "repo-001", "source": "github", "metadata_": {"pr_number": 42, "author": "dev-alice"}},
    {"type": "ci.failed", "repo_id": "repo-003", "source": "gitlab", "metadata_": {"branch": "main", "error": "provider config invalid"}},
    {"type": "deploy.failed", "repo_id": "repo-003", "source": "system", "metadata_": {"environment": "production"}},
    {"type": "issue.created", "repo_id": "repo-004", "source": "github", "metadata_": {"issue_number": 15, "title": "Memory leak in auth handler"}},
    {"type": "pr.merged", "repo_id": "repo-002", "source": "github", "metadata_": {"pr_number": 78, "author": "dev-bob"}},
    {"type": "ci.success", "repo_id": "repo-006", "source": "github", "metadata_": {"branch": "main", "commit": "f4e5d6c"}},
    {"type": "repo.updated", "repo_id": "repo-005", "source": "system", "metadata_": {"field": "description"}},
]


async def seed():
    """Seed the database with sample data."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with session_factory() as session:
        print("🌱 Seeding repositories...")
        for data in REPOS:
            repo = Repo(**data)
            session.add(repo)
        await session.commit()
        print(f"   ✅ {len(REPOS)} repositories created")

        print("🌱 Seeding automation rules...")
        for data in RULES:
            rule = Rule(**data)
            session.add(rule)
        await session.commit()
        print(f"   ✅ {len(RULES)} rules created")

        print("🌱 Seeding pipelines...")
        for data in PIPELINES:
            pipeline = Pipeline(**data)
            session.add(pipeline)
        await session.commit()
        print(f"   ✅ {len(PIPELINES)} pipelines created")

        print("🌱 Seeding alerts...")
        for data in ALERTS:
            alert = Alert(**data)
            session.add(alert)
        await session.commit()
        print(f"   ✅ {len(ALERTS)} alerts created")

        print("🌱 Seeding events...")
        for data in EVENTS:
            event = Event(**data, processed=True)
            session.add(event)
        await session.commit()
        print(f"   ✅ {len(EVENTS)} events created")

    print("\n🎉 Seed complete! NexOps database is ready.")
    print("   Run: uvicorn app.main:app --reload --port 8000")


if __name__ == "__main__":
    asyncio.run(seed())
