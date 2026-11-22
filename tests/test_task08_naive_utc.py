"""
Task 08 Phase 2 Guard Tests
===========================
Verifies:
a) AST guard: No datetime.now(timezone.utc) or datetime.utcnow() appears under app/ outside common.py.
b) Schema flush guard: Every SQLModel table instantiates with default timestamps and flushes
   cleanly against PostgreSQL naive columns without DataError.
c) Real routes: GET /api/v1/analytics/activity, GET /api/v1/dependencies/topology, and
   GET /health/detailed return HTTP 2xx on clean DB.
d) Webhooks E2E: Real PagerDuty webhook handler (trigger -> Event -> Incident -> CandidateCauses)
   and real GitHub deployment webhook succeed against real local DB.
"""

import ast
import hmac
import hashlib
import json
import os
import uuid
import pytest
import httpx
from datetime import datetime, timezone
from sqlalchemy import text
from sqlmodel import select

from app.main import app
from app.core.config import settings
from app.core.database import async_session
from app.core.crypto import encrypt_secret
from app.api.routes.integrations import _make_pd_uid_token
from app.core.security import get_current_user

# Models
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.models.event import Event
from app.models.incident import Incident
from app.models.alert import Alert
from app.models.deployment import Deployment
from app.models.dependency import Dependency
from app.models.postmortem import Postmortem
from app.models.candidate_cause import CandidateCause
from app.models.candidate_cause_feedback_log import CandidateCauseFeedbackLog
from app.models.scoring_weight_recalibration import ScoringWeightRecalibration
from app.models.workspace_acknowledgment import WorkspaceAcknowledgment


# ---------------------------------------------------------------------------
# Guard (a): AST Check
# ---------------------------------------------------------------------------
def test_guard_a_ast_no_forbidden_datetime_calls():
    """Fails if datetime.now(timezone.utc) or datetime.utcnow() appears under app/ outside common.py."""
    forbidden = []
    app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
    common_py = os.path.normpath(os.path.join(app_dir, "models", "common.py"))

    for root, _, files in os.walk(app_dir):
        for f in files:
            if f.endswith(".py"):
                full_path = os.path.normpath(os.path.join(root, f))
                if full_path == common_py:
                    continue
                with open(full_path, "r", encoding="utf-8") as fp:
                    tree = ast.parse(fp.read(), filename=full_path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func
                        # Detect datetime.now(timezone.utc)
                        if isinstance(func, ast.Attribute) and func.attr == "now":
                            if isinstance(func.value, ast.Name) and func.value.id == "datetime":
                                forbidden.append((full_path, node.lineno, "datetime.now(...)"))
                        # Detect datetime.utcnow()
                        elif isinstance(func, ast.Attribute) and func.attr == "utcnow":
                            forbidden.append((full_path, node.lineno, "datetime.utcnow()"))

    assert not forbidden, f"Forbidden datetime calls detected: {forbidden}"


# ---------------------------------------------------------------------------
# Guard (b): SQLModel Table Defaults Flush Check
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_guard_b_all_sqlmodel_tables_flush_defaults():
    """For every SQLModel table, builds an instance with defaults and flushes against real naive columns."""
    uid = uuid.uuid4().hex[:8]
    ws_id = f"ws-flush-{uid}"
    user_id = f"usr-flush-{uid}"
    repo_id = f"repo-flush-{uid}"
    inc_id = f"inc-flush-{uid}"
    evt_id = f"evt-flush-{uid}"
    alt_id = f"alt-flush-{uid}"
    dep_id = f"dep-flush-{uid}"

    async with async_session() as session:
        # Build instances in dependency order
        ws = Workspace(id=ws_id, name="Flush WS")
        usr = User(id=user_id, email=f"{user_id}@test.com", full_name="Flush User", workspace_id=ws_id, role="admin")
        repo = Repo(id=repo_id, name="flush-repo", workspace_id=ws_id, user_id=user_id)
        evt = Event(id=evt_id, workspace_id=ws_id, repo_id=repo_id, type="flush.event", source="test", payload={})
        inc = Incident(id=inc_id, workspace_id=ws_id, root_cause_repo_id=repo_id, title="Flush Incident", severity="high")
        alt = Alert(id=alt_id, workspace_id=ws_id, repo_id=repo_id, title="Flush Alert", message="Flush Alert Message", severity="warning", category="test")
        deploy = Deployment(id=dep_id, workspace_id=ws_id, repo_id=repo_id, environment="production", status="success", commit_hash="abc1234")
        dependency = Dependency(workspace_id=ws_id, source_repo_id=repo_id, target_repo_id=repo_id, dependency_type="internal_api")
        pm = Postmortem(workspace_id=ws_id, incident_id=inc_id, title="Flush PM")
        cc = CandidateCause(workspace_id=ws_id, incident_id=inc_id, repo_id=repo_id, event_id=evt_id, score=80.0, reason="test")
        fb = CandidateCauseFeedbackLog(workspace_id=ws_id, candidate_cause_id=cc.id, incident_id=inc_id, repo_id=repo_id, event_id=evt_id, confirmed=True)
        recal = ScoringWeightRecalibration(workspace_id=ws_id, weights="{}", previous_weights="{}", sample_size=20, status="active")
        ack = WorkspaceAcknowledgment(workspace_id=ws_id, user_id=user_id, terms_version="v1.0")

        instances = [ws, usr, repo, evt, inc, alt, deploy, dependency, pm, cc, fb, recal, ack]

        for inst in instances:
            session.add(inst)
            await session.flush()

        # Rollback all flushed instances
        await session.rollback()


# ---------------------------------------------------------------------------
# Guard (c): Real Routes 2xx on Clean DB
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_guard_c_real_routes_2xx_on_clean_db():
    """GET /api/v1/analytics/activity, /api/v1/dependencies/topology, /health/detailed return 2xx."""
    uid = uuid.uuid4().hex[:8]
    ws_id = f"ws-routes-{uid}"
    user_id = f"usr-routes-{uid}"
    email = f"{user_id}@test.com"

    test_user = User(id=user_id, email=email, full_name="Route User", workspace_id=ws_id, role="admin")

    async with async_session() as session:
        ws = Workspace(id=ws_id, name="Route WS")
        session.add(ws)
        await session.flush()
        session.add(test_user)
        await session.commit()

    app.dependency_overrides[get_current_user] = lambda: test_user
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Analytics activity
            r_act = await client.get("/api/v1/analytics/activity")
            assert r_act.status_code == 200, f"Analytics activity failed: {r_act.status_code} {r_act.text}"

            # 2. Dependencies topology
            r_top = await client.get("/api/v1/dependencies/topology")
            assert r_top.status_code == 200, f"Topology failed: {r_top.status_code} {r_top.text}"

            # 3. Health detailed with secret
            r_hlth = await client.get(
                "/health/detailed",
                headers={"X-Health-Check-Secret": settings.HEALTH_CHECK_SECRET}
            )
            assert r_hlth.status_code == 200, f"Health detailed failed: {r_hlth.status_code} {r_hlth.text}"
            data = r_hlth.json()
            assert data.get("status") == "pass"
            assert data["checks"]["database_connection"]["status"] == "pass"
            assert data["checks"]["database_events_query"]["status"] == "pass"
            assert data["checks"]["database_alerts_query"]["status"] == "pass"
    finally:
        app.dependency_overrides.clear()
        async with async_session() as session:
            await session.execute(text("DELETE FROM users WHERE workspace_id = :ws"), {"ws": ws_id})
            await session.execute(text("DELETE FROM workspaces WHERE id = :ws"), {"ws": ws_id})
            await session.commit()


# ---------------------------------------------------------------------------
# Guard (d): Real Webhook Handlers End-to-End
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_guard_d_real_webhooks_end_to_end():
    """Real PagerDuty & GitHub deployment webhook handlers succeed and create rows in local DB."""
    uid = uuid.uuid4().hex[:8]
    ws_id = f"ws-wh-{uid}"
    user_id = f"usr-wh-{uid}"
    repo_id = f"repo-wh-{uid}"
    repo_name = f"payment-service-{uid}"
    pd_event_id = f"pd-evt-{uid}"
    pd_incident_id = f"pd-inc-{uid}"

    pd_secret = "test_pd_secret_key"
    test_user = User(
        id=user_id,
        email=f"{user_id}@test.com",
        full_name="WH User",
        workspace_id=ws_id,
        role="admin",
        pagerduty_webhook_secret=encrypt_secret(pd_secret)
    )

    async with async_session() as session:
        ws = Workspace(id=ws_id, name="Webhook WS")
        session.add(ws)
        await session.flush()
        session.add(test_user)
        await session.flush()
        repo = Repo(id=repo_id, name=repo_name, owner="acme", workspace_id=ws_id, user_id=user_id, platform="github")
        session.add(repo)
        await session.commit()

    token = _make_pd_uid_token(user_id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. PagerDuty trigger webhook
        pd_payload = {
            "event": {
                "id": pd_event_id,
                "event_type": "incident.triggered",
                "data": {
                    "id": pd_incident_id,
                    "title": "Payment gateway latency elevated",
                    "service": {"summary": repo_name}
                }
            }
        }
        pd_bytes = json.dumps(pd_payload).encode("utf-8")
        pd_sig = "v1=" + hmac.new(
            pd_secret.encode("utf-8"),
            pd_bytes,
            hashlib.sha256
        ).hexdigest()

        res_pd = await client.post(
            f"/api/v1/webhooks/pagerduty?uid={token}",
            content=pd_bytes,
            headers={
                "X-PagerDuty-Signature": pd_sig,
                "Content-Type": "application/json"
            }
        )
        assert res_pd.status_code == 200, f"PD webhook failed: {res_pd.status_code} {res_pd.text}"
        data_pd = res_pd.json()
        assert data_pd.get("status") in ("processed", "success", "enqueued") or "incident_id" in data_pd

        # 2. GitHub deployment webhook
        gh_payload = {
            "deployment_status": {
                "state": "success",
                "description": "Deployment finished"
            },
            "deployment": {
                "sha": "1234567890abcdef1234567890abcdef12345678",
                "environment": "production",
                "creator": {"login": "deploy-bot"}
            },
            "repository": {
                "full_name": f"acme/{repo_name}",
                "name": repo_name
            }
        }
        body_bytes = json.dumps(gh_payload).encode("utf-8")
        sig = "sha256=" + hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
            body_bytes,
            hashlib.sha256
        ).hexdigest()

        res_gh = await client.post(
            "/api/v1/webhooks/github",
            content=body_bytes,
            headers={
                "X-GitHub-Event": "deployment_status",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json"
            }
        )
        assert res_gh.status_code == 200, f"GH webhook failed: {res_gh.status_code} {res_gh.text}"

    # Verify rows in DB
    async with async_session() as session:
        # Check Event created for PagerDuty
        evt = await session.execute(select(Event).where(Event.pd_event_id == pd_event_id))
        evt_row = evt.scalars().first()
        assert evt_row is not None, "PagerDuty Event row not found in DB"
        assert evt_row.created_at.tzinfo is None, "Event created_at must be naive"

        # Check Incident created
        inc = await session.execute(select(Incident).where(Incident.pd_incident_id == pd_incident_id))
        inc_row = inc.scalars().first()
        assert inc_row is not None, "Incident row not found in DB"
        assert inc_row.started_at.tzinfo is None, "Incident started_at must be naive"

        # Check Candidate Causes
        cc_res = await session.execute(select(CandidateCause).where(CandidateCause.incident_id == inc_row.id))
        # Might be 0 or more depending on prior events, but table query must succeed without DataError
        _ = cc_res.scalars().all()

        # Check GitHub deployment row
        deploy_res = await session.execute(select(Deployment).where(Deployment.workspace_id == ws_id))
        deploy_row = deploy_res.scalars().first()
        assert deploy_row is not None, "GitHub Deployment row not found in DB"
        assert deploy_row.created_at.tzinfo is None, "Deployment created_at must be naive"

        # Cleanup test workspace
        await session.execute(text("DELETE FROM candidate_causes WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM incidents WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM events WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM deployments WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM repos WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM users WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM workspaces WHERE id = :ws"), {"ws": ws_id})
        await session.commit()


# ---------------------------------------------------------------------------
# BaseTable Session Lifecycle: refresh, merge, and attribute loading
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_base_table_refresh_merge_lifecycle():
    """Verify session.refresh() and session.merge() work on at least two model classes (Workspace, Repo)
    and that BaseTable.__setattr__ does not alter non-datetime types or corrupt ORM state.
    """
    uid = uuid.uuid4().hex[:8]
    ws_id = f"ws-bm-{uid}"
    user_id = f"usr-bm-{uid}"
    repo_id = f"repo-bm-{uid}"

    async with async_session() as session:
        # 1. Model Class 1: Workspace
        ws = Workspace(id=ws_id, name="Original WS", description="Initial description", color="red")
        session.add(ws)
        await session.commit()

        # Update in database behind the session's back to test session.refresh()
        await session.execute(
            text("UPDATE workspaces SET description = 'Refreshed description' WHERE id = :id"),
            {"id": ws_id}
        )
        await session.commit()

        # Execute session.refresh()
        await session.refresh(ws)
        assert ws.description == "Refreshed description", "session.refresh failed to update description"
        assert ws.name == "Original WS"
        assert ws.color == "red"
        assert ws.created_at.tzinfo is None, "created_at must be naive after refresh"
        assert ws.updated_at.tzinfo is None, "updated_at must be naive after refresh"

        # Test session.merge() with detached Workspace instance having aware datetime
        aware_dt = datetime.now(timezone.utc)
        detached_ws = Workspace(
            id=ws_id,
            name="Merged WS",
            description="Merged description",
            color="purple",
            updated_at=aware_dt
        )
        merged_ws = await session.merge(detached_ws)
        await session.commit()

        assert merged_ws.name == "Merged WS"
        assert merged_ws.description == "Merged description"
        assert merged_ws.color == "purple"
        assert merged_ws.updated_at.tzinfo is None, "updated_at must be normalized to naive UTC after merge"

        # 2. Model Class 2: Repo (with foreign key to Workspace)
        user = User(id=user_id, email=f"{user_id}@test.com", full_name="BM User", workspace_id=ws_id, role="admin")
        session.add(user)
        await session.flush()
        repo = Repo(
            id=repo_id,
            name=f"test-repo-{uid}",
            owner="acme",
            workspace_id=ws_id,
            user_id=user_id,
            platform="github",
            activity=55.5
        )
        session.add(repo)
        await session.commit()

        # Test session.refresh() on Repo
        await session.execute(
            text("UPDATE repos SET activity = 88.0 WHERE id = :id"),
            {"id": repo_id}
        )
        await session.commit()

        await session.refresh(repo)
        assert repo.activity == 88.0, "session.refresh failed to update activity"
        assert repo.name == f"test-repo-{uid}"
        assert repo.created_at.tzinfo is None
        assert repo.updated_at.tzinfo is None

        # Test session.merge() on Repo with updated attributes
        detached_repo = Repo(
            id=repo_id,
            name=f"test-repo-{uid}-merged",
            owner="acme",
            workspace_id=ws_id,
            user_id=user_id,
            platform="github",
            activity=95.0,
            last_commit_at=aware_dt
        )
        merged_repo = await session.merge(detached_repo)
        await session.commit()

        assert merged_repo.name == f"test-repo-{uid}-merged"
        assert merged_repo.activity == 95.0
        assert merged_repo.last_commit_at.tzinfo is None, "last_commit_at must be normalized to naive UTC"

        # Cleanup
        await session.execute(text("DELETE FROM repos WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM users WHERE workspace_id = :ws"), {"ws": ws_id})
        await session.execute(text("DELETE FROM workspaces WHERE id = :ws"), {"ws": ws_id})
        await session.commit()

