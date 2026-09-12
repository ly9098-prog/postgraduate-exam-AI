#!/usr/bin/env python3
"""Apply ocr-audit/fixes.json via update_import_question (project business API).

Run: .venv/bin/python /abs/apply_ocr_fixes.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

BASE = "/home/lmh/projects/postgraduate-ai"
FIXES = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit/fixes.json")
LOG = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit/fixes-applied.jsonl")


async def main():
    with open(FIXES) as f:
        fixes = json.load(f)

    from app.core.database import async_session
    from app.schemas.admin_imports import AdminImportQuestionUpdateRequest
    from app.services.admin_import_service import update_import_question

    log_lines = []
    async with async_session() as db:
        for item in fixes:
            clean = {k: v for k, v in item.items() if k != "id"}
            data = AdminImportQuestionUpdateRequest(**clean)
            await update_import_question(db, item["id"], data)
            log_lines.append(json.dumps({
                "database_id": item["id"],
                "field": "ocr_fix",
                "value_after": json.dumps(item, ensure_ascii=False),
                "reason": item.get("review_note", "ocr fix"),
                "edit_api": "update_import_question",
            }, ensure_ascii=False))
            print(f"fixed id={item['id']}")
        await db.commit()

    with open(LOG, "a", encoding="utf-8") as f:
        for line in log_lines:
            f.write(line + "\n")
    print(f"applied {len(fixes)} fixes; log -> {LOG}")


if __name__ == "__main__":
    asyncio.run(main())
