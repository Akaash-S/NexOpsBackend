# NexOps Database Inventory

This document represents a direct introspection of the live Neon PostgreSQL database. All schemas, row counts, and samples were retrieved using direct SQL queries.

## 1. Full Schema

**Introspection Queries Executed:**
```sql
-- Tables
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';

-- Columns
SELECT column_name, data_type, is_nullable, column_default 
FROM information_schema.columns WHERE table_name = '<table_name>';

-- Constraints
SELECT tc.constraint_name, tc.constraint_type, kcu.column_name, ccu.table_name, ccu.column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
LEFT JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
WHERE tc.table_name = '<table_name>';

-- Indexes
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = '<table_name>';
```

### Table: `cloud_providers`
*   **Columns:**
    *   `config` | json | Nullable: YES | Default: None
    *   `last_validated_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `updated_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `access_token` | character varying | Nullable: YES | Default: None
    *   `secret_key` | character varying | Nullable: YES | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `status` | character varying | Nullable: NO | Default: None
    *   `account_id` | character varying | Nullable: YES | Default: None
    *   `workspace_id` | character varying | Nullable: NO | Default: None
    *   `name` | character varying | Nullable: NO | Default: None
    *   `type` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `cloud_providers_pkey` (PRIMARY KEY): `id`
*   **Indexes:**
    *   `cloud_providers_pkey`: `CREATE UNIQUE INDEX cloud_providers_pkey ON public.cloud_providers USING btree (id)`
    *   `ix_cloud_providers_id`: `CREATE INDEX ix_cloud_providers_id ON public.cloud_providers USING btree (id)`
    *   `ix_cloud_providers_type`: `CREATE INDEX ix_cloud_providers_type ON public.cloud_providers USING btree (type)`
    *   `ix_cloud_providers_workspace_id`: `CREATE INDEX ix_cloud_providers_workspace_id ON public.cloud_providers USING btree (workspace_id)`

### Table: `repos`
*   **Columns:**
    *   `updated_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `last_commit_at` | timestamp without time zone | Nullable: YES | Default: None
    *   `open_issues` | integer | Nullable: NO | Default: None
    *   `open_prs` | integer | Nullable: NO | Default: None
    *   `stars` | integer | Nullable: NO | Default: None
    *   `forks` | integer | Nullable: NO | Default: None
    *   `contributors` | integer | Nullable: NO | Default: None
    *   `activity` | double precision | Nullable: NO | Default: None
    *   `health_score` | double precision | Nullable: NO | Default: None
    *   `vulnerabilities` | integer | Nullable: NO | Default: None
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `workspace_id` | character varying | Nullable: YES | Default: None
    *   `cluster_id` | character varying | Nullable: YES | Default: None
    *   `name` | character varying | Nullable: NO | Default: None
    *   `platform` | character varying | Nullable: NO | Default: None
    *   `description` | character varying | Nullable: YES | Default: None
    *   `language` | character varying | Nullable: YES | Default: None
    *   `default_branch` | character varying | Nullable: NO | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `owner` | character varying | Nullable: YES | Default: None
    *   `ci_status` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `repos_pkey` (PRIMARY KEY): `id`
*   **Indexes:**
    *   `repos_pkey`: `CREATE UNIQUE INDEX repos_pkey ON public.repos USING btree (id)`
    *   `ix_repos_name`: `CREATE INDEX ix_repos_name ON public.repos USING btree (name)`
    *   `ix_repos_workspace_id`: `CREATE INDEX ix_repos_workspace_id ON public.repos USING btree (workspace_id)`
    *   `ix_repos_id`: `CREATE INDEX ix_repos_id ON public.repos USING btree (id)`
    *   `ix_repos_cluster_id`: `CREATE INDEX ix_repos_cluster_id ON public.repos USING btree (cluster_id)`

### Table: `events`
*   **Columns:**
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `payload` | json | Nullable: YES | Default: None
    *   `processed` | boolean | Nullable: NO | Default: None
    *   `source` | character varying | Nullable: NO | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `message` | character varying | Nullable: YES | Default: None
    *   `severity` | character varying | Nullable: NO | Default: None
    *   `type` | character varying | Nullable: NO | Default: None
    *   `repo_id` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `events_pkey` (PRIMARY KEY): `id`
    *   `events_repo_id_fkey` (FOREIGN KEY): `repo_id` -> `repos(id)`
*   **Indexes:**
    *   `events_pkey`: `CREATE UNIQUE INDEX events_pkey ON public.events USING btree (id)`
    *   `ix_events_processed`: `CREATE INDEX ix_events_processed ON public.events USING btree (processed)`
    *   `ix_events_repo_id`: `CREATE INDEX ix_events_repo_id ON public.events USING btree (repo_id)`
    *   `ix_events_created_at`: `CREATE INDEX ix_events_created_at ON public.events USING btree (created_at)`
    *   `ix_events_type`: `CREATE INDEX ix_events_type ON public.events USING btree (type)`
    *   `ix_events_id`: `CREATE INDEX ix_events_id ON public.events USING btree (id)`

### Table: `dependencies`
*   **Columns:**
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `source_repo_id` | character varying | Nullable: NO | Default: None
    *   `target_repo_id` | character varying | Nullable: NO | Default: None
    *   `type` | character varying | Nullable: NO | Default: None
    *   `label` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `dependencies_pkey` (PRIMARY KEY): `id`
    *   `dependencies_source_repo_id_fkey` (FOREIGN KEY): `source_repo_id` -> `repos(id)`
    *   `dependencies_target_repo_id_fkey` (FOREIGN KEY): `target_repo_id` -> `repos(id)`
*   **Indexes:**
    *   `dependencies_pkey`: `CREATE UNIQUE INDEX dependencies_pkey ON public.dependencies USING btree (id)`
    *   `ix_dependencies_type`: `CREATE INDEX ix_dependencies_type ON public.dependencies USING btree (type)`
    *   `ix_dependencies_target_repo_id`: `CREATE INDEX ix_dependencies_target_repo_id ON public.dependencies USING btree (target_repo_id)`
    *   `ix_dependencies_id`: `CREATE INDEX ix_dependencies_id ON public.dependencies USING btree (id)`
    *   `ix_dependencies_source_repo_id`: `CREATE INDEX ix_dependencies_source_repo_id ON public.dependencies USING btree (source_repo_id)`

### Table: `incidents`
*   **Columns:**
    *   `impacted_repos` | json | Nullable: YES | Default: None
    *   `started_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `resolved_at` | timestamp without time zone | Nullable: YES | Default: None
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `updated_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `status` | character varying | Nullable: NO | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `impact_summary` | character varying | Nullable: YES | Default: None
    *   `root_cause_repo_id` | character varying | Nullable: YES | Default: None
    *   `cluster_id` | character varying | Nullable: YES | Default: None
    *   `title` | character varying | Nullable: NO | Default: None
    *   `description` | character varying | Nullable: YES | Default: None
    *   `severity` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `incidents_pkey` (PRIMARY KEY): `id`
    *   `incidents_root_cause_repo_id_fkey` (FOREIGN KEY): `root_cause_repo_id` -> `repos(id)`
*   **Indexes:**
    *   `incidents_pkey`: `CREATE UNIQUE INDEX incidents_pkey ON public.incidents USING btree (id)`
    *   `ix_incidents_cluster_id`: `CREATE INDEX ix_incidents_cluster_id ON public.incidents USING btree (cluster_id)`
    *   `ix_incidents_id`: `CREATE INDEX ix_incidents_id ON public.incidents USING btree (id)`
    *   `ix_incidents_status`: `CREATE INDEX ix_incidents_status ON public.incidents USING btree (status)`
    *   `ix_incidents_severity`: `CREATE INDEX ix_incidents_severity ON public.incidents USING btree (severity)`

### Table: `deployments`
*   **Columns:**
    *   `deployed_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `finished_at` | timestamp without time zone | Nullable: YES | Default: None
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `updated_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `status` | character varying | Nullable: NO | Default: None
    *   `deployed_by` | character varying | Nullable: YES | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `changelog` | character varying | Nullable: YES | Default: None
    *   `provider_id` | character varying | Nullable: YES | Default: None
    *   `commit_hash` | character varying | Nullable: YES | Default: None
    *   `repo_id` | character varying | Nullable: NO | Default: None
    *   `version` | character varying | Nullable: NO | Default: None
    *   `environment` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `deployments_pkey` (PRIMARY KEY): `id`
    *   `deployments_repo_id_fkey` (FOREIGN KEY): `repo_id` -> `repos(id)`
*   **Indexes:**
    *   `deployments_pkey`: `CREATE UNIQUE INDEX deployments_pkey ON public.deployments USING btree (id)`
    *   `ix_deployments_id`: `CREATE INDEX ix_deployments_id ON public.deployments USING btree (id)`
    *   `ix_deployments_provider_id`: `CREATE INDEX ix_deployments_provider_id ON public.deployments USING btree (provider_id)`
    *   `ix_deployments_environment`: `CREATE INDEX ix_deployments_environment ON public.deployments USING btree (environment)`
    *   `ix_deployments_repo_id`: `CREATE INDEX ix_deployments_repo_id ON public.deployments USING btree (repo_id)`
    *   `ix_deployments_status`: `CREATE INDEX ix_deployments_status ON public.deployments USING btree (status)`

### Table: `alerts`
*   **Columns:**
    *   `resolved` | boolean | Nullable: NO | Default: None
    *   `resolved_at` | timestamp without time zone | Nullable: YES | Default: None
    *   `acknowledged` | boolean | Nullable: NO | Default: None
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `category` | character varying | Nullable: NO | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `event_id` | character varying | Nullable: YES | Default: None
    *   `repo_id` | character varying | Nullable: NO | Default: None
    *   `title` | character varying | Nullable: NO | Default: None
    *   `message` | character varying | Nullable: NO | Default: None
    *   `severity` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `alerts_pkey` (PRIMARY KEY): `id`
    *   `alerts_repo_id_fkey` (FOREIGN KEY): `repo_id` -> `repos(id)`
    *   `alerts_event_id_fkey` (FOREIGN KEY): `event_id` -> `events(id)`
*   **Indexes:**
    *   `ix_alerts_created_at`: `CREATE INDEX ix_alerts_created_at ON public.alerts USING btree (created_at)`
    *   `alerts_pkey`: `CREATE UNIQUE INDEX alerts_pkey ON public.alerts USING btree (id)`
    *   `ix_alerts_id`: `CREATE INDEX ix_alerts_id ON public.alerts USING btree (id)`
    *   `ix_alerts_severity`: `CREATE INDEX ix_alerts_severity ON public.alerts USING btree (severity)`
    *   `ix_alerts_resolved`: `CREATE INDEX ix_alerts_resolved ON public.alerts USING btree (resolved)`
    *   `ix_alerts_repo_id`: `CREATE INDEX ix_alerts_repo_id ON public.alerts USING btree (repo_id)`

### Table: `candidate_causes`
*   **Columns:**
    *   `confirmed` | boolean | Nullable: YES | Default: None
    *   `score` | double precision | Nullable: NO | Default: None
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `updated_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `confirmed_by` | character varying | Nullable: YES | Default: None
    *   `reason` | character varying | Nullable: NO | Default: None
    *   `incident_id` | character varying | Nullable: NO | Default: None
    *   `repo_id` | character varying | Nullable: NO | Default: None
    *   `event_id` | character varying | Nullable: YES | Default: None
*   **Constraints:**
    *   `candidate_causes_pkey` (PRIMARY KEY): `id`
    *   `uq_candidate_cause_incident_event` (UNIQUE): `incident_id`, `event_id`
    *   `candidate_causes_incident_id_fkey` (FOREIGN KEY): `incident_id` -> `incidents(id)`
    *   `candidate_causes_repo_id_fkey` (FOREIGN KEY): `repo_id` -> `repos(id)`
    *   `candidate_causes_event_id_fkey` (FOREIGN KEY): `event_id` -> `events(id)`
    *   `candidate_causes_confirmed_by_fkey` (FOREIGN KEY): `confirmed_by` -> `users(id)`
*   **Indexes:**
    *   `candidate_causes_pkey`: `CREATE UNIQUE INDEX candidate_causes_pkey ON public.candidate_causes USING btree (id)`
    *   `uq_candidate_cause_incident_event`: `CREATE UNIQUE INDEX uq_candidate_cause_incident_event ON public.candidate_causes USING btree (incident_id, event_id)`
    *   `ix_candidate_causes_incident_id`: `CREATE INDEX ix_candidate_causes_incident_id ON public.candidate_causes USING btree (incident_id)`
    *   `ix_candidate_causes_id`: `CREATE INDEX ix_candidate_causes_id ON public.candidate_causes USING btree (id)`
    *   `ix_candidate_causes_repo_id`: `CREATE INDEX ix_candidate_causes_repo_id ON public.candidate_causes USING btree (repo_id)`

### Table: `users`
*   **Columns:**
    *   `onboarding_completed` | boolean | Nullable: NO | Default: None
    *   `created_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `updated_at` | timestamp without time zone | Nullable: NO | Default: None
    *   `avatar_url` | character varying | Nullable: YES | Default: None
    *   `id` | character varying | Nullable: NO | Default: None
    *   `github_access_token` | character varying | Nullable: YES | Default: None
    *   `role` | character varying | Nullable: NO | Default: None
    *   `email` | character varying | Nullable: NO | Default: None
    *   `full_name` | character varying | Nullable: NO | Default: None
*   **Constraints:**
    *   `users_pkey` (PRIMARY KEY): `id`
*   **Indexes:**
    *   `users_pkey`: `CREATE UNIQUE INDEX users_pkey ON public.users USING btree (id)`
    *   `ix_users_email`: `CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email)`
    *   `ix_users_id`: `CREATE INDEX ix_users_id ON public.users USING btree (id)`

---

## 2. Row Counts and Sample Data

```sql
SELECT COUNT(*) FROM <table>;
SELECT * FROM <table> LIMIT 5;
```

*   **`cloud_providers`**: 0 rows
*   **`repos`**: 10 rows
    *   `id=repo-003, name=infra-terraform, owner=ops-team, cluster_id=cluster-1`
    *   `id=5d3b110f..., name=test-integration-repo, description=Created by integration test`
    *   `id=repo-002, name=nexops-api, owner=nexops-io`
*   **`events`**: 38 rows
    *   `id=d67db08c..., type=ci.failed, repo_id=repo-003, message=CI Pipeline Failed: infra-terraform`
    *   `id=evt-001, type=push, repo_id=repo-001, message=Mock event for unique constraint test`
*   **`dependencies`**: 2 rows
    *   `id=243b7f64..., source_repo_id=repo-001, target_repo_id=repo-002, label=calls api`
    *   `id=16c2a063..., source_repo_id=repo-002, target_repo_id=repo-003, label=requires infra`
*   **`incidents`**: 2 rows
    *   `id=inc-001, title=Systemic API Degradation, root_cause_repo_id=repo-003`
    *   `id=8375c8f9..., title=Systemic Failure: ci.failed, root_cause_repo_id=repo-001`
*   **`deployments`**: 6 rows
    *   `id=71435834..., repo_id=repo-001, version=v1.2.0, environment=production`
    *   `id=061be9a4..., version=v1.0.0, deployed_by=NexOps Sync, commit_hash=a1b2c3d4`
*   **`alerts`**: 5 rows
    *   `id=62e3becf..., title=Critical vulnerability in lodash@4.17.20, category=security`
    *   `id=60a368f3..., title=CI Pipeline Failed — infra-terraform, repo_id=repo-003`
*   **`candidate_causes`**: 3 rows
    *   `id=a4c91b6d..., incident_id=inc-001, repo_id=repo-001, score=50.0, reason=Test reason 1`
    *   `id=e52cd8ba..., incident_id=8375c..., reason=Same repository (+35)..., confirmed_by=dev-user-123`
*   **`users`**: 4 rows
    *   `id=bb161358..., email=sarah@nexops.io, full_name=Sarah Chen`
    *   `id=dev-user-123, email=dev@nexops.local, full_name=Local Developer`
    *   `id=6HJsfwvQGu..., email=mattpersonal321@gmail.com, full_name=Matt Murdock`

---

## 3. Orphaned / Leftover Tables

*   **Tables in DB with NO corresponding model:** 0 (None)
*   **Models in codebase with NO corresponding table:** 0 (None)

Every table found in the PostgreSQL `public` schema maps perfectly to the 9 models in `app/models/` (`alert.py`, `candidate_cause.py`, `cloud_provider.py`, `dependency.py`, `deployment.py`, `event.py`, `incident.py`, `repo.py`, `user.py`). The previous stripping runs successfully dropped everything else.

---

## 4. Migration History

*   **Migration Tool:** None.
*   **Status:** There is no `alembic` setup (no `alembic.ini` or `alembic/migrations` directory). The tables are managed directly by SQLModel's `create_all()` during application boot-up or via script triggers (`seed.py`, `reset_db.py`).

---

## 5. Real vs. Seed/Mock Data Assessment

My assessment of the data origin, table by table:

1.  **`users`**: Contains **One Real Row**.
    *   **Real Data:** `id: 6HJsfwvQGuTlxKT4L4egPBfoTpX2` (email `mattpersonal321@gmail.com`). Reason: This ID format exactly matches Firebase Authentication UIDs. It includes an actual Google profile avatar URL (`lh3.googleusercontent.com/...`) and has an encrypted `github_access_token`. This row was created by a real user logging in through Firebase and completing an OAuth flow.
    *   **Seed/Test Data:** The other 3 rows (`sarah@nexops.io`, `akaash@nexops.io`, `dev@nexops.local`) are clearly generated by a seed script or test suite. `dev-user-123` is a hardcoded ID used in backend tests, and the others use `dicebear.com` avatar seeds.
2.  **`repos`**: **Seed/Test Data**.
    *   Reason: Several rows literally contain `description: Created by integration test`. The others have hardcoded `repo-00X` ID formats and mock `cluster-1`/`ws-1` references which do not correlate to real GitHub webhook or integration events.
3.  **`cloud_providers`**: **Empty**.
4.  **`events`**: **Seed/Test Data**.
    *   Reason: Hardcoded IDs like `evt-001` with descriptions like `Mock event for unique constraint test` prove they were created by the test suite (likely `test_correlation.py`). Others reference the dummy `repo-00X` IDs.
5.  **`dependencies`**: **Seed Data**.
    *   Reason: Hardcoded relationships between `repo-001`, `repo-002`, and `repo-003` with simple labels (`calls api`, `requires infra`).
6.  **`incidents`**: **Seed/Test Data**.
    *   Reason: Titles like `Systemic API Degradation` and references to `repo-00X` tables.
7.  **`deployments`**: **Seed Data**.
    *   Reason: All rows have `deployed_by` set to `None` or `NexOps Sync` with a hardcoded mock `commit_hash` (`a1b2c3d4`).
8.  **`alerts`**: **Seed/Test Data**.
    *   Reason: Hardcoded simulated CVE alerts (e.g., `lodash@4.17.20`) directly attached to `repo-003`.
9.  **`candidate_causes`**: **Test Data**.
    *   Reason: The rows contain `reason: Test reason 1` and `confirmed_by: dev-user-123`. They are artifacts left behind by the test runner (`test_correlation.py`).
