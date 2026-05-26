"""修复数据库中题目内容重复的脚本。

检测并修复 questions 表中 content.text、answer、analysis 字段出现
"同一段文本被上下拼接两次"的情况。

运行方式：
    cd backend
    python scripts/fix_duplicate_content.py [--dry-run]
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.question import Question


def _deduplicate_text(text: str) -> str:
    """去除文本中完全重复的上下拼接段落。

    "abc\nabc" → "abc"
    "abc\ndef" → "abc\ndef"  (不处理)
    "abc\n\nabc" → "abc"    (空行分隔的重复段落)
    """
    if not text:
        return text

    # 按行去重（保留顺序，仅去除相邻重复）
    lines = text.split("\n")
    deduped_lines = []
    for i, line in enumerate(lines):
        if i == 0 or line.strip() != lines[i - 1].strip():
            deduped_lines.append(line)
    result = "\n".join(deduped_lines)

    # 检查整段文本是否是自身的2倍重复
    # "abc\ndef\nabc\ndef" → "abc\ndef"
    half = len(result) // 2
    if half > 0 and result[:half] == result[half:]:
        return result[:half].rstrip("\n")
    if half > 0 and result[:half].strip() == result[half:].strip():
        return result[:half].strip()

    return result.strip() if result != text else result


def _is_duplicated(text: str) -> bool:
    if not text:
        return False
    deduped = _deduplicate_text(text)
    return deduped != text and deduped != text.strip()


async def fix_duplicate_content(dry_run: bool = True):
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    fixed = 0
    checked = 0

    async with async_session() as db:
        result = await db.execute(select(Question).where(Question.is_active == True))
        questions = list(result.scalars().all())

        print(f"检查题目数量: {len(questions)}")

        for q in questions:
            checked += 1
            changed = False
            updates = {}

            # 检查 content.text (题干)
            content = q.content or {}
            stem_text = content.get("text", "")
            if _is_duplicated(stem_text):
                fixed_stem = _deduplicate_text(stem_text)
                print(f"  [题目 {q.id}] content.text 重复:")
                print(f"    原始: {repr(stem_text[:80])}")
                print(f"    修复: {repr(fixed_stem[:80])}")
                if not dry_run:
                    new_content = {**content, "text": fixed_stem}
                    if "segments" in new_content:
                        del new_content["segments"]
                    q.content = new_content
                changed = True

            # 检查 answer
            if _is_duplicated(q.answer):
                fixed_answer = _deduplicate_text(q.answer)
                print(f"  [题目 {q.id}] answer 重复:")
                print(f"    原始: {repr(q.answer[:80])}")
                print(f"    修复: {repr(fixed_answer[:80])}")
                if not dry_run:
                    q.answer = fixed_answer
                changed = True

            # 检查 analysis
            if q.analysis and _is_duplicated(q.analysis):
                fixed_analysis = _deduplicate_text(q.analysis)
                print(f"  [题目 {q.id}] analysis 重复:")
                print(f"    原始: {repr(q.analysis[:80])}")
                print(f"    修复: {repr(fixed_analysis[:80])}")
                if not dry_run:
                    q.analysis = fixed_analysis
                changed = True

            # 检查 options（每个选项文本）
            options = q.options or {}
            options_changed = False
            new_options = {}
            for k, v in options.items():
                if isinstance(v, str) and _is_duplicated(v):
                    fixed_v = _deduplicate_text(v)
                    print(f"  [题目 {q.id}] options[{k}] 重复:")
                    print(f"    原始: {repr(v[:60])}")
                    print(f"    修复: {repr(fixed_v[:60])}")
                    new_options[k] = fixed_v
                    options_changed = True
                    changed = True
                else:
                    new_options[k] = v
            if options_changed and not dry_run:
                q.options = new_options

            if changed:
                fixed += 1

        if not dry_run and fixed > 0:
            await db.commit()
            print(f"\n已修复 {fixed} 道题目（共检查 {checked} 道）")
        else:
            print(f"\n{'[DRY RUN] ' if dry_run else ''}发现需修复 {fixed} 道题目（共检查 {checked} 道）")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复题目内容重复")
    parser.add_argument("--dry-run", action="store_true", default=True, help="只检查不修复")
    parser.add_argument("--fix", action="store_true", help="实际执行修复")
    args = parser.parse_args()

    dry_run = not args.fix
    if dry_run:
        print("=== DRY RUN 模式（仅检查，不修改数据库）===")
        print("加 --fix 参数执行实际修复")
    else:
        print("=== 修复模式（将修改数据库）===")

    asyncio.run(fix_duplicate_content(dry_run=dry_run))
