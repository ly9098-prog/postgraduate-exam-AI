"""extend subject field length and add sub_subject support

subject 字段从 String(16) 扩展到 String(32)，支持 exam408-ds / math2-calculus 等子科目值。
旧数据 exam408 / math2 / english 保持不变（向后兼容）。
"""
import sqlalchemy as sa

from alembic import op

revision = "b4e3d2c1f0a9"
down_revision = "a3f2e1b0c9d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 用 batch_alter_table，PostgreSQL 直接支持 ALTER COLUMN
    with op.batch_alter_table("questions") as batch:
        batch.alter_column("subject", type_=sa.String(32), existing_nullable=False)
    with op.batch_alter_table("question_imports") as batch:
        batch.alter_column("subject", type_=sa.String(32), existing_nullable=True)
    with op.batch_alter_table("practice_records") as batch:
        batch.alter_column("subject", type_=sa.String(32), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("questions") as batch:
        batch.alter_column("subject", type_=sa.String(16), existing_nullable=False)
    with op.batch_alter_table("question_imports") as batch:
        batch.alter_column("subject", type_=sa.String(16), existing_nullable=True)
    with op.batch_alter_table("practice_records") as batch:
        batch.alter_column("subject", type_=sa.String(16), existing_nullable=False)
