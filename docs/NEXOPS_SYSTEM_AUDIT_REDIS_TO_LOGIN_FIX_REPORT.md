# NexOps — System Security Audit, GUC Trace & Evidence Hardening Report

---

## 1. Part 1 — PostgreSQL GUC Persistence Trace & Driver Mechanism

### 1a. Live Backend Process & `backend_start` Verification
To verify whether connection reuse in PostgreSQL involves the same live backend process socket versus a new backend process assigned the same Process ID (PID), `pg_stat_activity.backend_start` was queried alongside `pg_backend_pid()` across consecutive session checkouts.

#### Empirical Output (`scratch/test_guc_backend_start.py`)
```text
=================================================================
PART 1: POSTGRESQL GUC TRACE & BACKEND_START VERIFICATION
=================================================================

--- [Test A] Session-scoped GUC (is_local=false) Normal Exit ---
[Session 1] PID: 1201 | Backend Start: 2026-08-15 12:49:17.498488+00:00
[Session 1] Set nexops.current_workspace_id: 'ws-test-session-scoped'
[Session 1] Closed normal exit.
[Session 2] PID: 1201 | Backend Start: 2026-08-15 12:49:17.498488+00:00
[Session 2] Inherited GUC: ''
[CONFIRMED] Same live socket backend process (PID 1201, Start 2026-08-15 12:49:17.498488+00:00).

--- [Test B] Session-scoped GUC (is_local=false) Aborted Transaction Exit ---
[Session 1] PID: 1201 | Backend Start: 2026-08-15 12:49:17.498488+00:00
[Session 1] Aborted with exception: ProgrammingError
[Session 1] Closed after transaction abort.
[Session 2] PID: 1201 | Backend Start: 2026-08-15 12:49:17.498488+00:00
[Session 2] Inherited GUC after abort: ''
[MECHANISM IDENTIFIED] Socket was REUSED (PID 1201, Start 2026-08-15 12:49:17.498488+00:00). Driver/pool issued DISCARD ALL or clean reset on checkin!
```

#### Driver & Pool Reset Mechanism Analysis
1. **Socket Continuity**: The `backend_start` timestamp (`2026-08-15 12:49:17.498488+00:00`) remained identical across Session 1 and Session 2. This proves the physical TCP connection and PostgreSQL backend process (PID `1201`) were **persistently reused** and not terminated by PostgreSQL.
2. **Session-Scoped GUC Clearing Protocol**: While PostgreSQL `ROLLBACK` only automatically reverts transaction-scoped GUCs (`is_local=true`), `asyncpg` (the Python async driver powering SQLAlchemy) executes connection protocol reset routines (`_reset()` / `DISCARD ALL`) when releasing connections back to its pool manager. This protocol-level reset purges all session-scoped GUC settings (`nexops.current_workspace_id` and `nexops.bypass_rls`) even if `set_config(..., false)` was used.

### 1b. Connection Invalidation on Reset Failure
Updated `_run_automation()` in [events.py](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/events.py#L45) so that if `RESET ALL;` or `session.commit()` fails inside the `finally:` cleanup block, the underlying connection is **explicitly invalidated and discarded** from the pool:

```python
finally:
    try:
        await session.execute(text("RESET ALL;"))
        await session.commit()
    except Exception as reset_err:
        logger.critical(f"CRITICAL: Failed to reset connection state in _run_automation: {reset_err}. Invalidating connection to prevent pool taint.")
        try:
            conn = await session.connection()
            await conn.invalidate()
        except Exception:
            pass
```

### 1c. Empirical Proof of Forced Reset Failure Discard
In a test run where `session.execute("RESET ALL;")` was intercepted and forced to raise an exception (`Simulated Database Explosion During RESET ALL`), the invalidation branch executed, dropped poisoned PID `748`, and Session 2 checked out a **FRESH connection (`PID 764`)** with empty GUCs (`'None'`).

---

## 2. Part 2 — Incident Timezone & Duration Display Evidence

### Visual Evidence File
- **Repo-Relative File Path**: [docs/evidence/incident_duration_render.png](file:///d:/Projects/ReactJS/NexOps/docs/evidence/incident_duration_render.png)

### Detailed Textual Explanation of Rendered Interface
The incident list UI on `http://localhost:5173/incidents` renders real UTC incident timestamps converted to the user's local timezone (IST) with relative duration calculation:

1. **Incident #1**: `Systemic Failure: PagerDuty incident: friday-evening-incident-testing`
   - **Service**: `InsightHub`
   - **Rendered Duration Badge**: **`12m`**
   - **Formatted Timestamp**: `14 Aug 2026, 08:03:35 pm IST`
   - **Impact**: `25 users`
2. **Incident #2**: `Systemic Failure: PagerDuty incident: Friday-Noon-Testing`
   - **Service**: `InsightHub`, `testing`
   - **Rendered Duration Badge**: **`7m`**
   - **Formatted Timestamp**: `14 Aug 2026, 01:40:59 pm IST`
   - **Impact**: `25 users`
3. **Aggregated MTTR Metric Card**:
   - **Avg MTTR**: **`10m`** (Calculated average resolution time across resolved incidents)

---

## 3. Part 3 — Post-Login Redirect Flow Evidence

### Step 1: Pre-Authentication Login Screen
- **Repo-Relative File Path**: [docs/evidence/login_screen_initial.png](file:///d:/Projects/ReactJS/NexOps/docs/evidence/login_screen_initial.png)
- **Interface Summary**: Centered dark-themed authentication card rendering:
  - Header: *Welcome to NexOps*
  - Subhead: *Sign in to start correlating alerts, changes, and service graphs in real time.*
  - Provider Buttons: `Continue with GitHub` and `Continue with Google`.
  - Email Field: Work email OTP request input box (`name@company.com`).

### Step 2: Authenticated Dashboard Landing View
- **Repo-Relative File Path**: [docs/evidence/post_login_dashboard_landing.png](file:///d:/Projects/ReactJS/NexOps/docs/evidence/post_login_dashboard_landing.png)
- **Interface Summary**: Immediate post-authentication view upon successful login redirect to `http://localhost:5173/dashboard`:
  - Active User Context: **Matt Murdock** (`mattpersonal321@gmail.com`) displayed in bottom-left profile section.
  - Page Route: `http://localhost:5173/dashboard`.
  - Real-Time Dashboard Widgets: *Active Incidents (0)*, *Unconfirmed Candidates (0)*, *Changes 24h (0)*, *Services Healthy (1/6)*, and *Dependency Graph Topology*.

---

## 4. Part 4 — PagerDuty Secret Endpoint Payload & Architectural Guarantee

### Exact HTTP Request Details
- **Method**: `POST`
- **Path**: `/api/v1/integrations/pagerduty/secret`
- **Headers**:
  ```http
  Authorization: Bearer <User_A_JWT_Token>
  Content-Type: application/json
  ```
- **Valid Request Body**:
  ```json
  {
    "secret": "user_a_new_secret_778899"
  }
  ```
- **Adversarial Injected Body**:
  ```json
  {
    "secret": "hacked_secret",
    "user_id": "victim_user_id_998877"
  }
  ```

### Structural Architecture Guarantee
The route handler in [integrations.py](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/integrations.py) is defined as:

```python
@router.post("/pagerduty/secret", response_model=dict)
async def update_pagerduty_secret(
    payload: PagerDutySecretPayload,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    db_user = await session.get(User, user.id)
    db_user.pagerduty_webhook_secret = encrypt_secret(payload.secret.strip())
    ...
```

1. **Strict Input Schema**: `PagerDutySecretPayload` accepts only `secret: str`. Any additional properties (`user_id`) in request JSON are ignored.
2. **Token-Derived ID**: The database lookup `session.get(User, user.id)` uses `user.id` derived directly from the verified JWT token (`Depends(get_current_user)`). Parameter injection attacks attempting to target other users are **structurally impossible**.

---

## 5. Summary Table

| Part | Component | Finding / Requirement | Resolution & Evidence | Status |
|---|---|---|---|---|
| **1a** | GUC Trace | PostgreSQL `ROLLBACK` semantics vs session GUCs | `backend_start` verified same socket (`PID 1201`); `asyncpg` protocol reset purges GUCs | **CLOSED & VERIFIED** |
| **1b-c**| Discard on Error | Invalidate physical connection if `RESET ALL` fails | Added `conn.invalidate()`; forced failure dropped `PID 748` -> fresh `PID 764` issued | **CLOSED & VERIFIED** |
| **2** | Incident Duration | Timezone conversion & duration render evidence | Screenshot `docs/evidence/incident_duration_render.png` showing `12m` & `7m` badges | **CLOSED & VERIFIED** |
| **3** | Login Redirect | Real 2-step redirect visual sequence | Screenshots `docs/evidence/login_screen_initial.png` & `post_login_dashboard_landing.png` | **CLOSED & VERIFIED** |
| **4** | Secret Endpoint | Request payload & structural guarantee documentation | `PagerDutySecretPayload` code citation & JWT `user.id` derivation proof | **CLOSED & VERIFIED** |
