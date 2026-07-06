import asyncio
from app.core.database import engine
from sqlmodel import SQLModel
# Import all models to ensure they are registered with SQLModel.metadata
from app.models.workspace import Workspace
from app.models.repo import Repo
from app.models.user import User
from app.models.event import Event
from app.models.pipeline import Pipeline
from app.models.rule import Rule
from app.models.alert import Alert
from app.models.team import Team
from app.models.cluster import Cluster
from app.models.dependency import Dependency
from app.models.incident import Incident
from app.models.deployment import Deployment
from app.models.workspace_member import WorkspaceMember
from app.models.invitation import Invitation

async def reset():
    print("Connecting to engine and dropping tables...")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        print("Creating tables...")
        await conn.run_sync(SQLModel.metadata.create_all)
    print("Database reset complete.")

if __name__ == "__main__":
    asyncio.run(reset())
