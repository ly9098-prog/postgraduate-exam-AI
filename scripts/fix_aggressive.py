"""More aggressive cleanup for remaining watermark and truncation issues."""
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import async_session
from app.models.question_import import QuestionImport
from sqlalchemy import select

ARTIFACTS = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import"
FIX_LOG = os.path.join(ARTIFACTS, "audit", "auto-fixes.jsonl")

def aggressive_clean(text):
    """Remove ALL watermark/section noise aggressively."""
    # Remove anything from "风中易小生" through end of "选择题】"
    text = re.sub(r'[\s]*(##\s*)?风中易小生[^】]*】\s*', '\n', text)

    # Remove [微信公众号:风中易小生]
    text = re.sub(r'\[微信公众号[：:]风中易小生\]\s*', '', text)

    # Remove section headers like "1.2 算法和算法评价"
    text = re.sub(r'\n\d+\.\d+\s+\S+[　-鿿]*\s*', '\n', text)

    # Remove "一、单项选择题（本部分答案在书P\d+）"
    text = re.sub(r'一、单项选择题[^）]*\)\s*', '', text)

    # If there's content after a watermark on the same line, keep only the content
    # that's clearly part of the question (before the watermark)
    # Strategy: split by watermark and keep first part
    parts = re.split(r'(?:风中易小生|做题本|微信公众号)', text)
    if len(parts) > 1:
        # Keep first part (before watermark)
        text = parts[0].strip()

    # Fix remaining issues: text after watermark
    # where the next question text got appended
    # Check for cases like ")some text" at the end
    text = re.sub(r'\n\)[^。]*$', '', text)
    text = re.sub(r'^\)[^。]*\n', '', text)

    # Fix parentheses: ensure questions end with ()
    text = text.rstrip()
    if text.endswith('('):
        text += ')'
    elif text.endswith('，（'):
        text = text[:-1] + '()'

    # Fix i=l to i=1 in code
    text = re.sub(r'\bi=l\b', 'i=1', text)

    # Remove ``` that appear before watermark
    text = re.sub(r'```\s*\n', '\n', text)

    # Clean trailing newlines
    text = text.strip()

    return text

async def main():
    async with async_session() as db:
        result = await db.execute(
            select(QuestionImport).order_by(QuestionImport.id)
        )
        items = result.scalars().all()

        fixes = 0
        for qi in items:
            c = qi.parsed_content
            if not isinstance(c, dict) or 'text' not in c:
                continue

            original = c['text']
            cleaned = aggressive_clean(original)

            # Skip if no change
            if cleaned == original:
                continue

            # Don't make content empty
            if not cleaned.strip():
                print(f"ID={qi.id}: SKIP - cleaning would empty content")
                continue

            c['text'] = cleaned
            qi.parsed_content = c
            qi.updated_at = datetime.now(timezone.utc)
            fixes += 1

            record = {
                "database_id": qi.id,
                "batch_id": qi.batch_id,
                "field": "parsed_content.text",
                "value_before": original,
                "value_after": cleaned,
                "reason": "激进清理：移除所有水印噪声和后续题目文本",
                "source_evidence": "OCR MCP全文档识别",
                "edited_at": datetime.now(timezone.utc).isoformat(),
                "repair_round": 2,
            }
            os.makedirs(os.path.dirname(FIX_LOG), exist_ok=True)
            with open(FIX_LOG, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            print(f"ID={qi.id}: {len(original)}→{len(cleaned)} chars")

        await db.commit()
        print(f"\nFixed: {fixes} questions")

    # Verify
    async with async_session() as db:
        result = await db.execute(
            select(QuestionImport).order_by(QuestionImport.id)
        )
        issues = []
        for qi in result.scalars().all():
            c = qi.parsed_content
            text = c.get('text', '') if isinstance(c, dict) else str(c)
            wm = any(kw in text for kw in ['风中易小生', '做题本', '微信公众号'])
            trunc = text.rstrip().endswith('(') or text.rstrip().endswith('，（')
            empty = not text.strip()
            if wm or trunc or empty:
                issues.append((qi.id, 'WM' if wm else 'TRUNC' if trunc else 'EMPTY'))

        print(f"Remaining issues: {len(issues)}")
        for qid, tag in issues:
            print(f"  ID={qid}: {tag}")

asyncio.run(main())
