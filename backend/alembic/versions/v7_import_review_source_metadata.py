"""v7: add source metadata and answer status fields to question_imports

Adds source_question_no, source_question_label, source_image_seq,
source_image_name, source_page_start, source_page_end, source_order_index,
raw_text_preview, answer_status, answer_source, answer_confidence,
review_priority fields to support import review source-location and
answer status enhancement.

Revision ID: v7_import_review_source_metadata
Revises: v6_adaptive_learning
Create Date: 2026-07-04
"""
import sqlalchemy as sa

from alembic import op

revision = "v7_import_review_source_metadata"
down_revision = "v6_adaptive_learning"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # Only add columns if they don't already exist
    columns = {c["name"] for c in insp.get_columns("question_imports")}

    additions = {
        "source_question_no": sa.Column("source_question_no", sa.String(32), nullable=True, index=True),
        "source_question_label": sa.Column("source_question_label", sa.String(32), nullable=True),
        "source_image_seq": sa.Column("source_image_seq", sa.Integer, nullable=True),
        "source_image_name": sa.Column("source_image_name", sa.String(256), nullable=True),
        "source_page_start": sa.Column("source_page_start", sa.Integer, nullable=True),
        "source_page_end": sa.Column("source_page_end", sa.Integer, nullable=True),
        "source_order_index": sa.Column("source_order_index", sa.Integer, nullable=True),
        "raw_text_preview": sa.Column("raw_text_preview", sa.Text, nullable=True),
        "answer_status": sa.Column("answer_status", sa.String(24), nullable=True, index=True),
        "answer_source": sa.Column("answer_source", sa.String(16), nullable=True),
        "answer_confidence": sa.Column("answer_confidence", sa.Float, nullable=True),
        "review_priority": sa.Column("review_priority", sa.Integer, nullable=True, index=True),
    }

    for col_name, col in additions.items():
        if col_name not in columns:
            op.add_column("question_imports", col)

    # Add composite index for batch source ordering (skip if exists)
    existing_idxs = {idx["name"] for idx in insp.get_indexes("question_imports")}
    if "ix_question_imports_source_order" not in existing_idxs:
        op.create_index(
            "ix_question_imports_source_order",
            "question_imports",
            ["batch_id", "source_image_seq", "source_order_index"],
        )
    if "ix_question_imports_answer_status" not in existing_idxs:
        op.create_index(
            "ix_question_imports_answer_status",
            "question_imports",
            ["answer_status"],
        )
    if "ix_question_imports_source_question_no" not in existing_idxs:
        op.create_index(
            "ix_question_imports_source_question_no",
            "question_imports",
            ["source_question_no"],
        )
    if "ix_question_imports_review_priority" not in existing_idxs:
        op.create_index(
            "ix_question_imports_review_priority",
            "question_imports",
            ["review_priority"],
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = {c["name"] for c in insp.get_columns("question_imports")}

    # SQLite rejects DROP COLUMN while an index still references that column.
    # Remove the indexes first on every dialect; this also makes the downgrade
    # safe when a partially applied upgrade left only some indexes behind.
    index_names = [
        "ix_question_imports_source_order",
        "ix_question_imports_answer_status",
        "ix_question_imports_source_question_no",
        "ix_question_imports_review_priority",
    ]
    existing_idxs = {idx["name"] for idx in insp.get_indexes("question_imports")}
    for idx_name in index_names:
        if idx_name in existing_idxs:
            op.drop_index(idx_name, table_name="question_imports")

    removals = [
        "source_question_no", "source_question_label", "source_image_seq",
        "source_image_name", "source_page_start", "source_page_end",
        "source_order_index", "raw_text_preview", "answer_status",
        "answer_source", "answer_confidence", "review_priority",
    ]
    present_removals = [col_name for col_name in removals if col_name in columns]
    if conn.dialect.name == "sqlite" and present_removals:
        with op.batch_alter_table("question_imports", recreate="auto") as batch_op:
            for col_name in present_removals:
                batch_op.drop_column(col_name)
    else:
        for col_name in present_removals:
            op.drop_column("question_imports", col_name)
