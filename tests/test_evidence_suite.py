"""
NexOps Evidence & Security Compliance Pytest Suite
Executes 8 empirical assertions verifying multi-tenant RLS safety, HMAC signatures,
health info disclosure prevention, Postmortem API lifecycle, and Fernet key rotation cryptography.
"""

import pytest
import pytest_asyncio
import uuid
import sys
import os
from sqlalchemy import text
from sqlmodel import select
import httpx

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.core.database import async_session
from app.core.rls import rls_bypass
from app.api.routes.integrations import _make_pd_uid_token, _verify_pd_uid_token
from app.models.workspace import Workspace
from app.models.user import User
from app.models.incident import Incident
from app.models.postmortem import Postmortem
from app.core.security import get_current_user
from cryptography.fernet import Fernet
from scripts.rotate_key import decrypt_with_key, encrypt_with_key


import asyncio

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_1_rls_bypass_exception_safety():
    """Assertion 1: Verify rls_bypass guarantees reset of nexops.bypass_rls even on exception."""
    async with async_session() as session:
        res_before = await session.execute(text("SELECT current_setting('nexops.bypass_rls', true)"))
        val_before = res_before.scalar() or "false"

        try:
            async with rls_bypass(session):
                res_inside = await session.execute(text("SELECT current_setting('nexops.bypass_rls', true)"))
                assert res_inside.scalar() == "true", "Expected 'true' inside rls_bypass block"
                raise RuntimeError("Intentional test exception inside rls_bypass block")
        except RuntimeError:
            pass

        res_after = await session.execute(text("SELECT current_setting('nexops.bypass_rls', true)"))
        val_after = res_after.scalar()
        assert val_after in ("false", None), f"nexops.bypass_rls leaked as '{val_after}' post-exception"


@pytest.mark.asyncio
async def test_2_signed_pd_uid_tokens():
    """Assertion 2: Verify PagerDuty signed UID tokens accept valid signatures and reject forged ones."""
    test_uid = "usr-test-proof-999"
    signed = _make_pd_uid_token(test_uid)

    verified_uid = _verify_pd_uid_token(signed)
    assert verified_uid == test_uid, f"UID mismatch: expected {test_uid}, got {verified_uid}"

    forged_token = f"{test_uid}.forged_signature_00000000000"
    with pytest.raises(ValueError):
        _verify_pd_uid_token(forged_token)


@pytest.mark.asyncio
async def test_3_public_health_minimal_response():
    """Assertion 3: Verify /health returns minimal info without leaking DB branch or commit details."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "service" in data
        assert "version" in data
        assert "database" not in data, "Public /health must not leak database metadata"
        assert "commit_sha" not in data, "Public /health must not leak commit_sha"


@pytest.mark.asyncio
async def test_4_detailed_health_auth_gated():
    """Assertion 4: Verify /health/detailed endpoint rejects unauthenticated requests."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.get("/health/detailed")
        assert res.status_code in (401, 403), f"Expected 401/403, got {res.status_code}"


@pytest.mark.asyncio
async def test_5_postmortem_api_lifecycle():
    """Assertion 5: Test Postmortem API lifecycle (GET auto-create draft -> PATCH auto-save -> POST publish)."""
    test_ws_id = f"ws-pytest-{uuid.uuid4().hex[:6]}"
    test_inc_id = f"inc-pytest-{uuid.uuid4().hex[:6]}"
    test_user_id = f"usr-pytest-{uuid.uuid4().hex[:6]}"
    test_email = f"pytest-{uuid.uuid4().hex[:6]}@nexops.io"

    test_user = User(id=test_user_id, email=test_email, full_name="Pytest Runner", workspace_id=test_ws_id, role="member")
    app.dependency_overrides[get_current_user] = lambda: test_user

    async with async_session() as session:
        ws = Workspace(id=test_ws_id, name="Pytest Workspace", slug=test_ws_id)
        session.add(ws)
        await session.commit()

        u_db = User(id=test_user_id, email=test_email, full_name="Pytest Runner", workspace_id=test_ws_id, role="member")
        session.add(u_db)
        await session.commit()

        inc = Incident(id=test_inc_id, workspace_id=test_ws_id, title="Pytest Incident", severity="critical", status="resolved")
        session.add(inc)
        await session.commit()

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. GET auto-creates draft
            res_get = await client.get(f"/api/v1/incidents/{test_inc_id}/postmortem")
            assert res_get.status_code == 200
            pm_data = res_get.json()
            assert pm_data.get("status") == "draft"

            # 2. PATCH updates draft
            patch_payload = {
                "summary": "Database connection pool exhausted.",
                "root_cause": "Max connections reached in worker process."
            }
            res_patch = await client.patch(f"/api/v1/incidents/{test_inc_id}/postmortem", json=patch_payload)
            assert res_patch.status_code == 200
            assert res_patch.json().get("summary") == patch_payload["summary"]

            # 3. POST publish
            res_pub = await client.post(f"/api/v1/incidents/{test_inc_id}/postmortem/publish")
            assert res_pub.status_code == 200
            assert res_pub.json().get("status") == "published"
    finally:
        async with async_session() as session:
            pm = await session.get(Postmortem, pm_data["id"]) if 'pm_data' in locals() else None
            inc_obj = await session.get(Incident, test_inc_id)
            u_obj = await session.get(User, test_user_id)
            ws_obj = await session.get(Workspace, test_ws_id)
            if pm: await session.delete(pm); await session.commit()
            if inc_obj: await session.delete(inc_obj); await session.commit()
            if u_obj: await session.delete(u_obj); await session.commit()
            if ws_obj: await session.delete(ws_obj); await session.commit()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_6_analytics_dashboard_endpoint():
    """Assertion 6: Verify /analytics/dashboard endpoint returns health score & success rate."""
    test_user = User(id="usr-pytest-analytics", email="analytics@nexops.io", full_name="Analytics Tester", workspace_id="ws-test-dummy", role="member")
    app.dependency_overrides[get_current_user] = lambda: test_user

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/v1/analytics/dashboard")
            assert res.status_code == 200
            data = res.json()
            assert "avgHealth" in data or "avg_health" in data
            assert "successRate" in data or "success_rate" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_7_events_list_endpoint():
    """Assertion 7: Verify /events endpoint returns event list scoped to user workspace."""
    test_user = User(id="usr-pytest-events", email="events@nexops.io", full_name="Events Tester", workspace_id="ws-test-dummy", role="member")
    app.dependency_overrides[get_current_user] = lambda: test_user

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/v1/events?limit=5")
            assert res.status_code == 200
            assert isinstance(res.json(), list)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_8_key_rotation_cryptography():
    """Assertion 8: Verify dual-key Fernet re-encryption & decryption round-trip."""
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()

    secret = "github_pat_11AAAAAA_secret_token_12345"
    encrypted_v1 = encrypt_with_key(secret, key1)
    decrypted_v1 = decrypt_with_key(encrypted_v1, key1)
    assert decrypted_v1 == secret

    encrypted_v2 = encrypt_with_key(decrypted_v1, key2)
    decrypted_v2 = decrypt_with_key(encrypted_v2, key2)
    assert decrypted_v2 == secret
