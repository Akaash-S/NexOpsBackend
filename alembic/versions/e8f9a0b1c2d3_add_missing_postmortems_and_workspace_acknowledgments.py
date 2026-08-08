"""add_missing_postmortems_and_workspace_acknowledgments

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-08 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create workspace_acknowledgments table
    op.create_table(
        'workspace_acknowledgments',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('terms_version', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False, server_default='v1.0'),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', name='uq_workspace_acknowledgments_workspace_id')
    )
    op.create_index(op.f('ix_workspace_acknowledgments_id'), 'workspace_acknowledgments', ['id'], unique=False)
    op.create_index(op.f('ix_workspace_acknowledgments_user_id'), 'workspace_acknowledgments', ['user_id'], unique=False)
    op.create_index(op.f('ix_workspace_acknowledgments_workspace_id'), 'workspace_acknowledgments', ['workspace_id'], unique=True)

    # 2. Create postmortems table
    op.create_table(
        'postmortems',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('incident_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('author_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('timeline', sa.Text(), nullable=True),
        sa.Column('root_cause', sa.Text(), nullable=True),
        sa.Column('contributing_factors', sa.Text(), nullable=True),
        sa.Column('impact', sa.Text(), nullable=True),
        sa.Column('action_items', sa.Text(), nullable=True),
        sa.Column('lessons_learned', sa.Text(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('incident_id', name='uq_postmortems_incident_id')
    )
    op.create_index(op.f('ix_postmortems_id'), 'postmortems', ['id'], unique=False)
    op.create_index(op.f('ix_postmortems_incident_id'), 'postmortems', ['incident_id'], unique=True)
    op.create_index(op.f('ix_postmortems_status'), 'postmortems', ['status'], unique=False)
    op.create_index(op.f('ix_postmortems_workspace_id'), 'postmortems', ['workspace_id'], unique=False)

    # 3. Grant Permissions to nexops_app_role
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO nexops_app_role;")
    op.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO nexops_app_role;")

    # 4. Add RLS Policies for Tenant Isolation
    op.execute("ALTER TABLE workspace_acknowledgments ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY tenant_isolation_workspace_acknowledgments ON workspace_acknowledgments
        USING (workspace_id = current_setting('nexops.current_workspace_id', true) OR current_setting('nexops.bypass_rls', true) = 'true');
    """)

    op.execute("ALTER TABLE postmortems ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY tenant_isolation_postmortems ON postmortems
        USING (workspace_id = current_setting('nexops.current_workspace_id', true) OR current_setting('nexops.bypass_rls', true) = 'true');
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_postmortems ON postmortems;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_workspace_acknowledgments ON workspace_acknowledgments;")
    op.drop_table('postmortems')
    op.drop_table('workspace_acknowledgments')
