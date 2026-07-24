# NexOps Backend Architecture & Reference Manual

This document provides a line-level technical reference for the NexOps backend system. Every feature, routing path, model definition, and system integration described below is backed by a direct code reference (file path and line number range).

---

## 1. Stack & Entry Point

### Framework & Dependencies
The NexOps backend is built using **Python 3.11** and the **FastAPI** web framework.
* **Core Web Server**:
  * FastAPI framework implementation in [app/main.py](file:///d:/Projects/ReactJS/NexOps/backend/app/main.py#L17)
  * Server engine powered by Uvicorn (with standard WebSockets support) in [requirements.txt](file:///d:/Projects/ReactJS/NexOps/backend/requirements.txt#L2-L3)
* **Database & ORM**:
  * SQLModel (SQLAlchemy wrapper) in [requirements.txt](file:///d:/Projects/ReactJS/NexOps/backend/requirements.txt#L7)
  * SQLAlchemy with asyncio support in [requirements.txt](file:///d:/Projects/ReactJS/NexOps/backend/requirements.txt#L8)
  * Asyncpg (PostgreSQL client driver) in [requirements.txt](file:///d:/Projects/ReactJS/NexOps/backend/requirements.txt#L9)
* **Real-time Communication & Caching**:
  * Redis async driver in [requirements.txt](file:///d:/Projects/ReactJS/NexOps/backend/requirements.txt#L13)
* **Security & Auth**:
  * Firebase Admin SDK (token verification) in [requirements.txt](file:///d:/Projects/ReactJS/NexOps/backend/requirements.txt#L22)
  * Cryptography (Fernet symmetric key encryption) in [requirements.txt](file:///d:/Projects/ReactJS/NexOps/backend/requirements.txt#L23)

### Application Entry Point
* **Core entry file**: [app/main.py](file:///d:/Projects/ReactJS/NexOps/backend/app/main.py)
* **Local Run Command**: 
  ```bash
  venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```
* **Docker Deployment**:
  * Documented in [Dockerfile](file:///d:/Projects/ReactJS/NexOps/backend/Dockerfile). Builds on top of `python:3.11-slim` [Dockerfile:L2](file:///d:/Projects/ReactJS/NexOps/backend/Dockerfile#L2), installs system libraries including `nodejs` [Dockerfile:L13-L20](file:///d:/Projects/ReactJS/NexOps/backend/Dockerfile#L13-L20), and starts using Uvicorn [Dockerfile:L33](file:///d:/Projects/ReactJS/NexOps/backend/Dockerfile#L33):
    ```dockerfile
    CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    ```
  * Orchestrated via [docker-compose.yml](file:///d:/Projects/ReactJS/NexOps/backend/docker-compose.yml). Exposes port 8000 [docker-compose.yml:L7](file:///d:/Projects/ReactJS/NexOps/backend/docker-compose.yml#L7), and depends on database (`db`) and `redis` containers [docker-compose.yml:L14-L16](file:///d:/Projects/ReactJS/NexOps/backend/docker-compose.yml#L14-L16).

### Environment Variables
Loaded type-safely via `Settings` class in [app/core/config.py:L11-L80](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L11-L80):
1. `APP_NAME`: Application name [app/core/config.py:L13](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L13). Documented in [.env.example:L8](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L8).
2. `APP_ENV`: Deployment environment (`development` / `production`) [app/core/config.py:L14](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L14). Documented in [.env.example:L9](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L9).
3. `DEBUG`: Boolean debug flag [app/core/config.py:L15](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L15). Documented in [.env.example:L10](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L10).
4. `API_PREFIX`: Base routing path prefix (e.g. `/api/v1`) [app/core/config.py:L16](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L16). Documented in [.env.example:L11](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L11).
5. `DATABASE_URL`: Primary PostgreSQL connection string [app/core/config.py:L19](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L19). Documented in [.env.example:L2](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L2).
6. `REDIS_URL`: Cache database connection string [app/core/config.py:L22](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L22). Documented in [.env.example:L5](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L5).
7. `CORS_ORIGINS`: JSON list or comma-separated origins [app/core/config.py:L25](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L25). Documented in [.env.example:L14](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L14).
8. `FIREBASE_SERVICE_ACCOUNT_PATH`: Path to Firebase JSON credentials [app/core/config.py:L36](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L36). *Not documented in `.env.example`.*
9. `ENCRYPTION_KEY`: Symmetric key for encryption of integrations tokens [app/core/config.py:L39](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L39). *Not documented in `.env.example`.*
10. `GITHUB_WEBHOOK_SECRET`: Secure signature verification string [app/core/config.py:L42](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L42). *Not documented in `.env.example`.*
11. `GEMINI_API_KEY`: API token for AI summarizing [app/core/config.py:L45](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L45). Documented in [.env.example:L17](file:///d:/Projects/ReactJS/NexOps/backend/.env.example#L17).

---

## 2. Database

### Query Layer & Connection
* **ORM**: Uses `SQLModel` declarative classes connected using async engine pools.
* **Configuration**: Set up in [app/core/database.py](file:///d:/Projects/ReactJS/NexOps/backend/app/core/database.py).
  * Automatically strips standard query parameters (like `sslmode`) from `DATABASE_URL` via the `async_database_url` config property [app/core/config.py:L48-L60](file:///d:/Projects/ReactJS/NexOps/backend/app/core/config.py#L48-L60).
  * Passes SSL parameters directly to connection arguments if requested [app/core/database.py:L13-L15](file:///d:/Projects/ReactJS/NexOps/backend/app/core/database.py#L13-L15).
  * Engine parameters [app/core/database.py:L23-L25](file:///d:/Projects/ReactJS/NexOps/backend/app/core/database.py#L23-L25): `pool_size=10`, `max_overflow=20`, `pool_recycle=3600`.

### Database Schema Models
All models are defined under `app/models/` and registered under [app/models/__init__.py](file:///d:/Projects/ReactJS/NexOps/backend/app/models/__init__.py).

#### User
* **File Reference**: [app/models/user.py:L12-L26](file:///d:/Projects/ReactJS/NexOps/backend/app/models/user.py#L12-L26)
* **Table**: `users`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `email`: `str` (Index, unique, max length 255)
  * `full_name`: `str` (Max length 255)
  * `avatar_url`: `Optional[str]` (Max length 500)
  * `role`: `str` (Default `"member"`)
  * `created_at`: `datetime` (Default UTC now)
  * `updated_at`: `datetime` (Default UTC now)

#### Workspace
* **File Reference**: [app/models/workspace.py:L13-L38](file:///d:/Projects/ReactJS/NexOps/backend/app/models/workspace.py#L13-L38)
* **Table**: `workspaces`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `name`: `str` (Index, max length 255)
  * `color`: `str` (Default `"blue"`, max length 50)
  * `description`: `Optional[str]` (Max length 500)
  * `provider`: `str` (Default `"custom"`, max length 50)
  * `status`: `str` (Default `"connected"`, max length 50)
  * `access_token`: `Optional[str]` (Max length 500, Fernet encrypted)
  * `refresh_token`: `Optional[str]` (Max length 500)
  * `last_synced_at`: `Optional[datetime]`
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

#### WorkspaceMember
* **File Reference**: [app/models/workspace_member.py:L11-L26](file:///d:/Projects/ReactJS/NexOps/backend/app/models/workspace_member.py#L11-L26)
* **Table**: `workspace_members`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `workspace_id`: `str` (Foreign Key referencing `workspaces.id`, index)
  * `user_id`: `str` (Foreign Key referencing `users.id`, index)
  * `role`: `str` (Default `"member"`)
  * `joined_at`: `datetime`
  * `updated_at`: `datetime`

#### Invitation
* **File Reference**: [app/models/invitation.py:L12-L34](file:///d:/Projects/ReactJS/NexOps/backend/app/models/invitation.py#L12-L34)
* **Table**: `invitations`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `workspace_id`: `str` (Foreign Key referencing `workspaces.id`, index)
  * `email`: `str` (Index)
  * `role`: `str` (Default `"member"`)
  * `token`: `str` (Unique)
  * `status`: `str` (Default `"pending"`)
  * `invited_by_id`: `str` (Foreign Key referencing `users.id`)
  * `expires_at`: `datetime` (Default +7 days)
  * `created_at`: `datetime`
  * `accepted_at`: `Optional[datetime]`

#### Repo
* **File Reference**: [app/models/repo.py:L13-L54](file:///d:/Projects/ReactJS/NexOps/backend/app/models/repo.py#L13-L54)
* **Table**: `repos`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `workspace_id`: `Optional[str]` (Foreign Key referencing `workspaces.id`, index)
  * `cluster_id`: `Optional[str]` (Foreign Key referencing `clusters.id`, index)
  * `name`: `str` (Index, max length 255)
  * `platform`: `str` (Default `"github"`)
  * `description`: `Optional[str]` (Max length 500)
  * `language`: `Optional[str]` (Max length 50)
  * `default_branch`: `str` (Default `"main"`, max length 100)
  * `last_commit_at`: `Optional[datetime]`
  * `open_issues`: `int` (Default 0)
  * `open_prs`: `int` (Default 0)
  * `stars`: `int` (Default 0)
  * `forks`: `int` (Default 0)
  * `contributors`: `int` (Default 0)
  * `activity`: `float` (Default 50.0)
  * `owner`: `Optional[str]` (Max length 100)
  * `ci_status`: `str` (Default `"passing"`)
  * `health_score`: `float` (Default 100.0)
  * `vulnerabilities`: `int` (Default 0)
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

#### Cluster
* **File Reference**: [app/models/cluster.py:L14-L40](file:///d:/Projects/ReactJS/NexOps/backend/app/models/cluster.py#L14-L40)
* **Table**: `clusters`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `workspace_id`: `str` (Foreign Key referencing `workspaces.id`, index)
  * `name`: `str` (Index, max length 255)
  * `description`: `Optional[str]` (Max length 500)
  * `color`: `str` (Default `"blue"`, max length 50)
  * `owner_team_id`: `Optional[str]` (Foreign Key referencing `teams.id`, index)
  * `health_score`: `float` (Default 100.0)
  * `ci_status`: `str` (Default `"passing"`)
  * `alert_critical`: `int` (Default 0)
  * `alert_high`: `int` (Default 0)
  * `alert_total`: `int` (Default 0)
  * `repo_count`: `int` (Default 0)
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

#### Alert
* **File Reference**: [app/models/alert.py:L14-L38](file:///d:/Projects/ReactJS/NexOps/backend/app/models/alert.py#L14-L38)
* **Table**: `alerts`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `title`: `str` (Max length 255)
  * `message`: `str` (Max length 2000)
  * `severity`: `str` (Index, nullable=False)
  * `category`: `str` (Default `"system"`)
  * `repo_id`: `str` (Foreign Key referencing `repos.id`, index)
  * `event_id`: `Optional[str]` (Foreign Key referencing `events.id`)
  * `resolved`: `bool` (Default `False`, index)
  * `resolved_at`: `Optional[datetime]`
  * `acknowledged`: `bool` (Default `False`)
  * `created_at`: `datetime` (Index)

#### Event
* **File Reference**: [app/models/event.py:L14-L36](file:///d:/Projects/ReactJS/NexOps/backend/app/models/event.py#L14-L36)
* **Table**: `events`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `type`: `str` (Index, nullable=False)
  * `repo_id`: `str` (Foreign Key referencing `repos.id`, index)
  * `source`: `str` (Default `"system"`)
  * `payload`: `Optional[Dict[str, Any]]` (JSON column)
  * `message`: `Optional[str]` (Max length 500)
  * `severity`: `str` (Default `"info"`, max length 20)
  * `processed`: `bool` (Default `False`, index)
  * `created_at`: `datetime` (Index)

#### Pipeline
* **File Reference**: [app/models/pipeline.py:L14-L48](file:///d:/Projects/ReactJS/NexOps/backend/app/models/pipeline.py#L14-L48)
* **Table**: `pipelines`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `repo_id`: `str` (Foreign Key referencing `repos.id`, index)
  * `name`: `str` (Default `"default"`, max length 255)
  * `branch`: `str` (Default `"main"`, max length 100)
  * `status`: `str` (Index, nullable=False)
  * `duration`: `Optional[float]`
  * `trigger`: `str` (Default `"push"`)
  * `commit_hash`: `Optional[str]` (Max length 40)
  * `commit_message`: `Optional[str]` (Max length 500)
  * `triggered_by`: `Optional[str]` (Max length 100)
  * `environment`: `str` (Default `"staging"`, max length 50)
  * `stages`: `Optional[list]` (JSON column)
  * `logs`: `Optional[str]` (Text column)
  * `created_at`: `datetime` (Index)
  * `updated_at`: `datetime`

#### Rule
* **File Reference**: [app/models/rule.py:L14-L50](file:///d:/Projects/ReactJS/NexOps/backend/app/models/rule.py#L14-L50)
* **Table**: `rules`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `name`: `str` (Max length 255)
  * `description`: `Optional[str]` (Max length 500)
  * `condition_type`: `str` (Index, nullable=False)
  * `condition_config`: `Optional[list]` (JSON column)
  * `action_config`: `Optional[list]` (JSON column)
  * `is_active`: `bool` (Default `True`, index)
  * `execution_count`: `int` (Default 0)
  * `last_triggered_at`: `Optional[datetime]`
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

#### Team
* **File Reference**: [app/models/team.py:L12-L30](file:///d:/Projects/ReactJS/NexOps/backend/app/models/team.py#L12-L30)
* **Table**: `teams`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `name`: `str` (Index, max length 255)
  * `description`: `Optional[str]` (Max length 500)
  * `avatar_url`: `Optional[str]` (Max length 500)
  * `member_count`: `int` (Default 0)
  * `repo_count`: `int` (Default 0)
  * `health_score`: `float` (Default 100.0)
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

#### Dependency
* **File Reference**: [app/models/dependency.py:L14-L34](file:///d:/Projects/ReactJS/NexOps/backend/app/models/dependency.py#L14-L34)
* **Table**: `dependencies`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `source_repo_id`: `str` (Foreign Key referencing `repos.id`, index)
  * `target_repo_id`: `str` (Foreign Key referencing `repos.id`, index)
  * `type`: `str` (Default `"api"`, max length 50, index)
  * `label`: `str` (Default `"depends on"`, max length 100)
  * `created_at`: `datetime`

#### Incident
* **File Reference**: [app/models/incident.py:L14-L40](file:///d:/Projects/ReactJS/NexOps/backend/app/models/incident.py#L14-L40)
* **Table**: `incidents`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `cluster_id`: `Optional[str]` (Foreign Key referencing `clusters.id`, index)
  * `title`: `str` (Max length 255)
  * `description`: `Optional[str]` (Max length 1000)
  * `severity`: `str` (Default `"medium"`, index)
  * `status`: `str` (Default `"open"`, index)
  * `root_cause_repo_id`: `Optional[str]` (Foreign Key referencing `repos.id`)
  * `impacted_repos`: `List[str]` (JSON list column)
  * `impact_summary`: `Optional[str]` (Max length 1000)
  * `started_at`: `datetime`
  * `resolved_at`: `Optional[datetime]`
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

#### Deployment
* **File Reference**: [app/models/deployment.py:L12-L39](file:///d:/Projects/ReactJS/NexOps/backend/app/models/deployment.py#L12-L39)
* **Table**: `deployments`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `repo_id`: `str` (Foreign Key referencing `repos.id`, index)
  * `version`: `str` (Max length 100)
  * `environment`: `str` (Default `"staging"`, index)
  * `status`: `str` (Default `"pending"`, index)
  * `deployed_by`: `Optional[str]` (Max length 100)
  * `commit_hash`: `Optional[str]` (Max length 40)
  * `changelog`: `Optional[str]` (Max length 2000)
  * `provider_id`: `Optional[str]` (Index, added via custom migration script)
  * `deployed_at`: `datetime`
  * `finished_at`: `Optional[datetime]`
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

#### CloudProvider
* **File Reference**: [app/models/cloud_provider.py:L13-L48](file:///d:/Projects/ReactJS/NexOps/backend/app/models/cloud_provider.py#L13-L48)
* **Table**: `cloud_providers`
* **Fields**:
  * `id`: `str` (Primary Key, index)
  * `workspace_id`: `str` (Foreign Key referencing `workspaces.id`, index)
  * `name`: `str` (Max length 100)
  * `type`: `str` (Index)
  * `access_token`: `Optional[str]` (Fernet encrypted)
  * `secret_key`: `Optional[str]` (Fernet encrypted)
  * `account_id`: `Optional[str]`
  * `config`: `Dict[str, Any]` (JSON config object)
  * `status`: `str` (Default `"active"`)
  * `last_validated_at`: `datetime`
  * `created_at`: `datetime`
  * `updated_at`: `datetime`

### Migration Configuration & DDL State
Alembic is **not** configured for this project. Instead, the application runs dynamic startup tables check/creation inside [app/core/database.py:L36-L40](file:///d:/Projects/ReactJS/NexOps/backend/app/core/database.py#L36-L40):
```python
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
```
Incremental alterations are executed through four custom script migrations:
1. [migrate_add_cluster_id.py:L11-L76](file:///d:/Projects/ReactJS/NexOps/backend/migrate_add_cluster_id.py#L11-L76): Runs text DDL commands to check for and add the `cluster_id` column to the `repos` table, along with an foreign key constraint (`fk_repos_cluster_id`) and index.
2. [migrate_cloud.py:L6-L30](file:///d:/Projects/ReactJS/NexOps/backend/migrate_cloud.py#L6-L30): Creates the `cloud_providers` table.
3. [migrate_deployment.py:L5-L14](file:///d:/Projects/ReactJS/NexOps/backend/migrate_deployment.py#L5-L14): Adds the `provider_id` column to the `deployments` table, along with its index.
4. [migrate_logs.py:L5-L23](file:///d:/Projects/ReactJS/NexOps/backend/migrate_logs.py#L5-L23): Checks for and adds the `logs` column to the `pipelines` table.

### Unimplemented Planned Tables
* **`candidate_causes` Table**: The table specified in the correlation/feedback loop MVP design [NEXOPS_BACKEND_MVP_PLAN.md:L115-L127](file:///d:/Projects/ReactJS/NexOps/backend/docs/NEXOPS_BACKEND_MVP_PLAN.md#L115-L127) does not exist anywhere in the code.

---

## 3. API Routes

### Route Registrations
All route endpoints are mounted in [app/main.py:L82-L102](file:///d:/Projects/ReactJS/NexOps/backend/app/main.py#L82-L102) with `settings.API_PREFIX` prepended.

### Route Catalog

| Method | Endpoint Path | Source Location | Request Body / Query Params | Response Shape | Behavior Description |
|---|---|---|---|---|---|
| **GET** | `/alerts/counts` | [alerts.py:L16-L22](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/alerts.py#L16-L22) | `repo_id: Optional[str]` | `dict` | Returns active/resolved alert counts grouped by severity. |
| **GET** | `/alerts` | [alerts.py:L25-L42](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/alerts.py#L25-L42) | Query parameters: `repo_id`, `severity`, `resolved`, `limit`, `offset` | `List[AlertResponse]` | Lists security/system alerts matching filters. |
| **POST** | `/alerts` | [alerts.py:L45-L51](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/alerts.py#L45-L51) | `AlertCreate` | `AlertResponse` | Manually inserts a custom alert (bypasses rules pipeline). |
| **PATCH** | `/alerts/{alert_id}/resolve` | [alerts.py:L54-L63](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/alerts.py#L54-L63) | None | `AlertResponse` | Resolves the alert, logging `resolved_at` timestamp. |
| **PATCH** | `/alerts/{alert_id}/acknowledge` | [alerts.py:L66-L75](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/alerts.py#L66-L75) | None | `AlertResponse` | Acknowledges the alert without resolving it. |
| **GET** | `/analytics/dashboard/summary` | [analytics.py:L69-L108](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/analytics.py#L69-L108) | `workspace_id: Optional[str]` | `DashboardSummary` | Aggregate summary (stats + repos + unresolved alerts + clusters) cached in Redis for 30s. |
| **GET** | `/analytics/dashboard` | [analytics.py:L110-L123](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/analytics.py#L110-L123) | None | `DashboardStats` | Aggregates health score, CI pipeline success rate, vulnerability count, and infrastructure load. Cached for 30s. |
| **GET** | `/analytics/activity` | [analytics.py:L125-L178](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/analytics.py#L125-L178) | None | `ActivityResponse` | Aggregates commits, issues, and deployments over the last 7 days from the event log. Cached for 30s. |
| **GET** | `/cloud-providers` | [cloud_providers.py:L16-L25](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/cloud_providers.py#L16-L25) | `workspace_id: str` | `List[CloudProviderResponse]` | Lists connected workspace cloud infrastructure providers. |
| **POST** | `/cloud-providers` | [cloud_providers.py:L27-L57](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/cloud_providers.py#L27-L57) | `CloudProviderCreate` | `CloudProviderResponse` | Validates hosting tokens against target cloud services, encrypts tokens via Fernet, and saves provider credentials. |
| **DELETE**| `/cloud-providers/{provider_id}` | [cloud_providers.py:L59-L72](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/cloud_providers.py#L59-L72) | None | None (204 Status) | Disconnects the cloud provider config from the workspace. |
| **GET** | `/clusters` | [clusters.py:L23-L30](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L23-L30) | `workspace_id: str` | `List[ClusterResponse]` | Lists clusters. |
| **POST** | `/clusters` | [clusters.py:L33-L40](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L33-L40) | `ClusterCreate` | `ClusterResponse` | Creates a cluster. |
| **GET** | `/clusters/alert-summary` | [clusters.py:L43-L50](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L43-L50) | `workspace_id: str` | `List[ClusterAlertSummary]` | Fetches active alert severity stats grouped by cluster. |
| **GET** | `/clusters/{cluster_id}` | [clusters.py:L53-L62](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L53-L62) | None | `ClusterResponse` | Returns a single cluster. |
| **PATCH** | `/clusters/{cluster_id}` | [clusters.py:L65-L75](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L65-L75) | `ClusterUpdate` | `ClusterResponse` | Updates a cluster's name, color, or owner team. |
| **DELETE**| `/clusters/{cluster_id}` | [clusters.py:L78-L87](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L78-L87) | None | None (204 Status) | Deletes a cluster. |
| **GET** | `/clusters/{cluster_id}/repos` | [clusters.py:L89-L96](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L89-L96) | None | `List[RepoResponse]` | Lists repos belonging to the cluster. |
| **POST** | `/clusters/{cluster_id}/recalculate`| [clusters.py:L99-L109](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L99-L109) | None | `ClusterResponse` | Manually triggers cluster health score recalculation. |
| **POST** | `/clusters/{cluster_id}/assign-repo`| [clusters.py:L112-L148](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L112-L148) | `repo_id: str` | `ClusterResponse` | Assigns repository to cluster and forces cluster health recalculation. |
| **DELETE**| `/clusters/{cluster_id}/repos/{repo_id}`| [clusters.py:L151-L184](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L151-L184) | None | `ClusterResponse` | Removes a repo from the cluster and recalculates health. |
| **GET** | `/clusters/{cluster_id}/pods` | [clusters.py:L191-L219](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L191-L219) | None | `List[dict]` | **Mock/Stub**: Returns mock container workload pod stats. |
| **GET** | `/clusters/{cluster_id}/pods/{pod_name}/logs`| [clusters.py:L222-L243](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L222-L243) | None | `dict` | **Mock/Stub**: Returns mock historical diagnostics stdout logs. |
| **POST** | `/clusters/{cluster_id}/pods/{pod_name}/exec`| [clusters.py:L246-L310](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/clusters.py#L246-L310) | `ExecRequest` | `dict` | **Mock/Stub**: Simulates running commands (`help`, `ls`, `env`, `top`, `curl localhost:8000/health`) inside a mock container pod. |
| **GET** | `/dependencies/topology` | [dependencies.py:L25-L86](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/dependencies.py#L25-L86) | Query parameters: `workspace_id`, `cluster_id` | `TopologyResponse` | Returns topology network nodes/edges, setting `is_broken` on dependencies of failing repositories. |
| **GET** | `/dependencies` | [dependencies.py:L89-L92](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/dependencies.py#L89-L92) | None | `List[DependencyResponse]` | Returns all dependency link configurations. |
| **POST** | `/dependencies` | [dependencies.py:L95-L124](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/dependencies.py#L95-L124) | `DependencyCreate` | `DependencyResponse` | Persists a custom dependency connection between repositories. |
| **DELETE**| `/dependencies/{dependency_id}` | [dependencies.py:L127-L136](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/dependencies.py#L127-L136) | None | None (204 Status) | Removes a dependency edge. |
| **GET** | `/deployments` | [deployments.py:L16-L30](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/deployments.py#L16-L30) | Query parameters: `repo_id`, `environment` | `List[DeploymentResponse]` | Lists deployments ordered by date descending. |
| **POST** | `/deployments` | [deployments.py:L32-L84](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/deployments.py#L32-L84) | `DeploymentCreate` | `DeploymentResponse` | Creates a deployment, registers a `deploy.started` event, creates a running pipeline record, and triggers background automation. |
| **POST** | `/events` | [events.py:L47-L70](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/events.py#L47-L70) | `EventCreate` | `EventResponse` | Ingests a new event and spawns background automation runner. |
| **GET** | `/events` | [events.py:L72-L90](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/events.py#L72-L90) | Query parameters: `repo_id`, `type`, `processed`, `limit`, `offset` | `List[EventResponse]` | Lists system events. |
| **POST** | `/execute` | [executor.py:L58-L129](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/executor.py#L58-L129) | `ExecutionRequest` | `ExecutionResponse` | Runs Python or JavaScript code inside a temporary sandbox (handles Windows Proactor loop on Win32 platform, limits execution to 5s, sanitizes database config keys). |
| **GET** | `/incidents` | [incidents.py:L13-L27](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L13-L27) | Query parameters: `status`, `cluster_id` | `List[IncidentResponse]` | Lists incidents. |
| **GET** | `/incidents/{incident_id}` | [incidents.py:L29-L38](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L29-L38) | None | `IncidentResponse` | Returns details for a single incident. |
| **PATCH** | `/incidents/{incident_id}/resolve` | [incidents.py:L40-L50](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/incidents.py#L40-L50) | None | `IncidentResponse` | Resolves incident and resolves alerts (via `incident_service.resolve_incident`). |
| **GET** | `/insights/{repo_id}` | [insights.py:L20-L32](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/insights.py#L20-L32) | None | `InsightResponse` | Aggregates repository stats, alert counts, pipeline metrics, and active cascade incident metadata. |
| **POST** | `/insights/{repo_id}/recalculate-health`| [insights.py:L35-L44](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/insights.py#L35-L44) | None | `dict` | Triggers recalculation of repository health based on pipelines stability, commit activity, and active alert severity penalties. |
| **GET** | `/insights/workspace/{workspace_id}/ai-summary`| [insights.py:L55-L153](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/insights.py#L55-L153) | None | `str` | Submits aggregate metrics to Gemini and returns a text health summary (falls back to a static summary template if key is missing). |
| **POST** | `/insights/workspace/{workspace_id}/ai-query`| [insights.py:L163-L319](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/insights.py#L163-L319) | `AIQueryRequest` | `str` | Conversational DevOps query using Gemini (falls back to keyword-based template output if key is missing). |
| **POST** | `/insights/code-audit` | [insights.py:L327-L511](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/insights.py#L327-L511) | `CodeAuditRequest` | `dict` | Audits or explains code in `explain`, `diagnose`, or `test` mode (falls back to a regex parser if key is missing). |
| **POST** | `/integrations/sync` | [integrations.py:L26-L127](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/integrations.py#L26-L127) | `SyncRequest` | `dict` | Syncs repositories from the chosen VCS provider (GitHub, GitLab, or Bitbucket) and seeds synthetic history. |
| **GET** | `/workspaces/{workspace_id}/members` | [members.py:L45-L53](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/members.py#L45-L53) | None | `List[UserResponse]` | Lists members of the workspace. |
| **POST** | `/workspaces/{workspace_id}/invitations` | [members.py:L55-L67](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/members.py#L55-L67) | Email / role query params | `InvitationResponse` | Creates a workspace invitation token. Requires admin/lead role. |
| **POST** | `/invitations/{token}/accept` | [members.py:L69-L82](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/members.py#L69-L82) | None | `dict` | Accepts the workspace invitation, adding the user to the workspace. |
| **GET** | `/workspaces/{workspace_id}/invitations` | [members.py:L84-L92](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/members.py#L84-L92) | None | `List[InvitationResponse]` | Lists workspace invitations. |
| **DELETE**| `/workspaces/{workspace_id}/members/{user_id}`| [members.py:L94-L116](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/members.py#L94-L116) | None | `dict` | Revokes member access to workspace. Requires admin/lead role. |
| **DELETE**| `/workspaces/{workspace_id}/invitations/{invitation_id}`| [members.py:L118-L133](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/members.py#L118-L133) | None | `dict` | Cancels a workspace invitation. Requires admin/lead role. |
| **GET** | `/pipelines` | [pipelines.py:L134-L146](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/pipelines.py#L134-L146) | Query parameters: `repo_id`, `status`, `limit`, `offset` | `List[PipelineResponse]` | Lists pipeline execution history. |
| **GET** | `/pipelines/{pipeline_id}` | [pipelines.py:L149-L155](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/pipelines.py#L149-L155) | None | `PipelineResponse` | Returns detailed pipeline stages and execution logs. |
| **POST** | `/pipelines/trigger` | [pipelines.py:L158-L188](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/pipelines.py#L158-L188) | `TriggerRequest` | `PipelineResponse` | Manually triggers a simulated pipeline run that runs in background asyncio stages. |
| **POST** | `/pipelines/{pipeline_id}/cancel` | [pipelines.py:L191-L207](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/pipelines.py#L191-L207) | None | `PipelineResponse` | Cancels a running/pending pipeline. |
| **POST** | `/pipelines/{pipeline_id}/retry` | [pipelines.py:L210-L244](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/pipelines.py#L210-L244) | None | `PipelineResponse` | Clones a pipeline execution run as a new pending run. |
| **GET** | `/repos` | [repos.py:L20-L37](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/repos.py#L20-L37) | Query parameters: `workspace_id`, `cluster_id`, `platform`, `limit`, `offset` | `List[RepoResponse]` | Lists repositories. |
| **GET** | `/repos/search` | [repos.py:L40-L58](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/repos.py#L40-L58) | `q: str` | `List[RepoResponse]` | Searches repositories. |
| **GET** | `/repos/{repo_id}` | [repos.py:L61-L70](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/repos.py#L61-L70) | None | `RepoResponse` | Returns detail info for a single repo. |
| **POST** | `/repos` | [repos.py:L73-L79](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/repos.py#L73-L79) | `RepoCreate` | `RepoResponse` | Registers a repository. |
| **PATCH** | `/repos/{repo_id}` | [repos.py:L82-L114](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/repos.py#L82-L114) | `RepoUpdate` | `RepoResponse` | Updates repository and recalculates cluster health if modified. |
| **GET** | `/repos/{repo_id}/tree` | [repos.py:L117-L167](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/repos.py#L117-L167) | `path: str` | `List[dict]` | Fetches directory tree from VCS provider. Cached in Redis for 10 min. Throws 401 if token is unauthenticated. |
| **GET** | `/repos/{repo_id}/files/{path:path}`| [repos.py:L169-L214](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/repos.py#L169-L214) | None | `dict` | Fetches file content from VCS provider. Cached in Redis for 10 min. Throws 401 if token is unauthenticated. |
| **GET** | `/rules` | [rules.py:L18-L31](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/rules.py#L18-L31) | Query parameters: `is_active`, `limit`, `offset` | `List[RuleResponse]` | Lists automation rules. |
| **POST** | `/rules` | [rules.py:L34-L51](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/rules.py#L34-L51) | `RuleCreate` | `RuleResponse` | Creates a new automation rule with custom conditions and actions configuration. |
| **PATCH** | `/rules/{rule_id}` | [rules.py:L54-L87](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/rules.py#L54-L87) | `RuleUpdate` | `RuleResponse` | Updates rule configurations. |
| **DELETE**| `/rules/{rule_id}` | [rules.py:L90-L101](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/rules.py#L90-L101) | None | None (204 Status) | Deletes an automation rule. |
| **GET** | `/teams` | [teams.py:L17-L21](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/teams.py#L17-L21) | None | `List[TeamResponse]` | Lists all teams. |
| **GET** | `/teams/{team_id}` | [teams.py:L24-L30](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/teams.py#L24-L30) | None | `TeamResponse` | Returns details for a single team. |
| **GET** | `/users` | [users.py:L17-L21](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/users.py#L17-L21) | None | `List[UserResponse]` | Lists all registered users. |
| **GET** | `/users/me` | [users.py:L27-L30](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/users.py#L27-L30) | None (Bearer header) | `UserResponse` | Returns profile of current user. |
| **POST** | `/webhooks/github` | [webhooks.py:L40-L128](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L40-L128) | Webhook payload | `dict` | Ingests webhook events from GitHub, updates repo stats, and executes automation rules. |
| **GET** | `/workspaces` | [workspaces.py:L38-L56](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/workspaces.py#L38-L56) | None | `List[WorkspaceResponse]` | Lists workspaces with calculated counts and average health score. |
| **POST** | `/workspaces` | [workspaces.py:L59-L67](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/workspaces.py#L59-L67) | `WorkspaceCreate` | `WorkspaceResponse` | Creates workspace. |
| **GET** | `/workspaces/{workspace_id}` | [workspaces.py:L70-L86](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/workspaces.py#L70-L86) | None | `WorkspaceResponse` | Returns detailed stats for a workspace. |
| **PATCH** | `/workspaces/{workspace_id}` | [workspaces.py:L18-L35](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/workspaces.py#L18-L35) | `WorkspaceUpdate` | `WorkspaceResponse` | Updates workspace. |
| **DELETE**| `/workspaces/{workspace_id}` | [workspaces.py:L88-L98](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/workspaces.py#L88-L98) | None | None (204 Status) | Deletes workspace. |

---

## 4. Ingestion / Webhooks

### GitHub Ingestion Handler
* **Endpoint File**: [app/api/routes/webhooks.py](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py)
* **Handler Method**: `github_webhook_handler` at [webhooks.py:L40-L128](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L40-L128).
* **Verification Code**:
  Verified via `verify_signature` [webhooks.py:L19-L38](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L19-L38):
  ```python
  async def verify_signature(request: Request, x_hub_signature_256: str = Header(None)):
      if not settings.GITHUB_WEBHOOK_SECRET:
          logger.warning("GITHUB_WEBHOOK_SECRET not set, skipping verification.")
          return

      if not x_hub_signature_256:
          raise HTTPException(status_code=401, detail="X-Hub-Signature-256 header missing")

      body = await request.body()
      signature = hmac.new(
          settings.GITHUB_WEBHOOK_SECRET.encode(),
          body,
          hashlib.sha256
      ).hexdigest()

      if not hmac.compare_digest(f"sha256={signature}", x_hub_signature_256):
          raise HTTPException(status_code=401, detail="Invalid signature")
  ```
  > [!WARNING]
  > **Header Resolution Defect**: The handler calls this verification function inline as `await verify_signature(request)` at [webhooks.py:L52](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L52). Because it is not resolved as a FastAPI dependency parameter, the parameter `x_hub_signature_256` defaults to `None`. This causes signature validation to fail with a `401 Unauthorized` response in all production environments where a webhook secret is defined.

### Payload Processing
Upon receiving valid webhooks, the code parses the payload:
1. Extracts repo names [webhooks.py:L58-L62](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L58-L62) and queries the local database `Repo` [webhooks.py:L65-L68](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L65-L68).
2. Maps event structures [webhooks.py:L78-L107](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L78-L107):
   * `push` -> `repo.updated` event, updates the repo's `last_commit_at` field in SQL.
   * `pull_request` (opened) -> `pr.opened` event.
   * `pull_request` (closed & merged) -> `pr.merged` event.
   * `issues` (opened) -> `issue.created` event, increments `repo.open_issues` by 1.
3. Saves a new record in the `events` table [webhooks.py:L112-L121](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L112-L121).
4. Launches the automation engine in a background task via `_run_automation(new_event.id)` [webhooks.py:L124-L126](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/webhooks.py#L124-L126).

### OAuth / Connect Flow
No full OAuth handshake flow is implemented.
* The repository sync flow is initiated via `POST /integrations/sync` in [app/api/routes/integrations.py:L26-L127](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/integrations.py#L26-L127).
* The user passes the provider name and OAuth/Access Token manually.
* The VCS sync layer calls `vcs_service.sync_repositories` in [app/services/vcs_service.py:L111-L137](file:///d:/Projects/ReactJS/NexOps/backend/app/services/vcs_service.py#L111-L137), making live API requests using `httpx.AsyncClient` to list the repositories:
  * For GitHub: `https://api.github.com/user/repos` [vcs_service.py:L12-L24](file:///d:/Projects/ReactJS/NexOps/backend/app/services/vcs_service.py#L12-L24)
  * For GitLab: `https://gitlab.com/api/v4/projects` [vcs_service.py:L26-L38](file:///d:/Projects/ReactJS/NexOps/backend/app/services/vcs_service.py#L26-L38)
  * For Bitbucket: `https://api.bitbucket.org/2.0/repositories?role=member` [vcs_service.py:L40-L52](file:///d:/Projects/ReactJS/NexOps/backend/app/services/vcs_service.py#L40-L52)
* The access token is encrypted using the symmetric `ENCRYPTION_KEY` and saved to `Workspace.access_token` [integrations.py:L47](file:///d:/Projects/ReactJS/NexOps/backend/app/api/routes/integrations.py#L47).

---

## 5. Correlation Logic

### Incident Correlation
There is **no scoring or correlation function** implemented in the codebase.
* Incoming alerts are handled by `get_or_create_incident` in [app/services/incident_service.py:L18-L67](file:///d:/Projects/ReactJS/NexOps/backend/app/services/incident_service.py#L18-L67).
* Instead of analyzing files or scores, the service groups alerts strictly by timeframe and cluster location:
  * Looks back 30 minutes for an existing open incident in the same cluster [incident_service.py:L33-L41](file:///d:/Projects/ReactJS/NexOps/backend/app/services/incident_service.py#L33-L41).
  * If found, groups the alert into that incident [incident_service.py:L43-L50](file:///d:/Projects/ReactJS/NexOps/backend/app/services/incident_service.py#L43-L50).
  * If none exists, creates a new incident and assigns the reporting repo directly as the root cause (`root_cause_repo_id=repo_id`) [incident_service.py:L53-L61](file:///d:/Projects/ReactJS/NexOps/backend/app/services/incident_service.py#L53-L61).

### Blast Radius Analysis
No blast radius score or risk basis computation exists in the code yet.
* Downstream impact is computed by `propagate_impact` in [app/services/impact_service.py:L18-L80](file:///d:/Projects/ReactJS/NexOps/backend/app/services/impact_service.py#L18-L80), which:
  * Recursively traverses downstream nodes via `Dependency` records [impact_service.py:L36-L70](file:///d:/Projects/ReactJS/NexOps/backend/app/services/impact_service.py#L36-L70).
  * Deducts points from downstream repository `health_score` values based on root cause severity (halves at each hop) [impact_service.py:L57-L59](file:///d:/Projects/ReactJS/NexOps/backend/app/services/impact_service.py#L57-L59).
  * Marks CI status as `"failing"` if the score drops below 50 [impact_service.py:L61-L63](file:///d:/Projects/ReactJS/NexOps/backend/app/services/impact_service.py#L61-L63).
  * Recalculates health metrics for all affected clusters [impact_service.py:L73-L78](file:///d:/Projects/ReactJS/NexOps/backend/app/services/impact_service.py#L73-L78).

---

## 6. Feedback / State Persistence

### Decision Persistence
No feedback endpoint or database storage mechanism exists for saving user decisions.
* The planned endpoint `POST /api/incidents/{id}/feedback` from the design specs is missing.
* The database schema does not have a `candidate_causes` table or matching fields.
* The GET incidents endpoints return database records containing basic severity, status, and root cause fields, but no correlation ratings or confirm/reject states.

---

## 7. Testing & Validation

The backend repository includes 5 Python verification scripts under `tests/`:

### 1. `tests/test_endpoints.py`
* **Coverage**: Verifies all standard route endpoints, ensuring they return the expected JSON structures matching the frontend's camelCase mapping requirements.
  * Health status check [test_endpoints.py:L22-L29](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L22-L29).
  * Listing and details schema validation for `/users` and `/users/me` [test_endpoints.py:L31-L46](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L31-L46).
  * Teams listing and details lookup [test_endpoints.py:L48-L62](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L48-L62).
  * Repository CRUD operations and camelCase checks [test_endpoints.py:L64-L96](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L64-L96).
  * Workspaces listing and stats [test_endpoints.py:L97-L107](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L97-L107).
  * Pipeline history and metadata validation [test_endpoints.py:L109-L119](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L109-L119).
  * Automation rule multi-actions check [test_endpoints.py:L121-L136](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L121-L136).
  * Event ingestion validation and background processing [test_endpoints.py:L138-L172](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L138-L172).
  * Alert listing and patch resolution checks [test_endpoints.py:L174-L196](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L174-L196).
  * Intelligence insight recommendation checks [test_endpoints.py:L198-L211](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_endpoints.py#L198-L211).
* **Execution Status**: **PASS** (10/10 test groups pass).

### 2. `tests/test_security.py`
* **Coverage**: Validates security hardening measures:
  * Sandbox environment variable isolation (verifies that `DATABASE_URL` and `ENCRYPTION_KEY` are removed from the process namespace before executing code) [test_security.py:L30-L59](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_security.py#L30-L59).
  * WebSocket session validation (asserts that connections without valid credentials are terminated with code 4001) [test_security.py:L60-L81](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_security.py#L60-L81).
  * Decrypted access token safety (asserts that `WorkspaceResponse` models omit sensitive key strings) [test_security.py:L83-L105](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_security.py#L83-L105).
* **Execution Status**: **PASS** (3/3 checks pass).

### 3. `tests/test_members_security.py`
* **Coverage**: Tests authorization rules for team management:
  * Verifies current authenticated user profile [test_members_security.py:L21-L28](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_members_security.py#L21-L28).
  * Verifies that list members and invite requests are rejected with `403 Forbidden` for unauthorized users [test_members_security.py:L30-L53](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_members_security.py#L30-L53).
  * Simulates elevating a user to workspace admin directly in the database [test_members_security.py:L55-L91](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_members_security.py#L55-L91).
  * Asserts that Workspace Admins can successfully list members and create invitations [test_members_security.py:L93-L112](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_members_security.py#L93-L112).
* **Execution Status**: **PASS** (5/5 checks pass).

### 4. `tests/test_performance.py`
* **Coverage**: Asserts Redis cache caching hits and invalidation latency thresholds:
  * Cache population [test_performance.py:L36-L54](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_performance.py#L36-L54).
  * Cache hit latency (asserts subsequent request resolves in < 50ms) [test_performance.py:L56-L78](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_performance.py#L56-L78).
  * Invalidation check (asserts event creation clears dashboard caches) [test_performance.py:L80-L124](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_performance.py#L80-L124).
* **Execution Status**: **FAIL**.
  * > [!CAUTION]
  * **Firebase Blocking Latency**: During development tests, calling the auth route dependency `Depends(get_current_user)` triggers a verification call `auth.verify_id_token("dev-dummy-token")` in [app/core/security.py:L43](file:///d:/Projects/ReactJS/NexOps/backend/app/core/security.py#L43). Because `dev-dummy-token` is a dummy token, Firebase attempts to fetch public certificates from Google's keyserver over the network. This network call blocks for ~2.4 seconds on *every* API request before raising an exception, causing subsequent requests to take ~2476ms, violating the cache hit latency threshold of < 50ms.

### 5. `tests/test_vcs_caching.py`
* **Coverage**: Asserts live file tree directory caching in Redis [test_vcs_caching.py:L58-L136](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_vcs_caching.py#L58-L136).
* **Execution Status**: **SKIP**.
  * Skips tests with a warning because the database was seeded with dummy workspaces lacking authentic GitHub tokens [test_vcs_caching.py:L69-L71](file:///d:/Projects/ReactJS/NexOps/backend/tests/test_vcs_caching.py#L69-L71).

---

## 8. Gaps Summary

Below is a consolidated list of divergence points, security issues, and stubbed features identified in the NexOps backend:

1. **`candidate_causes` Table Missing**: The primary database table designed to persist candidate causes, correlation scores, and user confirmation flags is completely missing from the codebase.
2. **Missing Correlation & Scoring Algorithm**: Point-based logic from the MVP plan does not exist. Root cause is assigned directly to the reporting repository.
3. **No Feedback Persistence Endpoint**: The feedback ingestion endpoint `/api/incidents/{id}/feedback` is unimplemented.
4. **No Blast Radius Metrics**: Blast radius score and risk basis are not computed or stored.
5. **FastAPI Webhook Signature Verification Defect**: GitHub webhook signature checks are called inline without passing `x_hub_signature_256` as a route dependency, causing validation failures in production if a webhook secret is defined.
6. **Container Diagnostic Stubs**: Pod shell execution paths (`GET /pods`, `GET /pods/{name}/logs`, and `POST /pods/{name}/exec` in `app/api/routes/clusters.py`) return hardcoded mock responses.
7. **OAuth Connect Handshake Stubbed**: The workspace connect endpoint relies on users manually pasting an access token into the `/integrations/sync` request payload.
8. **Performance Cache Latency Test Failure**: Verification of caching hits fails on `test_performance.py` due to Firebase certificate fetching delays when validating dummy session tokens.
9. **Missing Env variables in `.env.example`**: Secrets configuration items (`FIREBASE_SERVICE_ACCOUNT_PATH`, `ENCRYPTION_KEY`, and `GITHUB_WEBHOOK_SECRET`) are missing from the configuration template.
