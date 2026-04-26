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
from app.services.repo_service import update_repo_state
from app.services.insight_service import calculate_health_score

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

    impacted_clusters = set()
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
                    
                    if repo.cluster_id:
                        impacted_clusters.add(repo.cluster_id)
                    
                    session.add(repo)
                    to_visit.append(downstream_repo_id)

    await session.commit()

    # RECALCULATE CLUSTER HEALTH FOR ALL IMPACTED CLUSTERS
    if impacted_clusters:
        from app.services.cluster_service import recalculate_cluster_health
        logger.info(f"Recalculating health for {len(impacted_clusters)} impacted clusters")
        for cluster_id in impacted_clusters:
            await recalculate_cluster_health(session, cluster_id)

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
