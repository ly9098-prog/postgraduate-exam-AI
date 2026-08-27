"""normalize question version knowledge points

Move ``question_versions.knowledge_points`` from a denormalized JSON list into
``question_version_knowledge_points``. Historical version rows then reference
``knowledge_points.id`` through ``question_versions.id`` while preserving the
original display order.

The backfill is fail-closed: every legacy name must resolve to a knowledge point
before the JSON column is dropped. Resolution prefers a subject that is
consistent across all names in one version, then the question's current subject,
and only falls back to a globally unique normalized name.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision: str = "qvkp20260827"
down_revision: str | None = "z0a1b2c3d4e5"
branch_labels = None
depends_on = None

_TABLE = "question_version_knowledge_points"
_LEGACY_COLUMN = "knowledge_points"

_FULLWIDTH_MAP = {
    "（": "(", "）": ")", "【": "[", "】": "]",
    "｛": "{", "｝": "}", "，": ",", "。": ".",
    "；": ";", "：": ":", "！": "!", "？": "?",
    "＋": "+", "－": "-", "＊": "*", "／": "/",
    "＝": "=", "＜": "<", "＞": ">",
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
}


def _normalize_name(value: str) -> str:
    text = "".join(_FULLWIDTH_MAP.get(ch, ch) for ch in str(value or ""))
    text = unicodedata.normalize("NFKC", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _column_names(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _parse_legacy(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"question_versions.knowledge_points 存在非法 JSON: {value!r}") from exc
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError(
            "question_versions.knowledge_points 必须为 JSON 数组，"
            f"实际类型为 {type(value).__name__}"
        )
    return [str(item).strip() for item in value if str(item).strip()]


def _create_relation_table(bind) -> None:
    if _TABLE in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "question_version_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            sa.ForeignKey("question_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_points.id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "question_version_id",
            "knowledge_point_id",
            name="uq_qvkp_version_kp",
        ),
        sa.UniqueConstraint(
            "question_version_id",
            "position",
            name="uq_qvkp_version_position",
        ),
    )
    op.create_index(
        "ix_question_version_knowledge_points_question_version_id",
        _TABLE,
        ["question_version_id"],
    )
    op.create_index(
        "ix_question_version_knowledge_points_knowledge_point_id",
        _TABLE,
        ["knowledge_point_id"],
    )


def _backfill(bind) -> None:
    kp_rows = bind.execute(
        sa.text(
            "SELECT id, subject_id, name, normalized_name "
            "FROM knowledge_points ORDER BY id"
        )
    ).fetchall()
    by_norm: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for kp_id, subject_id, name, normalized_name in kp_rows:
        key = _normalize_name(normalized_name or name)
        if key:
            by_norm[key].append((int(kp_id), int(subject_id), str(name)))

    question_subject = {
        int(question_id): int(subject_id)
        for question_id, subject_id in bind.execute(
            sa.text("SELECT id, subject_id FROM questions")
        ).fetchall()
    }

    versions = bind.execute(
        sa.text(
            "SELECT id, question_id, knowledge_points "
            "FROM question_versions ORDER BY id"
        )
    ).fetchall()

    # Safe retry for databases where failed DDL is not fully transactional.
    bind.execute(sa.text(f"DELETE FROM {_TABLE}"))

    relation = sa.table(
        _TABLE,
        sa.column("question_version_id", sa.BigInteger()),
        sa.column("knowledge_point_id", sa.Integer()),
        sa.column("position", sa.Integer()),
    )
    inserts: list[dict[str, int]] = []
    unresolved: list[str] = []

    for version_id, question_id, raw_names in versions:
        names = _parse_legacy(raw_names)
        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for display in names:
            norm = _normalize_name(display)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            deduped.append((display, norm))

        if not deduped:
            continue

        candidate_subject_sets: list[set[int]] = []
        has_missing_candidate = False
        for display, norm in deduped:
            candidates = by_norm.get(norm, [])
            if not candidates:
                unresolved.append(
                    f"version_id={version_id}, question_id={question_id}, name={display!r}: 主表无匹配"
                )
                has_missing_candidate = True
                continue
            candidate_subject_sets.append({subject_id for _, subject_id, _ in candidates})

        if has_missing_candidate:
            continue

        inferred_subjects = set.intersection(*candidate_subject_sets) if candidate_subject_sets else set()
        current_subject = question_subject.get(int(question_id))
        if len(inferred_subjects) == 1:
            preferred_subject = next(iter(inferred_subjects))
        elif current_subject is not None and current_subject in inferred_subjects:
            preferred_subject = current_subject
        elif current_subject is not None:
            # Some historical names may be globally unique and therefore make the
            # intersection empty. Use current subject only as a local preference;
            # globally unique names can still resolve below.
            preferred_subject = current_subject
        else:
            preferred_subject = None

        resolved_ids: list[int] = []
        version_failed = False
        for display, norm in deduped:
            candidates = by_norm.get(norm, [])
            subject_matches = (
                [item for item in candidates if item[1] == preferred_subject]
                if preferred_subject is not None
                else []
            )
            if len(subject_matches) == 1:
                resolved_ids.append(subject_matches[0][0])
                continue
            if len(candidates) == 1:
                resolved_ids.append(candidates[0][0])
                continue

            unresolved.append(
                "version_id={version_id}, question_id={question_id}, name={name!r}: "
                "存在跨科目歧义 candidates={candidates}".format(
                    version_id=version_id,
                    question_id=question_id,
                    name=display,
                    candidates=[(item[0], item[1], item[2]) for item in candidates],
                )
            )
            version_failed = True
            break

        if version_failed:
            continue

        inserts.extend(
            {
                "question_version_id": int(version_id),
                "knowledge_point_id": kp_id,
                "position": position,
            }
            for position, kp_id in enumerate(resolved_ids)
        )

    if unresolved:
        preview = "\n".join(unresolved[:20])
        raise RuntimeError(
            "question_versions.knowledge_points 自动迁移失败，存在无法安全解析的知识点。"
            f"共 {len(unresolved)} 条，示例：\n{preview}"
        )

    if inserts:
        # Keep statement sizes bounded on large history tables.
        for start in range(0, len(inserts), 1000):
            bind.execute(relation.insert(), inserts[start:start + 1000])


def _verify_completeness(bind) -> None:
    legacy_rows = bind.execute(
        sa.text("SELECT id, knowledge_points FROM question_versions ORDER BY id")
    ).fetchall()
    joined_rows = bind.execute(
        sa.text(
            "SELECT qvkp.question_version_id, kp.name "
            f"FROM {_TABLE} qvkp "
            "JOIN knowledge_points kp ON kp.id = qvkp.knowledge_point_id "
            "ORDER BY qvkp.question_version_id, qvkp.position, qvkp.id"
        )
    ).fetchall()

    actual: dict[int, set[str]] = defaultdict(set)
    for version_id, name in joined_rows:
        norm = _normalize_name(name)
        if norm:
            actual[int(version_id)].add(norm)

    mismatches: list[tuple[int, list[str], list[str]]] = []
    for version_id, raw_names in legacy_rows:
        expected = {_normalize_name(item) for item in _parse_legacy(raw_names) if _normalize_name(item)}
        found = actual.get(int(version_id), set())
        if expected != found:
            mismatches.append((int(version_id), sorted(expected), sorted(found)))

    if mismatches:
        raise RuntimeError(
            "question_version_knowledge_points 回填完整性校验失败，"
            f"共 {len(mismatches)} 个版本不一致。示例：{mismatches[:5]}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    columns = _column_names(bind, "question_versions")
    _create_relation_table(bind)

    if _LEGACY_COLUMN not in columns:
        return

    _backfill(bind)
    _verify_completeness(bind)

    op.drop_column("question_versions", _LEGACY_COLUMN)


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return

    if _LEGACY_COLUMN not in _column_names(bind, "question_versions"):
        with op.batch_alter_table("question_versions") as batch_op:
            batch_op.add_column(sa.Column(_LEGACY_COLUMN, sa.JSON(), nullable=True))

    version_table = sa.table(
        "question_versions",
        sa.column("id", sa.BigInteger()),
        sa.column(_LEGACY_COLUMN, sa.JSON()),
    )
    rows = bind.execute(
        sa.text(
            "SELECT qv.id, kp.name "
            "FROM question_versions qv "
            f"LEFT JOIN {_TABLE} qvkp ON qvkp.question_version_id = qv.id "
            "LEFT JOIN knowledge_points kp ON kp.id = qvkp.knowledge_point_id "
            "ORDER BY qv.id, qvkp.position, qvkp.id"
        )
    ).fetchall()
    names_by_version: dict[int, list[str]] = defaultdict(list)
    all_version_ids: set[int] = set()
    for version_id, name in rows:
        version_id = int(version_id)
        all_version_ids.add(version_id)
        if name is not None:
            names_by_version[version_id].append(str(name))

    for version_id in all_version_ids:
        bind.execute(
            version_table.update()
            .where(version_table.c.id == version_id)
            .values({_LEGACY_COLUMN: names_by_version.get(version_id, [])})
        )

    op.drop_table(_TABLE)
