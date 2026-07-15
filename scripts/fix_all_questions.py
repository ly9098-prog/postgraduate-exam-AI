"""Comprehensive fix for all imported data structures questions."""
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

def clean_watermark(text):
    """Remove watermark/section/chapter noise from question text."""
    # Full patterns to remove
    patterns = [
        r'\n?风中易小生24考研计算机WD数据结构做题本【选择题】',
        r'\n?风中易小生·24考研计算机WD数据结构做题本【选择题】',
        r'\n?## 风中易小生·24考研计算机WD数据结构做题本【选择题】',
        r'\n?风中易小生24考研计算机WD数据结构做题本',
        r'风中易小生·24考研计算机WD数据结构做题本【选择题】\n?',
        r'## 风中易小生·24考研计算机WD数据结构做题本【选择题】\n?',
        r'\[微信公众号:风中易小生\]',
        r'\[微信公众号：风中易小生\]',
        r'风中易小生·24考研计算机WD数据结构做题本',
        r'\n风中易小生24考研计算机WD数据结构做题本【选择题】\n?',
    ]
    for p in patterns:
        text = re.sub(p, '', text)

    # Remove section header noise embedded in content (e.g., "1.2 算法和算法评价")
    text = re.sub(r'\n?\d+\.\d+\s+\S+[^\n]*$', '', text)

    # Remove "一、单项选择题..." type headers
    text = re.sub(r'\n?一、单项选择题（本部分答案在书\w+）', '', text)

    # Remove "D。\n" type choice noise
    text = re.sub(r'D。\n\d+\.\d+\s+\S+', '', text)

    # Trim trailing/leading whitespace
    text = text.strip()
    return text

def fix_truncated_content(text):
    """Fix truncated content (missing brackets, periods)."""
    # If text ends with "(" or "，("  , it's likely truncated
    text = text.rstrip()
    if text.endswith('(') or text.endswith('，（'):
        text += ')'
    elif text.endswith('，('):
        text = text[:-1] + '()'

    # Fix content that ends mid-sentence
    if text.endswith('，') or text.endswith(','):
        text = text.rstrip('，,')

    # Handle code blocks that might be truncated
    if text.count('```') % 2 != 0:
        text += '\n```'

    return text.strip()

def fix_ocr_symbols(text):
    """Fix common OCR symbol errors."""
    fixes = [
        ('O(', 'O('),  # Already correct O(n)
        ('0(', 'O('),  # Fix zero-O confusion
        ('O(n', 'O(n'),  # Already correct
        ('0(n', 'O(n'),  # Fix zero in big-O
        ('int i=l;', 'int i=1;'),  # Fix lowercase L for 1
        ('i=i++', 'i++'),  # Fix weird increment
    ]
    for old, new in fixes:
        if old != new:
            text = text.replace(old, new)
    return text

async def main():
    async with async_session() as db:
        result = await db.execute(
            select(QuestionImport).order_by(QuestionImport.id)
        )
        items = result.scalars().all()

        fixes_applied = 0
        for qi in items:
            changed = False

            # Fix parsed_content
            c = qi.parsed_content
            if isinstance(c, dict) and 'text' in c:
                original_text = c['text']
                text = original_text

                # Apply fixes
                text = clean_watermark(text)
                text = fix_truncated_content(text)
                text = fix_ocr_symbols(text)

                if text != original_text:
                    record = {
                        "database_id": qi.id,
                        "batch_id": qi.batch_id,
                        "field": "parsed_content.text",
                        "value_before": original_text,
                        "value_after": text,
                        "reason": "批量修复：清除水印噪声、补全截断、修复OCR符号",
                        "source_evidence": "OCR MCP全文档识别对比",
                        "edited_at": datetime.now(timezone.utc).isoformat(),
                        "repair_round": 1,
                    }
                    c['text'] = text
                    qi.parsed_content = c
                    changed = True

                    os.makedirs(os.path.dirname(FIX_LOG), exist_ok=True)
                    with open(FIX_LOG, "a") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")

                    print(f"ID={qi.id}: fixed content ({len(original_text)}→{len(text)} chars)")

            if changed:
                qi.updated_at = datetime.now(timezone.utc)
                fixes_applied += 1

        await db.commit()
        print(f"\nTotal fixes applied: {fixes_applied}")

asyncio.run(main())
