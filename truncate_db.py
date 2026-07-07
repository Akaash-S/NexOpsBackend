import asyncio
import sys
import os

# Add the current directory to sys.path so we can import 'app'
sys.path.append(os.getcwd())

from sqlalchemy import text
from app.core.database import engine

async def truncate_database():
    """
    Dynamically queries all user tables in the database schema and truncates them,
    preserving the schema without needing python model imports.
    """
    print("Connecting to database to discover tables...")
    
    try:
        async with engine.begin() as conn:
            # 1. Discover all tables in the public schema
            result = await conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """))
            tables = [row[0] for row in result.fetchall()]
            
            if not tables:
                print("No tables found in the public database schema.")
                return
                
            print(f"Discovered {len(tables)} tables to truncate: {', '.join(tables)}")
            
            # 2. Truncate all tables in a single transaction with CASCADE
            # In PostgreSQL, we can truncate multiple tables in a single command, which handles FK dependencies gracefully
            tables_str = ", ".join(tables)
            print(f"Truncating all tables...")
            await conn.execute(text(f"TRUNCATE TABLE {tables_str} CASCADE;"))
            
        print("\n--- Database truncated successfully. All tables are now empty. ---")
    except Exception as e:
        print(f"\nERROR: Failed to truncate database: {e}")

if __name__ == "__main__":
    if not os.path.exists("app"):
        print("Error: This script must be run from the backend root directory.")
    else:
        asyncio.run(truncate_database())
