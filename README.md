# NexOps — FastAPI Backend & Background Worker Engine

<p align="center">
  <a href="https://skillicons.dev">
    <img src="https://skillicons.dev/icons?i=py,fastapi,postgres,redis,docker,gcp,git,github,githubactions" alt="Backend Tech Stack Icons" />
  </a>
</p>

The high-throughput, async Python backend for **NexOps** — powers real-time incident correlation, GitHub/PagerDuty webhook processing, Redis stream event processing, microservice topology analysis, and automated deployment risk scoring.

---

## 🏗️ System Architecture

```mermaid
graph TD
    subgraph External ["External Integrations"]
        GH[GitHub Webhooks / VCS API]
        PD[PagerDuty Webhooks]
    end

    subgraph API_Layer ["API Layer (FastAPI)"]
        API[FastAPI App :8000]
        SEC[Security / RLS Context]
        HMAC[HMAC-SHA256 Signature Validator]
        LIM[SlowAPI Rate Limiter]
    end

    subgraph Storage ["State & Message Bus"]
        PG[(PostgreSQL + Row Level Security)]
        RDS[(Redis: Cache + Stream Bus)]
    end

    subgraph Worker_Layer ["Worker Engine"]
        WKR[Stream Consumer Worker]
        SYNC[GitHub Auto-Sync Loop (60s)]
        DLQ[Dead-Letter Stream: nexops:events:dead]
    end

    subgraph Intelligence ["Correlation Engine"]
        CORR[Candidate Cause Scorer]
        RECAL[Weight Recalibration Engine]
        POSTM[Postmortem Lifecycle Engine]
    end

    GH -->|HMAC-SHA256| HMAC
    PD -->|HMAC-SHA256 + Signed UID| HMAC
    HMAC --> API
    API --> LIM
    API --> SEC
    SEC -->|Advisory Lock / RLS| PG
    API -->|xadd nexops:events| RDS
    RDS -->|xreadgroup| WKR
    WKR --> CORR
    CORR --> PG
    WKR -->|Max 3 Retries Exceeded| DLQ
    SYNC -->|Fetch VCS metadata| GH
    SYNC --> PG
    API --> RECAL
    RECAL --> PG
    API --> POSTM
```

---

## ⚡ Webhook Ingestion & Worker Sequence

```mermaid
sequenceDiagram
    autonumber
    participant VCS as GitHub / PagerDuty
    participant API as FastAPI Webhook Route
    participant DB as PostgreSQL (RLS)
    participant Redis as Redis Stream (nexops:events)
    participant WKR as Background Worker
    participant CORR as Correlation Engine

    VCS->>API: POST /api/v1/webhooks/* (Signature, Payload)
    API->>API: Validate HMAC-SHA256 & Target Workspace UID
    API->>DB: Acquire Transaction Advisory Lock (Workspace + Repo)
    API->>DB: Check Event Deduplication Window (30 min)
    API->>DB: INSERT INTO events (workspace_id, repo_id, ...)
    API->>Redis: XADD nexops:events (event_id, workspace_id)
    API-->>VCS: HTTP 200 OK {"status": "processed", "event_id": "..."}
    
    Note over Redis,WKR: Asynchronous Worker Processing
    Redis->>WKR: XREADGROUP nexops-workers
    WKR->>DB: SELECT event + Set RLS Context (workspace_id)
    WKR->>CORR: Run Multi-Factor Correlation & Scoring
    CORR->>DB: Update Incident / Candidate Causes
    WKR->>Redis: XACK nexops:events (message_id)
    alt Worker Failure
        WKR->>Redis: Retry with incremented count (Max 3)
        WKR->>Redis: Route to nexops:events:dead on 3rd failure
    end
```

---

## 🛠️ Tech Stack & Badges

| Technology | Purpose | Icon Badge |
| :--- | :--- | :--- |
| **Python 3.12** | Core Programming Language | <img src="https://skillicons.dev/icons?i=py" width="36" height="36" alt="Python" /> |
| **FastAPI** | Asynchronous REST API Framework | <img src="https://skillicons.dev/icons?i=fastapi" width="36" height="36" alt="FastAPI" /> |
| **PostgreSQL & Neon** | Relational Database & Row-Level Security (RLS) | <img src="https://skillicons.dev/icons?i=postgres" width="36" height="36" alt="PostgreSQL" /> |
| **Redis** | In-Memory Cache & Redis Streams Consumer | <img src="https://skillicons.dev/icons?i=redis" width="36" height="36" alt="Redis" /> |
| **Docker** | Containerization & Local Development | <img src="https://skillicons.dev/icons?i=docker" width="36" height="36" alt="Docker" /> |
| **Google Cloud Platform** | Compute Engine Background Worker Host | <img src="https://skillicons.dev/icons?i=gcp" width="36" height="36" alt="GCP" /> |
| **GitHub Actions** | Automated CI/CD Pipelines & Webhooks | <img src="https://skillicons.dev/icons?i=githubactions" width="36" height="36" alt="GitHub Actions" /> |
| **Git & GitHub** | Source Control & Versioning | <img src="https://skillicons.dev/icons?i=git,github" height="36" alt="Git & GitHub" /> |

---

## 📊 Empirically Verified Repository Facts

| Dimension | Count / Status | Verification Evidence |
| :--- | :--- | :--- |
| **API Endpoints** | 39 distinct endpoints | Inspected across 13 FastAPI router files under `app/api/routes/` |
| **Database Tables** | 13 SQLModel models | `users`, `workspaces`, `repos`, `clusters`, `events`, `alerts`, `deployments`, `incidents`, `candidate_causes`, `postmortems`, `dependencies`, `alert_rules`, `scoring_weight_recalibrations` |
| **Core Services** | 10 domain services | `alert_service`, `automation_service`, `correlation_service`, `event_service`, `impact_service`, `incident_service`, `insight_service`, `queue_service`, `recalibration_service`, `repo_service`, `vcs_service` |
| **Worker Loops** | 2 continuous loops | `stream_consumer.py` (Redis Streams consumer group `nexops-workers`) + GitHub background auto-sync polling loop (every 60s) |
| **Pytest Test Suite** | 61 passed / 0 failed (100%) | `test_venv/Scripts/python -m pytest` across 14 test files in `tests/` |
| **Weight Recalibration** | Fully wired & tested | `< 20` samples returns defaults; `≥ 20` samples recalculates win rates bounded $[0.5\times, 1.5\times]$ and persists weights (`tests/test_recalibration.py`) |
| **Worker Resilience** | Retries, DLQ & Idempotency | Max 3 retries, dead-letter routing to `nexops:events:dead`, transaction advisory lock deduplication on `(workspace_id, repo_id)` |
| **Mock Authentication** | Production Safe | Gated by `ALLOW_MOCK_AUTH` (default `False`), neutral dummy credentials (`usr-mock-dev-001`), hard startup refusal in production |

---

## ⏱️ Local Load Benchmark (Classification: local, single machine)

> [!NOTE]
> All numbers below were recorded on a single development machine (Windows laptop with 12 CPU cores, local PostgreSQL on port 5432, local Redis on port 6379). **They reflect local execution and must not be quoted as production capacity.**

### Webhook Ingestion Throughput (3 Concurrency Tiers)

| Concurrency | Total Requests | Success Rate | Throughput (RPS) | p50 Latency (ms) | p95 Latency (ms) | p99 Latency (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10** | 25 | **100% (25/25)** | 5.3 req/s | 1,525.6 ms | 3,197.9 ms | 3,287.6 ms |
| **20** | 40 | **100% (40/40)** | 6.8 req/s | 2,293.7 ms | 5,127.9 ms | 5,140.6 ms |
| **30** | 60 | **100% (60/60)** | 6.6 req/s | 3,822.4 ms | 7,177.9 ms | 7,554.5 ms |

### Worker Stream Consumption Throughput

- **Batch Size**: 50 pipeline events
- **Worker Execution Time**: 3.042 seconds
- **Worker Throughput**: **16.4 events/sec**

---

## 🚀 Run the Demo (Local Step-by-Step)

Follow these steps to run the complete NexOps stack locally:

### 1. Prerequisites
- Python 3.12+
- PostgreSQL running locally on port 5432
- Redis running locally on port 6379

### 2. Setup Virtual Environment & Dependencies

```bash
# Clone and enter backend directory
cd backend

# Create virtual environment
python -m venv test_venv

# Activate environment
# Windows:
test_venv\Scripts\activate
# Linux/macOS:
source test_venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install pytest pytest-asyncio
```

### 3. Environment Configuration

Create a `.env` file in `backend/` with:

```env
APP_NAME=NexOps
APP_ENV=development
DEBUG=true
API_PREFIX=/api/v1
ALLOW_MOCK_AUTH=true
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/nexops_dev
REDIS_URL=redis://localhost:6379
REDIS_MAX_CONNECTIONS=50
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
ENCRYPTION_KEY=MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE=
GITHUB_WEBHOOK_SECRET=demo_github_secret
PAGERDUTY_WEBHOOK_SECRET=demo_pagerduty_secret
```

### 4. Run Migrations & Seed Database

```bash
# Apply Alembic schema migrations
alembic upgrade head

# Seed demo workspace, repositories, and incident precedent
python seed.py
```

### 5. Launch the API & Background Worker

Open two separate terminals:

**Terminal 1 — FastAPI Server:**
```bash
uvicorn app.main:app --reload --port 8000
```
*Interactive Swagger docs available at [http://localhost:8000/docs](http://localhost:8000/docs)*

**Terminal 2 — Redis Stream Consumer Worker:**
```bash
python -m app.worker.stream_consumer
```

### 6. Run the Test Suite & Load Benchmark

```bash
# Run full automated test suite (61 tests)
pytest -v

# Run local load benchmark (webhook ingestion + worker throughput)
python tests/load/load_test_webhooks.py
```

---

## 📁 Repository Structure

```
backend/
├── .github/
│   └── workflows/
│       ├── ci.yml              # GitHub Actions CI with Postgres & Redis service containers
│       └── db_backup.yml       # Automated database backup workflow
├── alembic/                    # Database migrations & RLS policies
├── app/
│   ├── api/routes/             # 13 REST API routes (auth, webhooks, incidents, health, etc.)
│   ├── core/                   # Security, RLS bypass context manager, Redis client, Database engine
│   ├── models/                 # 13 SQLModel data models with UTC timezone enforcement
│   ├── schemas/                # Pydantic request & response validation schemas
│   ├── services/               # Automation, Correlation, Recalibration, Impact analysis
│   ├── worker/                 # Redis stream consumer & background GitHub auto-sync loop
│   └── main.py                 # FastAPI application, lifespan checks, and health endpoints
├── tests/
│   ├── conftest.py             # Engine & Redis connection pool teardown fixture
│   ├── load/
│   │   └── load_test_webhooks.py # 3-tier concurrent webhook & worker load test
│   ├── test_correlation.py
│   ├── test_event_idempotency.py
│   ├── test_evidence_suite.py
│   ├── test_health_deep.py
│   ├── test_incident_race.py
│   ├── test_mock_auth_security.py
│   ├── test_no_score_injection.py
│   ├── test_pagerduty_decryption.py
│   ├── test_plain_english_match_reasons.py
│   ├── test_recalibration.py
│   ├── test_repo_sync_dedup.py
│   ├── test_repos_ownership.py
│   └── test_sentry.py
└── pytest.ini
```

---

## 🛠️ Production Commands (GCP Compute Engine)

```bash
# Restart background worker service on GCP VM
sudo systemctl restart nexops-worker

# Check worker service status
sudo systemctl status nexops-worker

# View live worker logs
sudo journalctl -u nexops-worker -f -n 50
```
