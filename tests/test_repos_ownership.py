"""
Automated Repository Ownership & Tenant Isolation Regression Test
==================================================================
Verifies that GET /repos, GET /repos/search, GET /repos/{repo_id}, and related
repository endpoints strictly scope results to the authenticated user's workspace_id.

Tests:
1. User B (Workspace B) receives ONLY Workspace B repositories from GET /repos.
2. User C (workspace_id = None) receives 0 repositories from GET /repos.
3. User B receives 0 results when searching for Workspace A repositories via GET /repos/search.
4. User B receives HTTP 404 when querying Workspace A repository details via GET /repos/{repo_id}.
5. User B receives HTTP 404 when querying Workspace A blast radius via GET /repos/{repo_id}/blast-radius.
"""

import uuid
import pytest
from datetime import datetime
from sqlalchemy import text
from sqlmodel import select
from fastapi import HTTPException

from app.core.database import async_session, init_db
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.api.routes.repos import (
    list_repos,
    search_repos,
    get_repo,
    get_repo_blast_radius,
)


@pytest.mark.asyncio
async def test_repo_list_and_detail_tenant_isolation():
    """
    Regression Test: Ensures GET /repos and GET /repos/{repo_id} do NOT leak
    cross-tenant repositories or unassigned repositories to other users.
    """
    await init_db()

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        # Setup Workspace A + User A + Repos A1, A2
        ws_a_id = f"ws-repo-a-{uuid.uuid4().hex[:8]}"
        ws_a = Workspace(id=ws_a_id, name="Repo Isolation WS A", color="blue", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws_a)
        await session.flush()

        usr_a_id = f"usr-repo-a-{uuid.uuid4().hex[:8]}"
        usr_a = User(id=usr_a_id, email=f"{usr_a_id}@test-a.com", full_name="User Repo A", role="admin", workspace_id=ws_a_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr_a)
        await session.flush()

        repo_a1_id = f"repo-a1-{uuid.uuid4().hex[:8]}"
        repo_a1 = Repo(id=repo_a1_id, name="secret-auth-service-a1", platform="github", default_branch="main", workspace_id=ws_a_id, user_id=usr_a_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        repo_a2_id = f"repo-a2-{uuid.uuid4().hex[:8]}"
        repo_a2 = Repo(id=repo_a2_id, name="secret-payment-gateway-a2", platform="github", default_branch="main", workspace_id=ws_a_id, user_id=usr_a_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_a1)
        session.add(repo_a2)

        # Setup Workspace B + User B + Repo B1
        ws_b_id = f"ws-repo-b-{uuid.uuid4().hex[:8]}"
        ws_b = Workspace(id=ws_b_id, name="Repo Isolation WS B", color="red", provider="github", status="connected", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(ws_b)
        await session.flush()

        usr_b_id = f"usr-repo-b-{uuid.uuid4().hex[:8]}"
        usr_b = User(id=usr_b_id, email=f"{usr_b_id}@test-b.com", full_name="User Repo B", role="admin", workspace_id=ws_b_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr_b)
        await session.flush()

        repo_b1_id = f"repo-b1-{uuid.uuid4().hex[:8]}"
        repo_b1 = Repo(id=repo_b1_id, name="public-frontend-b1", platform="github", default_branch="main", workspace_id=ws_b_id, user_id=usr_b_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(repo_b1)

        # Setup User C with workspace_id = None (Unassigned User)
        usr_c_id = f"usr-repo-c-{uuid.uuid4().hex[:8]}"
        usr_c = User(id=usr_c_id, email=f"{usr_c_id}@test-c.com", full_name="User Repo C (Unassigned)", role="member", workspace_id=None, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        session.add(usr_c)

        await session.commit()

        try:
            # 1. User B lists repos -> Must receive ONLY Repo B1, 0 repos from Workspace A
            repos_b = await list_repos(session=session, user=usr_b)
            assert len(repos_b) == 1
            assert repos_b[0].id == repo_b1_id
            assert repos_b[0].workspace_id == ws_b_id
            assert not any(r.workspace_id == ws_a_id for r in repos_b)

            # 2. User C (workspace_id = None) lists repos -> Must receive 0 repos (no leak of all repos)
            repos_c = await list_repos(session=session, user=usr_c)
            assert len(repos_c) == 0

            # 3. User B searches for "secret-auth" -> Must return 0 results
            search_b = await search_repos(q="secret-auth", session=session, user=usr_b)
            assert len(search_b) == 0

            # 4. User B attempts GET /repos/{repo_a1_id} -> Must raise HTTP 404
            with pytest.raises(HTTPException) as exc_a1:
                await get_repo(repo_id=repo_a1_id, session=session, user=usr_b)
            assert exc_a1.value.status_code == 404
            assert "Repository not found" in exc_a1.value.detail

            # 5. User B attempts GET /repos/{repo_a1_id}/blast-radius -> Must raise HTTP 404
            with pytest.raises(HTTPException) as exc_br:
                await get_repo_blast_radius(repo_id=repo_a1_id, session=session, user=usr_b)
            assert exc_br.value.status_code == 404
            assert "Repository not found" in exc_br.value.detail

        finally:
            await session.execute(text("RESET ROLE;"))
            await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))
            for tbl in [Repo, User, Workspace]:
                stmt = select(tbl).where(tbl.id.in_([repo_a1_id, repo_a2_id, repo_b1_id, usr_a_id, usr_b_id, usr_c_id, ws_a_id, ws_b_id]))
                res = await session.execute(stmt)
                for item in res.scalars().all():
                    await session.delete(item)
            await session.commit()
