"""
Migration: Add PagerDuty credential and webhook subscription columns to users table.
"""

import asyncio
import sys
from sqlalchemy import text
from app.core.database import engine


async def check_column_exists(column_name: str) -> bool:
    """Check if a column exists in the users table."""
    async with engine.begin() as conn:
        result = await conn.execute(text(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name='users' AND column_name='{column_name}';
        """))
        return result.fetchone() is not None


async def add_pagerduty_columns():
    """Add PagerDuty columns to users table if they don't exist."""
    print("=" * 60)
    print("  NexOps PagerDuty Integration Migration")
    print("=" * 60)

    columns_to_add = [
        ("pagerduty_access_token", "VARCHAR(500)"),
        ("pagerduty_webhook_secret", "VARCHAR(500)"),
        ("pagerduty_webhook_subscription_id", "VARCHAR(255)")
    ]

    async with engine.begin() as conn:
        for column_name, column_type in columns_to_add:
            exists = await check_column_exists(column_name)
            if exists:
                print(f"[OK] {column_name} column already exists")
                continue

            print(f"Adding {column_name} ({column_type}) column to users table...")
            try:
                await conn.execute(text(f"""
                    ALTER TABLE users
                    ADD COLUMN {column_name} {column_type};
                """))
                print(f"[OK] {column_name} column added")
            except Exception as e:
                print(f"[FAIL] Error adding column {column_name}: {e}")
                return False
        return True


async def main():
    try:
        success = await add_pagerduty_columns()
        if not success:
            sys.exit(1)
        print()
        print("Migration complete successfully.")
    except Exception as e:
        print(f"[FAIL] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
