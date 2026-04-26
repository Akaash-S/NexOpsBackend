import asyncio
import uuid
from datetime import datetime
from sqlmodel import select
from app.core.database import engine, AsyncSession
from app.models.event import Event
from app.models.repo import Repo
from app.models.cluster import Cluster
from app.models.workspace import Workspace
from app.models.dependency import Dependency
from app.models.incident import Incident
from app.models.event import Event
from app.models.pipeline import Pipeline
from app.models.alert import Alert
from app.models.rule import Rule
from app.models.team import Team
from app.models.user import User
from app.services.automation_service import process_event

async def simulate():
    print("Starting Systemic Failure Simulation...")
    
    async with AsyncSession(engine, expire_on_commit=False) as session:
        # 1. Identify the root cause repo (infra-terraform)
        result = await session.execute(select(Repo).where(Repo.name == "infra-terraform"))
        root_repo = result.scalar_one_or_none()
        
        if not root_repo:
            print("Error: 'infra-terraform' repo not found. Please run seed.py first.")
            return

        print(f"Root Cause identified: {root_repo.name} ({root_repo.id})")
        print(f"Current Health: {root_repo.health_score}%")

        # 2. Create a 'ci.failed' event for the root repo
        event = Event(
            id=str(uuid.uuid4()),
            type="ci.failed",
            repo_id=root_repo.id,
            severity="critical",
            message="Critical infrastructure failure detected in Terraform plan. Network partitions likely.",
            payload={"pipeline_id": "pip-999", "error": "Provider Auth Failure"},
            created_at=datetime.utcnow()
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        
        print(f"Event created: {event.type} for {root_repo.name}")
        print("Processing event through Intelligence Engine...")

        # 3. Process the event
        # This will trigger propagation, cluster sync, and incident creation
        actions = await process_event(session, event)
        
        print("\nSimulation Complete!")
        print(f"Impacted Repos: {actions.get('impacted_repos', 0)}")
        print(f"Incident Created: {actions.get('incident_id')}")
        print("\nCheck your dashboard to see the 'Evidence Chain' and updated Cluster Health!")

if __name__ == "__main__":
    asyncio.run(simulate())
