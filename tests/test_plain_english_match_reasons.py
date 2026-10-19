"""
Plain-English Match Reasons Test Suite (TASK-02)
================================================
Comprehensive verification that every correlation score factor emits deterministic,
plain-English explanatory sentences completely devoid of internal arithmetic,
raw weights, signed numbers (+35.0), hop-count parameters (1 hop away), or fraction scores (15/100).
"""

import re
import uuid
import json
import pytest
from datetime import datetime, timedelta
from urllib.parse import urlparse
from sqlalchemy import text
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session, init_db
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.models.event import Event
from app.models.incident import Incident
from app.models.candidate_cause import CandidateCause
from app.models.candidate_cause_feedback_log import CandidateCauseFeedbackLog
from app.models.dependency import Dependency
from app.services.incident_service import correlate_incident_causes
from app.api.routes.incidents import serialize_candidate_cause


def _verify_localhost_db():
    parsed = urlparse(settings.DATABASE_URL)
    host = parsed.hostname
    port = parsed.port
    dbname = parsed.path.lstrip("/")
    print(f"\n[DB Safety Check] Host: {host}:{port} | Database: {dbname}")
    assert host in ("localhost", "127.0.0.1"), f"SAFETY ABORT: Test database host is '{host}', expected localhost!"


@pytest.mark.asyncio
async def test_factor_same_repo():
    """Factor 1: Same repository deployment emits plain-English sentence."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-same-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Same Repo WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-same-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        repo_id = f"repo-same-{uuid.uuid4().hex[:8]}"
        repo = Repo(id=repo_id, name="auth-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo)
        await session.flush()

        now = datetime.utcnow()
        evt = Event(id=f"evt-same-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=5))
        session.add(evt)
        await session.flush()

        inc = Incident(id=f"inc-same-{uuid.uuid4().hex[:8]}", title="Auth Failure", workspace_id=ws_id, root_cause_repo_id=repo_id, status="open", created_at=now, updated_at=now)
        session.add(inc)
        await session.flush()

        await correlate_incident_causes(session, inc)
        await session.commit()

        res = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == inc.id))
        cand = res.scalars().first()
        assert cand is not None
        reasons = json.loads(cand.reason)

        print(f"Same repo reasons: {reasons}")
        assert "Deployed to auth-service, the same service that is alerting." in reasons
        assert "Deployed 5 minutes before the incident was triggered." in reasons


@pytest.mark.asyncio
async def test_factor_direct_dependency_1hop():
    """Factor 2: Direct dependency (1 hop) emits plain-English sentence."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-1hop-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="1Hop WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-1hop-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        # Alerting repo (api-gateway) depends on upstream repo (auth-service)
        repo_alert = Repo(id=f"repo-alert-{uuid.uuid4().hex[:8]}", name="api-gateway", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_up = Repo(id=f"repo-up-{uuid.uuid4().hex[:8]}", name="auth-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_alert)
        session.add(repo_up)
        await session.flush()

        dep = Dependency(id=f"dep-1-{uuid.uuid4().hex[:8]}", source_repo_id=repo_alert.id, target_repo_id=repo_up.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(dep)
        await session.flush()

        now = datetime.utcnow()
        evt = Event(id=f"evt-1hop-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_up.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=10))
        session.add(evt)
        await session.flush()

        inc = Incident(id=f"inc-1hop-{uuid.uuid4().hex[:8]}", title="Gateway 500s", workspace_id=ws_id, root_cause_repo_id=repo_alert.id, status="open", created_at=now, updated_at=now)
        session.add(inc)
        await session.flush()

        await correlate_incident_causes(session, inc)
        await session.commit()

        res = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == inc.id, CandidateCause.repo_id == repo_up.id))
        cand = res.scalars().first()
        assert cand is not None
        reasons = json.loads(cand.reason)

        print(f"1-hop reasons: {reasons}")
        expected_path = f"{repo_alert.id} -> {repo_up.id}"
        assert f"Changed a service that the alerting service depends on directly (via {expected_path})." in reasons
        assert "Deployed 10 minutes before the incident was triggered." in reasons


@pytest.mark.asyncio
async def test_factor_transitive_dependency_2hop():
    """Factor 3: Transitive dependency (2 hops) emits plain-English sentence."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-2hop-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="2Hop WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-2hop-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        # Chain: frontend -> api-service -> db-service
        repo_a = Repo(id=f"repo-fe-{uuid.uuid4().hex[:8]}", name="frontend", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_b = Repo(id=f"repo-api-{uuid.uuid4().hex[:8]}", name="api-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_c = Repo(id=f"repo-db-{uuid.uuid4().hex[:8]}", name="db-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_a)
        session.add(repo_b)
        session.add(repo_c)
        await session.flush()

        dep1 = Dependency(id=f"dep-2a-{uuid.uuid4().hex[:8]}", source_repo_id=repo_a.id, target_repo_id=repo_b.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        dep2 = Dependency(id=f"dep-2b-{uuid.uuid4().hex[:8]}", source_repo_id=repo_b.id, target_repo_id=repo_c.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(dep1)
        session.add(dep2)
        await session.flush()

        now = datetime.utcnow()
        evt = Event(id=f"evt-2hop-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_c.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=15))
        session.add(evt)
        await session.flush()

        inc = Incident(id=f"inc-2hop-{uuid.uuid4().hex[:8]}", title="Frontend Outage", workspace_id=ws_id, root_cause_repo_id=repo_a.id, status="open", created_at=now, updated_at=now)
        session.add(inc)
        await session.flush()

        await correlate_incident_causes(session, inc)
        await session.commit()

        res = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == inc.id, CandidateCause.repo_id == repo_c.id))
        cand = res.scalars().first()
        assert cand is not None
        reasons = json.loads(cand.reason)

        print(f"2-hop reasons: {reasons}")
        expected_path = f"{repo_a.id} -> {repo_b.id} -> {repo_c.id}"
        assert f"Changed a service two steps upstream of the alerting service (via {expected_path})." in reasons


@pytest.mark.asyncio
async def test_factor_transitive_dependency_3hop():
    """Factor 4: Transitive dependency (3 hops) emits plain-English sentence."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-3hop-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="3Hop WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-3hop-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        # Chain: A -> B -> C -> D
        repo_a = Repo(id=f"repo-3a-{uuid.uuid4().hex[:8]}", name="svc-a", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_b = Repo(id=f"repo-3b-{uuid.uuid4().hex[:8]}", name="svc-b", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_c = Repo(id=f"repo-3c-{uuid.uuid4().hex[:8]}", name="svc-c", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_d = Repo(id=f"repo-3d-{uuid.uuid4().hex[:8]}", name="svc-d", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add_all([repo_a, repo_b, repo_c, repo_d])
        await session.flush()

        dep1 = Dependency(id=f"dep-3a-{uuid.uuid4().hex[:8]}", source_repo_id=repo_a.id, target_repo_id=repo_b.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        dep2 = Dependency(id=f"dep-3b-{uuid.uuid4().hex[:8]}", source_repo_id=repo_b.id, target_repo_id=repo_c.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        dep3 = Dependency(id=f"dep-3c-{uuid.uuid4().hex[:8]}", source_repo_id=repo_c.id, target_repo_id=repo_d.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add_all([dep1, dep2, dep3])
        await session.flush()

        now = datetime.utcnow()
        evt = Event(id=f"evt-3hop-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_d.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=20))
        session.add(evt)
        await session.flush()

        inc = Incident(id=f"inc-3hop-{uuid.uuid4().hex[:8]}", title="Tier 3 Outage", workspace_id=ws_id, root_cause_repo_id=repo_a.id, status="open", created_at=now, updated_at=now)
        session.add(inc)
        await session.flush()

        await correlate_incident_causes(session, inc)
        await session.commit()

        res = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == inc.id, CandidateCause.repo_id == repo_d.id))
        cand = res.scalars().first()
        assert cand is not None
        reasons = json.loads(cand.reason)

        print(f"3-hop reasons: {reasons}")
        expected_path = f"{repo_a.id} -> {repo_b.id} -> {repo_c.id} -> {repo_d.id}"
        assert f"Changed a service three steps upstream of the alerting service (via {expected_path})." in reasons


@pytest.mark.asyncio
async def test_factor_temporal_tiers():
    """Factor 5: Temporal tiers (<=15m, 15-60m, 60-120m, and singular 1m) emit plain English."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-temp-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Temporal WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-temp-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        now = datetime.utcnow()
        # Test distinct time intervals: 1 min, 10 min (<=15m), 45 min (15-60m), 90 min (60-120m)
        test_intervals = [
            (1, "Deployed 1 minute before the incident was triggered."),
            (10, "Deployed 10 minutes before the incident was triggered."),
            (45, "Deployed 45 minutes before the incident was triggered."),
            (90, "Deployed 90 minutes before the incident was triggered.")
        ]

        for minutes_ago, expected_sentence in test_intervals:
            repo_id = f"repo-temp-{minutes_ago}-{uuid.uuid4().hex[:8]}"
            repo = Repo(id=repo_id, name=f"temporal-{minutes_ago}m", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            session.add(repo)
            await session.flush()

            evt = Event(
                id=f"evt-t-{minutes_ago}-{uuid.uuid4().hex[:8]}",
                type="push",
                source="github",
                repo_id=repo_id,
                workspace_id=ws_id,
                payload={},
                created_at=now - timedelta(minutes=minutes_ago)
            )
            session.add(evt)
            await session.flush()

            inc = Incident(
                id=f"inc-t-{minutes_ago}-{uuid.uuid4().hex[:8]}",
                title=f"Incident {minutes_ago}m",
                workspace_id=ws_id,
                root_cause_repo_id=repo_id,
                status="open",
                created_at=now,
                updated_at=now
            )
            session.add(inc)
            await session.flush()

            await correlate_incident_causes(session, inc)
            await session.commit()

            res = await session.execute(
                select(CandidateCause).where(CandidateCause.incident_id == inc.id, CandidateCause.event_id == evt.id)
            )
            cand = res.scalars().first()
            assert cand is not None
            reasons = json.loads(cand.reason)
            print(f"Interval {minutes_ago} min reasons: {reasons}")
            assert expected_sentence in reasons, f"Expected '{expected_sentence}' in reasons: {reasons}"


@pytest.mark.asyncio
async def test_factor_past_precedent():
    """Factor 6: Historical precedent (<90d confirmed cause, 1 day singular & N days plural) emits plain English."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-prec-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Precedent WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-prec-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        now = datetime.utcnow()

        # 1. Test plural days (14 days ago)
        repo_id_14 = f"repo-prec-14-{uuid.uuid4().hex[:8]}"
        repo_14 = Repo(id=repo_id_14, name="order-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_14)
        await session.flush()

        past_inc_14 = Incident(
            id=f"inc-past-14-{uuid.uuid4().hex[:8]}",
            title="Order Processing Deadlock",
            workspace_id=ws_id,
            root_cause_repo_id=repo_id_14,
            status="resolved",
            created_at=now - timedelta(days=14),
            updated_at=now - timedelta(days=14)
        )
        session.add(past_inc_14)
        await session.flush()

        past_cand_14 = CandidateCause(
            id=f"cand-past-14-{uuid.uuid4().hex[:8]}",
            workspace_id=ws_id,
            incident_id=past_inc_14.id,
            repo_id=repo_id_14,
            score=85.0,
            reason="Confirmed cause",
            confirmed=True
        )
        session.add(past_cand_14)
        await session.flush()

        fb_log_14 = CandidateCauseFeedbackLog(
            id=f"fb-prec-14-{uuid.uuid4().hex[:8]}",
            workspace_id=ws_id,
            candidate_cause_id=past_cand_14.id,
            incident_id=past_inc_14.id,
            repo_id=repo_id_14,
            confirmed=True,
            created_at=now - timedelta(days=14)
        )
        session.add(fb_log_14)
        await session.flush()

        evt_14 = Event(id=f"evt-prec-14-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_id_14, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=5))
        session.add(evt_14)
        await session.flush()

        curr_inc_14 = Incident(id=f"inc-curr-14-{uuid.uuid4().hex[:8]}", title="Checkout Stalled", workspace_id=ws_id, root_cause_repo_id=repo_id_14, status="open", created_at=now, updated_at=now)
        session.add(curr_inc_14)
        await session.flush()

        await correlate_incident_causes(session, curr_inc_14)
        await session.commit()

        res_14 = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == curr_inc_14.id, CandidateCause.repo_id == repo_id_14))
        cand_14 = res_14.scalars().first()
        assert cand_14 is not None
        reasons_14 = json.loads(cand_14.reason)
        assert "This service was the confirmed root cause of past incident 'Order Processing Deadlock' (14 days ago)." in reasons_14

        # 2. Test singular day (1 day ago)
        repo_id_1 = f"repo-prec-1-{uuid.uuid4().hex[:8]}"
        repo_1 = Repo(id=repo_id_1, name="inventory-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_1)
        await session.flush()

        past_inc_1 = Incident(
            id=f"inc-past-1-{uuid.uuid4().hex[:8]}",
            title="Stock Sync Failure",
            workspace_id=ws_id,
            root_cause_repo_id=repo_id_1,
            status="resolved",
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1)
        )
        session.add(past_inc_1)
        await session.flush()

        past_cand_1 = CandidateCause(
            id=f"cand-past-1-{uuid.uuid4().hex[:8]}",
            workspace_id=ws_id,
            incident_id=past_inc_1.id,
            repo_id=repo_id_1,
            score=85.0,
            reason="Confirmed cause",
            confirmed=True
        )
        session.add(past_cand_1)
        await session.flush()

        fb_log_1 = CandidateCauseFeedbackLog(
            id=f"fb-prec-1-{uuid.uuid4().hex[:8]}",
            workspace_id=ws_id,
            candidate_cause_id=past_cand_1.id,
            incident_id=past_inc_1.id,
            repo_id=repo_id_1,
            confirmed=True,
            created_at=now - timedelta(days=1)
        )
        session.add(fb_log_1)
        await session.flush()

        evt_1 = Event(id=f"evt-prec-1-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_id_1, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=5))
        session.add(evt_1)
        await session.flush()

        curr_inc_1 = Incident(id=f"inc-curr-1-{uuid.uuid4().hex[:8]}", title="Inventory Empty", workspace_id=ws_id, root_cause_repo_id=repo_id_1, status="open", created_at=now, updated_at=now)
        session.add(curr_inc_1)
        await session.flush()

        await correlate_incident_causes(session, curr_inc_1)
        await session.commit()

        res_1 = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == curr_inc_1.id, CandidateCause.repo_id == repo_id_1))
        cand_1 = res_1.scalars().first()
        assert cand_1 is not None
        reasons_1 = json.loads(cand_1.reason)
        assert "This service was the confirmed root cause of past incident 'Stock Sync Failure' (1 day ago)." in reasons_1


@pytest.mark.asyncio
async def test_factor_deploy_risk_elevated():
    """Factor 7: Elevated deployment risk emits plain English without fractions/numbers."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-risk-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Risk WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-risk-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        # Topology:
        # repo_alert (alerting service) -> depends on -> repo_up (upstream service, deployed)
        # repo_down (downstream service) -> depends on -> repo_up
        # repo_down has an active open incident, but repo_up has NO open incidents on itself.
        repo_alert = Repo(id=f"repo-ra-alert-{uuid.uuid4().hex[:8]}", name="api-gateway", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_up = Repo(id=f"repo-ra-up-{uuid.uuid4().hex[:8]}", name="core-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_down = Repo(id=f"repo-ra-down-{uuid.uuid4().hex[:8]}", name="web-client", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add_all([repo_alert, repo_up, repo_down])
        await session.flush()

        # Alerting service depends on upstream service
        dep1 = Dependency(id=f"dep-r1-{uuid.uuid4().hex[:8]}", source_repo_id=repo_alert.id, target_repo_id=repo_up.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        # Downstream service depends on upstream service
        dep2 = Dependency(id=f"dep-r2-{uuid.uuid4().hex[:8]}", source_repo_id=repo_down.id, target_repo_id=repo_up.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add_all([dep1, dep2])
        await session.flush()

        now = datetime.utcnow()
        # Open incident on web-client (downstream of core-service)
        downstream_inc = Incident(id=f"inc-down-{uuid.uuid4().hex[:8]}", title="Web Outage", workspace_id=ws_id, root_cause_repo_id=repo_down.id, status="open", created_at=now - timedelta(minutes=30), updated_at=now - timedelta(minutes=30))
        session.add(downstream_inc)
        await session.flush()

        # Deployment event on upstream core-service
        evt = Event(id=f"evt-up-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_up.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=5))
        session.add(evt)
        await session.flush()

        # Alerting incident on api-gateway
        curr_inc = Incident(id=f"inc-alert-{uuid.uuid4().hex[:8]}", title="Gateway Timeout", workspace_id=ws_id, root_cause_repo_id=repo_alert.id, status="open", created_at=now, updated_at=now)
        session.add(curr_inc)
        await session.flush()

        await correlate_incident_causes(session, curr_inc)
        await session.commit()

        res = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == curr_inc.id, CandidateCause.repo_id == repo_up.id))
        cand = res.scalars().first()
        assert cand is not None
        reasons = json.loads(cand.reason)

        print(f"Deploy risk reasons: {reasons}")
        assert "Elevated deployment risk: active open incident on a downstream dependent service." in reasons


@pytest.mark.asyncio
async def test_deployment_risk_helper_sentences():
    """Verify all branches of calculate_deployment_risk emit exact plain-English sentences."""
    from app.services.impact_service import calculate_deployment_risk
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-rh-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Risk Helper WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-rh-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        # Branch 1: Isolated service with no downstream repos and no incidents -> Low risk
        repo_iso = Repo(id=f"repo-iso-{uuid.uuid4().hex[:8]}", name="isolated-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_iso)
        await session.flush()

        res_iso = await calculate_deployment_risk(session, repo_iso.id)
        assert res_iso["risk_score"] == 0.0
        assert res_iso["risk_basis"] == "Low risk: no downstream services depend on this service and no recent incidents."

        # Branch 2: Service with downstream repo but no incidents -> Baseline risk
        repo_base = Repo(id=f"repo-base-{uuid.uuid4().hex[:8]}", name="base-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_child = Repo(id=f"repo-ch-{uuid.uuid4().hex[:8]}", name="child-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add_all([repo_base, repo_child])
        await session.flush()

        dep_bc = Dependency(id=f"dep-bc-{uuid.uuid4().hex[:8]}", source_repo_id=repo_child.id, target_repo_id=repo_base.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(dep_bc)
        await session.flush()

        res_base = await calculate_deployment_risk(session, repo_base.id)
        assert res_base["risk_score"] == 15.0
        assert res_base["risk_basis"] == "Baseline deployment risk: no active incidents or past failures."


@pytest.mark.asyncio
async def test_arithmetic_patterns_scanner():
    """
    Rigorously scans produced candidate cause reason strings against forbidden arithmetic patterns:
    - Signed numbers: +35.0, +20.0
    - Fraction scores: 15/100, 85/100
    - Total score phrases: Total Score, Total:
    - Hop counts: 1 hop away, 2 hops away, hop, hops
    - Weight keywords: weight, weights
    - Score placeholders: (score)
    """
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        # Setup test workspace and scenarios covering all branches
        ws_id = f"ws-scan-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Scan WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-scan-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        repo_a = Repo(id=f"repo-sca-{uuid.uuid4().hex[:8]}", name="svc-a", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_b = Repo(id=f"repo-scb-{uuid.uuid4().hex[:8]}", name="svc-b", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_c = Repo(id=f"repo-scc-{uuid.uuid4().hex[:8]}", name="svc-c", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_d = Repo(id=f"repo-scd-{uuid.uuid4().hex[:8]}", name="svc-d", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add_all([repo_a, repo_b, repo_c, repo_d])
        await session.flush()

        # Dependencies: A -> B -> C -> D
        dep1 = Dependency(id=f"dep-sc1-{uuid.uuid4().hex[:8]}", source_repo_id=repo_a.id, target_repo_id=repo_b.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        dep2 = Dependency(id=f"dep-sc2-{uuid.uuid4().hex[:8]}", source_repo_id=repo_b.id, target_repo_id=repo_c.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        dep3 = Dependency(id=f"dep-sc3-{uuid.uuid4().hex[:8]}", source_repo_id=repo_c.id, target_repo_id=repo_d.id, workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add_all([dep1, dep2, dep3])
        await session.flush()

        now = datetime.utcnow()
        # Events on same repo, 1-hop, 2-hop, 3-hop
        evt_a = Event(id=f"evt-sca-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_a.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=5))
        evt_b = Event(id=f"evt-scb-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_b.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=10))
        evt_c = Event(id=f"evt-scc-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_c.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=45))
        evt_d = Event(id=f"evt-scd-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_d.id, workspace_id=ws_id, payload={}, created_at=now - timedelta(minutes=90))
        session.add_all([evt_a, evt_b, evt_c, evt_d])
        await session.flush()

        inc = Incident(id=f"inc-scan-{uuid.uuid4().hex[:8]}", title="Scan Incident", workspace_id=ws_id, root_cause_repo_id=repo_a.id, status="open", created_at=now, updated_at=now)
        session.add(inc)
        await session.flush()

        candidates = await correlate_incident_causes(session, inc)
        await session.commit()

        # Forbidden regex patterns
        forbidden_patterns = [
            (re.compile(r"\+\d+\.?\d*"), "Signed arithmetic number (e.g. +35.0, +20)"),
            (re.compile(r"\b\d+/\d+\b"), "Score fraction (e.g. 15/100)"),
            (re.compile(r"\bTotal\s+Score\b", re.IGNORECASE), "Total Score label"),
            (re.compile(r"\b\d+\s*hops?\s*away\b", re.IGNORECASE), "Hop count parameter (e.g. 1 hop away)"),
            (re.compile(r"\bhops?\b", re.IGNORECASE), "Hop term"),
            (re.compile(r"\bweights?\b", re.IGNORECASE), "Weight keyword"),
            (re.compile(r"\(score\)", re.IGNORECASE), "Score placeholder")
        ]

        # Scan candidate causes in current workspace
        res = await session.execute(select(CandidateCause).where(CandidateCause.workspace_id == ws_id))
        ws_candidates = res.scalars().all()
        assert len(ws_candidates) > 0, "Expected candidate causes for scan workspace"

        violations = []
        for cand in ws_candidates:
            serialized = serialize_candidate_cause(cand)
            for reason in serialized.get("match_reasons", []):
                for pattern, desc in forbidden_patterns:
                    if pattern.search(reason):
                        violations.append((cand.id, reason, desc))

        print(f"Scanned {len(ws_candidates)} candidate causes, violations: {len(violations)}")
        assert len(violations) == 0, f"Found arithmetic or internal parameter pattern violations: {violations}"


def test_serialization_round_trip():
    """Round-trip test: JSON serialize and deserialize preserves reasons containing commas, colons, quotes."""
    sample_reasons = [
        "Deployed to billing-api, the same service that is alerting.",
        "Changed a service that the alerting service depends on directly (via billing-api -> database-cluster).",
        "This service was the confirmed root cause of past incident 'Payment Gateway Crash (v2.1)' (42 days ago).",
        "Elevated deployment risk: active open incident on a downstream dependent service."
    ]

    serialized_json = json.dumps(sample_reasons)
    cand = CandidateCause(
        id=f"cand-{uuid.uuid4().hex[:8]}",
        incident_id=f"inc-{uuid.uuid4().hex[:8]}",
        repo_id=f"repo-{uuid.uuid4().hex[:8]}",
        score=95.0,
        reason=serialized_json,
        workspace_id="ws-roundtrip"
    )

    result_dict = serialize_candidate_cause(cand)
    assert result_dict["match_reasons"] == sample_reasons
    print("Round-trip serialization successfully verified.")


def test_legacy_format_backward_compatibility():
    """Backward compatibility: legacy delimiter strings (; or . ) parse cleanly without exceptions."""
    # Legacy semicolon-delimited format
    legacy_semi = CandidateCause(
        id=f"cand-{uuid.uuid4().hex[:8]}",
        incident_id=f"inc-{uuid.uuid4().hex[:8]}",
        repo_id=f"repo-{uuid.uuid4().hex[:8]}",
        score=75.0,
        reason="Deployed to payment-gateway; Deployed 10 min before incident; High deployment risk",
        workspace_id="ws-legacy"
    )
    parsed_semi = serialize_candidate_cause(legacy_semi)
    assert parsed_semi["match_reasons"] == [
        "Deployed to payment-gateway",
        "Deployed 10 min before incident",
        "High deployment risk"
    ]

    # Legacy period-delimited format
    legacy_dot = CandidateCause(
        id=f"cand-{uuid.uuid4().hex[:8]}",
        incident_id=f"inc-{uuid.uuid4().hex[:8]}",
        repo_id=f"repo-{uuid.uuid4().hex[:8]}",
        score=60.0,
        reason="Deployed to auth-service. Deployed 15 min before incident. Baseline risk",
        workspace_id="ws-legacy"
    )
    parsed_dot = serialize_candidate_cause(legacy_dot)
    assert parsed_dot["match_reasons"] == [
        "Deployed to auth-service",
        "Deployed 15 min before incident",
        "Baseline risk"
    ]

    # Legacy single raw string format
    legacy_single = CandidateCause(
        id=f"cand-{uuid.uuid4().hex[:8]}",
        incident_id=f"inc-{uuid.uuid4().hex[:8]}",
        repo_id=f"repo-{uuid.uuid4().hex[:8]}",
        score=40.0,
        reason="Single legacy explanation without delimiters",
        workspace_id="ws-legacy"
    )
    parsed_single = serialize_candidate_cause(legacy_single)
    assert parsed_single["match_reasons"] == ["Single legacy explanation without delimiters"]
    print("Legacy formats successfully parsed with full backward compatibility.")


@pytest.mark.asyncio
async def test_workspace_scoping_and_isolation():
    """Tenant isolation: Correlation never crosses workspace boundaries."""
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        # Workspace A
        ws_a_id = f"ws-iso-a-{uuid.uuid4().hex[:8]}"
        ws_a = Workspace(id=ws_a_id, name="WS A", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws_a)
        await session.flush()

        usr_a_id = f"usr-a-{uuid.uuid4().hex[:8]}"
        usr_a = User(id=usr_a_id, email=f"{usr_a_id}@test.com", full_name="User A", role="admin", workspace_id=ws_a_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr_a)
        await session.flush()

        repo_a = Repo(id=f"repo-a-{uuid.uuid4().hex[:8]}", name="service-a", platform="github", default_branch="main", workspace_id=ws_a_id, user_id=usr_a.id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_a)
        await session.flush()

        # Workspace B
        ws_b_id = f"ws-iso-b-{uuid.uuid4().hex[:8]}"
        ws_b = Workspace(id=ws_b_id, name="WS B", color="green", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws_b)
        await session.flush()

        usr_b_id = f"usr-b-{uuid.uuid4().hex[:8]}"
        usr_b = User(id=usr_b_id, email=f"{usr_b_id}@test.com", full_name="User B", role="admin", workspace_id=ws_b_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr_b)
        await session.flush()

        repo_b = Repo(id=f"repo-b-{uuid.uuid4().hex[:8]}", name="service-b", platform="github", default_branch="main", workspace_id=ws_b_id, user_id=usr_b.id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_b)
        await session.flush()

        now = datetime.utcnow()
        # Event in Workspace B
        evt_b = Event(id=f"evt-b-{uuid.uuid4().hex[:8]}", type="push", source="github", repo_id=repo_b.id, workspace_id=ws_b_id, payload={}, created_at=now - timedelta(minutes=5))
        session.add(evt_b)
        await session.flush()

        # Incident in Workspace A
        inc_a = Incident(id=f"inc-a-{uuid.uuid4().hex[:8]}", title="Incident in A", workspace_id=ws_a_id, root_cause_repo_id=repo_a.id, status="open", created_at=now, updated_at=now)
        session.add(inc_a)
        await session.flush()

        await correlate_incident_causes(session, inc_a)
        await session.commit()

        # Candidates for Incident A should NOT include events from Workspace B
        res = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == inc_a.id))
        candidates = res.scalars().all()
        for cand in candidates:
            assert cand.workspace_id == ws_a_id
            assert cand.repo_id != repo_b.id
        print("Workspace isolation verified: zero cross-tenant candidates correlated.")
