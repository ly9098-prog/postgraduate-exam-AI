"""add formula tables (formula_categories, formula_tags, formula_cards, etc.)

Revision ID: 6c11177c2437
Revises: 32d214360cf1
Create Date: 2026-07-12 22:43:12.680757

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision: str = "6c11177c2437"
down_revision: Union[str, Sequence[str], None] = "32d214360cf1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # formula_categories
    op.create_table(
        "formula_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("exam_scope", sa.String(32), nullable=False, server_default="math2"),
        sa.Column("node_type", sa.String(16), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["formula_categories.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_id", "code", name="uq_formula_categories_parent_code"),
    )
    op.create_index(
        op.f("ix_formula_categories_exam_scope"),
        "formula_categories",
        ["exam_scope"],
    )
    op.create_index(
        op.f("ix_formula_categories_parent_id"),
        "formula_categories",
        ["parent_id"],
    )

    # formula_tags (fixed seed)
    op.create_table(
        "formula_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_formula_tags_code"), "formula_tags", ["code"], unique=True
    )

    # formula_cards
    op.create_table(
        "formula_cards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("exam_scope", sa.String(32), nullable=False, server_default="math2"),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("aliases", sqlite.JSON(), nullable=True),
        sa.Column("search_text", sa.String(512), nullable=True),
        sa.Column("card_type", sa.String(32), nullable=False, server_default="pure_formula"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("formula_blocks", sqlite.JSON(), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("symbol_notes", sa.Text(), nullable=True),
        sa.Column("secondary_conclusions", sa.Text(), nullable=True),
        sa.Column("error_tips", sa.Text(), nullable=True),
        sa.Column("examples", sqlite.JSON(), nullable=True),
        sa.Column("function_properties", sqlite.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("source_title", sa.String(256), nullable=True),
        sa.Column("source_ref", sa.String(256), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["category_id"], ["formula_categories.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_formula_cards_exam_scope"), "formula_cards", ["exam_scope"]
    )
    op.create_index(
        op.f("ix_formula_cards_category_id"), "formula_cards", ["category_id"]
    )
    op.create_index(op.f("ix_formula_cards_status"), "formula_cards", ["status"])
    op.create_index(
        op.f("ix_formula_cards_content_hash"), "formula_cards", ["content_hash"]
    )

    # formula_card_tags
    op.create_table(
        "formula_card_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("formula_card_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["formula_card_id"], ["formula_cards.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["formula_tags.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "formula_card_id", "tag_id", name="uq_formula_card_tags_card_tag"
        ),
    )
    op.create_index(
        op.f("ix_formula_card_tags_formula_card_id"),
        "formula_card_tags",
        ["formula_card_id"],
    )
    op.create_index(
        op.f("ix_formula_card_tags_tag_id"), "formula_card_tags", ["tag_id"]
    )

    # formula_graph_assets
    op.create_table(
        "formula_graph_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("formula_card_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("template_type", sa.String(64), nullable=True),
        sa.Column("template_parameters", sqlite.JSON(), nullable=True),
        sa.Column("viewport", sqlite.JSON(), nullable=True),
        sa.Column("image_url", sa.String(512), nullable=True),
        sa.Column("thumbnail_url", sa.String(512), nullable=True),
        sa.Column("original_svg_url", sa.String(512), nullable=True),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["formula_card_id"], ["formula_cards.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "formula_card_id",
            "source_type",
            name="uq_formula_graph_assets_card_source",
        ),
    )
    op.create_index(
        op.f("ix_formula_graph_assets_formula_card_id"),
        "formula_graph_assets",
        ["formula_card_id"],
    )

    # formula_card_versions
    op.create_table(
        "formula_card_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("formula_card_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sqlite.JSON(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("edited_by", sa.Integer(), nullable=True),
        sa.Column("edit_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["formula_card_id"], ["formula_cards.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["edited_by"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "formula_card_id",
            "version",
            name="uq_formula_card_versions_card_version",
        ),
    )
    op.create_index(
        op.f("ix_formula_card_versions_formula_card_id"),
        "formula_card_versions",
        ["formula_card_id"],
    )

    # user_formula_favorites
    op.create_table(
        "user_formula_favorites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("formula_card_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["formula_card_id"], ["formula_cards.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "formula_card_id", name="uq_user_formula_favorites_user_card"
        ),
    )
    op.create_index(
        op.f("ix_user_formula_favorites_user_id"),
        "user_formula_favorites",
        ["user_id"],
    )
    op.create_index(
        op.f("ix_user_formula_favorites_formula_card_id"),
        "user_formula_favorites",
        ["formula_card_id"],
    )

    # formula_import_jobs
    op.create_table(
        "formula_import_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("stage", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("source_filename", sa.String(256), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_of", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sqlite.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by"], ["admin_users.id"]),
        sa.ForeignKeyConstraint(["retry_of"], ["formula_import_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_formula_import_jobs_status"), "formula_import_jobs", ["status"]
    )

    # formula_import_items
    op.create_table(
        "formula_import_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("source_locator", sa.String(256), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("raw_image_url", sa.String(512), nullable=True),
        sa.Column("generated_content", sqlite.JSON(), nullable=True),
        sa.Column("card_type", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("risk_flags", sqlite.JSON(), nullable=True),
        sa.Column("latex_valid", sa.Boolean(), nullable=True),
        sa.Column("latex_errors", sqlite.JSON(), nullable=True),
        sa.Column("scope_check", sqlite.JSON(), nullable=True),
        sa.Column("duplicate_check", sqlite.JSON(), nullable=True),
        sa.Column(
            "review_status", sa.String(32), nullable=False, server_default="pending"
        ),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("result_card_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["formula_import_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["result_card_id"], ["formula_cards.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["admin_users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_formula_import_items_job_id"), "formula_import_items", ["job_id"]
    )

    # Seed fixed formula tags
    op.execute(
        "INSERT INTO formula_tags (code, name, sort_order) VALUES "
        "('basic', '基础', 1), "
        "('high_frequency', '高频', 2), "
        "('error_prone', '易错', 3), "
        "('must_memorize', '必背', 4)"
    )


def downgrade() -> None:
    op.drop_table("formula_import_items")
    op.drop_table("formula_import_jobs")
    op.drop_table("user_formula_favorites")
    op.drop_table("formula_card_versions")
    op.drop_table("formula_graph_assets")
    op.drop_table("formula_card_tags")
    op.drop_table("formula_cards")
    op.drop_table("formula_tags")
    op.drop_table("formula_categories")
