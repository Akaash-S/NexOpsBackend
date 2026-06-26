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
