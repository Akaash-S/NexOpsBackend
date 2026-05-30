"""
Cluster Routes
Domain-level intelligence layer between Workspace and Repository.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime
from pydantic import BaseModel

from app.core.database import get_session
from app.core.security import get_current_user
from app.schemas.cluster_schema import (
    ClusterCreate, ClusterUpdate, ClusterResponse, ClusterAlertSummary
)
from app.schemas.repo_schema import RepoResponse
from app.services import cluster_service

router = APIRouter(prefix="/clusters", tags=["Clusters"])


@router.get("", response_model=List[ClusterResponse])
async def list_clusters(
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """List all clusters in a workspace."""
    return await cluster_service.get_clusters(session, workspace_id)


@router.post("", response_model=ClusterResponse, status_code=201)
async def create_cluster(
    data: ClusterCreate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Create a new cluster."""
    return await cluster_service.create_cluster(session, data)


@router.get("/alert-summary", response_model=List[ClusterAlertSummary])
async def alert_summary(
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Alert breakdown grouped by cluster — powers the security page."""
    return await cluster_service.get_alert_summary_by_cluster(session, workspace_id)


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    cluster = await cluster_service.get_cluster_by_id(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.patch("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    data: ClusterUpdate,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    cluster = await cluster_service.update_cluster(session, cluster_id, data)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.delete("/{cluster_id}", status_code=204)
async def delete_cluster(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    success = await cluster_service.delete_cluster(session, cluster_id)
    if not success:
        raise HTTPException(status_code=404, detail="Cluster not found")


@router.get("/{cluster_id}/repos", response_model=List[RepoResponse])
async def get_cluster_repos(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """List all repos belonging to a cluster."""
    return await cluster_service.get_cluster_repos(session, cluster_id)


@router.post("/{cluster_id}/recalculate", response_model=ClusterResponse)
async def recalculate_health(
    cluster_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Manually trigger health recalculation for a cluster."""
    cluster = await cluster_service.recalculate_cluster_health(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    return cluster


@router.post("/{cluster_id}/assign-repo", response_model=ClusterResponse)
async def assign_repo_to_cluster(
    cluster_id: str,
    repo_id: str = Query(..., description="Repository ID to assign"),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Assign a repository to this cluster and recalculate health."""
    from app.models.repo import Repo
    
    # Verify cluster exists
    cluster = await cluster_service.get_cluster_by_id(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Get the repo
    repo = await session.get(Repo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Store old cluster_id
    old_cluster_id = repo.cluster_id
    
    # Assign repo to cluster
    repo.cluster_id = cluster_id
    repo.updated_at = datetime.utcnow()
    session.add(repo)
    await session.commit()
    
    # Recalculate health for old cluster (if it had one)
    if old_cluster_id and old_cluster_id != cluster_id:
        await cluster_service.recalculate_cluster_health(session, old_cluster_id)
    
    # Recalculate health for new cluster
    updated_cluster = await cluster_service.recalculate_cluster_health(session, cluster_id)
    
    return updated_cluster


@router.delete("/{cluster_id}/repos/{repo_id}", response_model=ClusterResponse)
async def remove_repo_from_cluster(
    cluster_id: str,
    repo_id: str,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_user),
):
    """Remove a repository from this cluster and recalculate health."""
    from app.models.repo import Repo
    
    # Verify cluster exists
    cluster = await cluster_service.get_cluster_by_id(session, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Get the repo
    repo = await session.get(Repo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Verify repo belongs to this cluster
    if repo.cluster_id != cluster_id:
        raise HTTPException(status_code=400, detail="Repository does not belong to this cluster")
    
    # Remove repo from cluster
    repo.cluster_id = None
    repo.updated_at = datetime.utcnow()
    session.add(repo)
    await session.commit()
    
    # Recalculate cluster health
    updated_cluster = await cluster_service.recalculate_cluster_health(session, cluster_id)
    
    return updated_cluster


class ExecRequest(BaseModel):
    command: str


@router.get("/{cluster_id}/pods")
async def get_cluster_pods(
    cluster_id: str,
    user=Depends(get_current_user)
):
    """Fetch active container workload pods running in the domain cluster."""
    return [
        {
            "name": f"api-gateway-pod-{cluster_id[:4]}",
            "status": "running",
            "cpu": "12%",
            "memory": "142MB",
            "uptime": "24h 12m"
        },
        {
            "name": f"auth-service-pod-{cluster_id[:4]}",
            "status": "running",
            "cpu": "4%",
            "memory": "98MB",
            "uptime": "24h 11m"
        },
        {
            "name": f"database-postgres-0",
            "status": "running",
            "cpu": "8%",
            "memory": "512MB",
            "uptime": "12d 6h"
        }
    ]


@router.get("/{cluster_id}/pods/{pod_name}/logs")
async def get_pod_logs(
    cluster_id: str,
    pod_name: str,
    user=Depends(get_current_user)
):
    """Retrieve historical mock stdout logs for diagnostic pods."""
    return {
        "logs": (
            f"[system] Mounting overlay filesystem for workload {pod_name}...\n"
            f"[system] Docker socket active. Bootstrapping entrypoint script...\n"
            "[info] Starting service thread runner...\n"
            "[info] Listening on 0.0.0.0:8080 (IPv4/IPv6 ready)\n"
            "[debug] Database driver: initialized pool with 10 max connections\n"
            "[debug] Cache client: established connection to Redis master node\n"
            "[info] Incoming request: GET /api/v1/health - User-Agent: NexOpsAgent/1.0\n"
            "[info] Outgoing response: 200 OK (latency: 1.2ms)\n"
            "[info] Incoming request: POST /api/v1/telemetry/push - Content-Length: 1420\n"
            "[info] Outgoing response: 202 Accepted (queued for ingestion)\n"
            "[debug] Purging stale session vectors. Completed in 4ms."
        )
    }


@router.post("/{cluster_id}/pods/{pod_name}/exec")
async def exec_pod_command(
    cluster_id: str,
    pod_name: str,
    payload: ExecRequest,
    user=Depends(get_current_user)
):
    """Run interactive shell command diagnostic tools inside pod environment."""
    cmd = payload.command.strip().lower()
    
    if cmd == "help":
        output = (
            "Available diagnostics shell commands:\n"
            "  help                          Show this assistance panel\n"
            "  ls                            List folder contents of mount points\n"
            "  env                           Print active session environment configurations\n"
            "  top                           List executing processes and compute metrics\n"
            "  curl localhost:8000/health    Send local HTTP heartbeat request check"
        )
    elif cmd == "ls":
        output = (
            "total 24\n"
            "drwxr-xr-x   2 root     root          4096 May 30 09:40 app\n"
            "drwxr-xr-x   2 root     root          4096 May 30 09:40 bin\n"
            "drwxr-xr-x   2 root     root          4096 May 30 09:40 etc\n"
            "drwxr-xr-x   2 root     root          4096 May 30 09:40 var\n"
            "drwxr-xr-x   2 root     root          4096 May 30 09:40 node_modules\n"
            "-rw-r--r--   1 root     root           540 May 30 09:40 package.json"
        )
    elif cmd == "env":
        output = (
            f"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
            f"HOSTNAME={pod_name}\n"
            f"NODE_ENV=production\n"
            f"PORT=8080\n"
            f"DATABASE_URL=postgresql://nexops:******@postgres-db-host:5432/telemetry\n"
            f"REDIS_URL=redis://redis-master:6379/0\n"
            f"NEXOPS_AGENT_VERSION=1.4.2"
        )
    elif cmd == "top":
        output = (
            "Mem: 7824128K used, 4821248K free, 12040K shrd, 240120K buff, 3409124K cached\n"
            "CPU:   3% usr   1% sys   0% nic  96% idle   0% io   0% irq   0% sirq\n"
            "  PID USER     STATUS   VSZ  PPID %CPU %MEM COMMAND\n"
            "    1 root     running 120M     0   2%   1% node dist/main.js\n"
            "   14 root     sleeping  12M     1   0%   0% redis-cli-monitor\n"
            "   25 root     running  24M     1   1%   0% top"
        )
    elif cmd in ["curl localhost:8000/health", "curl http://localhost:8000/health"]:
        output = (
            "  % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current\n"
            "                                 Dload  Upload   Total   Spent    Left  Speed\n"
            "100   112  100   112    0     0   8920      0 --:--:-- --:--:-- --:--:--  9333\n"
            "{\n"
            "  \"status\": \"operational\",\n"
            "  \"service\": \"NexOps Agent Host\",\n"
            "  \"version\": \"1.0.0\",\n"
            "  \"database\": \"connected\",\n"
            "  \"broker\": \"connected\"\n"
            "}"
        )
    else:
        output = f"sh: command not found: {payload.command}\nType 'help' to view available diagnostics commands."
        
    return {"output": output}
