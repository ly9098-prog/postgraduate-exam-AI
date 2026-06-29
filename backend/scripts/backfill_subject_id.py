"""Backfill subject_id for questions and question_imports (raw SQL — image-independent).

Works with both SQLite and PostgreSQL. Run via:
  docker compose exec app python -m scripts.backfill_subject_id

Mapping logic (in priority order):
1. Exact match: questions.subject == subjects.code
2. Suffix match: suffix after last '-' == subjects.code  (e.g. "exam408-ds" → "ds")
3. Legacy alias match: well-known legacy subject → subjects.code  (e.g. "exam408" → "computer")
4. Unmatched active records → abort (no silent data loss)
"""

import asyncio
import logging
import sys

from sqlalchemy import text

from app.core.database import async_session

logger = logging.getLogger(__name__)

LEGACY_ALIASES: dict[str, str] = {
    "exam408": "computer",
}


def _resolve_subject_id(subject: str | None, subject_map: dict[str, int]) -> int | None:
    if not subject:
        return None
    key = subject.lower().strip()
    if key in subject_map:
        return subject_map[key]
    if "-" in key:
        suffix = key.rsplit("-", 1)[1]
        if suffix in subject_map:
            return subject_map[suffix]
    if key in LEGACY_ALIASES:
        alias_code = LEGACY_ALIASES[key].lower()
        if alias_code in subject_map:
            logger.info("  ↪ legacy alias '%s' → '%s' (id=%d)", key, alias_code, subject_map[alias_code])
            return subject_map[alias_code]
    return None


async def _ensure_subjects_seeded(db):
    """Seed default subjects if the subjects table is empty."""
    row = await db.execute(text("SELECT COUNT(*) FROM subjects"))
    count = row.scalar()
    if count and count > 0:
        return

    logger.warning("subjects table is EMPTY — seeding defaults")
    defaults = [
        (1, "math", "高数"),
        (2, "la", "线性代数"),
        (3, "ds", "数据结构"),
        (4, "cn", "计算机网络"),
        (5, "co", "计算机组成原理"),
        (6, "os", "操作系统"),
        (7, "pol", "政治"),
        (8, "eng", "英语"),
    ]
    for sid, code, name in defaults:
        await db.execute(
            text("INSERT INTO subjects (id, code, name, is_active) VALUES (:id, :code, :name, true) "
                 "ON CONFLICT (id) DO NOTHING"),
            {"id": sid, "code": code, "name": name},
        )
    await db.commit()
    logger.info("Seeded %d default subjects", len(defaults))


async def _column_exists(db, table: str, column: str) -> bool:
    """Check if a column exists (works with both PostgreSQL and SQLite)."""
    try:
        row = await db.execute(
            text("SELECT column_name FROM information_schema.columns "
                 "WHERE table_name = :table AND column_name = :col"),
            {"table": table, "col": column},
        )
        if row.first():
            return True
    except Exception:
        pass
    try:
        cols = (await db.execute(text(f"PRAGMA table_info({table})"))).all()
        return any(c[1] == column for c in cols)
    except Exception:
        return False


async def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async with async_session() as db:
        await _ensure_subjects_seeded(db)

        rows = (await db.execute(text("SELECT id, LOWER(code) FROM subjects"))).all()
        subject_map = {row[1]: row[0] for row in rows}
        logger.info("Subject map: %s", subject_map)

        has_subject_col = await _column_exists(db, "questions", "subject")

        if has_subject_col:
            # --- Backfill questions ---
            q_rows = (await db.execute(
                text("SELECT id, subject FROM questions WHERE subject_id IS NULL")
            )).all()
            logger.info("Questions to backfill: %d", len(q_rows))

            unmatched_q = []
            for qid, subj in q_rows:
                resolved = _resolve_subject_id(subj, subject_map)
                if resolved is not None:
                    await db.execute(
                        text("UPDATE questions SET subject_id = :sid WHERE id = :qid"),
                        {"sid": resolved, "qid": qid},
                    )
                else:
                    unmatched_q.append((qid, subj))

            if unmatched_q:
                logger.warning("Unmatched questions: %s", unmatched_q)

            # --- Backfill question_imports ---
            qi_rows = (await db.execute(
                text("SELECT id, subject FROM question_imports WHERE subject_id IS NULL")
            )).all()
            logger.info("QuestionImports to backfill: %d", len(qi_rows))

            unmatched_qi = []
            for qid, subj in qi_rows:
                resolved = _resolve_subject_id(subj, subject_map)
                if resolved is not None:
                    await db.execute(
                        text("UPDATE question_imports SET subject_id = :sid WHERE id = :qid"),
                        {"sid": resolved, "qid": qid},
                    )
                else:
                    unmatched_qi.append((qid, subj))

            if unmatched_qi:
                logger.warning("Unmatched question_imports: %s", unmatched_qi)

        else:
            logger.info("Column 'subject' no longer exists — checking subject_id completeness")

        # Validate active questions have subject_id
        orphaned = (await db.execute(
            text("SELECT id FROM questions WHERE subject_id IS NULL AND is_active = true")
        )).all()
        if orphaned:
            logger.error(
                "BLOCKING: %d active question(s) still have NULL subject_id: %s",
                len(orphaned), [r[0] for r in orphaned],
            )
            sys.exit(1)

        await db.commit()
        logger.info("Backfill completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
