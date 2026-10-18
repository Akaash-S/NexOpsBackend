"""
Event Processing & Incident Idempotency Test Suite
==================================================
Verifies that replaying an operational event N times:
1. Sequentially: Replaying the exact same event N=10 times results in exactly 1 incident.
2. Concurrently: Racing N=10 parallel workers on the same failure event produces exactly 1 incident
   due to transaction-scoped PostgreSQL advisory locking.
3. Alert Grouping: Subsequents replays correctly group into the single incident without duplicate creation.
"""

import asyncio
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from sqlmodel import select

from app.core.database import async_session, init_db
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.models.event import Event
from app.models.incident import Incident
from app.services.automation_service import process_event


@pytest.mark.asyncio
async def test_sequential_event_replay_idempotency():
    """
    Assert that executing process_event N=10 times with the same event
    results in exactly 1 Incident created in the database.
    """
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-idem-seq-{uuid.uuid4().hex[:8]}"
        ws = Workspace(
            id=ws_id,
            name="Idempotency Seq WS",
            provider="github",
            status="connected",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(ws)
        await session.flush()

        usr_id = f"usr-idem-{uuid.uuid4().hex[:8]}"
        usr = User(
            id=usr_id,
            email=f"{usr_id}@test.com",
            full_name="Idem User",
            role="admin",
            workspace_id=ws_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(usr)
        await session.flush()

        repo_id = f"repo-idem-{uuid.uuid4().hex[:8]}"
        repo = Repo(
            id=repo_id,
            name="checkout-service",
            platform="github",
            default_branch="main",
            workspace_id=ws_id,
            user_id=usr_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(repo)
        await session.flush()

        evt_id = f"evt-idem-seq-{uuid.uuid4().hex[:8]}"
        event = Event(
            id=evt_id,
            workspace_id=ws_id,
            repo_id=repo_id,
            type="ci.failed",
            source="github",
            severity="critical",
            message="Build #42 failed on main branch",
            payload={"commit": "abc1234", "branch": "main"},
            created_at=datetime.now(timezone.utc)
        )
        session.add(event)
        await session.commit()

        # Replay event N = 10 times sequentially
        N = 10
        incident_ids = []
        for i in range(N):
            async with async_session() as replay_session:
                await replay_session.execute(text("RESET ROLE;"))
                await replay_session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))
                db_event = await replay_session.get(Event, evt_id)
                res = await process_event(replay_session, db_event)
                await replay_session.commit()
                incident_ids.append(res.get("incident_id"))

        # Every replay must point to the identical incident ID
        assert len(incident_ids) == N
        assert len(set(incident_ids)) == 1, f"Expected 1 unique incident ID, got: {set(incident_ids)}"

        # Query database to confirm exactly 1 incident exists for this workspace and repo
        async with async_session() as verify_session:
            await verify_session.execute(text("RESET ROLE;"))
            await verify_session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))
            incidents = (await verify_session.execute(
                select(Incident).where(
                    Incident.workspace_id == ws_id,
                    Incident.root_cause_repo_id == repo_id
                )
            )).scalars().all()

            assert len(incidents) == 1, f"Expected exactly 1 incident in DB, found {len(incidents)}"
            assert incidents[0].id == incident_ids[0]
            assert incidents[0].status == "open"
            assert incidents[0].severity == "critical"


@pytest.mark.asyncio
async def test_concurrent_event_replay_idempotency():
    """
    Assert that racing N=10 parallel workers executing process_event concurrently
    for the exact same event results in exactly 1 Incident created in the database.
    """
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-idem-conc-{uuid.uuid4().hex[:8]}"
        ws = Workspace(
            id=ws_id,
            name="Idempotency Conc WS",
            provider="github",
            status="connected",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(ws)
        await session.flush()

        usr_id = f"usr-conc-{uuid.uuid4().hex[:8]}"
        usr = User(
            id=usr_id,
            email=f"{usr_id}@test.com",
            full_name="Conc User",
            role="admin",
            workspace_id=ws_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(usr)
        await session.flush()

        repo_id = f"repo-conc-{uuid.uuid4().hex[:8]}"
        repo = Repo(
            id=repo_id,
            name="auth-api",
            platform="github",
            default_branch="main",
            workspace_id=ws_id,
            user_id=usr_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(repo)
        await session.flush()

        evt_id = f"evt-idem-conc-{uuid.uuid4().hex[:8]}"
        event = Event(
            id=evt_id,
            workspace_id=ws_id,
            repo_id=repo_id,
            type="deploy.failed",
            source="github",
            severity="critical",
            message="Production deployment canary failure",
            payload={"deployment_id": "dep-99", "env": "production"},
            created_at=datetime.now(timezone.utc)
        )
        session.add(event)
        await session.commit()

    async def worker_task():
        async with async_session() as task_session:
            await task_session.execute(text("RESET ROLE;"))
            await task_session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))
            db_event = await task_session.get(Event, evt_id)
            result = await process_event(task_session, db_event)
            await task_session.commit()
            return result.get("incident_id")

    # Launch N=10 concurrent workers simulating simultaneous webhook delivery
    N = 10
    tasks = [worker_task() for _ in range(N)]
    returned_incident_ids = await asyncio.gather(*tasks)

    # All parallel workers must return the identical incident ID
    assert len(returned_incident_ids) == N
    unique_ids = set(returned_incident_ids)
    assert len(unique_ids) == 1, f"Concurrent workers returned diverging incident IDs: {unique_ids}"

    # Query DB to assert exactly 1 incident exists
    async with async_session() as verify_session:
        await verify_session.execute(text("RESET ROLE;"))
        await verify_session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))
        incidents = (await verify_session.execute(
            select(Incident).where(
                Incident.workspace_id == ws_id,
                Incident.root_cause_repo_id == repo_id
            )
        )).scalars().all()

        assert len(incidents) == 1, f"Expected exactly 1 incident under concurrency, found {len(incidents)}"
        assert incidents[0].id == returned_incident_ids[0]
