"""
Recalibration Test Suite
========================
Tests scoring weight recalibration behavior:
1. Below 20 samples: recalibration returns defaults (recalibrated=False) and does not persist new weights.
2. At 20 or more samples: recalibration computes updated weights, returns recalibrated=True, and persists
   the new weights to scoring_weight_recalibrations.
3. Subsequent get_current_scoring_weights() reflects the persisted weights.
4. Workspace scoping: recalibrations in Workspace A do not alter weights in Workspace B.
"""

import uuid
import json
import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from sqlmodel import select

from app.core.database import async_session, init_db
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.models.incident import Incident
from app.models.candidate_cause import CandidateCause
from app.models.candidate_cause_feedback_log import CandidateCauseFeedbackLog
from app.models.scoring_weight_recalibration import ScoringWeightRecalibration
from app.services.recalibration_service import (
    DEFAULT_WEIGHTS,
    MIN_SAMPLE_SIZE,
    get_current_scoring_weights,
    recalibrate_scoring_weights,
)


@pytest.mark.asyncio
async def test_recalibration_below_threshold_returns_defaults():
    """
    When a workspace has fewer than 20 feedback decisions (e.g. 5):
    - recalibrate_scoring_weights returns recalibrated=False
    - weights returned are DEFAULT_WEIGHTS
    - no new ScoringWeightRecalibration record is saved to the database
    - get_current_scoring_weights returns DEFAULT_WEIGHTS
    """
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-recal-below-{uuid.uuid4().hex[:8]}"
        ws = Workspace(
            id=ws_id,
            name="Recal Below Threshold WS",
            color="blue",
            provider="github",
            status="connected",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(ws)
        await session.flush()

        usr_id = f"usr-recal-{uuid.uuid4().hex[:8]}"
        usr = User(
            id=usr_id,
            email=f"{usr_id}@test.com",
            full_name="Recal User",
            role="admin",
            workspace_id=ws_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(usr)
        await session.flush()

        repo_id = f"repo-recal-{uuid.uuid4().hex[:8]}"
        repo = Repo(
            id=repo_id,
            name="order-service",
            platform="github",
            default_branch="main",
            workspace_id=ws_id,
            user_id=usr_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(repo)
        await session.flush()

        inc_id = f"inc-recal-{uuid.uuid4().hex[:8]}"
        inc = Incident(
            id=inc_id,
            workspace_id=ws_id,
            title="Order Outage",
            root_cause_repo_id=repo_id,
            status="resolved",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(inc)
        await session.flush()

        # Seed only 5 feedback log entries (< MIN_SAMPLE_SIZE = 20)
        for i in range(5):
            cand_id = f"cand-{uuid.uuid4().hex[:8]}"
            cand = CandidateCause(
                id=cand_id,
                workspace_id=ws_id,
                incident_id=inc_id,
                repo_id=repo_id,
                score=70.0,
                reason="Same repository. Deployed 5 minutes before the incident was triggered.",
                confirmed=(i % 2 == 0)
            )
            session.add(cand)
            await session.flush()

            fb = CandidateCauseFeedbackLog(
                id=f"fb-{uuid.uuid4().hex[:8]}" ,
                workspace_id=ws_id,
                candidate_cause_id=cand_id,
                incident_id=inc_id,
                repo_id=repo_id,
                confirmed=(i % 2 == 0),
                confirmed_by=usr_id,
                score_at_time=70.0,
                reasons_at_time="Same repository. within 15 min",
                created_at=datetime.now(timezone.utc)
            )
            session.add(fb)

        await session.commit()

        # Attempt recalibration with sample_size = 5
        result = await recalibrate_scoring_weights(session, ws_id, trigger_type="manual")

        assert result["recalibrated"] is False
        assert result["sample_size"] == 5
        assert result["weights"] == DEFAULT_WEIGHTS
        assert "below minimum threshold" in result["reason"]

        # Confirm no record was inserted into scoring_weight_recalibrations
        recal_records = (await session.execute(
            select(ScoringWeightRecalibration).where(ScoringWeightRecalibration.workspace_id == ws_id)
        )).scalars().all()
        assert len(recal_records) == 0

        # Confirm active weights remain default
        current_weights = await get_current_scoring_weights(session, ws_id)
        assert current_weights == DEFAULT_WEIGHTS


@pytest.mark.asyncio
async def test_recalibration_at_or_above_20_persists_new_weights():
    """
    When a workspace reaches 20 or more feedback decisions (>= MIN_SAMPLE_SIZE):
    - recalibrate_scoring_weights returns recalibrated=True
    - weights are adjusted based on confirmation rates and bounded to [0.5*default, 1.5*default]
    - a ScoringWeightRecalibration record is saved to the database
    - get_current_scoring_weights returns the newly written recalibrated weights
    """
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_id = f"ws-recal-above-{uuid.uuid4().hex[:8]}"
        ws = Workspace(
            id=ws_id,
            name="Recal Above Threshold WS",
            color="green",
            provider="github",
            status="connected",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(ws)
        await session.flush()

        usr_id = f"usr-recal-20-{uuid.uuid4().hex[:8]}"
        usr = User(
            id=usr_id,
            email=f"{usr_id}@test.com",
            full_name="Recal User 20",
            role="admin",
            workspace_id=ws_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(usr)
        await session.flush()

        repo_id = f"repo-recal-20-{uuid.uuid4().hex[:8]}"
        repo = Repo(
            id=repo_id,
            name="payment-service",
            platform="github",
            default_branch="main",
            workspace_id=ws_id,
            user_id=usr_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(repo)
        await session.flush()

        inc_id = f"inc-recal-20-{uuid.uuid4().hex[:8]}"
        inc = Incident(
            id=inc_id,
            workspace_id=ws_id,
            title="Payment Outage",
            root_cause_repo_id=repo_id,
            status="resolved",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(inc)
        await session.flush()

        # Seed exactly 20 feedback logs:
        # All 20 have "Same repository" and all 20 confirmed=True (100% win rate)
        # -> rate = 1.0, multiplier = 1.5, same_repo weight = 35.0 * 1.5 = 52.5
        for i in range(20):
            cand_id = f"cand-20-{uuid.uuid4().hex[:8]}"
            cand = CandidateCause(
                id=cand_id,
                workspace_id=ws_id,
                incident_id=inc_id,
                repo_id=repo_id,
                score=80.0,
                reason="Same repository. Deployed 5 minutes before the incident was triggered.",
                confirmed=True
            )
            session.add(cand)
            await session.flush()

            fb = CandidateCauseFeedbackLog(
                id=f"fb-20-{uuid.uuid4().hex[:8]}",
                workspace_id=ws_id,
                candidate_cause_id=cand_id,
                incident_id=inc_id,
                repo_id=repo_id,
                confirmed=True,
                confirmed_by=usr_id,
                score_at_time=80.0,
                reasons_at_time="Same repository. within 15 min",
                created_at=datetime.now(timezone.utc)
            )
            session.add(fb)

        await session.commit()

        # Execute recalibration with sample_size = 20
        result = await recalibrate_scoring_weights(session, ws_id, trigger_type="scheduled")

        assert result["recalibrated"] is True
        assert result["sample_size"] == 20
        assert "recalibration_id" in result
        new_weights = result["weights"]

        # same_repo had 100% confirmation (20/20) -> should be scaled up to 35.0 * 1.5 = 52.5
        assert new_weights["same_repo"] == 52.5
        # temp_15m also had 100% confirmation -> 25.0 * 1.5 = 37.5
        assert new_weights["temp_15m"] == 37.5
        # Factors with 0 occurrences in logs remain at default
        assert new_weights["transitive_2hop"] == DEFAULT_WEIGHTS["transitive_2hop"]

        # Verify record in scoring_weight_recalibrations
        recal_records = (await session.execute(
            select(ScoringWeightRecalibration).where(ScoringWeightRecalibration.workspace_id == ws_id)
        )).scalars().all()
        assert len(recal_records) == 1
        db_recal = recal_records[0]
        assert db_recal.sample_size == 20
        assert db_recal.trigger_type == "scheduled"
        stored_weights = json.loads(db_recal.weights)
        assert stored_weights["same_repo"] == 52.5

        # Verify get_current_scoring_weights now returns the new recalibrated weights
        active_weights = await get_current_scoring_weights(session, ws_id)
        assert active_weights["same_repo"] == 52.5
        assert active_weights["temp_15m"] == 37.5


@pytest.mark.asyncio
async def test_recalibration_workspace_isolation():
    """
    Assert that recalibration in Workspace A does not contaminate Workspace B.
    """
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        ws_a_id = f"ws-iso-recal-a-{uuid.uuid4().hex[:8]}"
        ws_b_id = f"ws-iso-recal-b-{uuid.uuid4().hex[:8]}"

        session.add(Workspace(id=ws_a_id, name="WS Recal A", provider="github", status="connected"))
        session.add(Workspace(id=ws_b_id, name="WS Recal B", provider="github", status="connected"))
        await session.flush()

        # Directly insert a recalibration record for WS A
        custom_weights = DEFAULT_WEIGHTS.copy()
        custom_weights["same_repo"] = 49.0
        recal_a = ScoringWeightRecalibration(
            workspace_id=ws_a_id,
            weights=json.dumps(custom_weights),
            sample_size=25,
            previous_weights=json.dumps(DEFAULT_WEIGHTS),
            trigger_type="manual",
            created_at=datetime.now(timezone.utc)
        )
        session.add(recal_a)
        await session.commit()

        # Workspace A gets custom weights; Workspace B gets DEFAULT_WEIGHTS
        weights_a = await get_current_scoring_weights(session, ws_a_id)
        weights_b = await get_current_scoring_weights(session, ws_b_id)

        assert weights_a["same_repo"] == 49.0
        assert weights_b["same_repo"] == DEFAULT_WEIGHTS["same_repo"]
