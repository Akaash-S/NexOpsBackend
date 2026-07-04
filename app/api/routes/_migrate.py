"""
Temporary endpoint: run pending database migrations against production.
Remove this file after use (see NEXOPS_PRODUCTION_MIGRATION_FIX_REPORT.md step 6).
"""
import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from app.core.database import engine

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
