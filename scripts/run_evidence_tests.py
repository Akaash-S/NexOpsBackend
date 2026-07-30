"""
NexOps Empirical Evidence Test Suite (Refined ASGI Async Harness)
Runs async HTTP requests via httpx.ASGITransport to test backend endpoints cleanly.
"""

import sys
import os
import asyncio
import logging
import uuid

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="[TEST] %(message)s")
logger = logging.getLogger("nexops.test")

test_results = []
bugs_found = []

def record_result(name: str, passed: bool, details: str = ""):
    status = "PASSED" if passed else "FAILED"
    test_results.append({"name": name, "status": status, "details": details})
    if passed:
        logger.info(f"✓ {name} — PASSED: {details}")
    else:
        logger.error(f"✗ {name} — FAILED: {details}")
        bugs_found.append({"test": name, "issue": details})


async def test_1_rls_bypass_exception_safety():
    """Verify rls_bypass guarantees reset of nexops.bypass_rls even on exception."""
    try:
        from app.core.database import async_session
        from app.core.rls import rls_bypass
        from sqlalchemy import text

        async with async_session() as session:
            # Initially bypass should be false
            res = await session.execute(text("SELECT current_setting('nexops.bypass_rls', true)"))
            val_before = res.scalar() or "false"

            # Enter rls_bypass block and raise an intentional exception
            try:
                async with rls_bypass(session):
                    res_inside = await session.execute(text("SELECT current_setting('nexops.bypass_rls', true)"))
                    val_inside = res_inside.scalar()
                    assert val_inside == "true", f"Expected 'true' inside CM, got {val_inside}"
                    raise RuntimeError("Intentional test exception inside rls_bypass block")
            except RuntimeError:
                pass  # Expected exception

            # Verify bypass was reset to false after exception
            res_after = await session.execute(text("SELECT current_setting('nexops.bypass_rls', true)"))
            val_after = res_after.scalar()
            
            if val_after == "false" or val_after is None:
                record_result("RLS Bypass Exception Safety", True, "nexops.bypass_rls correctly reset to 'false' post-exception")
            else:
                record_result("RLS Bypass Exception Safety", False, f"nexops.bypass_rls leaked as '{val_after}' post-exception")
    except Exception as e:
        record_result("RLS Bypass Exception Safety", False, f"Unexpected error: {e}")


async def test_2_signed_pd_uid_tokens():
    """Verify PagerDuty signed UID tokens accept valid signatures and reject forged ones."""
    try:
        from app.api.routes.integrations import _make_pd_uid_token, _verify_pd_uid_token

        test_uid = "usr-test-proof-999"
        signed = _make_pd_uid_token(test_uid)

        # 1. Round-trip verification
        verified_uid = _verify_pd_uid_token(signed)
        if verified_uid != test_uid:
            record_result("Signed PD UID Token Verification", False, f"UID mismatch: expected {test_uid}, got {verified_uid}")
            return

        # 2. Forged signature rejection
        forged_token = f"{test_uid}.forged_signature_00000000000"
        forged_rejected = False
        try:
            _verify_pd_uid_token(forged_token)
        except ValueError:
            forged_rejected = True

        if forged_rejected:
            record_result("Signed PD UID Token Verification", True, "Valid tokens verified; forged tokens successfully rejected with ValueError")
        else:
            record_result("Signed PD UID Token Verification", False, "Forged token was accepted without raising ValueError!")
    except Exception as e:
        record_result("Signed PD UID Token Verification", False, f"Unexpected error: {e}")


async def test_3_health_endpoints():
    """Verify /health returns minimal info and /health/detailed requires authentication."""
    try:
        import httpx
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Public /health
            res_public = await client.get("/health")
            if res_public.status_code != 200:
                record_result("Public /health Endpoint", False, f"Status code {res_public.status_code}")
                return

            data_public = res_public.json()
            has_metadata = "database" in data_public or "commit_sha" in data_public
            if has_metadata:
                record_result("Public /health Endpoint", False, "Exposes infrastructure metadata publicly!")
            else:
                record_result("Public /health Endpoint", True, f"Minimal public response verified: {data_public}")

            # 2. Unauthenticated /health/detailed (Must return 401 or 403)
            res_det_unauth = await client.get("/health/detailed")
            if res_det_unauth.status_code in (401, 403):
                record_result("Auth-Gated /health/detailed Endpoint", True, f"Unauthenticated request correctly rejected with HTTP {res_det_unauth.status_code}")
            else:
                record_result("Auth-Gated /health/detailed Endpoint", False, f"Unauthenticated request returned status {res_det_unauth.status_code}")
    except Exception as e:
        record_result("Health Endpoints Verification", False, f"Unexpected error: {e}")


async def test_4_postmortem_api_flow():
    """Test full Postmortem API lifecycle: Auto-create draft -> Patch updates -> Publish validation."""
    try:
        import httpx
        from app.main import app
        from app.core.database import async_session
        from app.models.workspace import Workspace
        from app.models.incident import Incident
        from app.models.postmortem import Postmortem
        from app.core.security import get_current_user
        from app.models.user import User

        test_ws_id = f"ws-test-{uuid.uuid4().hex[:6]}"
        test_inc_id = f"inc-test-{uuid.uuid4().hex[:6]}"
        test_user_id = f"usr-test-{uuid.uuid4().hex[:6]}"
        test_email = f"tester-{uuid.uuid4().hex[:6]}@nexops.io"
        test_user = User(id=test_user_id, email=test_email, full_name="E2E Tester", workspace_id=test_ws_id, role="member")
        app.dependency_overrides[get_current_user] = lambda: test_user

        # Create Workspace, User, and Incident in DB
        async with async_session() as session:
            ws = Workspace(id=test_ws_id, name="Test Workspace", slug=test_ws_id)
            session.add(ws)
            await session.commit()

            u_db = User(id=test_user_id, email=test_email, full_name="E2E Tester", workspace_id=test_ws_id, role="member")
            session.add(u_db)
            await session.commit()

            test_inc = Incident(
                id=test_inc_id,
                workspace_id=test_ws_id,
                title="Test System Outage",
                severity="critical",
                status="resolved"
            )
            session.add(test_inc)
            await session.commit()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. GET auto-creates draft
            res_get = await client.get(f"/api/v1/incidents/{test_inc_id}/postmortem")
            if res_get.status_code != 200:
                record_result("Postmortem API Lifecycle", False, f"GET failed with {res_get.status_code}: {res_get.text}")
                return
            pm_data = res_get.json()
            if pm_data.get("status") != "draft":
                record_result("Postmortem API Lifecycle", False, f"Expected status 'draft', got {pm_data.get('status')}")
                return

            # 2. PATCH updates draft
            patch_payload = {
                "summary": "Root cause was database connection pool exhaustion.",
                "root_cause": "Max connections reached due to unclosed sessions in legacy worker."
            }
            res_patch = await client.patch(f"/api/v1/incidents/{test_inc_id}/postmortem", json=patch_payload)
            if res_patch.status_code != 200 or res_patch.json().get("summary") != patch_payload["summary"]:
                record_result("Postmortem API Lifecycle", False, f"PATCH failed or summary mismatch: {res_patch.text}")
                return

            # 3. POST publish
            res_pub = await client.post(f"/api/v1/incidents/{test_inc_id}/postmortem/publish")
            if res_pub.status_code != 200 or res_pub.json().get("status") != "published":
                record_result("Postmortem API Lifecycle", False, f"Publish failed: {res_pub.text}")
                return

            record_result("Postmortem API Lifecycle", True, "Draft auto-creation, PATCH auto-save, and Publish transition verified")

        # Cleanup DB in child-to-parent order (pm -> inc -> user -> workspace)
        async with async_session() as session:
            pm = await session.get(Postmortem, pm_data["id"])
            if pm:
                await session.delete(pm)
                await session.commit()

            inc = await session.get(Incident, test_inc_id)
            if inc:
                await session.delete(inc)
                await session.commit()

            u_obj = await session.get(User, test_user_id)
            if u_obj:
                await session.delete(u_obj)
                await session.commit()

            ws_obj = await session.get(Workspace, test_ws_id)
            if ws_obj:
                await session.delete(ws_obj)
                await session.commit()

        app.dependency_overrides.clear()
    except Exception as e:
        record_result("Postmortem API Lifecycle", False, f"Unexpected error: {e}")


async def test_5_analytics_and_events_api():
    """Verify /analytics/dashboard and /events API endpoints return expected structure."""
    try:
        import httpx
        from app.main import app
        from app.core.security import get_current_user
        from app.models.user import User

        test_user = User(id="usr-e2e-tester", email="tester@nexops.io", workspace_id="ws-test-dummy", role="member")
        app.dependency_overrides[get_current_user] = lambda: test_user

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res_analytics = await client.get("/api/v1/analytics/dashboard")
            if res_analytics.status_code != 200:
                record_result("Analytics API Endpoint", False, f"Status code {res_analytics.status_code}: {res_analytics.text}")
            else:
                d = res_analytics.json()
                if ("avgHealth" in d or "avg_health" in d) and ("successRate" in d or "success_rate" in d):
                    record_result("Analytics API Endpoint", True, f"Dashboard stats returned: {d}")
                else:
                    record_result("Analytics API Endpoint", False, f"Missing fields in analytics response: {d}")

            res_events = await client.get("/api/v1/events?limit=5")
            if res_events.status_code != 200:
                record_result("Events API Endpoint", False, f"Status code {res_events.status_code}: {res_events.text}")
            else:
                record_result("Events API Endpoint", True, f"Returned {len(res_events.json())} event records")

        app.dependency_overrides.clear()
    except Exception as e:
        record_result("Analytics & Events API", False, f"Unexpected error: {e}")


async def test_6_key_rotation_dryrun():
    """Verify Key Rotation script logic with mock encryption keys."""
    try:
        from cryptography.fernet import Fernet
        from scripts.rotate_key import decrypt_with_key, encrypt_with_key

        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()

        secret = "github_pat_11AAAAAA_secret_token_12345"
        encrypted_v1 = encrypt_with_key(secret, key1)
        decrypted_v1 = decrypt_with_key(encrypted_v1, key1)

        assert decrypted_v1 == secret, "Key 1 decryption failed"

        # Re-encrypt with key 2
        encrypted_v2 = encrypt_with_key(decrypted_v1, key2)
        decrypted_v2 = decrypt_with_key(encrypted_v2, key2)

        assert decrypted_v2 == secret, "Key 2 decryption failed"

        record_result("Key Rotation Script Cryptography", True, "Dual-key re-encryption & decryption round-trip verified")
    except Exception as e:
        record_result("Key Rotation Script Cryptography", False, f"Unexpected error: {e}")


async def main():
    logger.info("=== STARTING NEXOPS EMPIRICAL EVIDENCE SUITE ===")
    await test_1_rls_bypass_exception_safety()
    await test_2_signed_pd_uid_tokens()
    await test_3_health_endpoints()
    await test_4_postmortem_api_flow()
    await test_5_analytics_and_events_api()
    await test_6_key_rotation_dryrun()

    logger.info("\n=== SUMMARY OF EVIDENCE TEST RESULTS ===")
    passed_count = sum(1 for r in test_results if r["status"] == "PASSED")
    logger.info(f"Passed: {passed_count}/{len(test_results)}")

    if bugs_found:
        logger.error(f"Bugs Found ({len(bugs_found)}):")
        for b in bugs_found:
            logger.error(f"  - {b['test']}: {b['issue']}")
    else:
        logger.info("🎉 100% ALL BACKEND TESTS PASSED cleanly!")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
