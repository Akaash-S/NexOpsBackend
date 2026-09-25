"""
NexOps Backend - Correlation Engine Unit and Integration Tests
==============================================================
Verifies core correlation engine guarantees:
1. Deduplication: Multiple events on the same repository are collapsed to the highest-scoring candidate.
2. Score Capping: Natural scoring factors summing to >100 points are capped at exactly 100.0 without backdoor overrides.
3. Unique Constraint: Database constraint enforces (incident_id, event_id) uniqueness on candidate_causes.
"""

import uuid
import json
import pytest
from datetime import datetime, timedelta
from urllib.parse import urlparse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session, init_db
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.models.event import Event
from app.models.incident import Incident
from app.models.candidate_cause import CandidateCause
from app.models.candidate_cause_feedback_log import CandidateCauseFeedbackLog
from app.models.scoring_weight_recalibration import ScoringWeightRecalibration
from app.services.incident_service import correlate_incident_causes
from app.services.recalibration_service import DEFAULT_WEIGHTS


def _verify_localhost_db():
    parsed = urlparse(settings.DATABASE_URL)
    host = parsed.hostname
    port = parsed.port
    dbname = parsed.path.lstrip("/")
    print(f"\n[DB Safety Check] Host: {host}:{port} | Database: {dbname}")
    assert host in ("localhost", "127.0.0.1"), f"SAFETY ABORT: Test database host is '{host}', expected localhost!"


@pytest.mark.asyncio
async def test_fix1_deduplication():
    """
    [Test Fix 1] Duplicate candidate causes deduplication:
    Ingests multiple events on the same repository within the correlation window.
    Asserts that correlate_incident_causes collapses them to at most 1 candidate cause per repo.
    """
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-dedup-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Dedup WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-dedup-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="Dedup User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        repo_id = f"repo-dedup-{uuid.uuid4().hex[:8]}"
        repo = Repo(id=repo_id, name="api-gateway", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo)
        await session.flush()

        now = datetime.utcnow()
        # Event 1: 10 minutes ago
        evt1 = Event(
            id=f"evt-1-{uuid.uuid4().hex[:8]}",
            type="push",
            source="github",
            repo_id=repo_id,
            workspace_id=ws_id,
            payload={},
            created_at=now - timedelta(minutes=10)
        )
        # Event 2: 5 minutes ago (same repo, different commit)
        evt2 = Event(
            id=f"evt-2-{uuid.uuid4().hex[:8]}",
            type="push",
            source="github",
            repo_id=repo_id,
            workspace_id=ws_id,
            payload={},
            created_at=now - timedelta(minutes=5)
        )
        session.add(evt1)
        session.add(evt2)
        await session.flush()

        incident = Incident(
            id=f"inc-dedup-{uuid.uuid4().hex[:8]}",
            title="Gateway 502 Outage",
            workspace_id=ws_id,
            root_cause_repo_id=repo_id,
            status="open",
            created_at=now,
            updated_at=now
        )
        session.add(incident)
        await session.flush()

        await correlate_incident_causes(session, incident)
        await session.commit()

        # Query candidates
        cand_res = await session.execute(
            select(CandidateCause).where(CandidateCause.incident_id == incident.id)
        )
        candidates = cand_res.scalars().all()

        repo_counts = {}
        for c in candidates:
            repo_counts[c.repo_id] = repo_counts.get(c.repo_id, 0) + 1

        print(f"Candidate causes: {[(c.repo_id, c.score) for c in candidates]}")
        assert repo_counts.get(repo_id, 0) == 1, f"Expected exactly 1 candidate cause for {repo_id}, got {repo_counts.get(repo_id)}"


@pytest.mark.asyncio
async def test_fix2_score_capping():
    """
    [Test Fix 2] Score capping at 100.0 without backdoor:
    Explicitly seeds calibrated weights and historical precedent such that natural
    scoring factors sum to >100.0. Asserts that the final candidate score is capped at 100.0.
    """
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-cap-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="Capping WS", color="green", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-cap-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="Cap User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        repo_id = f"repo-cap-{uuid.uuid4().hex[:8]}"
        repo = Repo(id=repo_id, name="billing-service", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo)
        await session.flush()

        # Explicitly seed weight recalibration state for this workspace
        # Weights: same_repo=50.0, temp_15m=35.0, past_precedent=20.0 -> sum = 105.0+ (>100.0)
        recal = ScoringWeightRecalibration(
            id=f"recal-{uuid.uuid4().hex[:8]}",
            workspace_id=ws_id,
            weights=json.dumps({
                "same_repo": 50.0,
                "temp_15m": 35.0,
                "past_precedent": 20.0,
                "deploy_risk": 20.0
            }),
            sample_size=25,
            previous_weights=json.dumps(DEFAULT_WEIGHTS),
            trigger_type="test_setup"
        )
        session.add(recal)

        # Seed confirmed past incident feedback log on this repo (within 90 days)
        now = datetime.utcnow()
        past_inc = Incident(
            id=f"inc-past-{uuid.uuid4().hex[:8]}",
            title="Past Database Crash",
            workspace_id=ws_id,
            root_cause_repo_id=repo_id,
            status="resolved",
            created_at=now - timedelta(days=20),
            updated_at=now - timedelta(days=20)
        )
        session.add(past_inc)
        await session.flush()

        past_cand = CandidateCause(
            id=f"cand-past-{uuid.uuid4().hex[:8]}",
            workspace_id=ws_id,
            incident_id=past_inc.id,
            repo_id=repo_id,
            score=80.0,
            reason="Past root cause",
            confirmed=True
        )
        session.add(past_cand)
        await session.flush()

        fb_log = CandidateCauseFeedbackLog(
            id=f"fb-{uuid.uuid4().hex[:8]}",
            workspace_id=ws_id,
            candidate_cause_id=past_cand.id,
            incident_id=past_inc.id,
            repo_id=repo_id,
            confirmed=True,
            created_at=now - timedelta(days=20)
        )
        session.add(fb_log)
        await session.flush()

        # Ingest event with standard empty payload (NO test_score_boost)
        evt = Event(
            id=f"evt-cap-{uuid.uuid4().hex[:8]}",
            type="push",
            source="github",
            repo_id=repo_id,
            workspace_id=ws_id,
            payload={},
            created_at=now - timedelta(minutes=5)
        )
        session.add(evt)
        await session.flush()

        # Trigger current incident
        incident = Incident(
            id=f"inc-curr-{uuid.uuid4().hex[:8]}",
            title="Billing Checkout Errors",
            workspace_id=ws_id,
            root_cause_repo_id=repo_id,
            status="open",
            created_at=now,
            updated_at=now
        )
        session.add(incident)
        await session.flush()

        # Correlate causes
        await correlate_incident_causes(session, incident)
        await session.commit()

        # Fetch candidate cause
        cand_res = await session.execute(
            select(CandidateCause).where(
                CandidateCause.incident_id == incident.id,
                CandidateCause.event_id == evt.id
            )
        )
        candidate = cand_res.scalars().first()
        assert candidate is not None, "Candidate cause for repo not found"

        print(f"Computed candidate score: {candidate.score} (reasons: {candidate.reason})")
        assert candidate.score == 100.0, f"Expected capped score of 100.0, got {candidate.score}"
        assert "Test score boost applied." not in candidate.reason


@pytest.mark.asyncio
async def test_fix3_unique_constraint():
    """
    [Test Fix 3] Missing unique constraint on CandidateCause:
    Verifies that inserting two CandidateCause records with the same (incident_id, event_id)
    is rejected by the database unique constraint uq_candidate_cause_incident_event.
    """
    _verify_localhost_db()
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-uq-{uuid.uuid4().hex[:8]}"
        ws = Workspace(id=ws_id, name="UQ WS", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws)
        await session.flush()

        usr_id = f"usr-uq-{uuid.uuid4().hex[:8]}"
        usr = User(id=usr_id, email=f"{usr_id}@test.com", full_name="UQ User", role="admin", workspace_id=ws_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr)
        await session.flush()

        repo_id = f"repo-uq-{uuid.uuid4().hex[:8]}"
        repo = Repo(id=repo_id, name="repo-uq", platform="github", default_branch="main", workspace_id=ws_id, user_id=usr_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo)
        await session.flush()

        now = datetime.utcnow()
        mock_event = Event(
            id=f"evt-uq-{uuid.uuid4().hex[:8]}",
            repo_id=repo_id,
            workspace_id=ws_id,
            type="push",
            source="github",
            payload={},
            created_at=now
        )
        session.add(mock_event)

        inc = Incident(
            id=f"inc-uq-{uuid.uuid4().hex[:8]}",
            title="UQ Incident",
            workspace_id=ws_id,
            status="open",
            created_at=now,
            updated_at=now
        )
        session.add(inc)
        await session.flush()

        # Create first candidate cause
        cand1 = CandidateCause(
            id=f"cand-1-{uuid.uuid4().hex[:8]}",
            incident_id=inc.id,
            repo_id=repo_id,
            event_id=mock_event.id,
            workspace_id=ws_id,
            score=50.0,
            reason="Test reason 1",
            confirmed=None
        )
        session.add(cand1)
        await session.commit()

        # Attempt to create second candidate cause with identical (incident_id, event_id)
        cand2 = CandidateCause(
            id=f"cand-2-{uuid.uuid4().hex[:8]}",
            incident_id=inc.id,
            repo_id=repo_id,
            event_id=mock_event.id,
            workspace_id=ws_id,
            score=60.0,
            reason="Test reason 2",
            confirmed=None
        )
        session.add(cand2)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        print("IntegrityError successfully raised on duplicate (incident_id, event_id) insertion.")
