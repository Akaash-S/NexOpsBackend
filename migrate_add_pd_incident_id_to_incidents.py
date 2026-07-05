"""
Database Migration: Add pd_incident_id column to incidents table.
Run once: python migrate_add_pd_incident_id_to_incidents.py
"""
import asyncio
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from app.core.database import engine


async def migrate():
    print("=" * 60)
    print("  Migration: Add pd_incident_id to incidents table")
    print("=" * 60)

    async with engine.begin() as conn:
        # 1. Check if column already exists
        check = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'incidents' AND column_name = 'pd_incident_id'
        """))
        if check.fetchone():
            print("  Column pd_incident_id already exists - skipping column creation.")
        else:
            await conn.execute(text("""
                ALTER TABLE incidents ADD COLUMN pd_incident_id VARCHAR(64)
            """))
            await conn.execute(text("""
                CREATE INDEX ix_incidents_pd_incident_id ON incidents (pd_incident_id)
            """))
            print("  [OK] Added pd_incident_id column + index to incidents table.")

        # 2. Backfill pd_incident_id for existing incidents from their triggering events
        # Use abs(epoch difference) < 600s (10 min window) to match incident to the event
        # that triggered it, regardless of whether root_cause_repo_id was later overwritten.
        backfill = await conn.execute(text("""
            UPDATE incidents inc
            SET pd_incident_id = ev.pd_incident_id
            FROM events ev
            WHERE ev.source = 'pagerduty'
              AND ev.pd_incident_id IS NOT NULL
              AND inc.pd_incident_id IS NULL
              AND abs(extract(epoch from (inc.created_at - ev.created_at))) < 600
        """))
        print(f"  [OK] Backfilled {backfill.rowcount} existing incidents with pd_incident_id from events.")

    print()
    print("  Migration complete. Restart the backend server.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())
