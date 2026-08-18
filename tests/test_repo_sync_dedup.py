import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dotenv
dotenv.load_dotenv(Path(__file__).resolve().parent.parent / '.env')

import os
os.environ['DATABASE_URL'] = os.getenv('DATABASE_URL_DIRECT')

import pytest
import asyncio
import uuid
from unittest.mock import AsyncMock, patch
from sqlmodel import select
from sqlalchemy.exc import IntegrityError
from app.core.database import async_session
from app.models.repo import Repo
from app.models.user import User
from app.api.routes.integrations import _perform_sync, SyncRequest, _active_sync_workspaces

@pytest.mark.asyncio
async def test_repo_sync_deduplication_and_constraint():
    """
    Automated Regression Test for Repo Sync Deduplication:
    1. Exercises workspace-scoped upsert match (workspace_id, name, platform).
    2. Exercises DB unique index uq_repos_workspace_name_platform.
    3. Exercises in-flight sync concurrency lock with full VCS service mocking.
    """
    test_user_id = "f0rwTkSUeieCH909q13HMo93jJp1"
    test_ws_id = "ws-f0rwTkSUeieC"

    # Step 1: Verify DB unique constraint raises IntegrityError on duplicate raw INSERT
    async with async_session() as session:
        user = await session.get(User, test_user_id)
        assert user is not None, "Test user f0rwTkSUeieCH909q13HMo93jJp1 must exist"

        dup_repo_name = f"unit_test_repo_{uuid.uuid4().hex[:6]}"
        r1 = Repo(
            id=str(uuid.uuid4()),
            workspace_id=test_ws_id,
            user_id=test_user_id,
            name=dup_repo_name,
            platform="github",
            default_branch="main",
            status="active"
        )
        session.add(r1)
        await session.commit()

        r2_duplicate = Repo(
            id=str(uuid.uuid4()),
            workspace_id=test_ws_id,
            user_id=test_user_id,
            name=dup_repo_name,  # Same workspace, name, platform
            platform="github",
            default_branch="main",
            status="active"
        )
        session.add(r2_duplicate)
        
        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()
        
        await session.rollback()
        assert "uq_repos_workspace_name_platform" in str(exc_info.value) or "unique constraint" in str(exc_info.value).lower()
        print("\n[PASS] DB Unique Constraint test passed: IntegrityError raised as expected.")

        # Clean up test row
        res_clean = await session.execute(select(Repo).where(Repo.name == dup_repo_name))
        for row in res_clean.scalars().all():
            await session.delete(row)
        await session.commit()

    # Step 2: Verify in-flight concurrency lock guard (with mocked VCS service so network errors never obscure lock behavior)
    with patch('app.services.vcs_service.vcs_service.sync_repositories', new_callable=AsyncMock) as mock_sync, \
         patch('app.services.vcs_service.vcs_service.register_github_webhook', new_callable=AsyncMock), \
         patch('app.services.vcs_service.vcs_service.fetch_github_deployments', new_callable=AsyncMock) as mock_deps:
        mock_sync.return_value = []
        mock_deps.return_value = []

        async with async_session() as session2:
            user2 = await session2.get(User, test_user_id)
            _active_sync_workspaces.add(test_ws_id)
            try:
                req = SyncRequest(provider="github", token="dummy_token_for_test", workspaceId=test_ws_id)
                res = await _perform_sync(req, user2, session2)
                assert res.get("status") == "already_syncing", "Concurrent sync should return already_syncing status"
                print("[PASS] In-flight concurrency lock test passed.")
            finally:
                _active_sync_workspaces.discard(test_ws_id)

    # Step 3: Verify workspace-scoped upsert match (multi-user scenario: User B syncing User A's repo in same workspace)
    async with async_session() as session3:
        # Create User A (original owner) and User B (secondary sync user in same workspace)
        user_a_id = test_user_id
        user_b_id = f"usr_b_{uuid.uuid4().hex[:6]}"
        user_b = User(
            id=user_b_id,
            email=f"user_b_{uuid.uuid4().hex[:6]}@example.com",
            full_name="Test User B",
            hashed_password="dummy_hashed_password",
            workspace_id=test_ws_id,
            is_active=True
        )
        session3.add(user_b)
        await session3.commit()

        target_name = f"upsert_test_{uuid.uuid4().hex[:6]}"
        existing_repo_user_a = Repo(
            id=str(uuid.uuid4()),
            workspace_id=test_ws_id,
            user_id=user_a_id,  # Created by User A
            name=target_name,
            platform="github",
            default_branch="main",
            description="Created by User A",
            status="active"
        )
        session3.add(existing_repo_user_a)
        await session3.commit()

        # User B triggers sync for the workspace repository
        incoming_repo = Repo(
            id=str(uuid.uuid4()),
            workspace_id=test_ws_id,
            user_id=user_b_id,
            name=target_name,
            platform="github",
            default_branch="main",
            description="Updated by User B via Workspace Sync",
            status="active"
        )

        with patch('app.services.vcs_service.vcs_service.sync_repositories', new_callable=AsyncMock) as mock_sync3, \
             patch('app.services.vcs_service.vcs_service.register_github_webhook', new_callable=AsyncMock), \
             patch('app.services.vcs_service.vcs_service.fetch_github_deployments', new_callable=AsyncMock) as mock_deps3:
            mock_sync3.return_value = [incoming_repo]
            mock_deps3.return_value = []
            req3 = SyncRequest(provider="github", token="dummy_token_for_test", workspaceId=test_ws_id)
            # Executed by User B
            sync_res = await _perform_sync(req3, user_b, session3)
            assert sync_res.get("status") == "success"

        # Verify only 1 repo exists for this name in the workspace and description was updated
        res_check = await session3.execute(select(Repo).where(Repo.workspace_id == test_ws_id, Repo.name == target_name))
        matched_repos = res_check.scalars().all()
        assert len(matched_repos) == 1, f"Expected exactly 1 repo, found {len(matched_repos)}"
        assert matched_repos[0].id == existing_repo_user_a.id, "Upsert should match User A's repo ID by workspace_id"
        assert matched_repos[0].description == "Updated by User B via Workspace Sync", "Upsert should update existing repo record"
        print("[PASS] Upsert match by (workspace_id, name, platform) multi-user test passed.")

        # Clean up test rows
        await session3.delete(matched_repos[0])
        await session3.delete(user_b)
        await session3.commit()
