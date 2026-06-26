"""
Migration: Add github_updated_at column to repos table.

This column stores the repo's last-updated timestamp from GitHub,
distinct from NexOps' own updated_at timestamp.
"""

import asyncio
import sys
from sqlalchemy import text
from app.core.database import engine


async def check_column_exists():
    """Check if github_updated_at column exists in repos table."""
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='repos' AND column_name='github_updated_at';
        """))
        return result.fetchone() is not None


async def add_github_updated_at_column():
    """Add github_updated_at column to repos table if it doesn't exist."""
    print("=" * 60)
    print("  NexOps Repo Metrics Migration")
    print("=" * 60)

    async with engine.begin() as conn:
        exists = await check_column_exists()
        if exists:
            print("[OK] github_updated_at column already exists")
            return True

        print("Adding github_updated_at column to repos table...")
        try:
            await conn.execute(text("""
                ALTER TABLE repos
                ADD COLUMN github_updated_at TIMESTAMP;
            """))
            print("[OK] github_updated_at column added")
            return True
        except Exception as e:
            print(f"[FAIL] Error adding column: {e}")
            return False


async def main():
    try:
        success = await add_github_updated_at_column()
        if not success:
            sys.exit(1)
        print()
        print("Migration complete. Restart the backend server for changes to take effect.")
    except Exception as e:
        print(f"[FAIL] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
