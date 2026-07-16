"""本地→云端增量同步脚本。

从本地 SQLite 导出 questions 和 tags，POST 到云端 /api/v1/sync/import。

用法：
    cd backend
    python -m scripts.sync_to_cloud --api-url https://server.example.com --token <admin_jwt>
    python -m scripts.sync_to_cloud --dry-run
    python -m scripts.sync_to_cloud --since 2025-06-01T00:00:00
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.models.admin import Subject  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.tag import Tag  # noqa: E402

LAST_SYNC_FILE = ROOT / ".last_sync"


def _serialize_question(q: Question) -> dict:
    subject_code = None
    if q.subject_ref:
        subject_code = q.subject_ref.code
    elif q.subject_id:
        subject_code = str(q.subject_id)
    return {
        "sync_uuid": q.sync_uuid,
        "sync_version": q.sync_version,
        "subject": subject_code,
        "subject_id": q.subject_id,
        "question_type": q.question_type,
        "content": q.content,
        "options": q.options,
        "answer": q.answer,
        "question_hash": q.question_hash,
        "analysis": q.analysis,
        "knowledge_points": q.knowledge_points,
        "difficulty": q.difficulty,
        "source": q.source,
        "source_type": q.source_type,
        "source_file": q.source_file,
        "import_batch_id": q.import_batch_id,
        "raw_content": q.raw_content,
        "image_url": q.image_url,
        "year": q.year,
        "review_status": q.review_status,
        "is_active": q.is_active,
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "updated_at": q.updated_at.isoformat() if q.updated_at else None,
    }


def _serialize_tag(t: Tag) -> dict:
    return {
        "sync_uuid": t.sync_uuid,
        "name": t.name,
        "subject": t.subject,
        "parent_id": t.parent_id,
        "sort_order": t.sort_order,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


async def export_package(since: datetime | None = None) -> dict:
    async with async_session() as db:
        q_query = select(Question).options(joinedload(Question.subject_ref)).where(Question.sync_uuid.isnot(None))
        if since:
            q_query = q_query.where(Question.updated_at > since)
        questions = (await db.execute(q_query)).scalars().all()

        t_query = select(Tag).where(Tag.sync_uuid.isnot(None))
        if since:
            t_query = t_query.where(Tag.created_at > since)
        tags = (await db.execute(t_query)).scalars().all()

    q_list = [_serialize_question(q) for q in questions]
    t_list = [_serialize_tag(t) for t in tags]

    payload_for_hash = json.dumps({"questions": q_list, "tags": t_list}, sort_keys=True, ensure_ascii=False)
    checksum = hashlib.sha256(payload_for_hash.encode()).hexdigest()

    return {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_env": "local",
        "questions": q_list,
        "tags": t_list,
        "manifest": {
            "question_count": len(q_list),
            "tag_count": len(t_list),
            "checksum": checksum,
        },
    }


async def upload(package: dict, api_url: str, token: str) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{api_url.rstrip('/')}/api/v1/sync/import",
            json=package,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code != 200:
            print(f"ERROR: 服务器返回 {resp.status_code}: {resp.text}")
            sys.exit(1)
        return resp.json()


def _read_last_sync() -> datetime | None:
    if LAST_SYNC_FILE.exists():
        text = LAST_SYNC_FILE.read_text().strip()
        if text:
            return datetime.fromisoformat(text)
    return None


def _save_last_sync(ts: datetime) -> None:
    LAST_SYNC_FILE.write_text(ts.isoformat())


async def run(args: argparse.Namespace):
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since)
    elif not args.full:
        since = _read_last_sync()

    if since:
        print(f"增量导出：仅导出 {since.isoformat()} 之后更新的数据")
    else:
        print("全量导出：导出所有带 sync_uuid 的数据")

    package = await export_package(since=since)
    q_count = package["manifest"]["question_count"]
    t_count = package["manifest"]["tag_count"]
    print(f"导出完成：{q_count} 道题目, {t_count} 个标签")

    if args.dry_run:
        out_path = ROOT / "sync_package.json"
        out_path.write_text(json.dumps(package, ensure_ascii=False, indent=2))
        print(f"Dry-run 模式，已保存到 {out_path}")
        return

    if not args.api_url or not args.token:
        print("ERROR: 非 dry-run 模式需要 --api-url 和 --token 参数")
        sys.exit(1)

    if q_count == 0 and t_count == 0:
        print("无数据需要同步，跳过上传")
        return

    print(f"上传到 {args.api_url} ...")
    result = await upload(package, args.api_url, args.token)

    print("\n===== 同步报告 =====")
    print(f"  成功: {result.get('success')}")
    print(f"  新增题目: {result.get('questions_new', 0)}")
    print(f"  更新题目: {result.get('questions_updated', 0)}")
    print(f"  跳过题目: {result.get('questions_skipped', 0)}")
    print(f"  冲突题目: {result.get('questions_conflict', 0)}")
    print(f"  去重题目: {result.get('questions_deduped', 0)}")
    print(f"  新增标签: {result.get('tags_new', 0)}")
    print(f"  跳过标签: {result.get('tags_skipped', 0)}")

    if result.get("conflicts"):
        print(f"\n  冲突详情 ({len(result['conflicts'])} 条):")
        for c in result["conflicts"][:10]:
            print(f"    - {c['sync_uuid']}: {c['reason']}")

    if result.get("success"):
        _save_last_sync(datetime.now(timezone.utc))
        print(f"\n已保存同步时间戳到 {LAST_SYNC_FILE}")


def main():
    parser = argparse.ArgumentParser(description="本地→云端增量同步")
    parser.add_argument("--api-url", help="云端 API 地址 (如 https://server.example.com)")
    parser.add_argument("--token", help="Admin JWT token")
    parser.add_argument("--since", help="仅导出此时间之后的数据 (ISO 格式)")
    parser.add_argument("--full", action="store_true", help="全量导出，忽略 .last_sync")
    parser.add_argument("--dry-run", action="store_true", help="仅导出 JSON 文件，不上传")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
