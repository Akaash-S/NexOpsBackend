"""
Database Migration: Add pd_event_id column to events table.
Run once: python migrate_add_pd_event_id.py
"""

import asyncio
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from app.core.database import engine


async def migrate():
    print("=" * 60)
    print("  Migration: Add pd_event_id to events table")
    print("=" * 60)

    async with engine.begin() as conn:
        # 1. Check if column already exists
        check = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'events' AND column_name = 'pd_event_id'
        """))
        if check.fetchone():
            print("  Column pd_event_id already exists - skipping column creation.")
        else:
            await conn.execute(text("""
                ALTER TABLE events ADD COLUMN pd_event_id VARCHAR(64)
            """))
            print("  [OK] Added pd_event_id column to events table.")

        # 2. Create a partial unique index (only for non-NULL values)
        idx_check = await conn.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'events' AND indexname = 'uq_events_pd_event_id_not_null'
        """))
        if idx_check.fetchone():
            print("  Unique index already exists - skipping.")
        else:
            await conn.execute(text("""
                CREATE UNIQUE INDEX uq_events_pd_event_id_not_null
                ON events (pd_event_id)
                WHERE pd_event_id IS NOT NULL
            """))
            print("  [OK] Created partial unique index on pd_event_id (WHERE NOT NULL).")

    print()
    print("  Migration complete. Restart the backend server.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())
