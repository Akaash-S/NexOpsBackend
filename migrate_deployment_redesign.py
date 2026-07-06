"""
Database Migration: Redesign deployments table columns.
Adds risk_score and risk_basis, drops provider_id and version.
Run once: python migrate_deployment_redesign.py
"""

import asyncio
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from app.core.database import engine


async def migrate():
    print("=" * 60)
    print("  Migration: Redesign Deployments Table")
    print("=" * 60)

    async with engine.begin() as conn:
        # 1. Add risk_score
        check_score = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'deployments' AND column_name = 'risk_score'
        """))
        if check_score.fetchone():
            print("  Column risk_score already exists - skipping.")
        else:
            await conn.execute(text("""
                ALTER TABLE deployments ADD COLUMN risk_score FLOAT DEFAULT 0.0
            """))
            print("  [OK] Added risk_score column.")

        # 2. Add risk_basis
        check_basis = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'deployments' AND column_name = 'risk_basis'
        """))
        if check_basis.fetchone():
            print("  Column risk_basis already exists - skipping.")
        else:
            await conn.execute(text("""
                ALTER TABLE deployments ADD COLUMN risk_basis TEXT DEFAULT ''
            """))
            print("  [OK] Added risk_basis column.")

        # 3. Drop provider_id
        check_prov = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'deployments' AND column_name = 'provider_id'
        """))
        if check_prov.fetchone():
            await conn.execute(text("""
                ALTER TABLE deployments DROP COLUMN provider_id
            """))
            print("  [OK] Dropped provider_id column.")
        else:
            print("  Column provider_id already dropped or doesn't exist.")

        # 4. Drop version
        check_ver = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'deployments' AND column_name = 'version'
        """))
        if check_ver.fetchone():
            await conn.execute(text("""
                ALTER TABLE deployments DROP COLUMN version
            """))
            print("  [OK] Dropped version column.")
        else:
            print("  Column version already dropped or doesn't exist.")

    print()
    print("  Migration complete. Restart the backend server.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())
