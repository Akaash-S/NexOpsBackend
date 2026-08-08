"""force_rls_on_postmortems_and_acknowledgments

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-08-08 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9a0b1c2d3e4'
down_revision: Union[str, Sequence[str], None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to enforce FORCE ROW LEVEL SECURITY parity."""
    op.execute("ALTER TABLE workspace_acknowledgments FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE postmortems FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE postmortems NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE workspace_acknowledgments NO FORCE ROW LEVEL SECURITY;")
