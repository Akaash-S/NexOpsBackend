"""add_unique_constraint_to_repos

Revision ID: h1a2b3c4d5e6
Revises: g1a2b3c4d5e6
Create Date: 2026-08-17 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'g1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add composite unique index on repos(workspace_id, name, platform)."""
    op.create_index(
        'uq_repos_workspace_name_platform',
        'repos',
        ['workspace_id', 'name', 'platform'],
        unique=True,
        if_not_exists=True
    )


def downgrade() -> None:
    """Downgrade schema: drop composite unique index on repos(workspace_id, name, platform)."""
    op.drop_index(
        'uq_repos_workspace_name_platform',
        table_name='repos',
        if_exists=True
    )

