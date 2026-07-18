"""
Recalibration Service
Manages scoring weight recalibration from the append-only feedback ledger.
Implements safe fallbacks when feedback sample size is below threshold.
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_cause_feedback_log import CandidateCauseFeedbackLog
from app.models.scoring_weight_recalibration import ScoringWeightRecalibration

logger = logging.getLogger("nexops.recalibration")

DEFAULT_WEIGHTS = {
    "same_repo": 35.0,
    "dep_repo": 20.0,
    "transitive_2hop": 10.0,
    "transitive_3hop": 5.0,
    "temp_15m": 25.0,
    "temp_60m": 15.0,
    "temp_120m": 5.0,
    "past_precedent": 15.0,
    "deploy_risk": 15.0,
}

# Minimum real feedback decisions required before recalibrated weights take effect
MIN_SAMPLE_SIZE = 20


async def get_current_scoring_weights(session: AsyncSession, workspace_id: str) -> Dict[str, float]:
    """
    Get active scoring weights for a workspace.
    Returns latest recalibrated weights if sample size >= MIN_SAMPLE_SIZE, else returns DEFAULT_WEIGHTS.
    """
    if not workspace_id:
        return DEFAULT_WEIGHTS.copy()

    query = (
        select(ScoringWeightRecalibration)
        .where(ScoringWeightRecalibration.workspace_id == workspace_id)
        .order_by(ScoringWeightRecalibration.created_at.desc())
    )
    result = await session.execute(query)
    latest = result.scalars().first()

    if latest and latest.sample_size >= MIN_SAMPLE_SIZE:
        try:
            weights = json.loads(latest.weights)
            # Ensure all required factors exist
            final_weights = DEFAULT_WEIGHTS.copy()
            final_weights.update({k: float(v) for k, v in weights.items() if k in DEFAULT_WEIGHTS})
            return final_weights
        except Exception as e:
            logger.error(f"Failed to parse recalibrated weights for workspace {workspace_id}: {e}")

    return DEFAULT_WEIGHTS.copy()


async def recalibrate_scoring_weights(
    session: AsyncSession,
    workspace_id: str,
    trigger_type: str = "manual"
) -> Dict[str, Any]:
    """
    Recalibrate scoring weights based on candidate_cause_feedback_logs.
    Safety Condition: Requires at least MIN_SAMPLE_SIZE decisions in workspace.
    """
    if not workspace_id:
        return {
            "recalibrated": False,
            "reason": "Missing workspace_id",
            "weights": DEFAULT_WEIGHTS.copy(),
            "sample_size": 0
        }

    # Fetch all feedback logs for the workspace
    query = select(CandidateCauseFeedbackLog).where(CandidateCauseFeedbackLog.workspace_id == workspace_id)
    result = await session.execute(query)
    logs = list(result.scalars().all())

    sample_size = len(logs)
    prev_weights = await get_current_scoring_weights(session, workspace_id)

    # Safety Check: Fallback to default constants if sample size < MIN_SAMPLE_SIZE
    if sample_size < MIN_SAMPLE_SIZE:
        logger.info(f"Workspace {workspace_id} feedback sample size ({sample_size}) < threshold ({MIN_SAMPLE_SIZE}). Retaining default fixed weights.")
        return {
            "recalibrated": False,
            "reason": f"Sample size ({sample_size}) below minimum threshold ({MIN_SAMPLE_SIZE}). Retaining default fixed weights.",
            "weights": DEFAULT_WEIGHTS.copy(),
            "previous_weights": prev_weights,
            "sample_size": sample_size
        }

    # Factor statistics counters: {factor: {"total": int, "confirmed": int}}
    factors = {
        "same_repo": {"total": 0, "confirmed": 0},
        "dep_repo": {"total": 0, "confirmed": 0},
        "transitive_2hop": {"total": 0, "confirmed": 0},
        "transitive_3hop": {"total": 0, "confirmed": 0},
        "temp_15m": {"total": 0, "confirmed": 0},
        "temp_60m": {"total": 0, "confirmed": 0},
        "temp_120m": {"total": 0, "confirmed": 0},
        "past_precedent": {"total": 0, "confirmed": 0},
        "deploy_risk": {"total": 0, "confirmed": 0},
    }

    for log in logs:
        reasons = log.reasons_at_time or ""
        is_conf = log.confirmed

        if "Same repository" in reasons:
            factors["same_repo"]["total"] += 1
            if is_conf: factors["same_repo"]["confirmed"] += 1

        if "Direct dependency (1 hop" in reasons or "Dependency repository" in reasons:
            factors["dep_repo"]["total"] += 1
            if is_conf: factors["dep_repo"]["confirmed"] += 1

        if "Transitive dependency (2 hops" in reasons:
            factors["transitive_2hop"]["total"] += 1
            if is_conf: factors["transitive_2hop"]["confirmed"] += 1

        if "Transitive dependency (3 hops" in reasons:
            factors["transitive_3hop"]["total"] += 1
            if is_conf: factors["transitive_3hop"]["confirmed"] += 1

        if "within 15 min" in reasons:
            factors["temp_15m"]["total"] += 1
            if is_conf: factors["temp_15m"]["confirmed"] += 1

        if "within 15-60 min" in reasons:
            factors["temp_60m"]["total"] += 1
            if is_conf: factors["temp_60m"]["confirmed"] += 1

        if "within 60-120 min" in reasons:
            factors["temp_120m"]["total"] += 1
            if is_conf: factors["temp_120m"]["confirmed"] += 1

        if "Past confirmed cause" in reasons:
            factors["past_precedent"]["total"] += 1
            if is_conf: factors["past_precedent"]["confirmed"] += 1

        if "Deployment risk" in reasons:
            factors["deploy_risk"]["total"] += 1
            if is_conf: factors["deploy_risk"]["confirmed"] += 1

    # Compute new bounded weights
    new_weights = {}
    for factor_name, default_w in DEFAULT_WEIGHTS.items():
        stats = factors[factor_name]
        tot = stats["total"]
        conf = stats["confirmed"]

        if tot > 0:
            rate = conf / tot
            # Scale multiplier between 0.5 (low confirmation) and 1.5 (high confirmation)
            # multiplier = 0.5 + rate
            raw_new = default_w * (0.5 + rate)
        else:
            raw_new = default_w

        # Enforce sane bounded limits [0.5 * default, 1.5 * default]
        min_bound = default_w * 0.5
        max_bound = default_w * 1.5
        bounded_w = max(min_bound, min(max_bound, raw_new))
        new_weights[factor_name] = round(bounded_w, 2)

    # Save recalibration event
    recal_record = ScoringWeightRecalibration(
        workspace_id=workspace_id,
        weights=json.dumps(new_weights),
        sample_size=sample_size,
        previous_weights=json.dumps(prev_weights),
        trigger_type=trigger_type,
        created_at=datetime.utcnow()
    )
    session.add(recal_record)
    await session.commit()
    await session.refresh(recal_record)

    logger.info(f"Successfully recalibrated scoring weights for workspace {workspace_id} (Sample size: {sample_size}): {new_weights}")

    return {
        "recalibrated": True,
        "weights": new_weights,
        "previous_weights": prev_weights,
        "sample_size": sample_size,
        "recalibration_id": recal_record.id
    }
