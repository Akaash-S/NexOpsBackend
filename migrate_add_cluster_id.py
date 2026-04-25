"""
Database Migration: Add cluster_id column to repos table
Run this script once to add the missing cluster_id column.
"""

import asyncio
from sqlalchemy import text
from app.core.database import engine


async def add_cluster_id_column():
    """Add cluster_id column to repos table if it doesn't exist."""
    
    print("=" * 60)
    print("  Database Migration: Adding cluster_id to repos table")
    print("=" * 60)
    print()
    
    async with engine.begin() as conn:
        # Check if column exists
        check_sql = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='repos' AND column_name='cluster_id';
        """
        
        result = await conn.execute(text(check_sql))
        exists = result.fetchone()
        
        if exists:
            print("✓ cluster_id column already exists in repos table")
            print()
            return
        
        print("Adding cluster_id column to repos table...")
        
        # Add the column
        alter_sql = """
        ALTER TABLE repos 
        ADD COLUMN cluster_id VARCHAR;
        """
        
        await conn.execute(text(alter_sql))
        print("✓ cluster_id column added")
        
        # Add foreign key constraint
        fk_sql = """
        ALTER TABLE repos 
        ADD CONSTRAINT fk_repos_cluster_id 
        FOREIGN KEY (cluster_id) REFERENCES clusters(id);
        """
        
        try:
            await conn.execute(text(fk_sql))
            print("✓ Foreign key constraint added")
        except Exception as e:
            print(f"⚠ Foreign key constraint skipped (may already exist): {e}")
        
        # Add index for performance
        index_sql = """
        CREATE INDEX IF NOT EXISTS idx_repos_cluster_id ON repos(cluster_id);
        """
        
        await conn.execute(text(index_sql))
        print("✓ Index added on cluster_id")
        
        print()
        print("=" * 60)
        print("  ✅ Migration completed successfully!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("1. Restart your backend server")
        print("2. The cluster_id column is now available")
        print()


if __name__ == "__main__":
    asyncio.run(add_cluster_id_column())
