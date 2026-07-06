"""
Impact Propagation Service
Responsible for traversing the dependency graph and calculating systemic impact.
"""

import logging
from typing import List, Set
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repo import Repo
from app.models.dependency import Dependency

logger = logging.getLogger("nexops.impact")

async def propagate_impact(session: AsyncSession, root_repo_id: str, severity: str):
    """
    Traverse the dependency tree starting from root_repo_id.
    Mark all downstream repositories as impacted.
    """
    visited = set()
    to_visit = [root_repo_id]
    
    impact_level = 0
    if severity == "critical": impact_level = 30
    elif severity == "high": impact_level = 15
    elif severity == "medium": impact_level = 5
    
    if impact_level == 0:
        return

    logger.info(f"Starting impact propagation from {root_repo_id} (Level: {impact_level})")

    while to_visit:
        current_repo_id = to_visit.pop(0)
        if current_repo_id in visited:
            continue
        
        visited.add(current_repo_id)
        
        # Find all repos that depend on this repo
        query = select(Dependency).where(Dependency.target_repo_id == current_repo_id)
        result = await session.execute(query)
        dependencies = result.scalars().all()
        
        for dep in dependencies:
            downstream_repo_id = dep.source_repo_id
            if downstream_repo_id not in visited:
                logger.info(f"Propagating impact to downstream repo: {downstream_repo_id}")
                
                # Apply health penalty to downstream repo
                repo = await session.get(Repo, downstream_repo_id)
                if repo:
                    # Decrease health score slightly for downstream impact
                    new_health = max(0, repo.health_score - (impact_level / 2)) # Impact halves as it goes deeper
                    repo.health_score = new_health
                    
                    # If health is very low, mark as failing
                    if new_health < 50:
                        repo.ci_status = "failing"
                    
                    session.add(repo)
                    to_visit.append(downstream_repo_id)

    await session.commit()
    logger.info(f"Impact propagation complete. Affected {len(visited) - 1} downstream repos.")

async def get_downstream_repos(session: AsyncSession, repo_id: str) -> List[str]:
    """Helper to find all downstream repos for insight generation."""
    visited = set()
    to_visit = [repo_id]
    
    while to_visit:
        current_repo_id = to_visit.pop(0)
        if current_repo_id in visited:
            continue
        visited.add(current_repo_id)
        
        query = select(Dependency).where(Dependency.target_repo_id == current_repo_id)
        result = await session.execute(query)
        for dep in result.scalars().all():
            if dep.source_repo_id not in visited:
                to_visit.append(dep.source_repo_id)
    
    visited.remove(repo_id)
    return list(visited)

async def calculate_blast_radius(session: AsyncSession, repo_id: str) -> dict:
    """
    Calculate the blast radius risk score and risk basis for a repository.
    """
    # Walk direct and indirect downstream
    direct_query = select(Dependency).where(Dependency.target_repo_id == repo_id)
    direct_result = await session.execute(direct_query)
    direct_repos = [dep.source_repo_id for dep in direct_result.scalars().all()]
    
    # All downstream (direct + indirect)
    all_downstream = await get_downstream_repos(session, repo_id)
    indirect_repos = [r for r in all_downstream if r not in direct_repos]
    
    # Risk score calculation (max 100)
    score = min(100.0, len(direct_repos) * 25.0 + len(indirect_repos) * 10.0)
    
    # Formulate basis explanation
    if not all_downstream:
        basis = "Low risk. No downstream services depend on this repository."
        score = 0.0
    else:
        basis = (
            f"Risk score of {score:.1f} based on {len(all_downstream)} downstream services: "
            f"{len(direct_repos)} direct dependencies ({', '.join(direct_repos[:3])}{'...' if len(direct_repos) > 3 else ''}) and "
            f"{len(indirect_repos)} indirect dependencies."
        )
        
    return {
        "risk_score": score,
        "risk_basis": basis,
        "downstream_count": len(all_downstream),
        "downstream_repos": all_downstream
    }


async def calculate_deployment_risk(session: AsyncSession, repo_id: str) -> dict:
    """
    Calculate the deployment risk score and risk basis for a repository.
    Reuses the exact weights from correlate_incident_causes() based on active/recent incident history.
    """
    from datetime import datetime, timedelta
    from app.models.incident import Incident
    from app.models.candidate_cause import CandidateCause
    
    # 1. Get downstream dependencies
    downstream_repos = await get_downstream_repos(session, repo_id)
    
    # 2. Check conditions
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    ninety_days_ago = now - timedelta(days=90)
    
    # Same repo incidents in last 7 days
    same_repo_query = select(Incident).where(
        Incident.root_cause_repo_id == repo_id,
        Incident.created_at >= seven_days_ago
    )
    same_repo_res = await session.execute(same_repo_query)
    same_repo_incidents = same_repo_res.scalars().all()
    
    # Downstream incidents in last 7 days
    downstream_incidents = []
    if downstream_repos:
        downstream_query = select(Incident).where(
            Incident.root_cause_repo_id.in_(downstream_repos),
            Incident.created_at >= seven_days_ago
        )
        downstream_res = await session.execute(downstream_query)
        downstream_incidents = downstream_res.scalars().all()
        
    # Past confirmed root causes in last 90 days
    confirmed_query = select(CandidateCause).where(
        CandidateCause.repo_id == repo_id,
        CandidateCause.confirmed == True,
        CandidateCause.created_at >= ninety_days_ago
    )
    confirmed_res = await session.execute(confirmed_query)
    confirmed_causes = confirmed_res.scalars().all()
    
    # If isolated (no downstream dependents) and no recent incidents/confirmed causes
    if not downstream_repos and not same_repo_incidents and not confirmed_causes:
        return {
            "risk_score": 0.0,
            "risk_basis": "Low risk. No downstream services depend on this repository and no recent incidents."
        }
        
    score = 15.0
    reasons = ["Base score (+15.0)"]
    
    # Same-Repo Incidents (Last 7 Days)
    has_active_same = any(inc.status == "open" for inc in same_repo_incidents)
    has_resolved_same = any(inc.status == "resolved" for inc in same_repo_incidents)
    
    if has_active_same:
        score += 35.0
        reasons.append("Active open incident on same repository (+35.0)")
    if has_resolved_same:
        score += 15.0
        reasons.append("Resolved incident on same repository in last 7 days (+15.0)")
        
    # Temporal proximity to most recent incident on the repo
    if same_repo_incidents:
        most_recent_inc = max(same_repo_incidents, key=lambda inc: inc.created_at)
        time_diff = (now - most_recent_inc.created_at).total_seconds()
        time_diff = max(0.0, time_diff)
        if time_diff <= 900:  # 15 minutes
            score += 25.0
            reasons.append("Temporal proximity to same-repo incident within 15 min (+25.0)")
        elif time_diff <= 3600:  # 60 minutes
            score += 15.0
            reasons.append("Temporal proximity to same-repo incident within 60 min (+15.0)")
        elif time_diff <= 7200:  # 120 minutes
            score += 5.0
            reasons.append("Temporal proximity to same-repo incident within 120 min (+5.0)")
            
    # Downstream Dependent Incidents (Last 7 Days)
    has_active_downstream = any(inc.status == "open" for inc in downstream_incidents)
    has_resolved_downstream = any(inc.status == "resolved" for inc in downstream_incidents)
    
    if has_active_downstream:
        score += 20.0
        reasons.append("Active open incident on downstream dependent repository (+20.0)")
    if has_resolved_downstream:
        score += 10.0
        reasons.append("Resolved incident on downstream dependent repository in last 7 days (+10.0)")
        
    # Past Confirmed Root Causes (Last 90 Days)
    if confirmed_causes:
        score += 15.0
        reasons.append("Repository was confirmed root cause of an incident within 90 days (+15.0)")
        
    # Cap score
    score = min(100.0, max(15.0, score))
    basis_str = ", ".join(reasons) + f". Final Risk Score: {score:.1f}"
    
    return {
        "risk_score": score,
        "risk_basis": basis_str
    }
