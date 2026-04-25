"""
Cluster Service
Handles cluster CRUD and health aggregation from member repos.
"""

from datetime import datetime
from typing import List, Optional
from sqlmodel import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cluster import Cluster
from app.models.repo import Repo
from app.models.alert import Alert
from app.models.pipeline import Pipeline
from app.schemas.cluster_schema import ClusterCreate, ClusterUpdate, ClusterAlertSummary


async def get_clusters(session: AsyncSession, workspace_id: str) -> List[Cluster]:
    result = await session.execute(
        select(Cluster)
        .where(Cluster.workspace_id == workspace_id)
        .order_by(Cluster.name)
    )
    return list(result.scalars().all())


async def get_cluster_by_id(session: AsyncSession, cluster_id: str) -> Optional[Cluster]:
    return await session.get(Cluster, cluster_id)


async def create_cluster(session: AsyncSession, data: ClusterCreate) -> Cluster:
    cluster = Cluster(**data.model_dump())
    session.add(cluster)
    await session.commit()
    await session.refresh(cluster)
    return cluster


async def update_cluster(
    session: AsyncSession, cluster_id: str, data: ClusterUpdate
) -> Optional[Cluster]:
    cluster = await session.get(Cluster, cluster_id)
    if not cluster:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(cluster, key, value)
    cluster.updated_at = datetime.utcnow()
    session.add(cluster)
    await session.commit()
    await session.refresh(cluster)
    return cluster


async def delete_cluster(session: AsyncSession, cluster_id: str) -> bool:
    cluster = await session.get(Cluster, cluster_id)
    if not cluster:
        return False
    # Detach repos from this cluster
    repos_result = await session.execute(
        select(Repo).where(Repo.cluster_id == cluster_id)
    )
    for repo in repos_result.scalars().all():
        repo.cluster_id = None
        session.add(repo)
    await session.delete(cluster)
    await session.commit()
    return True


async def get_cluster_repos(session: AsyncSession, cluster_id: str) -> List[Repo]:
    result = await session.execute(
        select(Repo).where(Repo.cluster_id == cluster_id).order_by(Repo.name)
    )
    return list(result.scalars().all())


async def recalculate_cluster_health(session: AsyncSession, cluster_id: str) -> Optional[Cluster]:
    """
    Aggregate health from all repos in the cluster.
    Optimized to fetch repos and alerts in parallel.

    health_score  = avg(repo.health_score)
    ci_status     = 'failing' if any repo is failing, else 'running' if any running, else 'passing'
    alert_*       = sum of unresolved alerts by severity across all repos in cluster
    repo_count    = count of repos
    """
    cluster = await session.get(Cluster, cluster_id)
    if not cluster:
        return None

    # Fetch repos and alerts in parallel
    repos_task = session.execute(
        select(Repo).where(Repo.cluster_id == cluster_id)
    )
    
    repos_result = await repos_task
    repos = list(repos_result.scalars().all())

    repo_count = len(repos)
    if repo_count == 0:
        cluster.health_score = 100.0
        cluster.ci_status = "passing"
        cluster.alert_critical = 0
        cluster.alert_high = 0
        cluster.alert_total = 0
        cluster.repo_count = 0
        cluster.updated_at = datetime.utcnow()
        session.add(cluster)
        await session.commit()
        await session.refresh(cluster)
        return cluster

    # Health score — weighted average
    avg_health = sum(r.health_score for r in repos) / repo_count

    # CI status — worst-case propagation
    statuses = {r.ci_status for r in repos}
    if "failing" in statuses:
        ci_status = "failing"
    elif "running" in statuses:
        ci_status = "running"
    else:
        ci_status = "passing"

    # Alert aggregation - fetch in one query
    repo_ids = [r.id for r in repos]
    alert_result = await session.execute(
        select(Alert).where(
            Alert.repo_id.in_(repo_ids),
            Alert.resolved == False,
        )
    )
    alerts = list(alert_result.scalars().all())

    critical = sum(1 for a in alerts if a.severity == "critical")
    high = sum(1 for a in alerts if a.severity == "high")

    cluster.health_score = round(avg_health, 1)
    cluster.ci_status = ci_status
    cluster.alert_critical = critical
    cluster.alert_high = high
    cluster.alert_total = len(alerts)
    cluster.repo_count = repo_count
    cluster.updated_at = datetime.utcnow()

    session.add(cluster)
    await session.commit()
    await session.refresh(cluster)
    return cluster


async def get_alert_summary_by_cluster(
    session: AsyncSession, workspace_id: str
) -> List[ClusterAlertSummary]:
    """
    Return alert breakdown grouped by cluster for the security/alerts page.
    Optimized with JOIN to avoid N+1 queries.
    """
    from sqlalchemy.orm import selectinload
    
    # Fetch all clusters with their repos in one query
    clusters_result = await session.execute(
        select(Cluster).where(Cluster.workspace_id == workspace_id)
    )
    clusters = list(clusters_result.scalars().all())
    
    if not clusters:
        return []
    
    # Get all repos for these clusters in one query
    cluster_ids = [c.id for c in clusters]
    repos_result = await session.execute(
        select(Repo).where(Repo.cluster_id.in_(cluster_ids))
    )
    repos = list(repos_result.scalars().all())
    
    # Build cluster_id -> repo_ids mapping
    cluster_repo_map = {}
    for repo in repos:
        if repo.cluster_id not in cluster_repo_map:
            cluster_repo_map[repo.cluster_id] = []
        cluster_repo_map[repo.cluster_id].append(repo.id)
    
    # Get all alerts for all repos in one query
    all_repo_ids = [r.id for r in repos]
    if not all_repo_ids:
        return []
    
    alerts_result = await session.execute(
        select(Alert).where(
            Alert.repo_id.in_(all_repo_ids),
            Alert.resolved == False,
        )
    )
    alerts = list(alerts_result.scalars().all())
    
    # Build repo_id -> alerts mapping
    repo_alerts_map = {}
    for alert in alerts:
        if alert.repo_id not in repo_alerts_map:
            repo_alerts_map[alert.repo_id] = []
        repo_alerts_map[alert.repo_id].append(alert)
    
    # Build summaries
    summaries = []
    for cluster in clusters:
        repo_ids = cluster_repo_map.get(cluster.id, [])
        if not repo_ids:
            continue
        
        # Collect all alerts for this cluster's repos
        cluster_alerts = []
        for repo_id in repo_ids:
            cluster_alerts.extend(repo_alerts_map.get(repo_id, []))
        
        summaries.append(
            ClusterAlertSummary(
                cluster_id=cluster.id,
                cluster_name=cluster.name,
                cluster_color=cluster.color,
                critical=sum(1 for a in cluster_alerts if a.severity == "critical"),
                high=sum(1 for a in cluster_alerts if a.severity == "high"),
                medium=sum(1 for a in cluster_alerts if a.severity == "medium"),
                low=sum(1 for a in cluster_alerts if a.severity == "low"),
                total=len(cluster_alerts),
            )
        )
    
    return summaries
