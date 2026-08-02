"""将 cs_ds.pdf 全部 524 条 pending question_imports 发布到本地 questions 表。

走官方发布路径（publish_single_question），并已修复三处共享归一化缺陷保证保真：
  1. _is_noise_line 全同数字串不再当噪声丢弃（11111111/00000000 选项）
  2. deduplicate_repeated_text 整体折叠对短对称 token 加门槛（不再折叠 10101010 等）
  3. clean_text 题号剥离加 (?!\\d)，小数/二进制选项前导数字不再被剥；罗马枚举不再拆行

流程：备份受影响行 JSONL → 逐条 approved + publish_single_question → commit → 校验。
任何失败行保持 pending 并报告（预期 0）。

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。
"""
import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from sqlalchemy import func, select, text  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.question_import import QuestionImport  # noqa: E402
from app.features.question_publish_service import publish_single_question  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_524_pre_publish_20260802.jsonl")
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/publish-cs-ds.jsonl")


def backup_pending_sync():
    """同步备份 cs_ds pending 行（发布前状态）。"""
    conn = sqlite3.connect("postgraduate.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM question_imports WHERE source_file='cs_ds.pdf' AND status='pending' ORDER BY id"
    )
    rows = cur.fetchall()
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    conn.close()
    return len(rows)


async def main():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
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

        # ── 备份（发布前状态，同步 SQLite）──
        n_backed = backup_pending_sync()
        print(f"backup written: {BACKUP} ({n_backed} rows)")

        stats = {"published": 0, "duplicate": 0, "failed": 0}
        failed: list[tuple[int, str]] = []
        changes = []

        for qi in rows:
            qi.status = "approved"
            qi.reject_reason = None
            qi.reviewed_by = 1
            qi.reviewed_at = now
            try:
                res = await publish_single_question(db, qi)
            except Exception as exc:  # noqa: BLE001
                stats["failed"] += 1
                failed.append((qi.id, f"EXC: {type(exc).__name__}: {exc}"))
                continue
            st = res["status"]
            if st == "published":
                stats["published"] += 1
                changes.append({"id": qi.id, "status": "published", "question_id": res.get("question_id")})
            elif st == "duplicate":
                stats["duplicate"] += 1
                changes.append({"id": qi.id, "status": "duplicate", "question_id": res.get("question_id")})
            else:
                stats["failed"] += 1
                failed.append((qi.id, res.get("reason")))
                qi.status = "pending"
                qi.reviewed_by = None
                qi.reviewed_at = None

        await db.commit()
        print("stats:", stats)
        for fid, reason in failed[:20]:
            print("  FAILED", fid, "|", reason)

        with open(OUT_LOG, "w", encoding="utf-8") as f:
            for ch in changes:
                f.write(json.dumps(ch, ensure_ascii=False) + "\n")
        print(f"changes logged: {len(changes)} -> {OUT_LOG}")

        # ── 校验 ──
        from sqlalchemy import func, text
        q_total = await db.execute(text("SELECT COUNT(*) FROM questions WHERE source_file='cs_ds.pdf'"))
        print("questions cs_ds total:", q_total.scalar())
        q_co = await db.execute(text("SELECT COUNT(*) FROM questions WHERE source_file='cs_ds.pdf' AND subject_id=8"))
        print("  subject_id=8:", q_co.scalar())
        q_su = await db.execute(text("SELECT COUNT(*) FROM questions WHERE source_file='cs_ds.pdf' AND sync_uuid IS NOT NULL"))
        print("  sync_uuid non-null:", q_su.scalar())
        pending = await db.execute(
            select(func.count()).select_from(QuestionImport).where(
                QuestionImport.source_file == "cs_ds.pdf",
                QuestionImport.status == "pending",
            )
        )
        print("  remaining pending imports:", pending.scalar())


if __name__ == "__main__":
    asyncio.run(main())
