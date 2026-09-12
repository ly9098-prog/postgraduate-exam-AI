#!/usr/bin/env python3
"""Apply trial-audit fixes to the cs_ds pages 1-10 question_imports rows.

Uses the project's own services:
  - admin_import_service.update_import_question  (edit existing rows)
  - review_service.submit_to_review               (create missing rows)

Usage:
    .venv/bin/python /abs/fix_trial_audit.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("PDF_MAX_FILE_BYTES", str(200 * 1024 * 1024))


async def main():
    from sqlalchemy import select

    from app.core.database import async_session
    from app.features.review_service import submit_to_review
    from app.schemas.admin_imports import AdminImportQuestionUpdateRequest
    from app.services.admin_import_service import update_import_question
    from app.models.question_import import QuestionImport

    fixes_log = []

    async with async_session() as db:
        rows = (await db.execute(
            select(QuestionImport).where(
                QuestionImport.source_file == "cs_ds.pdf",
                QuestionImport.status == "pending",
            ).order_by(QuestionImport.source_page_start)
        )).scalars().all()
        by_page = {}
        for r in rows:
            for p in range(r.source_page_start or 1, (r.source_page_end or r.source_page_start or 1) + 1):
                by_page.setdefault(p, r)
        print(f"loaded {len(rows)} rows")

        # ── Fix 1: page 1 (id={by_page[1].id if 1 in by_page else '?'}) — wrong options ──
        if 1 in by_page:
            r = by_page[1]
            old_opts = dict(r.parsed_options or {})
            data = AdminImportQuestionUpdateRequest(
                stem="微型计算机的发展以()技术为标志。",
                options={"A": "操作系统", "B": "微处理器", "C": "磁盘", "D": "软件"},
                source_page_start=1,
                source_page_end=1,
                source_question_no="1",
            )
            await update_import_question(db, r.id, data)
            fixes_log.append({"database_id": r.id, "field": "parsed_options+stem+page_end",
                              "value_before": json.dumps({"stem": r.parsed_content.get("text") if r.parsed_content else None,
                                                          "options": old_opts}, ensure_ascii=False),
                              "value_after": json.dumps({"options": {"A": "操作系统", "B": "微处理器", "C": "磁盘", "D": "软件"}}, ensure_ascii=False),
                              "reason": "page1 Q1 got page2's options (frozen-option cross-page contamination); restore correct options + page_end=1",
                              "source_evidence": "backend-ocr/remote/p-0001.txt", "edit_api": "update_import_question"})
            print("fixed page 1:", r.id)

        # ── Fix 2: page 4 stem "(\n)" cleanup ──
        if 4 in by_page:
            r = by_page[4]
            data = AdminImportQuestionUpdateRequest(stem="下列()是冯诺依曼机工作方式的基本特点。")
            await update_import_question(db, r.id, data)
            fixes_log.append({"database_id": r.id, "field": "stem", "value_before": "(\n) split", "value_after": "()",
                              "reason": "normalize split parens", "source_evidence": "backend-ocr/remote/p-0004.txt", "edit_api": "update_import_question"})

        # ── Fix 3: page 6 option C "MDR." → "MDR" ──
        if 6 in by_page:
            r = by_page[6]
            opts = dict(r.parsed_options or {})
            opts["C"] = "MDR"
            data = AdminImportQuestionUpdateRequest(options=opts,
                                                    stem="存放当前执行指令的寄存器是()。")
            await update_import_question(db, r.id, data)
            fixes_log.append({"database_id": r.id, "field": "options.C", "value_before": "MDR.", "value_after": "MDR",
                              "reason": "OCR trailing period", "source_evidence": "backend-ocr/remote/p-0006.txt", "edit_api": "update_import_question"})

        # ── Fix 4: page 7 stem cleanup ──
        if 7 in by_page:
            r = by_page[7]
            data = AdminImportQuestionUpdateRequest(stem="在CPU中，跟踪下一条要执行的指令的地址的寄存器是()。")
            await update_import_question(db, r.id, data)
            fixes_log.append({"database_id": r.id, "field": "stem", "value_before": "reg space", "value_after": "()",
                              "reason": "normalize paren spacing", "source_evidence": "backend-ocr/remote/p-0007.txt", "edit_api": "update_import_question"})

        # ── Fix 5: page 8 page_end → 8 ──
        if 8 in by_page:
            r = by_page[8]
            data = AdminImportQuestionUpdateRequest(source_page_start=8, source_page_end=8)
            await update_import_question(db, r.id, data)
            fixes_log.append({"database_id": r.id, "field": "page_end", "value_before": 9, "value_after": 8,
                              "reason": "Q7 is page 8 only; Q8(page9) is separate", "source_evidence": "backend-ocr/remote/p-0008.txt", "edit_api": "update_import_question"})

        # ── Fix 6: page 10 stem cleanup ──
        if 10 in by_page:
            r = by_page[10]
            data = AdminImportQuestionUpdateRequest(stem="在运算器中，不包含()。")
            await update_import_question(db, r.id, data)
            fixes_log.append({"database_id": r.id, "field": "stem", "value_before": "[公众号:风中易小生]", "value_after": "clean",
                              "reason": "watermark remnant", "source_evidence": "backend-ocr/remote/p-0010.txt", "edit_api": "update_import_question"})

        # ── Create page 9 Q8 (missing) via submit_to_review ──
        if 9 not in by_page:
            result = await submit_to_review(
                db,
                [{
                    "stem": "MAR和MDR的位数分别为()",
                    "options": [
                        {"key": "A", "text": "地址码长度、存储字长"},
                        {"key": "B", "text": "存储字长、存储字长"},
                        {"key": "C", "text": "地址码长度、地址码长度"},
                        {"key": "D", "text": "存储字长、地址码长度"},
                    ],
                    "question_type": "single_choice",
                    "page_start": 9,
                    "page_end": 9,
                    "source_question_no": "8",
                    "raw_question_text": "8.MAR和MDR的位数分别为(\n)\nA.地址码长度、存储字长\nB.存储字长、存储字长\nC.地址码长度、地址码长度\nD.存储字长、地址码长度",
                    "confidence_score": 0.9,
                    "is_valid": True,
                }],
                {"source_type": "pdf", "source_file": "cs_ds.pdf", "subject_id": 8},
                skip_existing=True,
            )
            fixes_log.append({"database_id": None, "field": "create",
                              "value_before": None, "value_after": f"created Q8 page9 batch={result.get('batch_id')}",
                              "reason": "pipeline dropped Q8 (OCR misread 8. as B.)", "source_evidence": "backend-ocr/remote/p-0009.txt",
                              "edit_api": "review_service.submit_to_review"})
            print("created page 9 Q8:", result)
        else:
            print("page 9 already exists")

        await db.commit()

    with open("/home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import/audit/auto-fixes.jsonl", "w") as f:
        for item in fixes_log:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"logged {len(fixes_log)} fixes")


if __name__ == "__main__":
    asyncio.run(main())
