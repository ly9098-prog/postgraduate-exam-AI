"""修复历史数据中"存在 WrongQuestion，但不存在对应 ReviewSchedule"的异常情况。

用法：
    cd backend
    python -m scripts.repair_review_schedule_for_wrong_questions --dry-run
    python -m scripts.repair_review_schedule_for_wrong_questions --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.review_scheduler import ReviewSchedule  # noqa: E402
from app.models.wrong_question import WrongQuestion  # noqa: E402


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def repair_review_schedule(*, apply: bool) -> dict[str, int]:
    """修复缺失的 ReviewSchedule 记录。

    Returns:
        dict with keys: scanned, exists, need_repair, created, skipped, errors
    """
    scanned = 0
    exists = 0
    need_repair = 0
    created = 0
    skipped = 0
    errors = 0

    async with async_session() as db:
        # 获取所有 WrongQuestion
        wq_query = select(WrongQuestion).order_by(WrongQuestion.id.asc())
        wq_result = await db.execute(wq_query)
        wrong_questions = list(wq_result.scalars().all())
        scanned = len(wrong_questions)

        print(f"扫描 WrongQuestion 数量: {scanned}")

        for wq in wrong_questions:
            # 检查是否存在对应的 ReviewSchedule
            schedule_query = select(ReviewSchedule).where(
                ReviewSchedule.user_id == wq.user_id,
                ReviewSchedule.question_id == wq.question_id,
            )
            schedule_result = await db.execute(schedule_query)
            existing_schedule = schedule_result.scalar_one_or_none()

            if existing_schedule:
                exists += 1
                continue

            # 不存在，需要创建
            need_repair += 1

            # 获取 Question 信息以回填 subject
            question_query = select(Question).where(Question.id == wq.question_id)
            question_result = await db.execute(question_query)
            question = question_result.scalar_one_or_none()

            if not question:
                print(f"  [跳过] WrongQuestion id={wq.id}, question_id={wq.question_id} 不存在")
                skipped += 1
                continue

            if apply:
                try:
                    new_schedule = ReviewSchedule(
                        user_id=wq.user_id,
                        question_id=wq.question_id,
                        subject=question.subject,
                        interval=1,
                        ease_factor=2.5,
                        repetitions=0,
                        next_review_at=utcnow(),
                        last_reviewed_at=wq.last_review_at,
                        mastered=wq.mastered or False,
                    )
                    db.add(new_schedule)
                    await db.commit()
                    created += 1
                    print(f"  [创建] user_id={wq.user_id}, question_id={wq.question_id}, subject={question.subject}")
                except IntegrityError:
                    await db.rollback()
                    print(f"  [跳过] user_id={wq.user_id}, question_id={wq.question_id} 已存在（并发冲突）")
                    skipped += 1
                except Exception as e:
                    await db.rollback()
                    print(f"  [错误] user_id={wq.user_id}, question_id={wq.question_id}: {e}")
                    errors += 1
            else:
                print(f"  [dry-run] 将创建 user_id={wq.user_id}, question_id={wq.question_id}, subject={question.subject}")

        print(f"\n统计:")
        print(f"  已存在 ReviewSchedule: {exists}")
        print(f"  需要修复: {need_repair}")
        print(f"  实际创建: {created}")
        print(f"  跳过: {skipped}")
        print(f"  错误: {errors}")

    return {
        "scanned": scanned,
        "exists": exists,
        "need_repair": need_repair,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="修复缺失的 ReviewSchedule 记录")
    parser.add_argument("--dry-run", action="store_true", help="仅扫描，不写入数据库")
    parser.add_argument("--apply", action="store_true", help="实际修复数据库")

    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("错误: 必须指定 --dry-run 或 --apply")
        sys.exit(1)

    if args.dry_run and args.apply:
        print("错误: 不能同时指定 --dry-run 和 --apply")
        sys.exit(1)

    apply = args.apply
    mode = "apply" if apply else "dry-run"
    print(f"运行模式: {mode}")
    print("=" * 60)

    result = asyncio.run(repair_review_schedule(apply=apply))

    if result["errors"] > 0:
        print(f"\n警告: 存在 {result['errors']} 个错误，请检查日志")
        sys.exit(1)

    if apply and result["created"] > 0:
        print(f"\n成功创建 {result['created']} 条 ReviewSchedule 记录")
    elif not apply:
        print(f"\ndry-run 完成，将创建 {result['need_repair']} 条记录")

    sys.exit(0)


if __name__ == "__main__":
    main()
