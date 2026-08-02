"""Dry-run: 将全部 pending cs_ds.pdf question_imports 走官方发布管线，不提交。

用于发布前验证：统计 publish/duplicate/failed 及失败原因。
事务末尾 rollback，不写库。
Usage: 从 backend/ 运行，PYTHONPATH=backend。
"""
import asyncio
import os
import sys
from collections import Counter

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.question_import import QuestionImport  # noqa: E402
from app.features.question_publish_service import publish_single_question  # noqa: E402


async def main():
    async with async_session() as db:
        stmt = (
            select(QuestionImport)
            .where(
                QuestionImport.source_file == "cs_ds.pdf",
                QuestionImport.status == "pending",
            )
            .order_by(QuestionImport.id)
        )
        rows = (await db.execute(stmt)).scalars().all()
        print(f"pending cs_ds imports: {len(rows)}")
        print("subject_id dist:", dict(Counter(q.subject_id for q in rows)))
        print("question_type dist:", dict(Counter(q.question_type for q in rows)))

        stats = {"published": 0, "duplicate": 0, "failed": 0}
        failed: list[tuple[int, str]] = []
        duplicated: list[tuple[int, int, str]] = []

        for qi in rows:
            qi.status = "approved"
            qi.reviewed_by = 1
            qi.reviewed_at = None
            try:
                res = await publish_single_question(db, qi)
            except Exception as exc:  # noqa: BLE001
                stats["failed"] += 1
                failed.append((qi.id, f"EXC: {type(exc).__name__}: {exc}"))
                continue
            st = res["status"]
            if st == "published":
                stats["published"] += 1
            elif st == "duplicate":
                stats["duplicate"] += 1
                duplicated.append((qi.id, res.get("question_id"), res.get("reason")))
            else:
                stats["failed"] += 1
                failed.append((qi.id, res.get("reason")))

        print("stats:", stats)
        print("duplicate count:", len(duplicated))
        for did in duplicated[:15]:
            print("  DUP", did)
        print("failed count:", len(failed))
        for fid, reason in failed[:40]:
            print("  FAILED", fid, "|", reason)

        await db.rollback()
        print("rolled back (dry run, no changes persisted)")


if __name__ == "__main__":
    asyncio.run(main())
