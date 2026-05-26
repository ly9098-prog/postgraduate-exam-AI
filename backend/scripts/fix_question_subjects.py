"""幂等数据修复脚本：根据关键词重新猜测题目 subject，修正历史误分类。

背景：在 _parse_pdf 旧逻辑中，整份 PDF 用 _guess_subject(全文) 一刀切打标
所有题目的 subject。混合 PDF（如 408 题 + 数学题混排）会把所有题贴成
得分最高的那个科目，导致刷题页切到「数学二」时找不到任何题。

本脚本：
1. 遍历 questions 表，对每道题用 stem + analysis 单独 _guess_subject
2. 仅在新猜测结果与现状不同、且置信度高时（min_score=2）才更新
3. 同步把 question_imports 中 status in (published, approved) 的对应记录
   subject 也更新（保持一致）
4. 输出 dry-run 与 apply 两种模式

用法：
    cd backend
    python -m scripts.fix_question_subjects --dry-run   # 只打印不改
    python -m scripts.fix_question_subjects --apply      # 真改
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 让脚本能直接 python 执行也能 -m 执行
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.features.question_pipeline import _guess_subject  # noqa: E402
from app.models.question import Question  # noqa: E402
from app.models.question_import import QuestionImport  # noqa: E402


def _stem_text(content: dict | str | None) -> str:
    if not content:
        return ""
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return content
    if isinstance(content, dict):
        return str(content.get("text") or content.get("stem") or "")
    return ""


async def _scan_questions(db) -> list[tuple[Question, str | None]]:
    """返回 [(question, new_subject)]；new_subject is None 表示无需变更。"""
    result = await db.execute(select(Question))
    questions = list(result.scalars().all())
    candidates: list[tuple[Question, str | None]] = []
    for q in questions:
        text = _stem_text(q.content) + " " + (q.analysis or "")
        guessed = _guess_subject(text, min_score=2)
        if not guessed:
            candidates.append((q, None))
            continue
        # 仅当新猜测的"父科目"与现有不同才视作误分类
        new_root = guessed.split("-")[0]
        old_root = (q.subject or "").split("-")[0]
        if new_root != old_root:
            candidates.append((q, guessed))
        else:
            candidates.append((q, None))
    return candidates


async def _scan_imports(db) -> list[tuple[QuestionImport, str | None]]:
    """同样的逻辑扫 question_imports，但放宽到 min_score=1（pending 题目通常很短）。"""
    result = await db.execute(select(QuestionImport))
    imports = list(result.scalars().all())
    candidates: list[tuple[QuestionImport, str | None]] = []
    for qi in imports:
        text = _stem_text(qi.parsed_content) + " " + (qi.parsed_analysis or "")
        guessed = _guess_subject(text, min_score=1)
        if not guessed:
            candidates.append((qi, None))
            continue
        new_root = guessed.split("-")[0]
        old_root = (qi.subject or "").split("-")[0]
        if new_root != old_root:
            candidates.append((qi, guessed))
        else:
            candidates.append((qi, None))
    return candidates


async def run(apply: bool) -> int:
    async with async_session() as db:
        candidates = await _scan_questions(db)
        import_candidates = await _scan_imports(db)

        print("=== questions 表扫描 ===")
        changed_q = 0
        affected_question_ids: set[int] = set()
        for q, new_subject in candidates:
            if new_subject is None:
                continue
            stem = _stem_text(q.content)[:60]
            print(
                f"  [Q#{q.id}] {q.subject!r:18} → {new_subject!r:18}  stem={stem!r}"
            )
            if apply:
                old = q.subject
                q.subject = new_subject
                affected_question_ids.add(q.id)
                print(f"           applied (was {old!r})")
            changed_q += 1

        print()
        print("=== question_imports 表扫描 ===")
        changed_i = 0
        for qi, new_subject in import_candidates:
            if new_subject is None:
                continue
            # 已被 questions 表行直接更新过的 import 跳过（避免重复）
            if qi.question_id in affected_question_ids:
                # 更新 import 行 subject 与 questions 一致
                if apply:
                    qi.subject = new_subject
                continue
            stem = _stem_text(qi.parsed_content)[:60]
            print(
                f"  [QI#{qi.id} status={qi.status}] {qi.subject!r:18} → {new_subject!r:18}  stem={stem!r}"
            )
            if apply:
                qi.subject = new_subject
                # 如果该 import 已发布且有对应 question_id，把 question 也一起改
                if qi.question_id and qi.status == "published":
                    q_result = await db.execute(
                        select(Question).where(Question.id == qi.question_id)
                    )
                    q = q_result.scalar_one_or_none()
                    if q and q.subject != new_subject:
                        q.subject = new_subject
                        print(f"           also updated questions.id={q.id} subject")
            changed_i += 1

        if apply:
            await db.commit()

    print()
    if apply:
        print(
            f"✓ 修复完成：questions 改 {changed_q} 条，question_imports 改 {changed_i} 条"
        )
    else:
        print(
            f"[dry-run] questions 待改 {changed_q} 条，question_imports 待改 {changed_i} 条；"
            f"使用 --apply 真正写入"
        )
    return changed_q + changed_i


def main() -> None:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", dest="dry_run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
