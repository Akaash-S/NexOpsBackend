"""add_rls_to_feedback_and_recalibration

Revision ID: b9e8d7c6b5a4
Revises: a8f9c2d1b4e7
Create Date: 2026-07-18 19:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b9e8d7c6b5a4'
down_revision = 'a8f9c2d1b4e7'
branch_labels = None
depends_on = None


def upgrade():
    # Enable RLS on candidate_cause_feedback_logs
    op.execute(sa.text("ALTER TABLE candidate_cause_feedback_logs ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE candidate_cause_feedback_logs FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY tenant_isolation_policy ON candidate_cause_feedback_logs "
        "USING (workspace_id = current_setting('nexops.current_workspace_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true') "
        "WITH CHECK (workspace_id = current_setting('nexops.current_workspace_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true')"
    ))

    # Enable RLS on scoring_weight_recalibrations
    op.execute(sa.text("ALTER TABLE scoring_weight_recalibrations ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE scoring_weight_recalibrations FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY tenant_isolation_policy ON scoring_weight_recalibrations "
        "USING (workspace_id = current_setting('nexops.current_workspace_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true') "
        "WITH CHECK (workspace_id = current_setting('nexops.current_workspace_id', true) "
        "OR current_setting('nexops.bypass_rls', true) = 'true')"
    ))


def downgrade():
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_policy ON scoring_weight_recalibrations"))
    op.execute(sa.text("ALTER TABLE scoring_weight_recalibrations NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE scoring_weight_recalibrations DISABLE ROW LEVEL SECURITY"))

    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation_policy ON candidate_cause_feedback_logs"))
    op.execute(sa.text("ALTER TABLE candidate_cause_feedback_logs NO FORCE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE candidate_cause_feedback_logs DISABLE ROW LEVEL SECURITY"))
