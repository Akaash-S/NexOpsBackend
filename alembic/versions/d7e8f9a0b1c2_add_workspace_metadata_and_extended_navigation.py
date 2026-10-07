"""add_workspace_metadata_and_extended_navigation

Revision ID: d7e8f9a0b1c2
Revises: c1a2b3c4d5e6
Create Date: 2026-08-01 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd7e8f9a0b1c2'
down_revision = 'c1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS show_extended_navigation BOOLEAN DEFAULT FALSE;"))
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS color VARCHAR;"))
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS description VARCHAR;"))
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS provider VARCHAR;"))
    op.execute(sa.text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'active';"))


def downgrade():
    op.execute(sa.text("ALTER TABLE workspaces DROP COLUMN IF EXISTS show_extended_navigation;"))
    op.execute(sa.text("ALTER TABLE workspaces DROP COLUMN IF EXISTS color;"))
    op.execute(sa.text("ALTER TABLE workspaces DROP COLUMN IF EXISTS description;"))
    op.execute(sa.text("ALTER TABLE workspaces DROP COLUMN IF EXISTS provider;"))
    op.execute(sa.text("ALTER TABLE workspaces DROP COLUMN IF EXISTS status;"))
