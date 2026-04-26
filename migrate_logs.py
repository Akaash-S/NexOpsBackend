import asyncio
from sqlalchemy import text
from app.core.database import engine

async def migrate():
    print("Running migration: Adding 'logs' column to 'pipelines' table...")
    async with engine.begin() as conn:
        try:
            # Check if column exists first (PostgreSQL specific check)
            check_sql = text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='pipelines' AND column_name='logs';
            """)
            result = await conn.execute(check_sql)
            if not result.fetchone():
                await conn.execute(text("ALTER TABLE pipelines ADD COLUMN logs TEXT;"))
                print("Successfully added 'logs' column.")
            else:
                print("Column 'logs' already exists.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    asyncio.run(migrate())
