#!/usr/bin/env python3
"""Resolve all open and investigating incidents in the database."""
import asyncio, os, sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    import asyncpg
except ImportError:
    sys.exit("pip install asyncpg")

async def main():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL not set")

    conn = await asyncpg.connect(url)
    try:
        incs = await conn.fetch(
            "SELECT id, title, status, pd_incident_id FROM incidents WHERE status IN ('open', 'investigating')"
        )
        print(f"\nFound {len(incs)} active incidents to resolve:")
        for i in incs:
            print(f"  id={i['id']}  title={i['title']}  status={i['status']}  pd_incident_id={i['pd_incident_id']}")

        if incs:
            res = await conn.execute(
                "UPDATE incidents SET status = 'resolved', resolved_at = NOW(), updated_at = NOW() "
                "WHERE status IN ('open', 'investigating')"
            )
            print(f"\nDatabase update result: {res}")
            print("All active incidents successfully marked as RESOLVED.")
        else:
            print("\nNo open or investigating incidents found to resolve.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
