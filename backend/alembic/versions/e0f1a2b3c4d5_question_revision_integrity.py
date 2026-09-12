"""make immutable question revisions the learning source of truth

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-09-04

This is an intentionally structural migration.  It establishes one immutable
QuestionVersion revision as the identity used by practice, wrong-book and review
history, removes legacy batch-shaped PracticeRecord columns, and normalizes the
historical duplicate wrong/review state that earlier code had to compensate for.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

import sqlalchemy as sa

from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None

LEGACY_PRACTICE_COLUMNS = (
    "question_ids",
    "answers",
    "correct_count",
    "wrong_count",
    "duration_sec",
    "started_at",
    "finished_at",
)


def _insp():
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    insp = _insp()
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(table: str) -> set[str]:
    insp = _insp()
    if table not in insp.get_table_names():
        return set()
    return {i["name"] for i in insp.get_indexes(table)}


def _unique_constraints(table: str) -> set[str]:
    insp = _insp()
    if table not in insp.get_table_names():
        return set()
    return {c.get("name") for c in insp.get_unique_constraints(table) if c.get("name")}


def _canonical_hash(row: dict, kp_links: list[tuple[int, int, str, float, str]]) -> str:
    payload = {
        "question_id": int(row["id"]),
        "subject_id": int(row["subject_id"]),
        "question_type": str(row.get("question_type") or ""),
        "content": row.get("content"),
        "options": row.get("options"),
        "answer": str(row.get("answer") or ""),
        "analysis": row.get("analysis"),
        "difficulty": int(row.get("difficulty") or 3),
        "image_url": row.get("image_url"),
        "is_active": bool(row.get("is_active")),
        "source": row.get("source"),
        "source_type": row.get("source_type"),
        "source_file": row.get("source_file"),
        "raw_content": row.get("raw_content"),
        "year": row.get("year"),
        "knowledge_points": [
            [int(k), int(p), str(role), float(weight), str(source)]
            for k, p, role, weight, source in kp_links
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _add_schema() -> None:
    qv_cols = _columns("question_versions")
    if "change_source" not in qv_cols:
        op.add_column("question_versions", sa.Column("change_source", sa.String(32), nullable=True))
    if "state_hash" not in qv_cols:
        op.add_column("question_versions", sa.Column("state_hash", sa.String(64), nullable=True))
    for name, typ in (
        ("source", sa.String(64)),
        ("source_type", sa.String(16)),
        ("source_file", sa.String(256)),
        ("raw_content", sa.Text()),
        ("year", sa.SmallInteger()),
    ):
        if name not in qv_cols:
            op.add_column("question_versions", sa.Column(name, typ, nullable=True))
    if "ix_question_versions_state_hash" not in _indexes("question_versions"):
        op.create_index("ix_question_versions_state_hash", "question_versions", ["state_hash"])
    with op.batch_alter_table("question_versions", recreate="auto") as batch:
        batch.alter_column("edited_by", existing_type=sa.Integer(), nullable=True)

    qvkp_cols = _columns("question_version_knowledge_points")
    if "role" not in qvkp_cols:
        op.add_column(
            "question_version_knowledge_points",
            sa.Column("role", sa.String(16), nullable=True, server_default="main"),
        )
    if "weight" not in qvkp_cols:
        op.add_column(
            "question_version_knowledge_points",
            sa.Column("weight", sa.Float(), nullable=True, server_default="1.0"),
        )
    if "source" not in qvkp_cols:
        op.add_column(
            "question_version_knowledge_points",
            sa.Column("source", sa.String(16), nullable=True, server_default="legacy"),
        )

    if "current_version_id" not in _columns("questions"):
        op.add_column("questions", sa.Column("current_version_id", sa.BigInteger(), nullable=True))
    if "ix_questions_current_version_id" not in _indexes("questions"):
        op.create_index("ix_questions_current_version_id", "questions", ["current_version_id"])

    if "question_version_id" not in _columns("practice_records"):
        op.add_column("practice_records", sa.Column("question_version_id", sa.BigInteger(), nullable=True))
    if "projection_state" not in _columns("practice_records"):
        op.add_column(
            "practice_records",
            sa.Column("projection_state", sa.String(20), nullable=True, server_default="archived"),
        )
    if "ix_practice_records_question_version_id" not in _indexes("practice_records"):
        op.create_index("ix_practice_records_question_version_id", "practice_records", ["question_version_id"])
    if "ix_practice_records_projection_state_answered" not in _indexes("practice_records"):
        op.create_index(
            "ix_practice_records_projection_state_answered",
            "practice_records",
            ["projection_state", "answered_at"],
        )

    for table in ("answer_behaviors", "wrong_questions"):
        if "question_version_id" not in _columns(table):
            op.add_column(table, sa.Column("question_version_id", sa.BigInteger(), nullable=True))
        idx = f"ix_{table}_question_version_id"
        if idx not in _indexes(table):
            op.create_index(idx, table, ["question_version_id"])

    schedule_cols = _columns("review_schedules")
    if "question_version_id" not in schedule_cols:
        op.add_column("review_schedules", sa.Column("question_version_id", sa.BigInteger(), nullable=True))
    if "is_active" not in schedule_cols:
        op.add_column("review_schedules", sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()))
    if "occurrence_seq" not in schedule_cols:
        op.add_column("review_schedules", sa.Column("occurrence_seq", sa.Integer(), nullable=True, server_default="0"))
    if "ix_review_schedules_question_version_id" not in _indexes("review_schedules"):
        op.create_index("ix_review_schedules_question_version_id", "review_schedules", ["question_version_id"])
    if "ix_review_schedules_user_version" not in _indexes("review_schedules"):
        op.create_index("ix_review_schedules_user_version", "review_schedules", ["user_id", "question_version_id"])

    rr_cols = _columns("review_records")
    additions = {
        "question_version_id": sa.BigInteger(),
        "request_id": sa.String(128),
        "occurrence_seq": sa.Integer(),
        "user_answer": sa.Text(),
        "is_correct": sa.Boolean(),
        "next_review_at": sa.DateTime(),
        "mastery_percent": sa.Integer(),
        "mastered": sa.Boolean(),
    }
    for name, typ in additions.items():
        if name not in rr_cols:
            op.add_column("review_records", sa.Column(name, typ, nullable=True))
    if "ix_review_records_question_version_id" not in _indexes("review_records"):
        op.create_index("ix_review_records_question_version_id", "review_records", ["question_version_id"])
    if "ix_review_records_user_version" not in _indexes("review_records"):
        op.create_index("ix_review_records_user_version", "review_records", ["user_id", "question_version_id"])


def _normalize_practice_sessions() -> None:
    bind = op.get_bind()
    if "practice_sessions" not in _insp().get_table_names():
        return
    meta = sa.MetaData()
    sessions = sa.Table("practice_sessions", meta, autoload_with=bind)
    rows = bind.execute(sa.select(sessions.c.id, sessions.c.request_id).order_by(sessions.c.id)).all()
    for session_id, raw_request_id in rows:
        request_id = str(raw_request_id or "").strip()
        if not request_id:
            request_id = f"migration-session:{int(session_id)}"
        elif len(request_id) > 128:
            request_id = f"migration-sha256:{hashlib.sha256(request_id.encode('utf-8')).hexdigest()}"
        bind.execute(sessions.update().where(sessions.c.id == session_id).values(request_id=request_id))

    if "ux_practice_sessions_user_request" in _indexes("practice_sessions"):
        op.drop_index("ux_practice_sessions_user_request", table_name="practice_sessions")
    with op.batch_alter_table("practice_sessions", recreate="auto") as batch:
        batch.alter_column(
            "request_id",
            existing_type=sa.String(256),
            type_=sa.String(128),
            nullable=False,
        )
    op.create_index(
        "ux_practice_sessions_user_request",
        "practice_sessions",
        ["user_id", "request_id"],
        unique=True,
    )


def _backfill_current_revisions() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    questions = sa.Table("questions", meta, autoload_with=bind)
    qv = sa.Table("question_versions", meta, autoload_with=bind)
    qkp = sa.Table("question_knowledge_points", meta, autoload_with=bind)
    qvkp = sa.Table("question_version_knowledge_points", meta, autoload_with=bind)

    # SQLite tables created by older migrations used BIGINT primary keys, which
    # are not rowid aliases and therefore need an explicit id.  PostgreSQL/MySQL
    # must *not* receive explicit ids here: doing so would leave their sequence /
    # auto-increment generator behind the inserted migration rows and make the
    # first post-upgrade QuestionVersion insert collide.
    sqlite_manual_id = bind.dialect.name == "sqlite"
    max_qv_id = (
        int(bind.execute(sa.select(sa.func.max(qv.c.id))).scalar() or 0)
        if sqlite_manual_id
        else 0
    )
    for raw in bind.execute(sa.select(questions).order_by(questions.c.id)).mappings().all():
        row = dict(raw)
        qid = int(row["id"])
        kp_rows = bind.execute(
            sa.select(
                qkp.c.knowledge_point_id,
                qkp.c.position,
                qkp.c.role,
                qkp.c.weight,
                qkp.c.source,
            )
            .where(qkp.c.question_id == qid)
            .order_by(qkp.c.position, qkp.c.id)
        ).all()
        kp_links = [
            (
                int(k),
                int(p or 0),
                str(role or "main"),
                float(weight if weight is not None else 1.0),
                str(source or "imported"),
            )
            for k, p, role, weight, source in kp_rows
        ]
        next_version = int(
            bind.execute(sa.select(sa.func.max(qv.c.version)).where(qv.c.question_id == qid)).scalar() or 0
        ) + 1
        values = dict(
                question_id=qid,
                version=next_version,
                subject_id=int(row["subject_id"]),
                question_type=str(row.get("question_type") or ""),
                image_url=row.get("image_url"),
                is_active=bool(row.get("is_active")),
                source=row.get("source"),
                source_type=row.get("source_type"),
                source_file=row.get("source_file"),
                raw_content=row.get("raw_content"),
                year=row.get("year"),
                content=row.get("content") or {},
                options=row.get("options"),
                answer=str(row.get("answer") or ""),
                analysis=row.get("analysis"),
                difficulty=int(row.get("difficulty") or 3),
                edited_by=None,
                change_source="migration_current",
                state_hash=_canonical_hash(row, kp_links),
                edit_reason="establish immutable current revision",
            )
        if sqlite_manual_id:
            max_qv_id += 1
            values["id"] = max_qv_id
        result = bind.execute(qv.insert().values(**values))
        revision_id = (
            max_qv_id
            if sqlite_manual_id
            else int(result.inserted_primary_key[0])
        )
        for kp_id, position, role, weight, source in kp_links:
            bind.execute(
                qvkp.insert().values(
                    question_version_id=revision_id,
                    knowledge_point_id=kp_id,
                    position=position,
                    role=role,
                    weight=weight,
                    source=source,
                )
            )
        bind.execute(questions.update().where(questions.c.id == qid).values(current_version_id=revision_id))

    bind.execute(qv.update().where(qv.c.change_source.is_(None)).values(change_source="legacy_history"))


def _backfill_learning_revision_links() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    questions = sa.Table("questions", meta, autoload_with=bind)
    practices = sa.Table("practice_records", meta, autoload_with=bind)
    behaviors = sa.Table("answer_behaviors", meta, autoload_with=bind)
    wrongs = sa.Table("wrong_questions", meta, autoload_with=bind)

    def current_revision(table):
        return sa.select(questions.c.current_version_id).where(
            questions.c.id == table.c.question_id
        ).scalar_subquery()

    bind.execute(
        practices.update().values(
            question_version_id=current_revision(practices),
            projection_state="archived",
        )
    )
    bind.execute(
        behaviors.update()
        .where(behaviors.c.practice_record_id.is_not(None))
        .values(
            question_version_id=sa.select(practices.c.question_version_id)
            .where(practices.c.id == behaviors.c.practice_record_id)
            .scalar_subquery()
        )
    )
    # Legacy /behavior/record writes were allowed without a PracticeRecord.
    # Bind those rows to the migration-time current revision instead of leaving
    # NULLs that would make the later NOT NULL transition fail.  They are
    # historical evidence only; no reconciliation is scheduled for them.
    bind.execute(
        behaviors.update()
        .where(behaviors.c.question_version_id.is_(None))
        .values(question_version_id=current_revision(behaviors))
    )
    bind.execute(
        wrongs.update().values(question_version_id=current_revision(wrongs))
    )


def _row_rank(row: dict) -> tuple[str, int]:
    marker = row.get("last_reviewed_at") or row.get("updated_at") or row.get("created_at") or ""
    return (str(marker), int(row.get("id") or 0))


def _dedupe_wrong_questions() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    wrongs = sa.Table("wrong_questions", meta, autoload_with=bind)
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for row in bind.execute(sa.select(wrongs).order_by(wrongs.c.id)).mappings().all():
        data = dict(row)
        groups[(int(data["user_id"]), int(data["question_id"]))].append(data)

    for rows in groups.values():
        if len(rows) <= 1:
            continue
        canonical = max(rows, key=_row_rank)
        cid = int(canonical["id"])
        active = any(bool(r.get("is_active")) for r in rows)
        review_count = max(int(r.get("review_count") or 0) for r in rows)
        latest_wrong = max(rows, key=lambda r: (str(r.get("last_review_at") or r.get("updated_at") or ""), int(r["id"])))
        mastered = bool(canonical.get("mastered")) if active else False
        values = {
            "question_version_id": latest_wrong.get("question_version_id") or canonical.get("question_version_id"),
            "wrong_answer": latest_wrong.get("wrong_answer"),
            "error_type": latest_wrong.get("error_type") or canonical.get("error_type") or "other",
            "ai_analysis": latest_wrong.get("ai_analysis"),
            "review_count": review_count,
            "last_review_at": max((r.get("last_review_at") for r in rows if r.get("last_review_at") is not None), default=None),
            "is_active": active,
            "removed_at": None if active else canonical.get("removed_at"),
            "mastered": mastered,
            "mastered_at": canonical.get("mastered_at") if mastered else None,
        }
        bind.execute(wrongs.update().where(wrongs.c.id == cid).values(**values))
        duplicate_ids = [int(r["id"]) for r in rows if int(r["id"]) != cid]
        bind.execute(wrongs.delete().where(wrongs.c.id.in_(duplicate_ids)))


def _backfill_and_dedupe_review_state() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    questions = sa.Table("questions", meta, autoload_with=bind)
    qv = sa.Table("question_versions", meta, autoload_with=bind)
    wrongs = sa.Table("wrong_questions", meta, autoload_with=bind)
    schedules = sa.Table("review_schedules", meta, autoload_with=bind)
    records = sa.Table("review_records", meta, autoload_with=bind)

    # Schedules follow the current wrong-book revision when available; otherwise
    # they bind to the migration current revision of their question.
    schedule_rows = bind.execute(sa.select(schedules).order_by(schedules.c.id)).mappings().all()
    for raw in schedule_rows:
        row = dict(raw)
        wq_version = bind.execute(
            sa.select(wrongs.c.question_version_id).where(
                wrongs.c.user_id == row["user_id"],
                wrongs.c.question_id == row["question_id"],
            )
        ).scalar()
        version_id = wq_version or bind.execute(
            sa.select(questions.c.current_version_id).where(questions.c.id == row["question_id"])
        ).scalar()
        subject_id = bind.execute(sa.select(qv.c.subject_id).where(qv.c.id == version_id)).scalar()
        wq_active = bind.execute(
            sa.select(wrongs.c.is_active).where(
                wrongs.c.user_id == row["user_id"],
                wrongs.c.question_id == row["question_id"],
            )
        ).scalar()
        bind.execute(
            schedules.update().where(schedules.c.id == row["id"]).values(
                question_version_id=version_id,
                subject_id=subject_id,
                is_active=True if wq_active is None else bool(wq_active),
            )
        )

    # Collapse historical duplicate schedules to one canonical row and remap all
    # ReviewRecord FKs before deleting duplicates.
    refreshed = bind.execute(sa.select(schedules).order_by(schedules.c.id)).mappings().all()
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for raw in refreshed:
        row = dict(raw)
        groups[(int(row["user_id"]), int(row["question_id"]))].append(row)
    for rows in groups.values():
        if len(rows) <= 1:
            continue
        canonical = max(rows, key=_row_rank)
        cid = int(canonical["id"])
        duplicate_ids = [int(r["id"]) for r in rows if int(r["id"]) != cid]
        bind.execute(records.update().where(records.c.schedule_id.in_(duplicate_ids)).values(schedule_id=cid))
        bind.execute(schedules.delete().where(schedules.c.id.in_(duplicate_ids)))

    # Review history is immutable from this migration onward. Historical rows did
    # not store a revision/request/occurrence, so derive deterministic identities.
    record_rows = bind.execute(
        sa.select(records).order_by(records.c.schedule_id, records.c.reviewed_at, records.c.id)
    ).mappings().all()
    occurrence_by_schedule: dict[int, int] = defaultdict(int)
    for raw in record_rows:
        row = dict(raw)
        version_id = None
        if row.get("schedule_id") is not None:
            version_id = bind.execute(
                sa.select(schedules.c.question_version_id).where(schedules.c.id == row["schedule_id"])
            ).scalar()
        if version_id is None:
            version_id = bind.execute(
                sa.select(questions.c.current_version_id).where(questions.c.id == row["question_id"])
            ).scalar()
        schedule_id = row.get("schedule_id")
        occurrence_seq = occurrence_by_schedule[int(schedule_id)] if schedule_id is not None else int(row["id"])
        if schedule_id is not None:
            occurrence_by_schedule[int(schedule_id)] += 1
        request_id = str(row.get("request_id") or "").strip() or f"migration-review:{int(row['id'])}"
        bind.execute(
            records.update().where(records.c.id == row["id"]).values(
                question_version_id=version_id,
                occurrence_seq=occurrence_seq,
                request_id=request_id,
                is_correct=bool(int(row.get("rating") or 0) >= 3),
            )
        )

    for schedule_id, next_occurrence in occurrence_by_schedule.items():
        bind.execute(
            schedules.update().where(schedules.c.id == schedule_id).values(
                occurrence_seq=int(next_occurrence)
            )
        )


def _normalize_review_numeric_state() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    schedules = sa.Table("review_schedules", meta, autoload_with=bind)
    records = sa.Table("review_records", meta, autoload_with=bind)
    bind.execute(
        schedules.update().where(schedules.c.occurrence_seq < 0).values(occurrence_seq=0)
    )
    bind.execute(schedules.update().where(schedules.c.interval < 0).values(interval=0))
    bind.execute(
        schedules.update().where(schedules.c.repetitions < 0).values(repetitions=0)
    )
    bind.execute(records.update().where(records.c.occurrence_seq < 0).values(occurrence_seq=0))
    bind.execute(records.update().where(records.c.rating < 0).values(rating=0))
    bind.execute(records.update().where(records.c.rating > 5).values(rating=5))
    bind.execute(
        records.update().where(records.c.mastery_percent < 0).values(mastery_percent=0)
    )
    bind.execute(
        records.update().where(records.c.mastery_percent > 100).values(mastery_percent=100)
    )


def _finalize_schema() -> None:
    # ``current_version_id`` intentionally remains nullable at the storage layer.
    # Creating a revision requires a persisted question_id, so a new Question must
    # be insertable with a transient NULL inside the same transaction.  Student-
    # facing/publish boundaries enforce the stronger invariant before commit/use.
    with op.batch_alter_table("questions", recreate="auto") as batch:
        batch.create_foreign_key(
            "fk_questions_current_version_id",
            "question_versions",
            ["current_version_id"],
            ["id"],
        )

    with op.batch_alter_table("practice_records", recreate="auto") as batch:
        batch.alter_column("question_version_id", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("projection_state", existing_type=sa.String(20), nullable=False, server_default=None)
        batch.create_check_constraint(
            "ck_practice_records_projection_state",
            "projection_state IN ('pending','completed','revision_only','archived')",
        )
        batch.create_foreign_key(
            "fk_practice_records_question_version_id",
            "question_versions",
            ["question_version_id"],
            ["id"],
        )

    with op.batch_alter_table("answer_behaviors", recreate="auto") as batch:
        batch.alter_column("question_version_id", existing_type=sa.BigInteger(), nullable=False)
        batch.create_foreign_key(
            "fk_answer_behaviors_question_version_id",
            "question_versions",
            ["question_version_id"],
            ["id"],
        )

    with op.batch_alter_table("wrong_questions", recreate="auto") as batch:
        batch.alter_column("question_version_id", existing_type=sa.BigInteger(), nullable=False)
        batch.create_foreign_key(
            "fk_wrong_questions_question_version_id",
            "question_versions",
            ["question_version_id"],
            ["id"],
        )
        if "uq_wrong_questions_user_question" not in _unique_constraints("wrong_questions"):
            batch.create_unique_constraint("uq_wrong_questions_user_question", ["user_id", "question_id"])

    with op.batch_alter_table("review_schedules", recreate="auto") as batch:
        batch.alter_column("question_version_id", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("is_active", existing_type=sa.Boolean(), nullable=False, server_default=None)
        batch.alter_column("occurrence_seq", existing_type=sa.Integer(), nullable=False, server_default=None)
        batch.create_foreign_key(
            "fk_review_schedules_question_version_id",
            "question_versions",
            ["question_version_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "ck_review_schedules_occurrence_nonnegative", "occurrence_seq >= 0"
        )
        batch.create_check_constraint(
            "ck_review_schedules_interval_nonnegative", "interval >= 0"
        )
        batch.create_check_constraint(
            "ck_review_schedules_repetitions_nonnegative", "repetitions >= 0"
        )
        if "uq_review_schedules_user_question" not in _unique_constraints("review_schedules"):
            batch.create_unique_constraint("uq_review_schedules_user_question", ["user_id", "question_id"])

    with op.batch_alter_table("review_records", recreate="auto") as batch:
        batch.alter_column("question_version_id", existing_type=sa.BigInteger(), nullable=False)
        batch.alter_column("request_id", existing_type=sa.String(128), nullable=False)
        batch.alter_column("occurrence_seq", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_review_records_question_version_id",
            "question_versions",
            ["question_version_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "ck_review_records_occurrence_nonnegative", "occurrence_seq >= 0"
        )
        batch.create_check_constraint(
            "ck_review_records_rating_range", "rating >= 0 AND rating <= 5"
        )
        batch.create_check_constraint(
            "ck_review_records_mastery_percent_range",
            "mastery_percent IS NULL OR (mastery_percent >= 0 AND mastery_percent <= 100)",
        )
    with op.batch_alter_table("review_records", recreate="auto") as batch:
        batch.create_unique_constraint(
            "uq_review_records_user_request", ["user_id", "request_id"]
        )
        batch.create_unique_constraint(
            "uq_review_records_schedule_occurrence", ["schedule_id", "occurrence_seq"]
        )

    existing = _columns("practice_records")
    with op.batch_alter_table("practice_records", recreate="auto") as batch:
        for name in LEGACY_PRACTICE_COLUMNS:
            if name in existing:
                batch.drop_column(name)

    # Legacy revision rows predate association metadata.  Preserve that fact with
    # explicit neutral defaults instead of borrowing mutable current mappings.
    qvkp = sa.Table("question_version_knowledge_points", sa.MetaData(), autoload_with=op.get_bind())
    op.get_bind().execute(
        qvkp.update().where(qvkp.c.role.is_(None)).values(role="main")
    )
    op.get_bind().execute(
        qvkp.update().where(qvkp.c.weight.is_(None)).values(weight=1.0)
    )
    op.get_bind().execute(
        qvkp.update().where(qvkp.c.source.is_(None)).values(source="legacy")
    )
    with op.batch_alter_table("question_version_knowledge_points", recreate="auto") as batch:
        batch.alter_column("role", existing_type=sa.String(16), nullable=False, server_default=None)
        batch.alter_column("weight", existing_type=sa.Float(), nullable=False, server_default=None)
        batch.alter_column("source", existing_type=sa.String(16), nullable=False, server_default=None)

    with op.batch_alter_table("question_versions", recreate="auto") as batch:
        batch.alter_column("change_source", existing_type=sa.String(32), nullable=False, server_default=None)


def upgrade() -> None:
    _add_schema()
    _normalize_practice_sessions()
    _backfill_current_revisions()
    _backfill_learning_revision_links()
    _dedupe_wrong_questions()
    _backfill_and_dedupe_review_state()
    _normalize_review_numeric_state()
    _finalize_schema()


def downgrade() -> None:
    raise RuntimeError(
        "e0f1a2b3c4d5 performs irreversible revision binding and duplicate-state normalization. "
        "Restore the pre-upgrade database backup instead of downgrading this revision."
    )
