#!/usr/bin/env python3
"""Apply audit fixes from a JSON file using the project's own services.

fixes.json structure:
{
  "fix": [
    {"id": 600, "stem": "...", "options": {"A":"256",...}, "page_start":12, "page_end":12,
     "source_question_no":"11"}
  ],
  "create": [
    {"stem": "...", "options": [{"key":"A","text":"..."}], "page_start":13, "page_end":13,
     "source_question_no":"12", "raw_question_text":"..."}
  ]
}
Run: .venv/bin/python /abs/apply_fixes.py /abs/fixes_11_35.json
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

LOG = "/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import/audit/auto-fixes.jsonl"


async def main():
    fixes_path = sys.argv[1]
    with open(fixes_path) as f:
        fixes = json.load(f)

    from app.core.database import async_session
    from app.features.review_service import submit_to_review
    from app.schemas.admin_imports import AdminImportQuestionUpdateRequest
    from app.services.admin_import_service import update_import_question

    log_lines = []
    async with async_session() as db:
        for item in fixes.get("fix", []):
            clean = {k: v for k, v in item.items() if k != "id"}
            # schema uses source_page_start/source_page_end, not page_start/page_end
            if "page_start" in clean and "source_page_start" not in clean:
                clean["source_page_start"] = clean.pop("page_start")
            if "page_end" in clean and "source_page_end" not in clean:
                clean["source_page_end"] = clean.pop("page_end")
            data = AdminImportQuestionUpdateRequest(**clean)
            await update_import_question(db, item["id"], data)
            log_lines.append({"database_id": item["id"], "field": "audit_fix",
                              "value_before": None, "value_after": json.dumps(item, ensure_ascii=False),
                              "reason": item.get("reason", "audit fix"),
                              "source_evidence": item.get("evidence", ""),
                              "edit_api": "update_import_question"})
            print(f"fixed id={item['id']}")

        for item in fixes.get("create", []):
            q = {
                "stem": item["stem"],
                "options": item["options"],
                "question_type": item.get("question_type", "single_choice"),
                "page_start": item["page_start"],
                "page_end": item["page_end"],
                "source_question_no": item.get("source_question_no"),
                "raw_question_text": item.get("raw_question_text", item["stem"]),
                "confidence_score": 0.9,
                "is_valid": True,
            }
            result = await submit_to_review(db, [q],
                                            {"source_type": "pdf", "source_file": "cs_ds.pdf", "subject_id": 8},
                                            skip_existing=True)
            new_id = (result.get("items") or [{}])[0].get("id")
            log_lines.append({"database_id": new_id, "field": "create",
                              "value_before": None, "value_after": json.dumps(item, ensure_ascii=False),
                              "reason": item.get("reason", "pipeline dropped page"),
                              "source_evidence": item.get("evidence", ""),
                              "edit_api": "review_service.submit_to_review"})
            print(f"created page={item['page_start']} id={new_id} batch={result.get('batch_id')}")

        await db.commit()

    with open(LOG, "a") as f:
        for line in log_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    print(f"logged {len(log_lines)} fixes")


if __name__ == "__main__":
    asyncio.run(main())
