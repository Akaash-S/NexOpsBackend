import httpx
from typing import List, Dict, Any
from app.models.repo import Repo
import uuid
import logging
from datetime import datetime

logger = logging.getLogger("nexops.vcs")

class VCService:
    @staticmethod
    async def fetch_github_repos(token: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.github.com/user/repos",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "NexOps-Intelligence-Engine"
                },
                params={"per_page": 100, "sort": "updated"}
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    async def fetch_gitlab_repos(token: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://gitlab.com/api/v4/projects",
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "NexOps-Intelligence-Engine"
                },
                params={"membership": True, "simple": True, "per_page": 100}
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    async def fetch_bitbucket_repos(token: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.bitbucket.org/2.0/repositories?role=member",
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "NexOps-Intelligence-Engine"
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("values", [])

    @staticmethod
    async def fetch_github_tree(token: str, owner: str, repo: str, path: str = "") -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            # GitHub 'contents' API returns a list of items for a directory
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path.lstrip('/')}"
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "NexOps-Intelligence-Engine"
                }
            )
            # Handle empty repositories (GitHub returns 404 for /contents/ if no commits)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            return response.json()

    @staticmethod
    async def fetch_github_file_content(token: str, owner: str, repo: str, path: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path.lstrip('/')}"
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "NexOps-Intelligence-Engine"
                }
            )
            
            if response.status_code == 404:
                return {
                    "path": path,
                    "content": "// No codes are there in this repository or file not found.",
                    "encoding": "none",
                    "size": 0
                }

            response.raise_for_status()
            data = response.json()
            
            import base64
            # Content is base64 encoded by GitHub
            encoded_content = data.get("content", "")
            # Remove newlines from base64 string
            decoded_content = base64.b64decode(encoded_content.replace("\n", "")).decode("utf-8")
            
            return {
                "path": path,
                "content": decoded_content,
                "encoding": data.get("encoding"),
                "size": data.get("size")
            }

    @staticmethod
    async def fetch_github_ci_status(token: str, owner: str, repo: str) -> str:
        """
        Fetch the most recent workflow run status from GitHub Actions.
        Returns one of: "passing", "failing", "running", "unconfigured", "no_runs", "unknown".
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NexOps-Intelligence-Engine"
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers=headers,
                    params={"per_page": 1, "page": 1}
                )
                if response.status_code in (404, 409):
                    return "unconfigured"
                response.raise_for_status()
                data = response.json()
                runs = data.get("workflow_runs", [])
                if not runs:
                    return "no_runs"

                run = runs[0]
                status = run.get("status")
                conclusion = run.get("conclusion")

                if status is None:
                    return "unknown"
                if status != "completed":
                    return "running"
                if conclusion == "success":
                    return "passing"
                if conclusion in ("failure", "timed_out", "action_required"):
                    return "failing"
                return "unknown"

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 409):
                return "unconfigured"
            logger.warning(f"CI status check failed for {owner}/{repo}: HTTP {e.response.status_code}")
            return "unknown"
        except Exception as e:
            logger.warning(f"CI status check failed for {owner}/{repo}: {e}")
            return "unknown"

    @staticmethod
    async def fetch_github_deployments(token: str, owner: str, repo: str) -> List[Dict[str, Any]]:
        """
        Fetch recent deployments for a repository via GitHub Deployments API.
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/deployments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NexOps-Intelligence-Engine"
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, params={"per_page": 10})
                if response.status_code == 404:
                    return []
                response.raise_for_status()
                deployments = response.json()
                
                results = []
                for dep in deployments:
                    dep_id = dep.get("id")
                    statuses_url = f"https://api.github.com/repos/{owner}/{repo}/deployments/{dep_id}/statuses"
                    st_resp = await client.get(statuses_url, headers=headers, params={"per_page": 1})
                    status_data = st_resp.json()[0] if st_resp.status_code == 200 and st_resp.json() else {}
                    results.append({
                        "id": str(dep_id),
                        "sha": dep.get("sha", ""),
                        "environment": dep.get("environment", "production"),
                        "creator": dep.get("creator", {}).get("login", "unknown"),
                        "description": dep.get("description") or status_data.get("description") or f"Deployment of {dep.get('sha', '')[:7] if dep.get('sha') else ''}",
                        "state": status_data.get("state", "success"),
                        "created_at": dep.get("created_at")
                    })
                return results
        except Exception as e:
            logger.warning(f"Failed to fetch GitHub deployments for {owner}/{repo}: {e}")
            return []

    @staticmethod
    async def register_github_webhook(token: str, owner: str, repo: str, webhook_url: str, secret: str = "") -> bool:
        """
        Automatically register a repository webhook on GitHub for deployment_status, push, pull_request events.
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/hooks"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NexOps-Intelligence-Engine"
        }
        payload = {
            "name": "web",
            "active": True,
            "events": ["deployment_status", "push", "pull_request", "issues"],
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0"
            }
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code in (200, 201, 422):
                    logger.info(f"GitHub webhook registered/verified for {owner}/{repo}")
                    return True
                else:
                    logger.warning(f"Failed to register GitHub webhook for {owner}/{repo}: HTTP {response.status_code}")
                    return False
        except Exception as e:
            logger.warning(f"Error registering GitHub webhook for {owner}/{repo}: {e}")
            return False

    @classmethod
    async def sync_repositories(cls, provider: str, token: str, workspace_id: str) -> List[Repo]:
        raw_repos = []
        if provider == "github":
            raw_repos = await cls.fetch_github_repos(token)
        elif provider == "gitlab":
            raw_repos = await cls.fetch_gitlab_repos(token)
        elif provider == "bitbucket":
            raw_repos = await cls.fetch_bitbucket_repos(token)
        
        logger.info(f"Fetched {len(raw_repos)} raw repositories from {provider}")
        sync_repos = []
        for raw in raw_repos:
            repo = Repo(
                id=str(uuid.uuid4()),
                workspace_id=workspace_id,
                name=raw.get("name") or raw.get("full_name"),
                platform=provider,
                description=raw.get("description"),
                language=raw.get("language") or raw.get("programming_language"),
                default_branch=raw.get("default_branch") or "main",
                owner=raw.get("owner", {}).get("login") if provider == "github" else None,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )

            if provider == "github":
                repo.open_issues = raw.get("open_issues_count", 0)
                repo.stars = raw.get("stargazers_count", 0)
                repo.forks = raw.get("forks_count", 0)
                pushed = raw.get("pushed_at")
                if pushed:
                    try:
                        repo.last_commit_at = datetime.fromisoformat(pushed.replace("Z", "+00:00")).replace(tzinfo=None)
                    except (ValueError, AttributeError):
                        pass
                gh_updated = raw.get("updated_at")
                if gh_updated:
                    try:
                        repo.github_updated_at = datetime.fromisoformat(gh_updated.replace("Z", "+00:00")).replace(tzinfo=None)
                    except (ValueError, AttributeError):
                        pass

            sync_repos.append(repo)
            
        return sync_repos

vcs_service = VCService()
