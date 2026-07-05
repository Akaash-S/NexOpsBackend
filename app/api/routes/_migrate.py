"""
Temporary endpoint: run pending database migrations against production.
Also provides POST /_internal/reset-db for full database reset (drop + re-create).
Remove this file after use (see NEXOPS_PRODUCTION_MIGRATION_FIX_REPORT.md step 6).
"""
import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from app.core.database import engine
from sqlmodel import SQLModel

# Force model registration so SQLModel.metadata knows all tables
import app.models  # noqa: F401

router = APIRouter(tags=["_internal"])

MIGRATION_SECRET = os.environ.get("MIGRATION_SECRET")

STATEMENTS = [
    # Migration 1: events.pd_event_id
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS pd_event_id VARCHAR(64)",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_events_pd_event_id_not_null
       ON events (pd_event_id) WHERE pd_event_id IS NOT NULL""",

    # Migration 2: events.pd_incident_id
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS pd_incident_id VARCHAR(64)",
    "CREATE INDEX IF NOT EXISTS ix_events_pd_incident_id ON events (pd_incident_id)",
    """UPDATE events
       SET pd_incident_id = (payload #>> '{event,data,id}')
       WHERE source = 'pagerduty'
         AND pd_incident_id IS NULL
         AND payload IS NOT NULL
         AND payload #>> '{event,data,id}' IS NOT NULL""",

    # Migration 3: users PagerDuty columns
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS pagerduty_access_token VARCHAR(500)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS pagerduty_webhook_secret VARCHAR(500)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS pagerduty_webhook_subscription_id VARCHAR(255)",

    # Migration 5: repos.github_updated_at
    "ALTER TABLE repos ADD COLUMN IF NOT EXISTS github_updated_at TIMESTAMP",

    # Migration 6: cloud_providers table
    """CREATE TABLE IF NOT EXISTS cloud_providers (
        id VARCHAR PRIMARY KEY,
        workspace_id VARCHAR NOT NULL,
        name VARCHAR(100) NOT NULL,
        type VARCHAR NOT NULL,
        access_token TEXT,
        secret_key TEXT,
        account_id VARCHAR,
        config JSON,
        status VARCHAR DEFAULT 'active',
        last_validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",

    # Migration 7: deployments.provider_id
    "ALTER TABLE deployments ADD COLUMN IF NOT EXISTS provider_id VARCHAR",
    "CREATE INDEX IF NOT EXISTS ix_deployments_provider_id ON deployments (provider_id)",

    # Migration 8: pipelines.logs
    "ALTER TABLE pipelines ADD COLUMN IF NOT EXISTS logs TEXT",
]


async def _run_single(stmt: str, label: str) -> str:
    """Run a single SQL statement in its own transaction, returning OK or FAILED."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text(stmt))
        return f"OK: {label}"
    except Exception as e:
        return f"FAILED: {label} -- {type(e).__name__}: {str(e)[:100]}"


async def _table_exists(name: str) -> bool:
    async with engine.connect() as conn:
        stmt = text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)")
        r = await conn.execute(stmt, {"t": name})
        return r.scalar()


@router.post("/_internal/migrate")
async def run_migrations(x_migration_secret: str = Header(None)):
    if not MIGRATION_SECRET or x_migration_secret != MIGRATION_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    results = []
    clusters_exists = await _table_exists("clusters")
    results.append(f"clusters table exists: {clusters_exists}")

    # Run each migration statement in its own transaction
    for stmt in STATEMENTS:
        label = stmt.strip()[:70]
        results.append(await _run_single(stmt, label))

    # cluster_id — requires pre-check for clusters table
    label = "repos.cluster_id"
    try:
        async with engine.begin() as conn:
            await conn.execute(text("ALTER TABLE repos ADD COLUMN IF NOT EXISTS cluster_id VARCHAR"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_repos_cluster_id ON repos(cluster_id)"))
            if clusters_exists:
                await conn.execute(text(
                    "ALTER TABLE repos ADD CONSTRAINT fk_repos_cluster_id "
                    "FOREIGN KEY (cluster_id) REFERENCES clusters(id)"
                ))
                results.append(f"OK: repos.cluster_id + FK")
            else:
                results.append(f"OK: repos.cluster_id (no FK - clusters table doesn't exist)")
    except Exception as e:
        results.append(f"FAILED: {label} -- {type(e).__name__}: {str(e)[:100]}")

    return {"status": "done", "results": results}


@router.get("/_internal/migrate/verify")
async def verify_migrations(x_migration_secret: str = Header(None)):
    if not MIGRATION_SECRET or x_migration_secret != MIGRATION_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE (table_name = 'events' AND column_name IN ('pd_event_id', 'pd_incident_id')) "
            "OR (table_name = 'users' AND column_name LIKE 'pagerduty%') "
            "OR (table_name = 'repos' AND column_name IN ('cluster_id', 'github_updated_at')) "
            "OR (table_name = 'deployments' AND column_name = 'provider_id')"
        ))
        columns_found = [f"{row[0]}.{row[1]}" for row in result]

        cp_check = await conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'cloud_providers')"
        ))
        cloud_providers_exists = cp_check.scalar()

    return {
        "columns_found": columns_found,
        "cloud_providers_exists": cloud_providers_exists,
    }


@router.post("/_internal/reset-db")
async def reset_database(
    x_migration_secret: str = Header(None),
    x_confirm_reset: str = Header(None),
):
    """DROP all tables, recreate from SQLModel definitions, add partial indexes."""
    if not MIGRATION_SECRET or x_migration_secret != MIGRATION_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    if x_confirm_reset != "yes":
        raise HTTPException(status_code=400, detail="Set X-Confirm-Reset: yes to confirm")

    import app.models  # noqa: F401 — ensure all models registered

    results = []
    errors = []

    # ── Pre-reset state ──
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ))
        tables_before = [row[0] for row in r]
    results.append(f"Tables before reset: {len(tables_before)}")

    # ── Drop all tables (CASCADE to handle FKs) ──
    async with engine.begin() as conn:
        await conn.execute(text("SET session_replication_role = 'replica'"))
        for t in tables_before:
            await conn.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
            results.append(f"  Dropped: {t}")
        await conn.execute(text("SET session_replication_role = 'origin'"))

    # ── Create all tables from models ──
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    results.append("Tables recreated from SQLModel metadata")

    # ── Partial unique index (can't express in model fields) ──
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_events_pd_event_id_not_null "
                "ON events (pd_event_id) WHERE pd_event_id IS NOT NULL"
            ))
        results.append("Created: uq_events_pd_event_id_not_null")
    except Exception as e:
        msg = f"FAILED partial unique index: {e}"
        results.append(msg)
        errors.append(msg)

    # ── Verify ──
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ))
        tables_after = [row[0] for row in r]
    results.append(f"Tables after reset: {len(tables_after)}")

    for t in sorted(tables_after):
        r = await conn.execute(text(f"SELECT count(*) FROM {t}"))
        count = r.scalar()
        results.append(f"  {t}: {count} rows")

    success = len(errors) == 0
    return {"status": "done" if success else "done_with_errors", "results": results, "errors": errors or None}
