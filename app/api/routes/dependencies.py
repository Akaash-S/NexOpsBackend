"""
Dependencies Routes
Manages repo-to-repo dependency edges and serves the full topology graph.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import List

from app.core.database import get_session
from app.core.security import get_current_user
from app.models.user import User
from app.models.dependency import Dependency
from app.models.repo import Repo
from app.schemas.dependency_schema import (
    DependencyCreate,
    DependencyResponse,
    TopologyResponse,
    TopologyNode,
    TopologyEdge,
)

router = APIRouter(prefix="/dependencies", tags=["Dependencies"])


@router.get("/topology", response_model=TopologyResponse)
async def get_topology(
    workspace_id: str | None = None,
    cluster_id: str | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return the topology graph for the authenticated user's repos.
    Only repos belonging to the current user are included.
    """
    repo_query = select(Repo).where(Repo.workspace_id == current_user.workspace_id)
    if cluster_id:
        repo_query = repo_query.where(Repo.cluster_id == cluster_id)
    repo_result = await session.execute(repo_query)
    repos = list(repo_result.scalars().all())

    repo_ids = {r.id for r in repos}

    # Fetch dependencies between repos in this scope
    dep_result = await session.execute(
        select(Dependency).where(Dependency.workspace_id == current_user.workspace_id)
    )
    all_deps = list(dep_result.scalars().all())

    # Only include edges where both endpoints are in scope
    scoped_deps = [
        d for d in all_deps
        if d.source_repo_id in repo_ids and d.target_repo_id in repo_ids
    ]

    # Fetch active incidents in workspace (or default-workspace)
    from app.models.incident import Incident
    from app.models.candidate_cause import CandidateCause

    inc_query = select(Incident).where(
        Incident.status.in_(["open", "investigating"]),
        (Incident.workspace_id == current_user.workspace_id) |
        (Incident.workspace_id == None) |
        (Incident.workspace_id == "") |
        (Incident.workspace_id == "default-workspace")
    )
    inc_result = await session.execute(inc_query)
    active_incidents = list(inc_result.scalars().all())

    # Map active incidents to affected repos & map incident titles
    incident_repo_map: dict[str, str] = {}
    active_inc_ids = [inc.id for inc in active_incidents]

    for inc in active_incidents:
        if inc.root_cause_repo_id:
            incident_repo_map[inc.root_cause_repo_id] = inc.title
        for imp_id in (inc.impacted_repos or []):
            if imp_id not in incident_repo_map:
                incident_repo_map[imp_id] = inc.title

    if active_inc_ids:
        cc_res = await session.execute(
            select(CandidateCause).where(CandidateCause.incident_id.in_(active_inc_ids))
        )
        for cc in cc_res.scalars().all():
            if cc.repo_id and cc.repo_id not in incident_repo_map:
                # Find matching incident title
                matching_inc = next((i for i in active_incidents if i.id == cc.incident_id), None)
                if matching_inc:
                    incident_repo_map[cc.repo_id] = matching_inc.title

    active_incident_repo_ids = set(incident_repo_map.keys())

    # Build a set of failing/incident repo IDs for cascade highlighting
    failing_ids = {r.id for r in repos if r.ci_status == "failing" or r.id in active_incident_repo_ids}

    from app.services.alert_service import get_noisy_rules

    nodes = []
    for r in repos:
        noisy_rules = await get_noisy_rules(session, r.id)
        has_inc = r.id in active_incident_repo_ids
        inc_title = incident_repo_map.get(r.id)

        # Drop effective health score if there's an active incident
        effective_health = min(r.health_score, 45.0) if has_inc else r.health_score
        effective_ci = "failing" if has_inc else r.ci_status

        nodes.append(
            TopologyNode(
                id=r.id,
                name=r.name,
                platform=r.platform,
                status="critical" if has_inc else getattr(r, "status", "active"),
                language=r.language,
                health_score=effective_health,
                ci_status=effective_ci,
                open_issues=r.open_issues,
                vulnerabilities=r.vulnerabilities,
                activity=r.activity,
                owner=r.owner,
                noisy_rule_ids=noisy_rules,
                has_active_incident=has_inc,
                active_incident_title=inc_title,
            )
        )

    edges = [
        TopologyEdge(
            id=d.id,
            source=d.source_repo_id,
            target=d.target_repo_id,
            label=d.label,
            # Edge is broken if target repo (upstream) OR source repo is failing/has incident
            is_broken=(d.target_repo_id in failing_ids or d.source_repo_id in failing_ids),
        )
        for d in scoped_deps
    ]

    return TopologyResponse(nodes=nodes, edges=edges)


@router.get("", response_model=List[DependencyResponse])
async def list_dependencies(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(Dependency).where(Dependency.workspace_id == current_user.workspace_id)
    )
    return list(result.scalars().all())


@router.post("", response_model=DependencyResponse, status_code=201)
async def create_dependency(
    data: DependencyCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Persist a new dependency edge (called when user draws a connection)."""
    # Verify repository ownership first
    source_repo = await session.get(Repo, data.source_repo_id)
    if not source_repo or source_repo.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=403, detail="Source repository access denied")

    target_repo = await session.get(Repo, data.target_repo_id)
    if not target_repo or target_repo.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=403, detail="Target repository access denied")

    # Prevent self-loops
    if data.source_repo_id == data.target_repo_id:
        raise HTTPException(status_code=400, detail="A repo cannot depend on itself")

    # Prevent duplicates
    existing = await session.execute(
        select(Dependency).where(
            Dependency.source_repo_id == data.source_repo_id,
            Dependency.target_repo_id == data.target_repo_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Dependency already exists")

    if not current_user.workspace_id:
        raise HTTPException(status_code=400, detail="User lacks a valid workspace context")

    dep = Dependency(
        source_repo_id=data.source_repo_id,
        target_repo_id=data.target_repo_id,
        label=data.label,
        type=data.type or "api",
        workspace_id=current_user.workspace_id,
    )
    session.add(dep)
    await session.commit()
    await session.refresh(dep)
    return dep


@router.delete("/{dependency_id}", status_code=204)
async def delete_dependency(
    dependency_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    dep = await session.get(Dependency, dependency_id)
    if not dep or dep.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=404, detail="Dependency not found")
    await session.delete(dep)
    await session.commit()
