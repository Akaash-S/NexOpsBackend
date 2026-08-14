"""add_workspace_scoped_pd_event_id_unique_index

Revision ID: g1a2b3c4d5e6
Revises: f9a0b1c2d3e4
Create Date: 2026-08-14 11:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'f9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add workspace-scoped partial unique index on events(workspace_id, pd_event_id)."""
    op.create_index(
        'uq_events_workspace_pd_event_id',
        'events',
        ['workspace_id', 'pd_event_id'],
        unique=True,
        postgresql_where=sa.text('pd_event_id IS NOT NULL')
    )


def downgrade() -> None:
    """Downgrade schema: drop workspace-scoped partial unique index."""
    op.drop_index(
        'uq_events_workspace_pd_event_id',
        table_name='events',
        postgresql_where=sa.text('pd_event_id IS NOT NULL')
    )
