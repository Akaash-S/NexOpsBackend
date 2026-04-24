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
            sync_repos.append(repo)
            
        return sync_repos

vcs_service = VCService()
