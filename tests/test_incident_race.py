import asyncio
import uuid
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest
from sqlalchemy import text, select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.models.incident import Incident
from app.models.candidate_cause import CandidateCause
from app.models.alert import Alert
from app.models.event import Event
from app.services.incident_service import get_or_create_incident


@pytest.fixture(autouse=True)
def localhost_guard():
    """Safety guard: verify resolved database host is strictly localhost."""
    parsed = urlparse(str(settings.DATABASE_URL))
    host = parsed.hostname
    ip = socket.gethostbyname(host)
    if host not in ("localhost", "127.0.0.1") or not ip.startswith("127."):
        pytest.fail(f"Safety violation: non-local DB host detected: {host} ({ip})")


@pytest.fixture
def engine():
    eng = create_async_engine(str(settings.DATABASE_URL), poolclass=NullPool)
    yield eng


@pytest.fixture
def session_maker(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_test_session(session_maker) -> AsyncSession:
    """Helper to acquire a session with RLS bypass enabled for testing fixtures."""
    session = session_maker()
    await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))
    return session


async def create_fixture_workspace_and_repo(session_maker):
    session = await get_test_session(session_maker)
    suffix = uuid.uuid4().hex[:8]
    ws = Workspace(
        id=f"ws-race-{suffix}",
        name=f"Race Test Workspace {suffix}",
        color="blue",
        provider="github",
        status="connected",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    user = User(
        id=f"usr-race-{suffix}",
        email=f"usr-race-{suffix}@test.local",
        full_name="Race Test User",
        role="admin",
        workspace_id=ws.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    repo = Repo(
        id=f"repo-race-{suffix}",
        name=f"service-race-{suffix}",
        platform="github",
        default_branch="main",
        workspace_id=ws.id,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(ws)
    await session.flush()
    session.add(user)
    await session.flush()
    session.add(repo)
    await session.flush()
    await session.commit()
    await session.close()
    return ws, user, repo


async def cleanup_fixture(session_maker, ws_id: str):
    session = await get_test_session(session_maker)
    try:
        # Delete related tables in reverse foreign key order
        await session.execute(
            delete(CandidateCause).where(
                CandidateCause.incident_id.in_(
                    select(Incident.id).where(Incident.workspace_id == ws_id)
                )
            )
        )
        await session.execute(delete(Alert).where(Alert.workspace_id == ws_id))
        await session.execute(delete(Event).where(Event.workspace_id == ws_id))
        await session.execute(delete(Incident).where(Incident.workspace_id == ws_id))
        await session.execute(delete(Repo).where(Repo.workspace_id == ws_id))
        await session.execute(delete(User).where(User.workspace_id == ws_id))
        await session.execute(delete(Workspace).where(Workspace.id == ws_id))
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_statistical_duplicate_incident_race(session_maker):
    """
    Statistical test: 20 concurrent triggers for one repo in one workspace,
    repeated 5 times with fresh fixtures each time.
    Expected with advisory lock: exactly 1 open incident created every time.
    """
    N = 20
    REPEATS = 5
    results = []

    for rep in range(REPEATS):
        ws, user, repo = await create_fixture_workspace_and_repo(session_maker)
        try:
            async def trigger_call(idx: int):
                call_session = await get_test_session(session_maker)
                try:
                    inc = await get_or_create_incident(
                        session=call_session,
                        repo_id=repo.id,
                        severity="high",
                        title=f"Statistical trigger rep={rep} idx={idx}",
                        impacted_repos=[]
                    )
                    await call_session.commit()
                    return inc.id
                finally:
                    await call_session.close()

            tasks = [asyncio.create_task(trigger_call(i)) for i in range(N)]
            incident_ids = await asyncio.gather(*tasks)

            # Check distinct open incident rows in DB for this repo
            verify_session = await get_test_session(session_maker)
            try:
                res = await verify_session.execute(
                    select(Incident).where(
                        Incident.root_cause_repo_id == repo.id,
                        Incident.status == "open"
                    )
                )
                open_incidents = res.scalars().all()
                results.append(len(open_incidents))
                assert len(open_incidents) == 1, (
                    f"Repetition {rep + 1}/{REPEATS}: expected 1 open incident, got {len(open_incidents)}."
                )
            finally:
                await verify_session.close()
        finally:
            await cleanup_fixture(session_maker, ws.id)

    assert results == [1] * REPEATS, f"Statistical distribution failed: {results}"


@pytest.mark.asyncio
async def test_deterministic_interleaving_duplicate_incident_race(session_maker, engine):
    """
    Deterministic test: force interleaving where caller 1 completes its existence SELECT (none found),
    and waits until caller 2 also executes its SELECT (or blocks on the lock).
    Without the advisory lock: produces 2 incidents (test fails).
    With the advisory lock: caller 2 blocks on the lock before SELECT, caller 1 proceeds, commits,
    then caller 2 unblocks, finds the incident, and returns 1 incident (test passes).
    """
    ws, user, repo = await create_fixture_workspace_and_repo(session_maker)
    try:
        c1_select_done = asyncio.Event()
        c2_select_done = asyncio.Event()

        async def caller1():
            s1 = await get_test_session(session_maker)
            orig_execute = s1.execute

            async def wrapped_execute(statement, *args, **kwargs):
                result = await orig_execute(statement, *args, **kwargs)
                stmt_str = str(statement)
                if "FROM incidents" in stmt_str and "status = :status_1" in stmt_str:
                    c1_select_done.set()
                    # Wait for either caller 2 to complete SELECT (if no lock)
                    # or for caller 2 to block on the advisory lock in Postgres (if lock present)
                    for _ in range(50):
                        if c2_select_done.is_set():
                            break
                        check_session = await get_test_session(session_maker)
                        try:
                            lock_res = await check_session.execute(
                                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
                            )
                            if lock_res.scalar() > 0:
                                break
                        finally:
                            await check_session.close()
                        await asyncio.sleep(0.01)
                return result

            s1.execute = wrapped_execute
            try:
                inc1 = await get_or_create_incident(
                    session=s1,
                    repo_id=repo.id,
                    severity="high",
                    title="Deterministic Alert 1",
                    impacted_repos=[]
                )
                await s1.commit()
                return inc1.id
            finally:
                await s1.close()

        async def caller2():
            # Wait for caller 1 to start and reach its check
            await c1_select_done.wait()
            s2 = await get_test_session(session_maker)
            orig_execute = s2.execute

            async def wrapped_execute(statement, *args, **kwargs):
                result = await orig_execute(statement, *args, **kwargs)
                stmt_str = str(statement)
                if "FROM incidents" in stmt_str and "status = :status_1" in stmt_str:
                    c2_select_done.set()
                return result

            s2.execute = wrapped_execute
            try:
                inc2 = await get_or_create_incident(
                    session=s2,
                    repo_id=repo.id,
                    severity="high",
                    title="Deterministic Alert 2",
                    impacted_repos=[]
                )
                await s2.commit()
                return inc2.id
            finally:
                await s2.close()

        res1, res2 = await asyncio.gather(caller1(), caller2())

        verify_session = await get_test_session(session_maker)
        try:
            open_res = await verify_session.execute(
                select(Incident).where(
                    Incident.root_cause_repo_id == repo.id,
                    Incident.status == "open"
                )
            )
            open_incidents = open_res.scalars().all()
            assert len(open_incidents) == 1, (
                f"Deterministic race produced {len(open_incidents)} distinct open incidents! "
                f"Incident IDs: {[i.id for i in open_incidents]}"
            )
            assert res1 == res2 or res2 == open_incidents[0].id
        finally:
            await verify_session.close()
    finally:
        await cleanup_fixture(session_maker, ws.id)


@pytest.mark.asyncio
async def test_different_repos_do_not_block_each_other(session_maker):
    """
    Two concurrent triggers for two different repos in one workspace both create their own incident,
    and the second does not wait on the first.
    Verified via asyncio.Event: caller 1 holds its transaction open while caller 2 completes immediately.
    """
    ws, user, repo1 = await create_fixture_workspace_and_repo(session_maker)
    session = await get_test_session(session_maker)
    suffix2 = uuid.uuid4().hex[:8]
    repo2 = Repo(
        id=f"repo-race2-{suffix2}",
        name=f"service-race2-{suffix2}",
        platform="github",
        default_branch="main",
        workspace_id=ws.id,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    session.add(repo2)
    await session.commit()
    await session.close()

    try:
        c1_holding = asyncio.Event()
        c2_finished = asyncio.Event()
        can_c1_finish = asyncio.Event()

        async def caller1():
            s1 = await get_test_session(session_maker)
            try:
                inc1 = await get_or_create_incident(
                    session=s1,
                    repo_id=repo1.id,
                    severity="high",
                    title="Repo 1 Alert"
                )
                c1_holding.set()
                # Hold lock until caller 2 signals it has finished
                await asyncio.wait_for(can_c1_finish.wait(), timeout=5.0)
                await s1.commit()
                return inc1.id
            finally:
                await s1.close()

        async def caller2():
            # Wait until caller 1 has acquired its lock and is holding
            await c1_holding.wait()
            s2 = await get_test_session(session_maker)
            try:
                # Repo 2 must NOT block on Repo 1's lock
                inc2 = await get_or_create_incident(
                    session=s2,
                    repo_id=repo2.id,
                    severity="high",
                    title="Repo 2 Alert"
                )
                await s2.commit()
                c2_finished.set()
                can_c1_finish.set()
                return inc2.id
            finally:
                await s2.close()

        res1, res2 = await asyncio.gather(caller1(), caller2())
        assert res1 != res2
        assert c2_finished.is_set()

        verify_session = await get_test_session(session_maker)
        try:
            r1_inc = await verify_session.execute(
                select(Incident).where(Incident.root_cause_repo_id == repo1.id)
            )
            r2_inc = await verify_session.execute(
                select(Incident).where(Incident.root_cause_repo_id == repo2.id)
            )
            assert len(r1_inc.scalars().all()) == 1
            assert len(r2_inc.scalars().all()) == 1
        finally:
            await verify_session.close()
    finally:
        await cleanup_fixture(session_maker, ws.id)


@pytest.mark.asyncio
async def test_window_semantics_preserved(session_maker):
    """
    A trigger more than 30 minutes after an open incident still creates a new incident.
    """
    ws, user, repo = await create_fixture_workspace_and_repo(session_maker)
    try:
        # Create an existing incident with created_at 35 minutes ago
        s1 = await get_test_session(session_maker)
        try:
            old_time = datetime.now(timezone.utc) - timedelta(minutes=35)
            old_inc = Incident(
                title="Older Incident",
                severity="high",
                status="open",
                root_cause_repo_id=repo.id,
                workspace_id=ws.id,
                created_at=old_time,
                started_at=old_time
            )
            s1.add(old_inc)
            await s1.commit()
            old_id = old_inc.id
        finally:
            await s1.close()

        # Trigger new alert now (> 30 mins window)
        s2 = await get_test_session(session_maker)
        try:
            new_inc = await get_or_create_incident(
                session=s2,
                repo_id=repo.id,
                severity="high",
                title="New Window Alert"
            )
            await s2.commit()
            new_id = new_inc.id
        finally:
            await s2.close()

        assert new_id != old_id

        verify_session = await get_test_session(session_maker)
        try:
            all_inc = await verify_session.execute(
                select(Incident).where(Incident.root_cause_repo_id == repo.id)
            )
            incidents = all_inc.scalars().all()
            assert len(incidents) == 2
        finally:
            await verify_session.close()
    finally:
        await cleanup_fixture(session_maker, ws.id)


@pytest.mark.asyncio
async def test_idempotency_of_pd_event_id_path(session_maker):
    """
    Idempotency of the existing pd_event_id path:
    The same pd_event_id delivered twice yields one incident.
    """
    ws, user, repo = await create_fixture_workspace_and_repo(session_maker)
    try:
        pd_id = f"pd-incident-{uuid.uuid4().hex[:8]}"
        s1 = await get_test_session(session_maker)
        try:
            inc1 = await get_or_create_incident(
                session=s1,
                repo_id=repo.id,
                severity="critical",
                title="PagerDuty Trigger 1",
                pd_incident_id=pd_id
            )
            await s1.commit()
            id1 = inc1.id
        finally:
            await s1.close()

        # Second delivery with same pd_incident_id
        s2 = await get_test_session(session_maker)
        try:
            inc2 = await get_or_create_incident(
                session=s2,
                repo_id=repo.id,
                severity="critical",
                title="PagerDuty Trigger 2",
                pd_incident_id=pd_id
            )
            await s2.commit()
            id2 = inc2.id
        finally:
            await s2.close()

        assert id1 == id2

        verify_session = await get_test_session(session_maker)
        try:
            all_inc = await verify_session.execute(
                select(Incident).where(Incident.root_cause_repo_id == repo.id)
            )
            incidents = all_inc.scalars().all()
            assert len(incidents) == 1
            assert incidents[0].pd_incident_id == pd_id
        finally:
            await verify_session.close()
    finally:
        await cleanup_fixture(session_maker, ws.id)
