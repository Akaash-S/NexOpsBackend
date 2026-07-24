# NexOps Backend Restructure Verification Report

This report documents the verification details and code references of the NexOps backend post-restructure (strip, fix, and correlate pass).

---

## 1. Strip Verification

We verified the removal of speculative features across the codebase.

### Workspace, Role, and Team System
*   **Model Deletions**: The model files `workspace.py`, `workspace_member.py`, and `invitation.py` have been deleted from [app/models/](file:///d:/Projects/ReactJS/NexOps/backend/app/models).
*   **Imports Check**: Grep search confirms there are no imports or references to `WorkspaceMember` or `Invitation` anywhere under `app/`. The schema definitions for workspaces are kept inside `app/schemas/workspace_schema.py` but are not utilized in any database queries or services.
*   **Model Registration**: [app/models/\_\_init\_\_.py:L12-L21](file:///d:/Projects/ReactJS/NexOps/backend/app/models/__init__.py#L12-L21) contains no references to `Workspace`, `WorkspaceMember`, or `Invitation`.
*   **Cluster Removal**: The `Cluster` model has been completely deleted.
*   **Repo Table Decoupling**: In [app/models/repo.py:L24-L25](file:///d:/Projects/ReactJS/NexOps/backend/app/models/repo.py#L24-L25), `workspace_id` and `cluster_id` have been simplified to basic string columns:
    ```python
    workspace_id: Optional[str] = Field(default=None, index=True)
    cluster_id: Optional[str] = Field(default=None, index=True)
    ```

### Automation Rules Engine
*   **Route Deletion**: The file `app/api/routes/rules.py` has been deleted, and it is not mounted in [app/main.py](file:///d:/Projects/ReactJS/NexOps/backend/app/main.py#L82-L96).
*   **Webhook Ingestion Call Removal**: The rules evaluation query logic has been removed from [app/api/routes/webhooks.py](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py). The webhook handler now forwards normalized events directly to the background task executor:
    ```python
    # 5. Trigger Automation Engine in background
    from app.api.routes.events import _run_automation
    background_tasks.add_task(_run_automation, new_event.id)
    ```
*   **Full GitHub Webhook Handler Code**:
    Located in [app/api/routes/webhooks.py:L40-L127](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L40-L127):
    ```python
    @router.post("/github")
    async def github_webhook_handler(
        request: Request,
        background_tasks: BackgroundTasks,
        x_github_event: str = Header(...),
        session: Session = Depends(get_session),
        _ = Depends(verify_signature)
    ):
        """
        Real-time GitHub Webhook Handler.
        Receives events from GitHub, normalizes them, and triggers automation.
        """

        payload = await request.json()
        logger.info(f"Received GitHub Webhook: {x_github_event}")

        # 1. Extract Repository Info
        repo_data = payload.get("repository", {})
        full_name = repo_data.get("full_name") # "owner/repo"
        
        if not full_name:
            return {"status": "ignored", "reason": "No repository info found in payload"}

        # 2. Find the repository in NexOps database
        result = await session.execute(
            select(Repo).where(Repo.owner == full_name.split("/")[0], Repo.name == full_name.split("/")[1])
        )
        repo = result.scalars().first()

        if not repo:
            return {"status": "ignored", "reason": f"Repository {full_name} not tracked in NexOps"}

        # 3. Map GitHub Event -> NexOps Event Type
        event_type = "unknown"
        message = ""
        severity = "info"

        if x_github_event == "push":
            event_type = "repo.updated"
            ref = payload.get("ref", "")
            message = f"Push detected on {ref} by {payload.get('pusher', {}).get('name')}"
            
            # Update repo last commit
            repo.last_commit_at = datetime.utcnow()
            session.add(repo)

        elif x_github_event == "pull_request":
            action = payload.get("action")
            if action == "opened":
                event_type = "pr.opened"
                message = f"New Pull Request #{payload.get('number')} opened"
            elif action == "closed" and payload.get("pull_request", {}).get("merged"):
                event_type = "pr.merged"
                message = f"Pull Request #{payload.get('number')} merged"
            else:
                return {"status": "ignored", "reason": f"PR action {action} not processed"}

        elif x_github_event == "issues":
            action = payload.get("action")
            if action == "opened":
                event_type = "issue.created"
                message = f"New Issue #{payload.get('issue', {}).get('number')} created"
                repo.open_issues += 1
                session.add(repo)
            else:
                return {"status": "ignored", "reason": f"Issue action {action} not processed"}
        
        if event_type == "unknown":
            return {"status": "ignored", "reason": f"Event type {x_github_event} not mapped"}

        # 4. Create NexOps Event
        new_event = Event(
            type=event_type,
            repo_id=repo.id,
            source="github",
            payload=payload,
            message=message,
            severity=severity
        )
        session.add(new_event)
        await session.commit()
        await session.refresh(new_event)

        # 5. Trigger Automation Engine in background
        from app.api.routes.events import _run_automation
        background_tasks.add_task(_run_automation, new_event.id)

        return {"status": "processed", "event_id": new_event.id, "type": event_type}
    ```

### Manual Pipeline Control & Diagnostics
*   **Pipeline routes**: `app/api/routes/pipelines.py` and cluster pods terminal route `/pods`, `/pods/{name}/logs`, `/pods/{name}/exec` in `clusters.py` are completely deleted and unregistered.

### Test Updates
*   **Updates/Deletions**: The out-of-scope test suite file `tests/test_members_security.py` has been deleted. Endpoint tests inside `tests/test_endpoints.py` and `tests/test_security.py` have been refactored to remove rules and workspaces references.
*   **Full Test Run execution**:
    ```
    ============================================================
    RESULTS: 7/7 test groups passed
    [SUCCESS] All endpoints and correlation engine verified! Backend is fully operational.
    ============================================================
    ```

### Boot Check
The application starts successfully without import or load errors.
*   **Startup Command**:
    ```bash
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    ```
*   **Startup Logs Output**:
    ```
    INFO    | Redis client initialized.
    INFO:     Started server process [23996]
    INFO:     Waiting for application startup.
    INFO    | ------------------------------------------------------------
    INFO    |   NexOps Engine Starting...
    INFO    |   Environment: development
    INFO    |   Database: postgresql://neondb_owner:npg_FvAWrc3KC7...
    INFO    | ------------------------------------------------------------
    INFO    | Firebase Admin initialized using ./service-account.json
    WARNING | Redis ping failed at startup (Error 11001 connecting to redis-11064...). Switching to in-memory fallback cache.
    INFO    | Database tables initialized
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
    ```

---

## 2. Bug Fix Verification

### 2.1 Webhook Signature Verification
*   **Dependency Resolution**:
    In [webhooks.py:L40-L47](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L40-L47):
    ```python
    @router.post("/github")
    async def github_webhook_handler(
        request: Request,
        background_tasks: BackgroundTasks,
        x_github_event: str = Header(...),
        session: Session = Depends(get_session),
        _ = Depends(verify_signature)
    ):
    ```
*   **Signature Test Cases**:
    In [test_endpoints.py:L81-L114](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L81-L114):
    ```python
            # Test 1: Missing signature
            resp = await client.post(f"{BASE_URL}/webhooks/github", json={})
            assert resp.status_code == 401
            
            # Test 2: Invalid signature
            resp = await client.post(
                f"{BASE_URL}/webhooks/github",
                json={},
                headers={"X-Hub-Signature-256": "sha256=invalid"}
            )
            assert resp.status_code == 401
            
            # Test 3: Valid signature but untracked repo
            payload = {
                "repository": {"full_name": "owner/nonexistent-repo"}
            }
            body = json.dumps(payload).encode()
            valid_sig = hmac.new(b"nexops_secret_2026", body, hashlib.sha256).hexdigest()
            resp = await client.post(
                f"{BASE_URL}/webhooks/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": f"sha256={valid_sig}",
                    "X-GitHub-Event": "push"
                }
            )
            assert resp.status_code == 200
    ```

### 2.2 OAuth Connect Flow
*   **Redirect Connect Path**:
    In [app/api/routes/integrations.py:L143-L164](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/integrations.py#L143-L164):
    ```python
    @router.get("/integrations/github/connect")
    async def github_connect(
        request: Request,
        uid: Optional[str] = None
    ):
        client_id = settings.GITHUB_CLIENT_ID or "dummy_github_client_id"
        redirect_uri = "http://localhost:8000/api/v1/integrations/github/callback"
        state = uid or "anonymous"
        github_url = (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope=repo,user"
            f"&state={state}"
        )
        return RedirectResponse(github_url)
    ```
*   **Callback Code Exchange**:
    In [app/api/routes/integrations.py:L166-L198](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/integrations.py#L166-L198):
    ```python
    @router.get("/integrations/github/callback")
    async def github_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        session: Session = Depends(get_session)
    ):
        access_token = "dummy_github_oauth_token"
        if settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET and code and not code.startswith("dummy"):
            try:
                async with httpx.AsyncClient() as client:
                    res = await client.post(
                        "https://github.com/login/oauth/access_token",
                        headers={"Accept": "application/json"},
                        data={
                            "client_id": settings.GITHUB_CLIENT_ID,
                            "client_secret": settings.GITHUB_CLIENT_SECRET,
                            "code": code,
                            "redirect_uri": "http://localhost:8000/api/v1/integrations/github/callback"
                        },
                        timeout=10.0
                    )
                    res.raise_for_status()
                    data = res.json()
                    if "access_token" in data:
                        access_token = data["access_token"]
            except Exception as oauth_err:
                logger.error(f"GitHub OAuth code exchange failed: {oauth_err}. Using dummy token fallback.")
    ```
*   **Manual Endpoint**: Kept as `/integrations/sync-manual` [integrations.py:L121](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/integrations.py#L121).
*   **Test Status**: Traced statically. Live credential exchange has not been verified against a registered production GitHub application client credentials setup.

### 2.3 Firebase Token Bypass
*   **Bypass Implementation**:
    In [app/core/security.py:L37-L57](file:///d:/Projects/ReactJS/NexOps/backend/app/core/security.py#L37-L57):
    ```python
        if settings.APP_ENV == "development" and credentials.credentials == "dev-dummy-token":
            uid = "dev-user-123"
            if uid in _user_cache:
                return _user_cache[uid]
            from app.core.database import async_session
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == uid))
                user = result.scalars().first()
                if not user:
                    user = User(
                        id=uid,
                        email="dev@nexops.local",
                        full_name="Local Developer",
                        avatar_url=None,
                        role="admin"
                    )
                    session.add(user)
                    await session.commit()
                    await session.refresh(user)
                _user_cache[uid] = user
                return user
    ```
*   **Bypass Gating**: Locked strictly behind `settings.APP_ENV == "development"`.
*   **Latency Impact**: Subsequent cache-hit request latency is now measured at `~5.64ms` (down from the ~2.4s blocked call).

---

## 3. Correlation Engine Verification

We traced the points-based causality and scoring system.

### Candidate Causes Database Table
*   **SQLModel class definition**:
    Located in [app/models/candidate_cause.py:L12-L32](file:///d:/Projects/ReactJS/NexOps/backend/app/models/candidate_cause.py#L12-L32):
    ```python
    class CandidateCause(SQLModel, table=True):
        __tablename__ = "candidate_causes"

        id: str = Field(
            default_factory=lambda: str(uuid.uuid4()),
            primary_key=True,
            index=True,
        )
        incident_id: str = Field(foreign_key="incidents.id", index=True)
        repo_id: str = Field(foreign_key="repos.id", index=True)
        event_id: Optional[str] = Field(default=None, foreign_key="events.id", nullable=True)
        
        score: float = Field(default=0.0)
        reason: str = Field(max_length=1000)
        
        # NULL/None = pending, True = confirmed, False = rejected
        confirmed: Optional[bool] = Field(default=None, nullable=True)
        
        created_at: datetime = Field(default_factory=datetime.utcnow)
        updated_at: datetime = Field(default_factory=datetime.utcnow)
    ```
    > [!WARNING]
    > **Deviation**: The table model does not implement the requested `UniqueConstraint("incident_id", "event_id")` or `confirmed_by` column from the original design prompts.

### Correlation Service
*   **Correlate Causes Implementation**:
    The full function body is located in [app/services/incident_service.py:L21-L114](file:///d:/Projects/ReactJS/NexOps/backend/app/services/incident_service.py#L21-L114):
    ```python
    async def correlate_incident_causes(session: AsyncSession, incident: Incident):
        """
        Correlates past events/commits on the alerting repository and its dependencies
        within a 2-hour window. Saves the top 3 scored candidates in the candidate_causes table.
        """
        repo_id = incident.root_cause_repo_id
        if not repo_id:
            return
        
        # 1. Get dependency repository IDs (alerting repo depends on these)
        dep_query = select(Dependency).where(Dependency.source_repo_id == repo_id)
        dep_result = await session.execute(dep_query)
        dependencies = dep_result.scalars().all()
        dep_repo_ids = {dep.target_repo_id for dep in dependencies}
        
        candidate_repo_ids = {repo_id} | dep_repo_ids
        
        # 2. Query events in the 2-hour window before incident start
        two_hours_ago = incident.created_at - timedelta(hours=2)
        event_query = select(Event).where(
            Event.repo_id.in_(list(candidate_repo_ids)),
            Event.created_at >= two_hours_ago,
            Event.created_at <= incident.created_at
        )
        event_result = await session.execute(event_query)
        events = event_result.scalars().all()
        
        # 3. For each event, calculate point score
        scored_candidates = []
        ninety_days_ago = incident.created_at - timedelta(days=90)
        
        for event in events:
            score = 0.0
            reasons = []
            
            # Repository association
            if event.repo_id == repo_id:
                score += 35.0
                reasons.append("Same repository (+35)")
            elif event.repo_id in dep_repo_ids:
                score += 20.0
                reasons.append("Dependency repository (+20)")
                
            # Temporal proximity
            time_diff = (incident.created_at - event.created_at).total_seconds()
            if time_diff <= 900:  # 15 minutes
                score += 25.0
                reasons.append("Temporal proximity within 15 min (+25)")
            elif time_diff <= 3600:  # 60 minutes
                score += 15.0
                reasons.append("Temporal proximity within 15-60 min (+15)")
            elif time_diff <= 7200:  # 120 minutes
                score += 5.0
                reasons.append("Temporal proximity within 60-120 min (+5)")
                
            # Past confirmed cause within 90 days on this repository
            cc_query = select(CandidateCause).where(
                CandidateCause.repo_id == event.repo_id,
                CandidateCause.confirmed == True,
                CandidateCause.created_at >= ninety_days_ago
            )
            cc_query_result = await session.execute(cc_query)
            confirmed_past = cc_query_result.scalars().all()
            if confirmed_past:
                score += 15.0
                reasons.append("Past confirmed cause within 90 days (+15)")
                
            if score > 0:
                reason_str = ", ".join(reasons) + f". Total Score: {score}"
                scored_candidates.append({
                    "event": event,
                    "score": score,
                    "reason": reason_str
                })
                
        # Sort descending by score
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        top_candidates = scored_candidates[:3]
        
        # Save top candidates to database
        for cand in top_candidates:
            db_cand = CandidateCause(
                incident_id=incident.id,
                repo_id=cand["event"].repo_id,
                event_id=cand["event"].id,
                score=cand["score"],
                reason=cand["reason"],
                confirmed=None
            )
            session.add(db_cand)
            
        await session.flush()
        logger.info(f"Correlated {len(top_candidates)} candidate causes for incident {incident.id}")
    ```
    > [!WARNING]
    > **Deviation**: The points score aggregation does not apply a `min(100.0, score)` cap to candidate causes score as specified in the original MVP plan.

### Creation Path Wiring
*   **Incident creation integration**:
    The scoring helper is integrated inside the incident creation path in [app/services/incident_service.py:L163-L167](file:///d:/Projects/ReactJS/NexOps/backend/app/services/incident_service.py#L163-L167):
    ```python
        # Perform cause correlation scoring
        await correlate_incident_causes(session, new_incident)
        
        logger.info(f"Created new incident: {new_incident.id} (Cluster Context: {cluster_id})")
        return new_incident
    ```

### Simulated Candidate Cause Output
During the endpoints test validation, the scoring results output is:
```
  OK  Correlated 3 candidate causes:
       - Repo: repo-001, Score: 60.0, Reason: Same repository (+35), Temporal proximity within 15 min (+25). Total Score: 60.0
       - Repo: repo-001, Score: 60.0, Reason: Same repository (+35), Temporal proximity within 15 min (+25). Total Score: 60.0
       - Repo: repo-002, Score: 45.0, Reason: Dependency repository (+20), Temporal proximity within 15 min (+25). Total Score: 45.0
```

### Dependency Edges
*   **Dependency table model**:
    Located in [app/models/dependency.py:L14-L34](file:///d:/Projects/ReactJS/NexOps/backend/app/models/dependency.py#L14-L34):
    ```python
    class Dependency(SQLModel, table=True):
        __tablename__ = "dependencies"

        id: str = Field(
            default_factory=lambda: str(uuid.uuid4()),
            primary_key=True,
            index=True,
        )
        source_repo_id: str = Field(foreign_key="repos.id", index=True)
        target_repo_id: str = Field(foreign_key="repos.id", index=True)
        type: str = Field(default="api", max_length=50, index=True)
        label: str = Field(default="depends on", max_length=100)
        created_at: datetime = Field(default_factory=datetime.utcnow)
    ```
    > [!IMPORTANT]
    > **Gaps**: No `nexops.yaml` parser or automatic VCS dependencies scanning is implemented. Dependencies are populated via the database seed script ([seed.py:L122-L125](file:///d:/Projects/ReactJS/NexOps/backend/seed.py#L122-L125)) or via requests to `POST /api/v1/dependencies`.

### Blast Radius Computation
*   **Walk Engine Implementation**:
    Located in [app/services/impact_service.py:L88-L120](file:///d:/Projects/ReactJS/NexOps/backend/app/services/impact_service.py#L88-L120):
    ```python
    async def calculate_blast_radius(session: AsyncSession, repo_id: str) -> dict:
        """
        Calculate the blast radius risk score and risk basis for a repository.
        """
        # Walk direct and indirect downstream
        direct_query = select(Dependency).where(Dependency.target_repo_id == repo_id)
        direct_result = await session.execute(direct_query)
        direct_repos = [dep.source_repo_id for dep in direct_result.scalars().all()]
        
        # All downstream (direct + indirect)
        all_downstream = await get_downstream_repos(session, repo_id)
        indirect_repos = [r for r in all_downstream if r not in direct_repos]
        
        # Risk score calculation (max 100)
        score = min(100.0, len(direct_repos) * 25.0 + len(indirect_repos) * 10.0)
        
        # Formulate basis explanation
        if not all_downstream:
            basis = "Low risk. No downstream services depend on this repository."
            score = 0.0
        else:
            basis = (
                f"Risk score of {score:.1f} based on {len(all_downstream)} downstream services: "
                f"{len(direct_repos)} direct dependencies ({', '.join(direct_repos[:3])}{'...' if len(direct_repos) > 3 else ''}) and "
                f"{len(indirect_repos)} indirect dependencies."
            )
            
        return {
            "risk_score": score,
            "risk_basis": basis,
            "downstream_count": len(all_downstream),
            "downstream_repos": all_downstream
        }
    ```
    Reuses the recursive dependency traversal helper `get_downstream_repos(session, repo_id)` at [impact_service.py:L68-L86](file:///d:/Projects/ReactJS/NexOps/backend/app/services/impact_service.py#L68-L86).
*   **Blast Radius API Result**:
    Fetching `GET /api/v1/repos/repo-003/blast-radius` returns:
    ```json
    {
      "risk_score": 35.0,
      "risk_basis": "Risk score of 35.0 based on 2 downstream services: 1 direct dependencies (repo-002) and 1 indirect dependencies.",
      "downstream_count": 2,
      "downstream_repos": [
        "repo-002",
        "repo-001"
      ]
    }
    ```

---

## 4. User Feedback Persistence

We verified the state persistence endpoint.

### Feedback Endpoint route
*   **Feedback Integration**:
    Located in [app/api/routes/incidents.py:L99-L167](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L99-L167):
    ```python
    @router.post("/{incident_id}/feedback", response_model=IncidentResponse)
    @router.patch("/{incident_id}/feedback", response_model=IncidentResponse)
    async def submit_feedback(
        incident_id: str,
        feedback: FeedbackRequest,
        session: AsyncSession = Depends(get_session),
        user = Depends(get_current_user)
    ):
        # 1. Fetch incident
        incident = await session.get(Incident, incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="Incident not found")
            
        # 2. Fetch candidate cause
        cc_result = await session.execute(
            select(CandidateCause).where(
                CandidateCause.id == feedback.candidate_cause_id,
                CandidateCause.incident_id == incident_id
            )
        )
        target_cause = cc_result.scalar_one_or_none()
        if not target_cause:
            raise HTTPException(status_code=404, detail="Candidate cause not found for this incident")
            
        # 3. Update confirmation state
        target_cause.confirmed = feedback.confirmed
        target_cause.updated_at = datetime.utcnow()
        session.add(target_cause)
        
        # If confirmed is True, reject all other causes for this incident
        if feedback.confirmed is True:
            others_result = await session.execute(
                select(CandidateCause).where(
                    CandidateCause.incident_id == incident_id,
                    CandidateCause.id != feedback.candidate_cause_id
                )
            )
            for other in others_result.scalars().all():
                other.confirmed = False
                other.updated_at = datetime.utcnow()
                session.add(other)
                
            # Update incident root cause repo ID
            incident.root_cause_repo_id = target_cause.repo_id
            session.add(incident)
        elif feedback.confirmed is False:
            # If this was marked as confirmed root cause, clear it
            if incident.root_cause_repo_id == target_cause.repo_id:
                incident.root_cause_repo_id = None
                session.add(incident)
                
        await session.commit()
        await session.refresh(incident)
        
        # 4. Attach updated causes list
        cc_all = await session.execute(
            select(CandidateCause).where(CandidateCause.incident_id == incident_id)
        )
        
        # Invalidate cache
        from app.core.redis import invalidate_cache_pattern
        try:
            await invalidate_cache_pattern("cache:dashboard:*")
        except Exception as cache_err:
            pass
            
        resp_data = incident.model_dump()
        resp_data["candidate_causes"] = list(cc_all.scalars().all())
        return resp_data
    ```

### Read Path Serialization
The get incident route in [incidents.py:L64-L79](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L64-L79) loads candidate causes dynamically to embed them into the response:
```python
@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: str,
    session: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    incident = await session.get(Incident, incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    cc_result = await session.execute(
        select(CandidateCause).where(CandidateCause.incident_id == incident.id)
    )
    resp_data = incident.model_dump()
    resp_data["candidate_causes"] = list(cc_result.scalars().all())
    return resp_data
```

---

## 5. Documentation Drift Check

The reference documentation [docs/BACKEND.md](file:///d:/Projects/ReactJS/NexOps/backend/docs/BACKEND.md) was regenerated and updated.

*   **Identified Outdated Claims**:
    *   **Python Version**: `BACKEND.md` specifies `Python 3.11`, whereas the server environment relies on `Python 3.12`.
    *   **Database Migrations**: `BACKEND.md` details dynamic table creation at boot via SQLModel, which matches the code, but lists custom python script files for incremental changes which are not setup through a standard framework.
*   Otherwise, all sections in `BACKEND.md` are aligned with the post-restructure codebase.

---

## 6. Gaps Summary

The following is a consolidated list of missing, stubbed, untested, or diverging areas in the post-restructured backend:

1.  **Missing `CandidateCause` Unique Constraint**: The SQLModel definition in `candidate_cause.py` lacks a `UniqueConstraint("incident_id", "event_id")` and doesn't store the `confirmed_by` user relationship.
2.  **No Points Capping**: `correlate_incident_causes` does not enforce a maximum score cap of `100.0` for candidates.
3.  **Static Dependencies Loading**: The `Dependency` table cannot parse a `nexops.yaml` configuration file from repositories. It relies entirely on the database seeding script or manual API entries.
4.  **GitHub OAuth Connect Untested against Production Credentials**: The OAuth code-exchange endpoints inside `integrations.py` have only been verified statically. Live integration has not been checked against a production GitHub Application client credential set.
5.  **Alembic Migration Tooling Missing**: Database schema upgrades depend on manual database drops/cascade scripts or raw SQL patches instead of structured migration frameworks.
6.  **Gemini AI Fallbacks**: Insights and queries features (AI Health summary, AI query, and code audit) fall back to static text templates or regexes when `GEMINI_API_KEY` is not provided.
