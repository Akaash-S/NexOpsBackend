import asyncio
import sys
import os

# Add the current directory to sys.path so we can import 'app'
sys.path.append(os.getcwd())

from sqlmodel import SQLModel
from app.core.database import engine

# Import all models to ensure they are registered with SQLModel.metadata
from app.models.repo import Repo
from app.models.alert import Alert
from app.models.event import Event
from app.models.pipeline import Pipeline
from app.models.rule import Rule
from app.models.team import Team
from app.models.user import User
from app.models.workspace import Workspace

async def clean_database():
    """
    Drops all tables and recreates them, effectively clearing all data.
    """
    print("Connecting to database and starting cleanup...")
    try:
        async with engine.begin() as conn:
            print("Dropping existing tables...")
            await conn.run_sync(SQLModel.metadata.drop_all)
            print("Recreating tables...")
            await conn.run_sync(SQLModel.metadata.create_all)
        print("--- Database cleaned successfully. ---")
    except Exception as e:
        print(f"ERROR: Failed to clean database: {e}")

if __name__ == "__main__":
    # Ensure we are in the backend directory
    if not os.path.exists("app"):
        print("Error: This script must be run from the backend root directory.")
    else:
        asyncio.run(clean_database())
