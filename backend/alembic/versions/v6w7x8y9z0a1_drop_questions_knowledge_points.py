"""drop questions.knowledge_points JSON column (contract phase)

After the expand phase (position column + relation backfill), ``questions``
no longer needs the denormalized ``knowledge_points`` JSON column — the relation
table ``question_knowledge_points`` is the single source of truth.

Safety: the upgrade refuses to drop the column while any question has duplicate
``(question_id, position)`` mappings (would break the new uniqueness guarantee
and silently reorder knowledge points). Run the backfill script first.

Downgrade rebuilds the JSON column from the relation table in ``position`` order.
"""
from __future__ import annotations

import json
import unicodedata

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v6w7x8y9z0a1"
down_revision = "p0q1r2s3t4u5"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_qkp_question_position"
_COLUMN = "knowledge_points"


def _column_names(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def _constraint_names(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_unique_constraints(table)}


def _norm_key(value: str) -> str:
    """与 app/services/knowledge_point_service.normalize_knowledge_name 对齐的
    轻量归一化：NFKC → strip → 合并空格 → 小写。仅用于迁移期一次性比对。"""
    return " ".join(unicodedata.normalize("NFKC", (value or "")).strip().lower().split())


def _completeness_mismatches(bind) -> list:
    """逐题校验关联表 normalized 展示名集合 == 旧 JSON 集合。

    JSON 内同名（归一化）重复元素在回填时折叠为一条映射（uq_qkp_question_kp 强制），
    set 比较天然容忍该折叠（如 qid=1050 的两个『文件系统实现』）。返回差异题列表。
    """
    rows = bind.execute(
        sa.text(
            "SELECT q.id, q.knowledge_points::text AS kp_json "
            "FROM questions q WHERE q.knowledge_points IS NOT NULL"
        )
    ).fetchall()
    rel = bind.execute(
        sa.text(
            "SELECT qkp.question_id, kp.name FROM question_knowledge_points qkp "
            "JOIN knowledge_points kp ON kp.id = qkp.knowledge_point_id"
        )
    ).fetchall()

    rel_by_q: dict[int, set[str]] = {}
    for qid, name in rel:
        rel_by_q.setdefault(qid, set()).add(_norm_key(name))

    mismatches: list = []
    for qid, kp_json in rows:
        try:
            legacy_norm = {
                _norm_key(i) for i in (str(item) for item in json.loads(kp_json)) if _norm_key(i)
            }
        except Exception:
            mismatches.append((qid, "invalid_json", []))
            continue
        rel_norm = rel_by_q.get(qid, set())
        if legacy_norm != rel_norm:
            mismatches.append((qid, sorted(legacy_norm), sorted(rel_norm)))
    return mismatches


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _COLUMN not in _column_names(inspector, "questions"):
        # Already contracted; nothing to do.
        return

    # Fail-closed guard: every (question_id, position) must be unique before the
    # unique constraint is added. Duplicates indicate the backfill has not run.
    dup = bind.execute(
        sa.text(
            "SELECT question_id, position, count(*) AS c "
            "FROM question_knowledge_points "
            "GROUP BY question_id, position HAVING count(*) > 1"
        )
    ).fetchall()
    if dup:
        raise RuntimeError(
            "question_knowledge_points 存在重复 (question_id, position)："
            f"{[tuple(r)[:2] for r in dup[:10]]}。请先运行回填脚本，再执行删列迁移。"
        )

    # Content-completeness guard (PG only): 删列前逐题比对关联表与旧 JSON 的
    # normalized 展示名集合。回填脚本版本有 bug / 只回填部分题时在此拦截，
    # 而不是静默删列丢数据。
    if bind.dialect.name == "postgresql":
        mismatches = _completeness_mismatches(bind)
        if mismatches:
            raise RuntimeError(
                "question_knowledge_points 与 questions.knowledge_points 内容不一致，"
                f"共 {len(mismatches)} 题。请先运行回填脚本，再执行删列迁移。"
                f"示例（qid, json_norm, rel_norm）：{mismatches[:5]}"
            )

    constraints = _constraint_names(inspector, "question_knowledge_points")
    if _CONSTRAINT not in constraints:
        op.create_unique_constraint(
            _CONSTRAINT,
            "question_knowledge_points",
            ["question_id", "position"],
        )

    # question_knowledge_points.question_id 外键补 ON DELETE CASCADE：与 ORM 的
    # passive_deletes 配合，硬删题目时在 DB 层级联清理关联行（lazy=noload 下
    # delete-orphan 不会触发）。幂等：已有 cascade 则跳过。
    fks = inspector.get_foreign_keys("question_knowledge_points")
    q_fk = next((f for f in fks if f["constrained_columns"] == ["question_id"]), None)
    if q_fk and "ondelete" not in q_fk.get("options", {}):
        fk_name = q_fk["name"]
        op.drop_constraint(fk_name, "question_knowledge_points", type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            "question_knowledge_points",
            "questions",
            ["question_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.drop_column("questions", _COLUMN)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cols = _column_names(inspector, "questions")
    if _COLUMN not in cols:
        op.add_column("questions", sa.Column(_COLUMN, sa.JSON(), nullable=True))

        # Postgres: rebuild the JSON column from the relation table in position
        # order (display names). SQLite is dev-only and has no json_agg, so it is
        # left NULL — integration tests exercise the PG path.
        if bind.dialect.name == "postgresql":
            op.execute(
                sa.text(
                    "UPDATE questions q SET knowledge_points = ("
                    "SELECT COALESCE(json_agg(kp.name ORDER BY qkp.position, qkp.id), '[]'::json) "
                    "FROM question_knowledge_points qkp "
                    "JOIN knowledge_points kp ON kp.id = qkp.knowledge_point_id "
                    "WHERE qkp.question_id = q.id) "
                    "WHERE EXISTS ("
                    "SELECT 1 FROM question_knowledge_points qkp WHERE qkp.question_id = q.id)"
                )
            )

    constraints = _constraint_names(inspector, "question_knowledge_points")
    if _CONSTRAINT in constraints:
        op.drop_constraint(_CONSTRAINT, "question_knowledge_points", type_="unique")
