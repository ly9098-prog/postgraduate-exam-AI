"""408 stability follow-up."""
from alembic import op
import sqlalchemy as sa
revision = "s408stability20260907"
down_revision = "s408error20260907"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("exam_answers", sa.Column("answer_revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wrong_question_error_diagnoses", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))

def downgrade():
    op.drop_column("wrong_question_error_diagnoses", "is_current")
    op.drop_column("exam_answers", "answer_revision")
