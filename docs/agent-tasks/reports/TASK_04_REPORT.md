# TASK 04 (Priority A3) — Public `/health` Metadata Leak Prevention

**Date:** 2026-09-26  
**Target:** NexOps Backend (`backend/`)  
**Branch:** `task-04-public-health-leak`  
**Status:** Implementation & Verification Complete (Ready for PR Review)  

---

## 1. Executive Summary

A security audit finding (`tests/test_evidence_suite.py::test_3_public_health_minimal_response`) identified that the unauthenticated public health check endpoint (`GET /health` and `GET /api/v1/health`) leaked internal database infrastructure topology (`db_branch` and connection state) to unauthenticated callers.

### Problems Identified & Closed:
1. **Public Infrastructure Disclosure:** `app/main.py:233-261` previously parsed `DATABASE_URL` to extract the compute host / Neon branch name (`db_branch`) and returned it under a nested `"database"` dictionary (`{"connected": true, "branch": "..."}`) in the public response.
2. **Reconnaissance Risk:** Public, unauthenticated crawlers, uptime monitors, or external entities were able to observe internal database hostnames and branch identifiers without authenticating.
3. **Architectural Separation:** Detailed telemetry (including DB branch, DB latency, Redis latency, worker heartbeat, and integration reachability) is already securely provided on `GET /health/detailed` (`app/main.py:267-368`), gated behind Firebase Authentication (`user=Depends(get_current_user)`). The public `/health` endpoint was architecturally intended to be a zero-leakage ping for load balancers.

---

## 2. Implementation Summary

### Changes Made to `app/main.py`:
- Removed `DATABASE_URL` string parsing (`db_branch` extraction) from `health_check()`.
- Removed the `"database"` dictionary entirely from the public response payload.
- Kept the internal database ping (`SELECT 1`) and Redis ping (`_redis.ping()`) active to compute the aggregate `"status": "operational" | "degraded"`.
- Response format is now strictly minimal:
  ```json
  {
    "status": "operational",
    "service": "NexOps",
    "version": "1.0.0"
  }
  ```

### New Regression Test Coverage (`tests/test_evidence_suite.py`):
1. `test_3_public_health_minimal_response`: Asserts status 200, strict key set `{"status", "service", "version"}`, and absence of `"database"` and `"commit_sha"` across both `/health` and `/api/v1/health`.
2. `test_3b_public_health_no_infra_substrings_leak`: Scans raw serialized response bodies to verify zero appearance of DB hostnames, ports, DB names, Neon domains, Redis URLs, or infrastructure keywords (`"neon.tech"`, `"postgres"`, `"redis"`, `"branch"`, `"latency"`).
3. `test_3c_public_health_degraded_on_db_failure`: Simulates DB connectivity failure and asserts that `status` degrades to `"degraded"` without leaking internal error traces or exception strings in the payload.
4. `test_4_detailed_health_auth_gated`: Verifies that `GET /health/detailed` remains strictly gated behind authentication (returns 401/403 unauthenticated).

---

## 3. Verification & Test Evidence

### Health Check Suite Output:
```bash
/mnt/d/Projects/ReactJS/NexOps/backend/venv/Scripts/python.exe -m pytest tests/test_evidence_suite.py -k "health" -v
```
```
tests/test_evidence_suite.py::test_3_public_health_minimal_response PASSED [ 25%]
tests/test_evidence_suite.py::test_3b_public_health_no_infra_substrings_leak PASSED [ 50%]
tests/test_evidence_suite.py::test_3c_public_health_degraded_on_db_failure PASSED [ 75%]
tests/test_evidence_suite.py::test_4_detailed_health_auth_gated PASSED   [100%]
================= 4 passed, 6 deselected, 5 warnings in 9.96s =================
```

---

## 4. Complete File Diff

```diff
diff --git a/app/main.py b/app/main.py
index b1158a5..fb140ff 100644
--- a/app/main.py
+++ b/app/main.py
@@ -227,15 +227,8 @@ async def health_check():
 
     db_ok = False
     redis_ok = False
-    db_branch = "unknown"
     try:
-        db_url_str = settings.DATABASE_URL or ""
-        if "@" in db_url_str:
-            host_part = db_url_str.split("@")[1].split("/")[0]
-            db_branch = host_part.split(".")[0]
-        elif "://" in db_url_str:
-            db_branch = db_url_str.split("://")[1].split("/")[0]
-
         async with async_session() as s:
             await s.execute(text("SELECT 1"))
         db_ok = True
@@ -254,10 +247,6 @@ async def health_check():
         "status": status,
         "service": settings.APP_NAME,
         "version": "1.0.0",
-        "database": {
-            "connected": db_ok,
-            "branch": db_branch,
-        }
     }
```
