import asyncio
from sqlalchemy import text
from app.core.database import engine

async def migrate():
    async with engine.begin() as conn:
        print("Adding provider_id column to deployments table...")
        try:
            await conn.execute(text("ALTER TABLE deployments ADD COLUMN provider_id VARCHAR;"))
            await conn.execute(text("CREATE INDEX ix_deployments_provider_id ON deployments (provider_id);"))
            print("Migration successful!")
        except Exception as e:
            print(f"Migration failed or column already exists: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())
