"""add_tenant_isolation

Revision ID: 6d4e7e2facef
Revises: 241e9fe3ed96
Create Date: 2026-07-09 14:28:41.388488

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6d4e7e2facef'
down_revision: Union[str, Sequence[str], None] = '241e9fe3ed96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create workspaces table
    op.create_table('workspaces',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('color', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('description', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
        sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workspaces_id'), 'workspaces', ['id'], unique=False)

    # 2. Add workspace_id columns as NULLABLE first
    op.add_column('alerts', sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_alerts_workspace_id'), 'alerts', ['workspace_id'], unique=False)
    op.create_foreign_key('fk_alerts_workspace_id', 'alerts', 'workspaces', ['workspace_id'], ['id'])

    op.add_column('candidate_causes', sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_candidate_causes_workspace_id'), 'candidate_causes', ['workspace_id'], unique=False)
    op.create_foreign_key('fk_candidate_causes_workspace_id', 'candidate_causes', 'workspaces', ['workspace_id'], ['id'])

    op.add_column('dependencies', sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_dependencies_workspace_id'), 'dependencies', ['workspace_id'], unique=False)
    op.create_foreign_key('fk_dependencies_workspace_id', 'dependencies', 'workspaces', ['workspace_id'], ['id'])

    op.add_column('deployments', sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_deployments_workspace_id'), 'deployments', ['workspace_id'], unique=False)
    op.create_foreign_key('fk_deployments_workspace_id', 'deployments', 'workspaces', ['workspace_id'], ['id'])

    op.add_column('events', sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_events_workspace_id'), 'events', ['workspace_id'], unique=False)
    op.create_foreign_key('fk_events_workspace_id', 'events', 'workspaces', ['workspace_id'], ['id'])

    op.add_column('incidents', sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_incidents_workspace_id'), 'incidents', ['workspace_id'], unique=False)
    op.create_foreign_key('fk_incidents_workspace_id', 'incidents', 'workspaces', ['workspace_id'], ['id'])

    # repos workspace_id is a pre-existing nullable VARCHAR; clear any stale values
    # that do not reference a workspace (they'll be re-populated in the backfill below).
    op.execute(sa.text("UPDATE repos SET workspace_id = NULL"))
    op.create_foreign_key('fk_repos_workspace_id', 'repos', 'workspaces', ['workspace_id'], ['id'])

    op.add_column('users', sa.Column('workspace_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_users_workspace_id'), 'users', ['workspace_id'], unique=False)
    op.create_foreign_key('fk_users_workspace_id', 'users', 'workspaces', ['workspace_id'], ['id'])

    # 3. Perform data backfill
    connection = op.get_bind()
    from alembic import context
    is_offline = context.is_offline_mode()
    
    if is_offline:
        users = []
        resolved_default_ws = "dummy-system-workspace"
    else:
        users = connection.execute(sa.text("SELECT id, full_name FROM users")).fetchall()
    
    workspace_mappings = {}  # user_id -> workspace_id
    for user_id, full_name in users:
        import uuid
        ws_id = str(uuid.uuid4())
        workspace_mappings[user_id] = ws_id
        
        if not is_offline:
            # Create workspace for user
            connection.execute(sa.text(
                "INSERT INTO workspaces (id, name, color, provider, status, created_at, updated_at) "
                "VALUES (:id, :name, 'blue', 'custom', 'connected', NOW(), NOW())"
            ), {"id": ws_id, "name": f"{full_name}'s Workspace"})
            
            # Link user to workspace
            connection.execute(sa.text(
                "UPDATE users SET workspace_id = :ws_id WHERE id = :user_id"
            ), {"ws_id": ws_id, "user_id": user_id})

    # Set default workspace ID if no users exist
    resolved_default_ws = None
    if workspace_mappings:
        resolved_default_ws = list(workspace_mappings.values())[0]
    else:
        import uuid
        resolved_default_ws = str(uuid.uuid4())
        if not is_offline:
            connection.execute(sa.text(
                "INSERT INTO workspaces (id, name, color, provider, status, created_at, updated_at) "
                "VALUES (:id, 'System Workspace', 'blue', 'custom', 'connected', NOW(), NOW())"
            ), {"id": resolved_default_ws})

    if not is_offline:
        # Update repos workspace_id with owner user's workspace
        repos = connection.execute(sa.text("SELECT id, user_id FROM repos")).fetchall()
        for repo_id, user_id in repos:
            ws_id = workspace_mappings.get(user_id) or resolved_default_ws
            connection.execute(sa.text(
                "UPDATE repos SET workspace_id = :ws_id WHERE id = :repo_id"
            ), {"ws_id": ws_id, "repo_id": repo_id})

        # Backfill workspace_id for all child tables
        connection.execute(sa.text(
            f"UPDATE alerts SET workspace_id = COALESCE((SELECT workspace_id FROM repos WHERE repos.id = alerts.repo_id), '{resolved_default_ws}')"
        ))
        connection.execute(sa.text(
            f"UPDATE events SET workspace_id = COALESCE((SELECT workspace_id FROM repos WHERE repos.id = events.repo_id), '{resolved_default_ws}')"
        ))
        connection.execute(sa.text(
            f"UPDATE deployments SET workspace_id = COALESCE((SELECT workspace_id FROM repos WHERE repos.id = deployments.repo_id), '{resolved_default_ws}')"
        ))
        connection.execute(sa.text(
            f"UPDATE incidents SET workspace_id = COALESCE((SELECT workspace_id FROM repos WHERE repos.id = incidents.root_cause_repo_id), '{resolved_default_ws}')"
        ))
        connection.execute(sa.text(
            f"UPDATE candidate_causes SET workspace_id = COALESCE((SELECT workspace_id FROM repos WHERE repos.id = candidate_causes.repo_id), '{resolved_default_ws}')"
        ))
        connection.execute(sa.text(
            f"UPDATE dependencies SET workspace_id = COALESCE((SELECT workspace_id FROM repos WHERE repos.id = dependencies.source_repo_id), '{resolved_default_ws}')"
        ))

    # 4. Alter columns to set NOT NULL
    op.alter_column('repos', 'workspace_id', existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column('alerts', 'workspace_id', existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column('events', 'workspace_id', existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column('deployments', 'workspace_id', existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column('incidents', 'workspace_id', existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column('dependencies', 'workspace_id', existing_type=sa.VARCHAR(), nullable=False)
    op.alter_column('candidate_causes', 'workspace_id', existing_type=sa.VARCHAR(), nullable=False)

    # 5. Enable RLS and add policies
    tenant_tables = [
        "repos", "alerts", "events", "dependencies", "deployments", "incidents", "candidate_causes"
    ]
    for table in tenant_tables:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(
            f"CREATE POLICY tenant_isolation_policy ON {table} "
            f"USING (workspace_id = current_setting('nexops.current_workspace_id', true) "
            f"OR current_setting('nexops.bypass_rls', true) = 'true') "
            f"WITH CHECK (workspace_id = current_setting('nexops.current_workspace_id', true) "
            f"OR current_setting('nexops.bypass_rls', true) = 'true')"
        ))

    # RLS for workspaces table
    op.execute(sa.text("ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE workspaces FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY tenant_isolation_policy ON workspaces "
        "USING (id = current_setting('nexops.current_workspace_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true') "
        "WITH CHECK (id = current_setting('nexops.current_workspace_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true')"
    ))

    # RLS for users table (allows reading own user or fellow workspace users)
    op.execute(sa.text("ALTER TABLE users ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE users FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY tenant_isolation_policy ON users "
        "USING (workspace_id = current_setting('nexops.current_workspace_id', true) "
        "OR id = current_setting('nexops.current_user_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true') "
        "WITH CHECK (workspace_id = current_setting('nexops.current_workspace_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true')"
    ))


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Disable and drop RLS policies
    all_tables = [
        "workspaces", "users", "repos", "alerts", "events", 
        "dependencies", "deployments", "incidents", "candidate_causes"
    ]
    for table in all_tables:
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    # 2. Drop constraints and columns
    op.drop_constraint('fk_users_workspace_id', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_workspace_id'), table_name='users')
    op.drop_column('users', 'workspace_id')

    op.drop_constraint('fk_repos_workspace_id', 'repos', type_='foreignkey')
    op.alter_column('repos', 'workspace_id', existing_type=sa.VARCHAR(), nullable=True)

    op.drop_constraint('fk_incidents_workspace_id', 'incidents', type_='foreignkey')
    op.drop_index(op.f('ix_incidents_workspace_id'), table_name='incidents')
    op.drop_column('incidents', 'workspace_id')

    op.drop_constraint('fk_events_workspace_id', 'events', type_='foreignkey')
    op.drop_index(op.f('ix_events_workspace_id'), table_name='events')
    op.drop_column('events', 'workspace_id')

    op.drop_constraint('fk_deployments_workspace_id', 'deployments', type_='foreignkey')
    op.drop_index(op.f('ix_deployments_workspace_id'), table_name='deployments')
    op.drop_column('deployments', 'workspace_id')

    op.drop_constraint('fk_dependencies_workspace_id', 'dependencies', type_='foreignkey')
    op.drop_index(op.f('ix_dependencies_workspace_id'), table_name='dependencies')
    op.drop_column('dependencies', 'workspace_id')

    op.drop_constraint('fk_candidate_causes_workspace_id', 'candidate_causes', type_='foreignkey')
    op.drop_index(op.f('ix_candidate_causes_workspace_id'), table_name='candidate_causes')
    op.drop_column('candidate_causes', 'workspace_id')

    op.drop_constraint('fk_alerts_workspace_id', 'alerts', type_='foreignkey')
    op.drop_index(op.f('ix_alerts_workspace_id'), table_name='alerts')
    op.drop_column('alerts', 'workspace_id')

    op.drop_index(op.f('ix_workspaces_id'), table_name='workspaces')
    op.drop_table('workspaces')
