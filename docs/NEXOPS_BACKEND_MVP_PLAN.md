# NexOps Backend MVP — Architecture & Build Plan

## Scope discipline, stated up front

This is the same discipline that made the frontend restructure work: build the smallest
thing that proves the actual claim, not the smallest thing that looks like a platform.

**The claim being tested:** given a real dependency graph, real deploy events, and real
alerts, NexOps can rank likely-cause deploys for an incident and compute blast radius for a
deploy — and get measurably better at this as humans confirm or reject its candidates.

**Everything in this plan exists to test that claim.** Nothing else. No multi-tenancy, no
billing, no role-based access control, no notification delivery, no automation/actions. If a
future idea doesn't make the correlation claim more provable, it doesn't belong in this MVP,
regardless of how natural it feels to add given the frontend already has a page for it.

---

## 1. System shape

```
                    ┌─────────────────────┐
                    │   GitHub (real)     │
                    │  webhooks + REST    │
                    └──────────┬──────────┘
                               │ push events, CODEOWNERS
                               ▼
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  PagerDuty   │────▶│   FastAPI app    │────▶│   PostgreSQL    │
│  (real)      │     │                  │     │  (managed)      │
│  webhooks    │     │  - ingestion     │     │                 │
└──────────────┘     │  - graph builder │     │  graph tables   │
                     │  - correlation   │     │  event log      │
                     │  - REST API      │     │  feedback table │
                     └────────┬─────────┘     └─────────────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │  Next.js frontend │
                     │  (already built)  │
                     └──────────────────┘
```

External systems are signal sources only — NexOps never becomes the system of record for a
deploy, an alert, or an incident. It stores its own derived graph, its own event log of what
it observed, and its own correlation output. This is the same "signal source, not system of
record" principle from the original research doc, now actually enforced by an architecture
instead of asserted in a README.

---

## 2. Data model (Postgres)

### 2.1 Graph tables — replaces `lib/graph.ts`

```sql
create table service_nodes (
  id              text primary key,        -- e.g. "payments-api"
  name            text not null,
  tier            text not null check (tier in ('ingress','service','data')),
  owner           text,                     -- derived from CODEOWNERS, nullable until resolved
  source_repo     text,                     -- github repo full_name this node was derived from
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table dependency_edges (
  id              bigserial primary key,
  from_node_id    text not null references service_nodes(id) on delete cascade,
  to_node_id      text not null references service_nodes(id) on delete cascade,
  source          text not null,            -- how this edge was derived, e.g. "import-analysis", "manual-seed"
  created_at      timestamptz not null default now(),
  unique (from_node_id, to_node_id)
);
```

**MVP-honest note on edges:** real dependency-graph derivation (static import analysis,
runtime tracing, service mesh data) is a deep problem on its own. For this MVP, derive edges
from the **simplest signal that's still real**: a declared `dependencies` field in a
`nexops.yaml` file per repo (own format, checked into the repo, parsed on sync), rather than
attempting real static analysis or runtime tracing. This keeps "derived, not manually
maintained" honest — it's derived from something in version control, not typed into a NexOps
form — without taking on a research project before the correlation claim is even tested.
Static/runtime dependency inference is a real Phase 2 problem, not an MVP blocker.

### 2.2 Event log — replaces mock `incidents` / `changes`

```sql
create table deploy_events (
  id              text primary key,         -- e.g. github run id or commit sha
  service_id      text not null references service_nodes(id),
  source          text not null default 'github',
  commit_sha      text,
  author          text,
  deployed_at     timestamptz not null,
  raw_payload     jsonb not null,            -- full webhook payload, for replay/debugging
  created_at      timestamptz not null default now()
);

create table alert_events (
  id              text primary key,          -- pagerduty incident id
  service_id      text references service_nodes(id),  -- nullable: not all alerts map cleanly yet
  rule_id         text,
  severity        text,
  fired_at        timestamptz not null,
  resolved_at     timestamptz,
  raw_payload     jsonb not null,
  created_at      timestamptz not null default now()
);
```

### 2.3 Correlation output + feedback — replaces `feedbackState`

```sql
create table candidate_causes (
  id              bigserial primary key,
  alert_event_id  text not null references alert_events(id),
  deploy_event_id text not null references deploy_events(id),
  match_score     int not null check (match_score between 0 and 100),
  match_reasons   jsonb not null,            -- array of strings, same shape the frontend already expects
  confirmed       boolean,                   -- null = unconfirmed, matches frontend's existing tri-state
  confirmed_by    text,                      -- user identifier, nullable
  confirmed_at    timestamptz,
  computed_at     timestamptz not null default now(),
  unique (alert_event_id, deploy_event_id)
);
```

**This table is the actual product.** Everything else in this document exists to populate it
correctly and to make `confirmed` durable. The frontend's `feedbackState` map
(`${incidentId}::${deployId}` → boolean|null) maps directly onto
`(alert_event_id, deploy_event_id)` → `confirmed` — this is a near 1:1 port, not a redesign.

---

## 3. Ingestion — GitHub (graph + deploys)

### 3.1 Day-zero flow (no repo connected yet)

Since there's no GitHub org connected yet, the build needs a real first-run path, mirroring
what the frontend's onboarding already promises:

1. GitHub OAuth App (not a full GitHub App initially — simpler token model, sufficient for
   MVP) — user authorizes read access to a chosen org/repos.
2. On connect: backend calls GitHub's REST API to list repos, fetch each repo's
   `CODEOWNERS` file and `nexops.yaml` (if present) to seed `service_nodes` and
   `dependency_edges`.
3. Register a webhook (`push` and `deployment_status` events, or `workflow_run` if deploys
   are tracked via GitHub Actions) on each connected repo pointing at the backend's ingestion
   endpoint.

### 3.2 Ongoing flow

- Webhook receiver validates GitHub's signature, writes the raw payload into `deploy_events`,
  resolves `service_id` from the repo-to-node mapping established at connect time.
- A repo with no `nexops.yaml` still creates a single default `service_node` (tier inferred
  as `"service"` unless the repo name matches an ingress-like pattern) so deploys aren't
  silently dropped just because dependency data is incomplete — partial data beats no data.

---

## 4. Ingestion — PagerDuty (alerts)

- PagerDuty webhook subscription (v3 webhooks) on incident triggered/resolved events.
- Receiver validates the signature, writes into `alert_events`.
- `service_id` resolution: PagerDuty services map to NexOps services via a simple
  user-configured mapping table (one-time setup during onboarding — "this PagerDuty service
  corresponds to this NexOps service node") rather than attempting fuzzy name-matching. This
  is the one place a small manual mapping step is justified: PagerDuty's service naming has
  no reliable structural link to a GitHub repo, so guessing would be worse than asking once.

---

## 5. The correlation function — the actual deliverable

This replaces the hand-picked `matchScore` numbers in mock data with something computed.
**Deliberately simple for MVP — no ML, no embeddings, no LLM call in the hot path.** A
transparent, explainable scoring function is also a better product fit: every score needs
visible `matchReasons`, and a hand-rolled scoring function produces those reasons for free,
because you write the reason text at the same time as the point calculation. An ML model
would need a separate explanation layer bolted on after the fact.

### 5.1 Trigger

Runs when a new `alert_event` is written: look back at `deploy_events` within a configurable
window (default: 2 hours before `fired_at`) across the alerting service and its direct graph
neighbors (one hop via `dependency_edges`).

### 5.2 Scoring (deterministic, explainable)

For each candidate deploy in the window, compute points and collect a reason string per point
awarded — this list of reason strings becomes `match_reasons` directly:

| Signal | Points | Reason text generated |
|---|---|---|
| Deploy is to the exact alerting service | +35 | `"deployed directly to {service}"` |
| Deploy is to a direct graph neighbor of the alerting service | +20 | `"touches {service}, a direct dependency"` |
| Deploy occurred within 15 min before alert | +25 | `"deployed {N} min before the alert fired"` |
| Deploy occurred within 15–60 min before alert | +15 | same shape, adjusted minutes |
| Deploy occurred 60–120 min before alert | +5 | same shape |
| A past confirmed cause exists for this service with a similar deploy pattern (same author, or same file-path prefix touched) within the last 90 days | +15 | `"similar to a confirmed cause in {past incident id}"` |

Sum points, cap at 100. Sort candidates by score descending, return top 3 to populate
`candidate_causes`. This formula is intentionally legible — every weight is a judgment call
you can see and argue with, which matters more at this stage than statistical rigor.

### 5.3 The feedback loop closing the actual loop

When a user confirms/rejects a candidate via the existing frontend action, the backend writes
`confirmed`, `confirmed_by`, `confirmed_at`. The "similar to a confirmed cause" signal in 5.2
directly reads from this table — **this is the first real instance of the product getting
measurably better from its own history**, even with a simple deterministic formula. This one
feedback-loop connection is the most important line in this entire document: it's the
difference between a scoring function and a product with a data moat that compounds.

### 5.4 Blast radius (mirrors `RecentChanges`)

On deploy ingestion, compute and store (either as a materialized result or computed on read —
materializing is simpler for MVP):
- `direct_services`: graph neighbors one hop downstream of the deployed service
- `downstream_services`: two hops
- `risk_score`: a similarly simple formula — base score from how many past alerts this
  service has had in the last 30 days (`alertHistory.count30d` equivalent, now computed from
  real `alert_events` instead of mock data) plus a bump if any direct/downstream service has
  had a confirmed-cause deploy before
- `risk_basis`: generated reason string, same explainability principle as 5.2

---

## 6. API surface (FastAPI)

Minimal REST surface — just enough for the existing frontend to swap mock data for real
calls without a frontend redesign:

```
GET  /api/graph                       → service_nodes + dependency_edges
GET  /api/incidents                   → alert_events + their candidate_causes
GET  /api/incidents/{id}              → single alert_event with full candidate detail
POST /api/incidents/{id}/feedback     → { deploy_id, confirmed: bool } → writes candidate_causes
GET  /api/changes                     → deploy_events + computed blast radius
GET  /api/integrations/status         → connection health for GitHub + PagerDuty
POST /api/integrations/github/connect → kicks off OAuth flow
POST /api/integrations/pagerduty/connect → stores webhook config
POST /webhooks/github                 → ingestion receiver
POST /webhooks/pagerduty              → ingestion receiver
```

This surface is deliberately shaped to match what the frontend's mock data already looks
like structurally (`candidateCauses`, `blastRadius`, `matchReasons`) — the goal is the
frontend swap is a data-fetching change, not a redesign.

---

## 7. What's explicitly OUT of this MVP

Restating the discipline from Part 1: none of the below get built now, even though they're
easy to imagine given the frontend already has surface area implying them.

- Multi-tenancy / workspaces (flagged correctly earlier as a non-MVP concern)
- Real user authentication beyond what's needed to call GitHub/PagerDuty OAuth (no full
  account system, no roles/permissions)
- Notification delivery (email/Slack) — the frontend's notification panel can stay reading
  from a simple polling endpoint or stay mock for now; this is genuinely lower priority than
  proving correlation works
- Any ML/embedding-based correlation — the deterministic formula in Section 5 is the whole
  MVP scoring system
- Automation or auto-remediation of any kind
- Multi-cloud, Kubernetes, Slack — consistent with the frontend's own scope cuts

---

## 8. Build order

1. **Postgres schema + FastAPI skeleton**, deployed to the chosen managed provider, with the
   tables in Section 2 and nothing else
2. **GitHub OAuth connect flow + repo listing + CODEOWNERS/nexops.yaml parsing** → populates
   `service_nodes` / `dependency_edges` for real, for the first time
3. **GitHub webhook receiver** → `deploy_events` start filling with real data
4. **PagerDuty connect flow + webhook receiver** → `alert_events` start filling with real data
5. **Correlation function (Section 5.2)** running on new alert ingestion → `candidate_causes`
   populated with real, explainable scores for the first time
6. **Feedback endpoint** wired to the existing frontend's confirm/reject UI, replacing
   `feedbackState`'s in-memory store with a real write
7. **Blast radius computation (Section 5.4)** on deploy ingestion
8. **Swap frontend mock data calls for the real API surface (Section 6)** — this is the
   moment the frontend stops being a demo and becomes the product

Steps 1–4 can be built and tested independently of each other. Step 5 is the first point
where "does this actually work" becomes answerable with real data instead of a plan.
