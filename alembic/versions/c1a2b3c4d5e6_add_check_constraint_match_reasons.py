"""add_check_constraint_match_reasons

Revision ID: c1a2b3c4d5e6
Revises: b9e8d7c6b5a4
Create Date: 2026-07-22 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c1a2b3c4d5e6'
down_revision = 'b9e8d7c6b5a4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text(
        "ALTER TABLE candidate_causes "
        "ADD CONSTRAINT ck_candidate_causes_score_reason "
        "CHECK (score <= 0 OR (reason IS NOT NULL AND TRIM(reason) <> ''))"
    ))


def downgrade():
    op.execute(sa.text(
        "ALTER TABLE candidate_causes "
        "DROP CONSTRAINT IF EXISTS ck_candidate_causes_score_reason"
    ))
