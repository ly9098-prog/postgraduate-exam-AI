"""Add graph generation fields to formula cards and graph assets.

Adds:
- ``formula_cards.graph_spec``, ``draft_graph_spec``, ``graph_status``,
  ``graph_last_error``, ``graph_generated_at``, ``graph_confirmed_at``
- ``formula_graph_assets.file_size``, ``renderer_version``, ``alt_text``,
  ``description``, ``reviewed_by``, ``reviewed_at``, ``review_note``, ``published_version``
- ``formula_graph_previews`` table
- ``formula_cards.graph_status`` index
- Backfill existing data based on ``card_type`` and existing ``graph_assets``

Revision ID: v10_formula_graph_spec_fields
Revises: 6c11177c2437
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

revision = "v10_formula_graph_spec_fields"
down_revision = "6c11177c2437"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # ── 1. formula_cards new columns ──
    op.add_column("formula_cards", sa.Column("graph_spec", sa.JSON(), nullable=True))
    op.add_column("formula_cards", sa.Column("draft_graph_spec", sa.JSON(), nullable=True))
    op.add_column(
        "formula_cards",
        sa.Column("graph_status", sa.String(32),
                  nullable=False, server_default="not_applicable"),
    )
    op.add_column("formula_cards", sa.Column("graph_last_error", sa.Text(), nullable=True))
    op.add_column("formula_cards", sa.Column("graph_generated_at", sa.DateTime(), nullable=True))
    op.add_column("formula_cards", sa.Column("graph_confirmed_at", sa.DateTime(), nullable=True))
    op.create_index("ix_formula_cards_graph_status", "formula_cards", ["graph_status"])

    # ── 2. formula_graph_assets new columns ──
    op.add_column("formula_graph_assets", sa.Column("file_size", sa.Integer(), nullable=True))
    op.add_column("formula_graph_assets", sa.Column("renderer_version", sa.Integer(), nullable=True))
    op.add_column("formula_graph_assets", sa.Column("alt_text", sa.String(512), nullable=True))
    op.add_column("formula_graph_assets", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("formula_graph_assets", sa.Column("reviewed_by", sa.Integer(), nullable=True))
    op.add_column("formula_graph_assets", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("formula_graph_assets", sa.Column("review_note", sa.String(256), nullable=True))
    op.add_column("formula_graph_assets", sa.Column("published_version", sa.Integer(), nullable=True))

    # ── 3. formula_graph_previews table ──
    op.create_table(
        "formula_graph_previews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("formula_card_id", sa.Integer(),
                  sa.ForeignKey("formula_cards.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("preview_token", sa.String(64), unique=True, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("preview_url", sa.String(512), nullable=True),
        sa.Column("thumbnail_url", sa.String(512), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("renderer_version", sa.Integer(), nullable=True),
        sa.Column("quality_errors", sa.JSON(), nullable=True),
        sa.Column("quality_warnings", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ── 4. Backfill existing data ──
    _backfill_graph_status(bind, is_sqlite)


def downgrade() -> None:
    # formula_graph_previews table
    op.drop_table("formula_graph_previews")

    # formula_graph_assets columns
    op.drop_column("formula_graph_assets", "published_version")
    op.drop_column("formula_graph_assets", "review_note")
    op.drop_column("formula_graph_assets", "reviewed_at")
    op.drop_column("formula_graph_assets", "reviewed_by")
    op.drop_column("formula_graph_assets", "description")
    op.drop_column("formula_graph_assets", "alt_text")
    op.drop_column("formula_graph_assets", "renderer_version")
    op.drop_column("formula_graph_assets", "file_size")

    # formula_cards columns
    op.drop_index("ix_formula_cards_graph_status", table_name="formula_cards")
    op.drop_column("formula_cards", "graph_confirmed_at")
    op.drop_column("formula_cards", "graph_generated_at")
    op.drop_column("formula_cards", "graph_last_error")
    op.drop_column("formula_cards", "graph_status")
    op.drop_column("formula_cards", "draft_graph_spec")
    op.drop_column("formula_cards", "graph_spec")


# ═══════════════════════════════════════════════════════════════
# Backfill
# ═══════════════════════════════════════════════════════════════

def _backfill_graph_status(bind, is_sqlite: bool) -> None:
    """Set graph_status for existing cards based on card_type and assets.

    Rules (idempotent — WHERE prevents re-application):
    1. ``card_type = 'pure_formula'`` → ``not_applicable``
    2. has existing graph asset with image_url → ``ready``
    3. has ``graph_spec`` → ``missing``
    4. everything else → ``unconfigured``
    """
    # For SQLite, we need to use raw SQL
    # Rule 1: pure_formula
    op.execute("""
        UPDATE formula_cards
        SET graph_status = 'not_applicable'
        WHERE card_type = 'pure_formula'
          AND deleted_at IS NULL
          AND graph_status = 'not_applicable'
    """)

    # Rule 2: has existing asset with image
    op.execute("""
        UPDATE formula_cards
        SET graph_status = 'ready'
        WHERE card_type IN ('function_graph', 'auto')
          AND deleted_at IS NULL
          AND id IN (
              SELECT DISTINCT formula_card_id
              FROM formula_graph_assets
              WHERE image_url IS NOT NULL
          )
          AND graph_status = 'not_applicable'
    """)

    # Rule 3: has graph_spec column (data already set)
    op.execute("""
        UPDATE formula_cards
        SET graph_status = 'missing'
        WHERE card_type IN ('function_graph', 'auto')
          AND deleted_at IS NULL
          AND graph_spec IS NOT NULL
          AND graph_status = 'not_applicable'
    """)

    # Rule 4: rest → unconfigured
    op.execute("""
        UPDATE formula_cards
        SET graph_status = 'unconfigured'
        WHERE card_type IN ('function_graph', 'auto')
          AND deleted_at IS NULL
          AND graph_status = 'not_applicable'
    """)
