"""Add formula_graph_specs table (one-to-many specs per card).

Revision ID: v11_formula_graph_specs
Revises: v10_formula_graph_spec_fields
Create Date: 2026-07-14

Adds:
- ``formula_graph_specs`` table with stable slug per card
- Unique constraint on (formula_card_id, slug)
- One-to-many relationship: each card can have multiple independent specs
"""

import sqlalchemy as sa

from alembic import op

revision = "v11_formula_graph_specs"
down_revision = "v10_formula_graph_spec_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "formula_graph_specs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("formula_card_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.String(256), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("alt_text", sa.String(512), nullable=True),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("spec_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("renderer_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_asset_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["formula_card_id"],
            ["formula_cards.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_asset_id"],
            ["formula_graph_assets.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["admin_users.id"],
        ),
        sa.UniqueConstraint(
            "formula_card_id", "slug",
            name="uq_formula_graph_specs_card_slug",
        ),
    )
    op.create_index(
        "ix_formula_graph_specs_formula_card_id",
        "formula_graph_specs",
        ["formula_card_id"],
    )
    op.create_index(
        "ix_formula_graph_specs_status",
        "formula_graph_specs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_formula_graph_specs_status", table_name="formula_graph_specs")
    op.drop_index("ix_formula_graph_specs_formula_card_id", table_name="formula_graph_specs")
    op.drop_table("formula_graph_specs")
