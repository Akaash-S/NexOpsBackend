"""
Database Migration: Add preferences column to users table
Run this script once to add the missing preferences column.
"""

import asyncio
from sqlalchemy import text
from app.core.database import engine


async def add_preferences_column():
    """Add preferences column to users table if it doesn't exist."""
    
    print("=" * 60)
    print("  Database Migration: Adding preferences to users table")
    print("=" * 60)
    print()
    
    async with engine.begin() as conn:
        # Check if column exists
        check_sql = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='users' AND column_name='preferences';
        """
        
        result = await conn.execute(text(check_sql))
        exists = result.fetchone()
        
        if exists:
            print("[OK] preferences column already exists in users table")
            print()
            return
        
        print("Adding preferences column to users table...")
        
        # Add the column
        alter_sql = """
        ALTER TABLE users 
        ADD COLUMN preferences JSONB DEFAULT '{}'::jsonb;
        """
        
        await conn.execute(text(alter_sql))
        print("[OK] preferences column added")
        
        print()
        print("=" * 60)
        print("  [OK] Migration completed successfully!")
        print("=" * 60)
        print()


if __name__ == "__main__":
    asyncio.run(add_preferences_column())