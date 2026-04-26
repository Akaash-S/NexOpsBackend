import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.models.cloud_provider import CloudProvider # Ensure it's imported to register with SQLModel

async def migrate():
    print("Running migration: Creating 'cloud_providers' table...")
    async with engine.begin() as conn:
        try:
            # Using raw SQL for safety and cross-db compatibility
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cloud_providers (
                    id VARCHAR PRIMARY KEY,
                    workspace_id VARCHAR NOT NULL,
                    name VARCHAR(100) NOT NULL,
                    type VARCHAR NOT NULL,
                    access_token TEXT,
                    secret_key TEXT,
                    account_id VARCHAR,
                    config JSON,
                    status VARCHAR DEFAULT 'active',
                    last_validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """))
            print("Successfully created 'cloud_providers' table.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())
