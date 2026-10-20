# NexOps — System Security Audit & `postmortems` Feature Investigation Report

---

## 1. Part 1 — Technical Architecture & Code Citation Analysis

### 1a. SQLModel Schema Citation ([app/models/postmortem.py](file:///d:/Projects/ReactJS/NexOps/backend/app/models/postmortem.py#L14-L66))
- **Table Name**: `postmortems`
- **Columns & Data Types**:
  - `id`: `str` (UUID primary key)
  - `incident_id`: `str` (Unique Foreign Key -> `incidents.id`)
  - `workspace_id`: `str` (Foreign Key -> `workspaces.id`)
  - `author_id`: `Optional[str]` (Foreign Key -> `users.id`)
  - `summary`: `Optional[Text]`
  - `timeline`: `Optional[Text]` (Event log in plain text/Markdown)
  - `root_cause`: `Optional[Text]`
  - `contributing_factors`: `Optional[Text]`
  - `impact`: `Optional[Text]`
  - `action_items`: `Optional[Text]`
  - `lessons_learned`: `Optional[Text]`
  - `status`: `str` (default `'draft'`, indexed; values: `'draft'`, `'published'`)
  - `created_at`, `updated_at`: `datetime`

### 1b. Backend Route Handlers Citation ([app/api/routes/incidents.py](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L236-L364))
1. `GET /api/v1/incidents/{incident_id}/postmortem`
   - Fetches or auto-creates an empty draft postmortem.
   - Pre-fills `root_cause` from `CandidateCause.reason` if a candidate cause was marked `confirmed = True`.
2. `PATCH /api/v1/incidents/{incident_id}/postmortem`
   - Auto-saves partial text updates to postmortem fields.
3. `POST /api/v1/incidents/{incident_id}/postmortem/publish`
   - Validates that `summary` and `root_cause` are non-empty and sets `status = 'published'`.

*Note: All 3 endpoints require `_ext = Depends(verify_extended_navigation)`, which checks `workspace.show_extended_navigation` (default `False`).*

### 1c. Frontend UI Accessibility Audit
- **Codebase Search Output (`updated-frontend`)**:
  ```text
  $ git grep -n -i "postmortem" -- 'src/'
  (Exited with code 1 — ZERO matches found in React frontend)
  ```
- **UI Reachability**: **UNREACHABLE**. The frontend UI contains zero pages, components, links, buttons, or navigation items for postmortems.

---

## 2. Part 2 — Production Database Usage Audit (`scratch/investigate_postmortems_usage.py`)

### Execution Output
Query executed across Neon production database under `nexops_app_user` with RLS bypassed:

```text
=================================================================
PART 2: PRODUCTION DATABASE POSTMORTEMS USAGE AUDIT
=================================================================

[Postmortems DB Query Output]
  Total Postmortem Records Found: 0

[EMPIRICAL FINDING] Zero postmortem rows exist in the production database.
```

- **Usage Record**: **0 postmortem rows** exist in the production database across all workspaces.
- **Cross-Feature Connections**: Zero active references or links from dashboards, alerts, or incident views.

---

## 3. Part 3 — Git Origin & Commit History Audit

### Git Log & Blame Output
```text
$ git log --oneline --follow -- app/models/postmortem.py
c06d7a1 feat: add Postmortem SQLModel & CRUD endpoints (GET, PATCH draft auto-save, POST publish)

$ git show c06d7a1 --stat
commit c06d7a14f271a54ef3c6dfcbb238341781d93a6e
Author: Akaash-S <akaashgithub21@gmail.com>
Date:   Thu Jul 30 23:06:30 2026 +0530

    feat: add Postmortem SQLModel & CRUD endpoints (GET, PATCH draft auto-save, POST publish)

 app/api/routes/incidents.py | 138 ++++++++++++++++++++++++++++++++++++++++++++
 app/models/__init__.py      |   2 +
 app/models/postmortem.py    |  65 +++++++++++++++++++++
 3 files changed, 205 insertions(+)
```

- **Commit Date**: July 30, 2026 (`c06d7a1`).
- **Context**: Created during initial backend API scaffolding prior to the project's narrow-scope pivot to a correlation engine. Frontend UI was never constructed for it.

---

## 4. Part 4 — Informational Scope-Fit Assessment

1. **Alignment with Core Moat ("What caused this incident, and how do we know?")**:
   - `postmortems` functions as a freeform text document editor for resolved incidents. While it can pre-fill root cause text, it does not participate in alert ingestion, temporal proximity scoring, or dependency graph correlation.
2. **Category Mapping**:
   - Operates as orphaned backend scaffolding (similar to the extended navigation routes gated behind `show_extended_navigation`).
3. **Maintenance & Complexity Footprint**:
   - Backend Model: 65 lines ([app/models/postmortem.py](file:///d:/Projects/ReactJS/NexOps/backend/app/models/postmortem.py))
   - Backend Routes: 138 lines ([app/api/routes/incidents.py](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L224-L364))
   - Database Table: 1 table (`postmortems`) with 2 foreign keys (`incidents.id`, `workspaces.id`).

---

## 5. Summary Matrix

| Investigation Axis | Empirical Finding | Evidence Reference |
|---|---|---|
| **Backend Models & Routes** | Table `postmortems` + 3 API routes (GET/PATCH/POST publish) | [postmortem.py](file:///d:/Projects/ReactJS/NexOps/backend/app/models/postmortem.py#L14), [incidents.py:L236](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L236) |
| **Frontend UI Reachability** | 0 UI components or routes in React frontend | `git grep -i "postmortem"` in `updated-frontend` -> **0 matches** |
| **Production DB Usage** | 0 records in production Neon database | `scratch/investigate_postmortems_usage.py` -> **0 rows** |
| **Git Commit History** | Added July 30, 2026 (Commit `c06d7a1`) | `git log --follow app/models/postmortem.py` |
| **Feature Flag Gate** | Protected by `verify_extended_navigation` | `_ext = Depends(verify_extended_navigation)` |
