"""
Read-only diagnostic endpoint — schema, row counts, and PagerDuty connection state.
No destructive capability. Remove once the current PagerDuty investigation is resolved.
"""
import os
from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text
from app.core.database import engine

router = APIRouter()
DIAG_SECRET = os.environ.get("DIAG_SECRET")


@router.get("/_internal/diag")
async def diagnostics(x_diag_secret: str = Header(None)):
    if not DIAG_SECRET or x_diag_secret != DIAG_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    async with engine.connect() as conn:
        columns = await conn.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE (table_name = 'events' AND column_name IN ('pd_event_id', 'pd_incident_id')) "
            "OR (table_name = 'users' AND column_name LIKE 'pagerduty%') "
            "OR (table_name = 'repos' AND column_name IN ('cluster_id', 'github_updated_at')) "
            "OR (table_name = 'deployments' AND column_name IN ('risk_score', 'risk_basis'))"
        ))
        columns_found = [f"{r[0]}.{r[1]}" for r in columns]

        counts = await conn.execute(text(
            "SELECT 'users' t, count(*) c FROM users "
            "UNION ALL SELECT 'repos', count(*) FROM repos "
            "UNION ALL SELECT 'events', count(*) FROM events "
            "UNION ALL SELECT 'incidents', count(*) FROM incidents "
            "UNION ALL SELECT 'alerts', count(*) FROM alerts "
            "UNION ALL SELECT 'deployments', count(*) FROM deployments"
        ))
        row_counts = {r[0]: r[1] for r in counts}

    return {
        "columns_found": columns_found,
        "row_counts": row_counts,
    }


@router.get("/_internal/diag/pagerduty")
async def pagerduty_diagnostics(x_diag_secret: str = Header(None)):
    if not DIAG_SECRET or x_diag_secret != DIAG_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT id, email, "
            "pagerduty_access_token IS NOT NULL AS has_token, "
            "pagerduty_webhook_secret IS NOT NULL AS has_secret, "
            "pagerduty_webhook_subscription_id "
            "FROM users"
        ))
        users = [
            {
                "id": r[0],
                "email": r[1],
                "has_token": r[2],
                "has_secret": r[3],
                "subscription_id": r[4],
            }
            for r in result
        ]

    return {"users": users}
