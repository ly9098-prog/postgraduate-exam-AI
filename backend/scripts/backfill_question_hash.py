"""非破坏性回填历史题目的 question_hash。

用法：
    cd backend
    python -m scripts.backfill_question_hash --dry-run
    python -m scripts.backfill_question_hash --apply --batch-size 500
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import or_, select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.features.question_pipeline import normalizer  # noqa: E402
from app.models.question import Question  # noqa: E402


def _stem_text(content: dict | str | None) -> str:
    if not content:
        return ""
    if isinstance(content, dict):
        for key in ("text", "stem", "题干", "题目"):
            value = content.get(key)
            if value:
                return str(value)
        return ""
    return str(content)


async def backfill_question_hash(*, apply: bool, batch_size: int, limit: int | None) -> dict[str, int]:
    scanned = 0
    updated = 0
    skipped = 0
    errors = 0
    last_id = 0

    async with async_session() as db:
        while True:
            query = (
                select(Question)
                .where(
                    Question.id > last_id,
                    or_(Question.question_hash.is_(None), Question.question_hash == ""),
                )
                .order_by(Question.id.asc())
                .limit(batch_size)
            )
            result = await db.execute(query)
            questions = list(result.scalars().all())
            if not questions:
                break

            for question in questions:
                last_id = question.id
                if limit is not None and scanned >= limit:
                    break

                scanned += 1
                try:
                    stem = _stem_text(question.content)
                    normalized_stem = normalizer.normalize_hash_text(stem)
                    normalized_options = normalizer.normalize_hash_options(question.options)
                    normalized_answer = normalizer.normalize_hash_answer(question.answer)
                    if not any([normalized_stem, normalized_options, normalized_answer]):
                        skipped += 1
                        continue
                    question_hash = normalizer.build_question_hash(
                        stem,
                        question.options,
                        question.answer,
                    )
                    if apply:
                        if question.question_hash:
                            skipped += 1
                            continue
                        question.question_hash = question_hash
                    updated += 1
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    print(f"[ERROR] question_id={question.id} {exc}")

            if apply:
                await db.commit()
            else:
                await db.rollback()

            print(
                f"batch last_id={last_id} scanned={scanned} "
                f"{'updated' if apply else 'would_update'}={updated} skipped={skipped} errors={errors}"
            )

            if limit is not None and scanned >= limit:
                break

    return {"scanned": scanned, "updated": updated, "skipped": skipped, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 questions.question_hash")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只统计不写入")
    mode.add_argument("--apply", action="store_true", help="实际写入 question_hash")
    parser.add_argument("--batch-size", type=int, default=500, help="每批处理数量")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描数量")
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size 必须大于 0")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit 必须大于 0")

    if args.apply:
        print("=== APPLY 模式：将只填充空 question_hash，不覆盖已有值 ===")
    else:
        print("=== DRY RUN 模式：只统计，不写入数据库 ===")

    stats = asyncio.run(
        backfill_question_hash(
            apply=args.apply,
            batch_size=args.batch_size,
            limit=args.limit,
        )
    )
    label = "updated" if args.apply else "would_update"
    print(
        f"完成：scanned={stats['scanned']} {label}={stats['updated']} "
        f"skipped={stats['skipped']} errors={stats['errors']}"
    )


if __name__ == "__main__":
    main()
