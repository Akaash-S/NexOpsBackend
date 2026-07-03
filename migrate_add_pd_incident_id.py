"""
Database Migration: Add pd_incident_id column to events table.
Run once: python migrate_add_pd_incident_id.py
"""
import asyncio
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from app.core.database import engine


async def migrate():
    print("=" * 60)
    print("  Migration: Add pd_incident_id to events table")
    print("=" * 60)

    async with engine.begin() as conn:
        # 1. Check if column already exists
        check = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'events' AND column_name = 'pd_incident_id'
        """))
        if check.fetchone():
            print("  Column pd_incident_id already exists - skipping column creation.")
        else:
            await conn.execute(text("""
                ALTER TABLE events ADD COLUMN pd_incident_id VARCHAR(64)
            """))
            await conn.execute(text("""
                CREATE INDEX ix_events_pd_incident_id ON events (pd_incident_id)
            """))
            print("  [OK] Added pd_incident_id column + index to events table.")

        # 2. Backfill pd_incident_id for existing PagerDuty events that have it in payload
        backfill = await conn.execute(text("""
            UPDATE events
            SET pd_incident_id = (payload #>> '{event,data,id}')
            WHERE source = 'pagerduty'
              AND pd_incident_id IS NULL
              AND payload IS NOT NULL
              AND payload #>> '{event,data,id}' IS NOT NULL
        """))
        print(f"  [OK] Backfilled {backfill.rowcount} existing PagerDuty events with pd_incident_id.")

    print()
    print("  Migration complete. Restart the backend server.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())
