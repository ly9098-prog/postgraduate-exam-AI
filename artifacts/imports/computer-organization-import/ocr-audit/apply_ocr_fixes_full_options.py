#!/usr/bin/env python3
"""Follow-up: re-set FULL options for the 14 questions whose partial options update
wiped the unchanged keys (update_import_question replaces the whole options dict).
"""
import json
import os
import sys

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
BASE = "/home/lmh/projects/postgraduate-ai"

fixes = [
    {"id": 603, "options": {"A": "II、III", "B": "II、IV", "C": "I、II", "D": "I、V"}},
    {"id": 684, "options": {"A": "I和II", "B": "III", "C": "IV", "D": "V和VI"}},
    {"id": 694, "options": {"A": "I、III", "B": "仅II", "C": "只有III", "D": "I、II、III"}},
    {"id": 781, "options": {"A": "I、III", "B": "II、III", "C": "II、IV", "D": "只有III"}},
    {"id": 848, "options": {"A": "I、III、IV", "B": "I、II、III", "C": "I、II、IV", "D": "II、III、IV"}},
    {"id": 879, "options": {"A": "((PC)+A)", "B": "((X)+A)", "C": "(X)+(A)", "D": "(X)+A"}},
    {"id": 885, "options": {"A": "2000H,2042H", "B": "2002H,2040H", "C": "2002H,2042H", "D": "2000H,2040H"}},
    {"id": 978, "options": {"A": "仅I、II", "B": "仅I、IV", "C": "仅II、IV", "D": "仅III、IV"}},
    {"id": 1009, "options": {"A": "仅I、II", "B": "仅I、III", "C": "仅II、IV", "D": "仅III、IV"}},
    {"id": 1017, "options": {"A": "I", "B": "I和II", "C": "I和III", "D": "I、II和III"}},
    {"id": 1037, "options": {"A": "PCI、CRT、USB、EISA", "B": "ISA、CPI、VESA.EISA",
                             "C": "ISA、SCSI、RAM、MIPS", "D": "ISA、EISA、PCI、PCI-Express"}},
    {"id": 1082, "options": {"A": "I、II和IV", "B": "I和V", "C": "I、II和V", "D": "I、III和V"}},
    {"id": 1085, "options": {"A": "仅I", "B": "仅III", "C": "I、III", "D": "II、III"}},
    {"id": 1120, "options": {"A": "仅I、II", "B": "仅I、III", "C": "仅II、III", "D": "I、II和III"}},
]

LOG = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit/fixes-applied.jsonl")


async def main():
    from app.core.database import async_session
    from app.schemas.admin_imports import AdminImportQuestionUpdateRequest
    from app.services.admin_import_service import update_import_question

    async with async_session() as db:
        for item in fixes:
            data = AdminImportQuestionUpdateRequest(options=item["options"],
                                                    review_note="补全被部分更新清空的选项")
            await update_import_question(db, item["id"], data)
            print("refixed id=%d" % item["id"])
        await db.commit()
    with open(LOG, "a", encoding="utf-8") as f:
        for item in fixes:
            f.write(json.dumps({"database_id": item["id"], "field": "ocr_fix",
                                "value_after": json.dumps(item, ensure_ascii=False),
                                "reason": "补全被部分更新清空的选项",
                                "edit_api": "update_import_question"}, ensure_ascii=False) + "\n")
    print("done")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
