"""回填已有 questions 和 tags 的 sync_uuid。

用法：
    cd backend
    python -m scripts.backfill_sync_uuid --dry-run
    python -m scripts.backfill_sync_uuid --apply --batch-size 500
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, update  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.tag import Tag  # noqa: E402


async def backfill_sync_uuid(*, apply: bool, batch_size: int) -> dict[str, int]:
    stats = {"questions_updated": 0, "tags_updated": 0}

    async with async_session() as db:
        # --- Questions ---
        last_id = 0
        while True:
            query = (
                select(Question.id)
                .where(Question.id > last_id, Question.sync_uuid.is_(None))
                .order_by(Question.id)
                .limit(batch_size)
            )
            rows = (await db.execute(query)).scalars().all()
            if not rows:
                break
            for qid in rows:
                if apply:
                    await db.execute(
                        update(Question)
                        .where(Question.id == qid)
                        .values(sync_uuid=str(uuid4()))
                    )
                stats["questions_updated"] += 1
                last_id = qid
            if apply:
                await db.commit()

        # --- Tags ---
        last_id = 0
        while True:
            query = (
                select(Tag.id)
                .where(Tag.id > last_id, Tag.sync_uuid.is_(None))
                .order_by(Tag.id)
                .limit(batch_size)
            )
            rows = (await db.execute(query)).scalars().all()
            if not rows:
                break
            for tid in rows:
                if apply:
                    await db.execute(
                        update(Tag)
                        .where(Tag.id == tid)
                        .values(sync_uuid=str(uuid4()))
                    )
                stats["tags_updated"] += 1
                last_id = tid
            if apply:
                await db.commit()

    return stats


def main():
    parser = argparse.ArgumentParser(description="回填 sync_uuid")
    parser.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不写入")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] 开始回填 sync_uuid (batch_size={args.batch_size})")

    stats = asyncio.run(backfill_sync_uuid(apply=apply, batch_size=args.batch_size))

    print(f"Questions: {stats['questions_updated']} 条需要回填")
    print(f"Tags: {stats['tags_updated']} 条需要回填")
    if not apply:
        print("（dry-run 模式，未实际写入。加 --apply 执行写入）")


if __name__ == "__main__":
    main()
