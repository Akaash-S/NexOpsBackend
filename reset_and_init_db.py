"""
NexOps — Full Database Reset & Reinitialization
================================================
Drops ALL tables and recreates the schema fresh from SQLModel definitions.
This is the single source of truth for the database schema going forward;
individual migrate_*.py scripts are superseded by this consolidated init step.

SAFETY: This script will NOT run unless the CONFIRM_RESET environment variable
is set to 'yes'. This prevents accidental execution.

HOW TO RUN (choose one):
  Option A — Standalone Python script:
      export CONFIRM_RESET=yes
      python reset_and_init_db.py

  Option B — Via the temporary _internal HTTP endpoint (Render free tier):
      Set MIGRATION_SECRET env var on Render
      Deploy with _migrate.py registered
      curl -X POST https://.../api/v1/_internal/reset-db \
        -H "X-Migration-Secret: <secret>" \
        -H "X-Confirm-Reset: yes"

After reset, the old migrate_*.py scripts are no longer needed for new
environments — this script supersedes them.
"""

import asyncio
import os
import sys

from sqlalchemy import text
from app.core.database import engine
import app.models  # Ensures all models are imported and registered


PARTIAL_UNIQUE_INDEX_SQL = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_events_pd_event_id_not_null
    ON events (pd_event_id)
    WHERE pd_event_id IS NOT NULL
"""


async def get_table_list():
    """Return sorted list of all user tables (excluding SQLAlchemy internals)."""
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ))
        return [row[0] for row in r]


async def get_row_counts():
    """Return dict of table_name -> row_count for all user tables."""
    tables = await get_table_list()
    counts = {}
    async with engine.connect() as conn:
        for t in tables:
            r = await conn.execute(text(f"SELECT count(*) FROM {t}"))
            counts[t] = r.scalar()
    return counts


async def get_schema_columns(table_name):
    """Return list of column names for a table."""
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY ordinal_position",
            {"t": table_name}
        ))
        return [row[0] for row in r]


def get_expected_tables() -> list:
    """Return the list of table names expected from SQLModel definitions."""
    from sqlmodel import SQLModel
    metadata = SQLModel.metadata
    return sorted([t.name for t in metadata.sorted_tables])


def get_expected_columns(table_name: str) -> list:
    """Return the column names expected for a table from its SQLModel definition."""
    from sqlmodel import SQLModel
    metadata = SQLModel.metadata
    for t in metadata.sorted_tables:
        if t.name == table_name:
            return [c.name for c in t.columns]
    return []


async def drop_all_tables():
    """Drop all user tables with CASCADE."""
    async with engine.begin() as conn:
        # Disable FK checks temporarily for clean drop
        await conn.execute(text("SET session_replication_role = 'replica'"))
        tables = await get_table_list()
        for t in tables:
            await conn.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
            print(f"  DROPPED: {t}")
        await conn.execute(text("SET session_replication_role = 'origin'"))
    print(f"  Dropped {len(tables)} tables.")


async def create_all_tables():
    """Create all tables fresh from SQLModel metadata."""
    from sqlmodel import SQLModel
    import app.models  # Ensure all models are registered
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    created = await get_table_list()
    print(f"  Created {len(created)} tables: {', '.join(created)}")


async def add_partial_unique_index():
    """Add the partial unique index that SQLModel's field defs can't express."""
    async with engine.begin() as conn:
        await conn.execute(text(PARTIAL_UNIQUE_INDEX_SQL))
    print("  Created: uq_events_pd_event_id_not_null (partial unique index)")


async def verify_schema():
    """Compare expected vs actual schema — every model field must exist in DB."""
    expected = get_expected_tables()
    actual_tables = await get_table_list()
    
    all_ok = True
    for table in expected:
        if table not in actual_tables:
            print(f"  MISSING TABLE: {table}")
            all_ok = False
            continue
        expected_cols = get_expected_columns(table)
        actual_cols = await get_schema_columns(table)
        missing = [c for c in expected_cols if c not in actual_cols]
        if missing:
            print(f"  MISSING COLUMNS in {table}: {', '.join(missing)}")
            all_ok = False
        else:
            print(f"  OK: {table} ({len(actual_cols)} columns)")
    
    # Check for extra tables (not in models)
    extra = [t for t in actual_tables if t not in expected]
    if extra:
        print(f"  EXTRA TABLES (not in models): {', '.join(extra)}")
    
    # Verify the partial unique index
    async with engine.connect() as conn:
        idx = await conn.execute(text(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'events' AND indexname = 'uq_events_pd_event_id_not_null'"
        ))
        if idx.scalar():
            print("  OK: uq_events_pd_event_id_not_null index exists")
        else:
            print("  MISSING: uq_events_pd_event_id_not_null index")
            all_ok = False

    return all_ok


async def verify_empty():
    """Confirm all tables have 0 rows."""
    counts = await get_row_counts()
    non_empty = {k: v for k, v in counts.items() if v > 0}
    if non_empty:
        print(f"  NON-EMPTY TABLES: {non_empty}")
        return False
    else:
        print(f"  All tables are empty (0 rows)")
        return True


async def main():
    print("=" * 60)
    print("  NexOps — Full Database Reset & Reinitialization")
    print("=" * 60)
    print()

    # ── Safety check ────────────────────────────────────────────────
    confirm = os.environ.get("CONFIRM_RESET", "").strip().lower()
    if confirm != "yes":
        print("  SAFETY: CONFIRM_RESET=yes not set. Aborting.")
        print()
        print("  To proceed, set the environment variable:")
        print("    export CONFIRM_RESET=yes")
        print()
        sys.exit(1)

    # ── Phase 1: Record pre-reset state ─────────────────────────────
    print("--- Pre-reset state ---")
    counts = await get_row_counts()
    tables = await get_table_list()
    if not tables:
        print("  No tables found. Database may already be empty.")
    else:
        total_rows = 0
        for t in tables:
            c = counts.get(t, 0)
            total_rows += c
            print(f"  {t}: {c} rows")
        print(f"  TOTAL: {total_rows} rows across {len(tables)} tables")
    print()

    # ── Phase 2: Drop ──────────────────────────────────────────────
    print("--- Dropping all tables ---")
    await drop_all_tables()
    print()

    # ── Phase 3: Create ─────────────────────────────────────────────
    print("--- Creating tables from models ---")
    await create_all_tables()
    print()

    # ── Phase 4: Additional indexes ─────────────────────────────────
    print("--- Adding constraints not expressible in model fields ---")
    await add_partial_unique_index()
    print()

    # ── Phase 5: Verify ─────────────────────────────────────────────
    print("--- Schema verification ---")
    schema_ok = await verify_schema()
    print()
    print("--- Emptiness verification ---")
    empty_ok = await verify_empty()
    print()

    # ── Summary ─────────────────────────────────────────────────────
    print("=" * 60)
    if schema_ok and empty_ok:
        print("  RESET COMPLETE — Schema matches models, all tables empty.")
        print()
        print("  Next steps:")
        print("  1. Restart the backend server")
        print("  2. Users will be created on first Firebase login")
        print("  3. Reconnect GitHub and PagerDuty integrations")
        print("  4. Run initial repository sync")
        print("=" * 60)
    else:
        print("  RESET COMPLETED WITH ISSUES — see details above.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
