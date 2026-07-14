"""Merge v10_v9_merge and v11_formula_graph_specs heads.

Revision ID: v11_merge_heads
Revises: v10_v9_merge, v11_formula_graph_specs
Create Date: 2026-07-14

Merges the two parallel heads:
1. v10_v9_merge (merge of v10 graph spec field + v9 approved→published migration)
2. v11_formula_graph_specs (new formula_graph_specs table)
"""

from alembic import op

revision = "v11_merge_heads"
down_revision = ("v10_v9_merge", "v11_formula_graph_specs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
