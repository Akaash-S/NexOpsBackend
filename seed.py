"""
NexOps Seed Script (Aligned with Refactored Models)
Populates the database with realistic sample data.
"""

import sys
import os
from datetime import datetime, timedelta
from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

# Models
from app.models.repo import Repo
from app.models.event import Event
from app.models.alert import Alert
from app.models.user import User
from app.models.dependency import Dependency
from app.models.incident import Incident
from app.models.deployment import Deployment

async_database_url = settings.async_database_url
engine = create_async_engine(async_database_url, echo=False)
session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

USERS = [
  {
    "full_name": "Akaash S",
    "email": "akaash@nexops.io",
    "role": "admin",
    "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=Akaash"
  },
  {
    "full_name": "Sarah Chen",
    "email": "sarah@nexops.io",
    "role": "lead",
    "avatar_url": "https://api.dicebear.com/7.x/avataaars/svg?seed=Sarah"
  }
]

REPOS = [
  {
    "id": "repo-001",
    "workspace_id": "ws-1",
    "cluster_id": "cluster-2",
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
    "health_score": 92.0
  },
  {
    "id": "repo-002",
    "workspace_id": "ws-1",
    "cluster_id": "cluster-1",
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
    "health_score": 88.0
  },
  {
    "id": "repo-003",
    "workspace_id": "ws-2",
    "cluster_id": "cluster-1",
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
    "vulnerabilities": 5
  }
]

ALERTS = [
  {
    "title": "Critical vulnerability in lodash@4.17.20",
    "message": "CVE-2021-23337: Prototype pollution in lodash. Upgrade to 4.17.21+.",
    "severity": "critical",
    "category": "security",
    "repo_id": "repo-003"
  },
  {
    "title": "CI Pipeline Failed \u2014 infra-terraform",
    "message": "Terraform plan failed due to invalid provider configuration.",
    "severity": "high",
    "category": "ci",
    "repo_id": "repo-003"
  }
]

EVENTS = [
  {
    "type": "ci.failed",
    "repo_id": "repo-003",
    "source": "gitlab",
    "message": "CI Pipeline Failed: infra-terraform",
    "severity": "error",
    "payload": {
      "branch": "main",
      "error": "provider config invalid"
    }
  }
]

DEPENDENCIES = [
  {
    "source_repo_id": "repo-001",
    "target_repo_id": "repo-002",
    "type": "api",
    "label": "calls api"
  },
  {
    "source_repo_id": "repo-002",
    "target_repo_id": "repo-003",
    "type": "hard",
    "label": "requires infra"
  }
]

INCIDENTS = [
  {
    "id": "inc-001",
    "cluster_id": "cluster-1",
    "title": "Systemic API Degradation",
    "severity": "high",
    "status": "investigating",
    "root_cause_repo_id": "repo-003",
    "impact_summary": "Infra failure in repo-003 is causing cascade failures in nexops-api and frontend.",
    "started_at": datetime.utcnow() - timedelta(minutes=15)
  }
]

DEPLOYMENTS = [
  {
    "repo_id": "repo-001",
    "version": "v1.2.0",
    "environment": "production",
    "status": "success",
    "deployed_at": datetime.utcnow() - timedelta(hours=5)
  },
  {
    "repo_id": "repo-002",
    "version": "v1.0.4",
    "environment": "production",
    "status": "failed",
    "deployed_at": datetime.utcnow() - timedelta(minutes=15)
  }
]

async def seed(user_id: str = None):
    print("Starting database seed process...")
    async with engine.begin() as conn:
        for table in [
            'candidate_causes', 'deployments', 'incidents', 'dependencies', 
            'alerts', 'events', 'repos', 'users', 'pipelines', 
            'rules', 'workspace_members', 'invitations', 'teams', 
            'clusters', 'workspaces'
        ]:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE;"))
        await conn.run_sync(SQLModel.metadata.create_all)
        
    async with session_factory() as session:
        print("Seeding Users...")
        for data in USERS:
            session.add(User(**data))
        if user_id:
            # Check if user already in database, otherwise add it
            from sqlmodel import select
            user_exists = await session.execute(select(User).where(User.id == user_id))
            if not user_exists.scalars().first():
                session.add(User(
                    id=user_id,
                    email="test-pd-verify@nexops.local",
                    full_name="Test Verification User",
                    role="member"
                ))
        await session.commit()
        
        print("Seeding Repositories...")
        for data in REPOS:
            repo_data = {**data}
            if user_id:
                repo_data["user_id"] = user_id
            session.add(Repo(**repo_data))
        await session.commit()
        
        print("Seeding Alerts...")
        for data in ALERTS:
            session.add(Alert(**data))
        await session.commit()
        
        print("Seeding Events...")
        for data in EVENTS:
            session.add(Event(**data))
        await session.commit()
        
        print("Seeding Dependencies...")
        for data in DEPENDENCIES:
            session.add(Dependency(**data))
        await session.commit()
        
        print("Seeding Incidents...")
        for data in INCIDENTS:
            session.add(Incident(**data))
        await session.commit()
        
        print("Seeding Deployments...")
        for data in DEPLOYMENTS:
            session.add(Deployment(**data))
        await session.commit()
        
    print("\nSeed complete! NexOps backend is fully aligned and ready.")

if __name__ == "__main__":
    import asyncio
    asyncio.run(seed())
