"""add_feedback_log_and_recalibration

Revision ID: a8f9c2d1b4e7
Revises: 6d4e7e2facef
Create Date: 2026-07-18 17:52:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision = 'a8f9c2d1b4e7'
down_revision = '6d4e7e2facef'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create candidate_cause_feedback_logs table
    op.create_table(
        'candidate_cause_feedback_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('candidate_cause_id', sa.String(), nullable=False),
        sa.Column('incident_id', sa.String(), nullable=False),
        sa.Column('repo_id', sa.String(), nullable=False),
        sa.Column('event_id', sa.String(), nullable=True),
        sa.Column('confirmed', sa.Boolean(), nullable=False),
        sa.Column('confirmed_by', sa.String(), nullable=True),
        sa.Column('score_at_time', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('reasons_at_time', sa.String(length=1000), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['candidate_cause_id'], ['candidate_causes.id'], ),
        sa.ForeignKeyConstraint(['confirmed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
        sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
        sa.ForeignKeyConstraint(['repo_id'], ['repos.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_candidate_cause_feedback_logs_candidate_cause_id'), 'candidate_cause_feedback_logs', ['candidate_cause_id'], unique=False)
    op.create_index(op.f('ix_candidate_cause_feedback_logs_id'), 'candidate_cause_feedback_logs', ['id'], unique=False)
    op.create_index(op.f('ix_candidate_cause_feedback_logs_incident_id'), 'candidate_cause_feedback_logs', ['incident_id'], unique=False)
    op.create_index(op.f('ix_candidate_cause_feedback_logs_repo_id'), 'candidate_cause_feedback_logs', ['repo_id'], unique=False)
    op.create_index(op.f('ix_candidate_cause_feedback_logs_workspace_id'), 'candidate_cause_feedback_logs', ['workspace_id'], unique=False)

    # 2. Create scoring_weight_recalibrations table
    op.create_table(
        'scoring_weight_recalibrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('weights', sa.String(length=2000), nullable=False),
        sa.Column('sample_size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('previous_weights', sa.String(length=2000), nullable=False),
        sa.Column('trigger_type', sa.String(length=50), nullable=False, server_default='manual'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scoring_weight_recalibrations_id'), 'scoring_weight_recalibrations', ['id'], unique=False)
    op.create_index(op.f('ix_scoring_weight_recalibrations_workspace_id'), 'scoring_weight_recalibrations', ['workspace_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_scoring_weight_recalibrations_workspace_id'), table_name='scoring_weight_recalibrations')
    op.drop_index(op.f('ix_scoring_weight_recalibrations_id'), table_name='scoring_weight_recalibrations')
    op.drop_table('scoring_weight_recalibrations')

    op.drop_index(op.f('ix_candidate_cause_feedback_logs_workspace_id'), table_name='candidate_cause_feedback_logs')
    op.drop_index(op.f('ix_candidate_cause_feedback_logs_repo_id'), table_name='candidate_cause_feedback_logs')
    op.drop_index(op.f('ix_candidate_cause_feedback_logs_incident_id'), table_name='candidate_cause_feedback_logs')
    op.drop_index(op.f('ix_candidate_cause_feedback_logs_id'), table_name='candidate_cause_feedback_logs')
    op.drop_index(op.f('ix_candidate_cause_feedback_logs_candidate_cause_id'), table_name='candidate_cause_feedback_logs')
    op.drop_table('candidate_cause_feedback_logs')
