# NexOps — FastAPI Backend & Background Worker Engine

<p align="center">
  <a href="https://skillicons.dev">
    <img src="https://skillicons.dev/icons?i=py,fastapi,postgres,redis,docker,gcp,git,github,githubactions" alt="Backend Tech Stack Icons" />
  </a>
</p>

The high-throughput, async Python backend for **NexOps** — powers real-time incident correlation, GitHub/PagerDuty webhook processing, Redis stream event processing, microservice topology analysis, and automated deployment risk scoring.

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

## 🚀 Key Features

1. **Async REST API**: Built on FastAPI with Pydantic validation, OAuth2 GitHub authentication, and tenant workspace isolation.
2. **Redis Streams Consumer Worker**: Dedicated background worker service (`app/worker/stream_consumer.py`) handling event streams, dead-letter queues, and automatic background GitHub synchronization.
3. **Automated GitHub Auto-Sync & Repo Pruning**: Background polling loop (every 60s) automatically discovers new repos, syncs deployments, and prunes deleted repos from PostgreSQL.
4. **Impact & Risk Scoring Engine**: Dynamically calculates deployment risk scores based on dependency depth, temporal proximity, and active incident correlation.
5. **Comprehensive Diagnostic `/health` Endpoint**: Live request-time checks for Database, Redis, Background Worker heartbeat, and GitHub/PagerDuty API reachability.
6. **Workspace Feature Flag Guard (`show_extended_navigation`)**: Security dependency (`app/core/security.py:verify_extended_navigation`) gating `/analytics/*`, `/events`, `/automation/*`, and `/incidents/{id}/postmortem` routes behind a workspace tenant flag (default `False`).


---

## 💻 Getting Started & Local Setup

### Prerequisites
- Python 3.12+
- PostgreSQL database (or Neon branch)
- Redis instance

### Installation

```bash
# Navigate to the backend folder
cd backend

# Create and activate virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration

Create a `.env` file in the `backend/` root directory:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/nexops
REDIS_URL=redis://localhost:6379
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret
GITHUB_WEBHOOK_SECRET=your_webhook_secret
ENCRYPTION_KEY=your_fernet_encryption_key
```

### Run API Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

Access API docs at [`http://localhost:8000/docs`](http://localhost:8000/docs).

### Run Background Stream Consumer Worker

```bash
python -m app.worker.stream_consumer
```

---

## 📁 Project Structure

```
backend/
├── app/
│   ├── api/
│   │   └── routes/             # API Endpoint handlers (auth, integrations, incidents, health, webhooks)
│   ├── core/                   # Security, Database session, Redis client, Config, Encryption
│   ├── models/                 # SQLModel / SQLAlchemy entities (User, Repo, Deployment, Incident, Event)
│   ├── services/               # Automation, Impact calculation, VCS service
│   ├── worker/                 # Redis stream consumer & background GitHub auto-sync loop
│   └── main.py                 # FastAPI app entry point & live diagnostic /health endpoint
├── alembic/                    # Database migration scripts
├── scratch/                    # Verification & diagnostic utility scripts
└── requirements.txt            # Python dependencies
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
