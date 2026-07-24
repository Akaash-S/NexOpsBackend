# NexOps Backend Restructure — Strip, Fix, Build Correlation — Agent Prompt

Use this as the instruction set for Claude Code working **in place** on the existing NexOps
backend. Read `docs/BACKEND.md` (the generated reference doc) fully before starting — it has
exact file/line references for everything mentioned below. This prompt has three parts, done
**in this order**: strip out-of-scope scope creep, fix two real defects in what remains, then
build the correlation engine that was the entire point of this backend.

---

## Why this order matters

The backend currently implements a multi-tenant workspace/role/invitation system, an
automation rules engine, manual pipeline trigger/cancel/retry, and Kubernetes pod
diagnostics — none of which were part of the MVP plan, and several of which were explicitly
cut from the *frontend* for the same reasons (automation/rules removed in the original
restructure; Kubernetes removed from Integrations scope). Meanwhile, the actual product
thesis — a real correlation/scoring function, a `candidate_causes` table, blast radius
computation, and feedback persistence — does not exist at all. `get_or_create_incident`
currently assigns root cause directly to whichever repo reported the alert, with zero
analysis. This is backwards: the hardest, most differentiating part of the product is the
part that's missing, while speculative platform scope got built instead.

Strip first so correlation logic gets built on a small, honest codebase — not layered on top
of, or entangled with, systems that don't belong in this MVP.

---

## Part 1 — Strip out-of-scope features

Remove the following entirely: routes, service files, models (where not needed by anything
else), and any background tasks tied to them. Do not leave dead imports or orphaned routes
registered in the router.

### Remove: Multi-tenant workspace/role/team system
- `app/models/workspace.py`, `app/models/workspace_member.py`, `app/models/invitation.py`,
  `app/models/cluster.py` and their tables — **unless** `Repo` (or whatever becomes the
  service-node equivalent) has a hard foreign-key dependency that's cheaper to keep than
  rip out. If `cluster_id` on `Repo` is the only real dependency, simplify `Repo` to drop
  that column rather than preserving the whole `Cluster` model just to satisfy one FK.
- `app/api/routes/workspaces.py`, `app/api/routes/members.py`, `app/api/routes/teams.py`
  and all their endpoints (workspace CRUD, member invite/list/remove, role elevation, team
  listing)
- Any role-based authorization checks (admin/lead role gating) tied to this system —
  if a simpler single-user/single-org model replaces it, document that assumption in a
  code comment at the top of `app/core/security.py`, don't silently leave half the
  authorization logic in place checking roles nothing assigns anymore

### Remove: Automation rules engine
- `app/api/routes/rules.py` and its model/service backing (rule CRUD, conditions, actions)
- The `_run_automation` call triggered from the GitHub webhook handler
  ([webhooks.py around L124-126]) — remove the call and the function entirely, not just
  the route

### Remove: Manual pipeline control
- `app/api/routes/pipelines.py` (trigger/cancel/retry/list/detail) and its backing service
  — this is CI/CD platform territory (GitLab/GitHub Actions own this), not NexOps's job per
  the original scope decision

### Remove: Pod/container diagnostics
- The `GET /pods`, `GET /pods/{name}/logs`, `POST /pods/{name}/exec` routes in
  `app/api/routes/clusters.py` (these were already flagged as hardcoded stubs — remove
  rather than implement, since Kubernetes was explicitly cut from frontend Integrations
  scope and shouldn't reappear here)
- The remainder of `clusters.py` should be removed if `Cluster` itself is removed per
  Part 1's first item

### Keep, unchanged
- `User`, `Repo` (simplified per above if needed), `Alert`, `Event` models and their tables
- The GitHub webhook ingestion path (after the Part 2 fix below)
- The VCS sync service (`vcs_service.py`) — GitHub/GitLab/Bitbucket repo listing — this is
  legitimate ingestion infrastructure, keep it
- Redis caching infrastructure and its tests
- Firebase auth — but see Part 2's note on the dev-token blocking issue

### Verify after stripping
- The app boots cleanly with no import errors from removed modules
- `app/models/__init__.py` no longer registers removed models
- `tests/test_endpoints.py`, `tests/test_security.py`, `tests/test_members_security.py` —
  update or remove test cases tied to removed routes; do not leave tests asserting behavior
  of code that no longer exists

---

## Part 2 — Fix two real defects

### Fix 2.1 — Webhook signature verification is structurally broken

Current code in `app/api/routes/webhooks.py` calls `verify_signature(request)` inline
instead of resolving it as a FastAPI dependency, so `x_hub_signature_256` always defaults to
`None` regardless of what header was actually sent. This means signature verification either
always fails (if a secret is set) or silently never runs correctly.

Fix: resolve `verify_signature` as a proper FastAPI dependency on the route, e.g.:
```python
@router.post("/webhooks/github")
async def github_webhook_handler(
    request: Request,
    _: None = Depends(verify_signature),
    ...
):
```
Confirm `x_hub_signature_256` is correctly read from the `X-Hub-Signature-256` header via
FastAPI's `Header(...)` parameter resolution when used this way, and that a real signed
test payload (HMAC-SHA256 over the raw body using a test secret) passes verification, and a
tampered payload or wrong secret correctly returns 401. Add or update a test case for both
cases in `tests/test_endpoints.py` or `tests/test_security.py`, whichever is more
appropriate.

### Fix 2.2 — OAuth connect flow accepts raw pasted tokens

Currently `POST /integrations/sync` expects the user to manually generate and paste an
access token. Replace with a real OAuth Authorization Code flow for GitHub at minimum (the
other providers in `vcs_service.py` can follow the same pattern later, but GitHub is the
priority since it's the integration the correlation engine actually depends on):

1. Add a GitHub OAuth App client ID/secret to `Settings` (`app/core/config.py`) and
   `.env.example`
2. `GET /integrations/github/connect` — redirects the user to GitHub's authorization URL
   with the configured client ID and scopes (`repo`, minimum needed to read CODEOWNERS and
   register webhooks)
3. `GET /integrations/github/callback` — receives the `code` param, exchanges it for an
   access token via GitHub's token endpoint, encrypts and stores it the same way the
   current manual-paste flow does (reuse the existing Fernet encryption call), then
   redirects back to the frontend's onboarding flow
4. Keep the existing manual-token path available behind a clearly-named
   `POST /integrations/sync-manual` or similar, for local development/testing only — don't
   delete the capability to manually test against a personal token, just stop presenting it
   as the primary connect flow

### Fix 2.3 (smaller, fold in here) — Firebase dev-token blocking call

`test_performance.py` already caught this: `auth.verify_id_token("dev-dummy-token")` makes
a real network call to Google's keyserver and blocks for ~2.4s on every request in dev/test
when using a dummy token. Add a dev-mode bypass in `app/core/security.py` —
e.g. if `settings.APP_ENV == "development"` and the token matches a configured dev-only
sentinel value, skip Firebase verification and return a fixed dev user, rather than letting
every local request pay a multi-second tax. Gate this clearly behind the environment check
so it can never accidentally apply in production.

---

## Part 3 — Build the correlation engine

This is the part of the backend MVP plan that's actually missing. Build it now, on the
stripped-down codebase from Part 1.

### 3.1 — `candidate_causes` table

Add a new SQLModel table:
```python
class CandidateCause(SQLModel, table=True):
    __tablename__ = "candidate_causes"
    id: Optional[int] = Field(default=None, primary_key=True)
    incident_id: str = Field(foreign_key="incidents.id", index=True)  # or alert id, match whatever the kept incident model is called post-strip
    event_id: str = Field(foreign_key="events.id", index=True)  # the candidate deploy/change event
    match_score: int
    match_reasons: list[str] = Field(sa_column=Column(JSON))
    confirmed: Optional[bool] = Field(default=None)
    confirmed_by: Optional[str] = Field(default=None, foreign_key="users.id")
    confirmed_at: Optional[datetime] = Field(default=None)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("incident_id", "event_id"),)
```
Adjust foreign key targets to match whatever the post-strip incident/event model names
actually are — check `docs/BACKEND.md`'s existing `Alert`/`Event` model definitions before
finalizing column types.

Generate the corresponding Alembic migration (or whatever migration tool is already
configured per `docs/BACKEND.md` section 2).

### 3.2 — Replace `get_or_create_incident`'s root-cause assignment

Currently this function assigns root cause directly to the reporting repo with no analysis.
Replace that direct assignment with a call to a new scoring function:

```python
async def correlate_incident_causes(incident_id: str, session: AsyncSession) -> list[CandidateCause]:
    """
    For the given incident, look back at events within a configurable window
    (default 2 hours) on the alerting repo and its direct dependency neighbors,
    score each as a candidate cause, persist the top 3, and return them.
    """
```

Scoring logic (deterministic, explainable — no ML, no LLM call in this path):

| Signal | Points | Reason text |
|---|---|---|
| Event is on the exact alerting repo | +35 | `"event occurred directly on {repo_name}"` |
| Event is on a direct dependency of the alerting repo (if a dependency-edge model exists — see 3.4 if not) | +20 | `"touches {repo_name}, a direct dependency"` |
| Event occurred within 15 min before alert `created_at` | +25 | `"occurred {N} min before the alert fired"` |
| Event occurred 15-60 min before | +15 | same shape |
| Event occurred 60-120 min before | +5 | same shape |
| A past `CandidateCause` for this repo with `confirmed = true` exists within the last 90 days, same event type | +15 | `"similar to a confirmed cause for incident {past_incident_id}"` |

Sum, cap at 100, take the top 3 by score, write them to `candidate_causes`, return them.
Every point awarded must produce a corresponding string appended to `match_reasons` — never
award points silently. This mirrors the existing `match_reasons` shape the frontend already
expects (verify against the frontend's `ScoreWithReasoning` prop shape if accessible).

Call this function from wherever `get_or_create_incident` currently does direct root-cause
assignment, replacing that assignment, not running alongside it.

### 3.3 — Feedback persistence endpoint

```
POST /api/incidents/{incident_id}/feedback
body: { event_id: str, confirmed: bool }
```
Writes `confirmed`, `confirmed_by` (from the authenticated user), `confirmed_at` onto the
matching `CandidateCause` row. Returns the updated record. Add a corresponding GET behavior
check: confirm that fetching an incident's detail afterward includes this `confirmed` state
from the database — not always `null` regardless of history (this was explicitly flagged as
broken/missing in `docs/BACKEND.md` section 6).

### 3.4 — Dependency edges (only if no dependency model currently exists)

Check `docs/BACKEND.md` for whether any existing model captures repo-to-repo dependency
relationships (distinct from `Cluster` grouping, which is being removed). If none exists,
add a minimal table:
```python
class DependencyEdge(SQLModel, table=True):
    __tablename__ = "dependency_edges"
    id: Optional[int] = Field(default=None, primary_key=True)
    from_repo_id: str = Field(foreign_key="repos.id", index=True)
    to_repo_id: str = Field(foreign_key="repos.id", index=True)
    source: str = Field(default="manual")  # how this edge was derived
    __table_args__ = (UniqueConstraint("from_repo_id", "to_repo_id"),)
```
Seed it by parsing a `nexops.yaml` file (if present in a repo, fetched via the existing VCS
service's file-content endpoint) declaring that repo's dependencies. If `nexops.yaml` isn't
present for a repo, that repo simply has no derived edges yet — don't block ingestion on its
absence.

### 3.5 — Blast radius computation

Reuse `impact_service.py`'s existing downstream traversal (`propagate_impact`) as the
graph-walking foundation, but produce the actual missing output: a `risk_score` and
`risk_basis` string per event, computed similarly to the correlation scoring above (e.g. base
score from the repo's recent alert count in the last 30 days, plus a bump if any
direct/downstream dependency has a `confirmed = true` candidate cause on record). Store this
alongside the event or in a small dedicated table — match whatever shape is simplest given
the post-strip `Event`/`Repo` models.

---

## What NOT to change

- Do not modify `vcs_service.py`'s repo-listing logic beyond what's needed to support the
  OAuth flow in Part 2.2
- Do not modify Redis caching configuration or its tests
- Do not add any new platform features beyond what's specified above — if something feels
  like a nice addition while in this code, write it down for later instead of building it
  now

---

## Definition of done

1. App boots with no references to removed workspace/role/automation/pipeline/pod code
2. A real signed GitHub webhook payload passes signature verification; a tampered one
   returns 401 — both covered by a test
3. GitHub connect flow redirects through a real OAuth authorization URL and exchanges a real
   code for a token — no more "paste your token" as the primary path
4. Local/dev requests no longer block ~2.4s per request on Firebase dummy-token verification
5. `candidate_causes` table exists, is populated by `correlate_incident_causes` with real
   scores and non-empty `match_reasons` for every candidate — not a hardcoded root cause
   assignment
6. `POST /api/incidents/{id}/feedback` persists confirm/reject state, and a subsequent GET
   for that incident reflects it
7. Blast radius (`risk_score` + `risk_basis`) is computed and retrievable for at least one
   real event end to end
8. `docs/BACKEND.md` is regenerated or manually updated to reflect the post-strip,
   post-build state — stale docs describing removed features are a deliverable gap, same
   standard as the frontend restructure
