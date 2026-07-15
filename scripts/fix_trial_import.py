"""Fix trial import questions (IDs 1-10) based on OCR MCP evidence.

Uses project ORM/service layer. Records before/after values.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import async_session
from app.models.question_import import QuestionImport
from sqlalchemy import select
from datetime import datetime, timezone

ARTIFACTS = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import"
FIX_LOG = os.path.join(ARTIFACTS, "audit", "auto-fixes.jsonl")

# Fix definitions: (import_id, field, old_value, new_value, reason)
FIXES = [
    # ID=2: content and options
    (2, "parsed_content",
     {"text": "以下数据结构中，("},
     {"text": "以下数据结构中，()是非线性数据结构。"},
     "OCR截断修复：补全'是非线性数据结构'"),
    (2, "parsed_options",
     {"A": "数据元素", "B": "数据对象", "C": "数据关系", "D": "抽象数据类型"},
     {"A": "树", "B": "字符串", "C": "队列", "D": "栈"},
     "OCR错位修复：选项应为树/字符串/队列/栈而非第1题选项"),

    # ID=3: content
    (3, "parsed_content",
     {"text": "以下属于逻辑结构的是("},
     {"text": "以下属于逻辑结构的是()。"},
     "补全结尾括号和句号"),

    # ID=4: content
    (4, "parsed_content",
     {"text": "以下与数据的存储结构无关的术语是("},
     {"text": "以下与数据的存储结构无关的术语是( )。"},
     "补全结尾空格、括号和句号"),

    # ID=5: remove watermark noise
    (5, "parsed_content",
     {"text": "以下关于数据结构的说法中，正确的是()。\n风中易小生24考研计算机WD数据结构做题本【选择题】"},
     {"text": "以下关于数据结构的说法中，正确的是()。"},
     "清除尾部水印噪声：风中易小生24考研计算机WD数据结构做题本"),

    # ID=7: content noise
    (7, "parsed_content",
     {"text": "链式存储设计时，结点内的存储单元地址(\nD。\n1.2 算法和算法评价一、单项选择题(本部分答案在书 P^{8})"},
     {"text": "链式存储设计时，结点内的存储单元地址()。"},
     "清除OCR噪声：删除'D。1.2 算法和算法评价...'"),

    # ID=8: remove watermark noise
    (8, "parsed_content",
     {"text": "一个算法应该是()。\n风中易小生24考研计算机WD数据结构做题本【选择题】"},
     {"text": "一个算法应该是()。"},
     "清除尾部水印噪声"),

    # ID=9: O(n²) fix
    (9, "parsed_content",
     {"text": "某算法的时间复杂度为O(n),表明该算法的(\n)。[微信公众号:风中易小生]"},
     {"text": "某算法的时间复杂度为O(n²)，表明该算法的()。"},
     "修复O(n)为O(n²)，清除公众号噪声"),
    (9, "parsed_options",
     {"A": "问题规模是n", "B": "执行时间等于n", "C": "执行时间与 n成正比", "D": "问题规模与n成正比"},
     {"A": "问题规模是n²", "B": "执行时间等于n²", "C": "执行时间与n²成正比", "D": "问题规模与n²成正比"},
     "选项均补加上标²"),

    # ID=10: code and options fix
    (10, "parsed_content",
     {"text": "以下算法的时间复杂度为(\n```text\nvoid fun(int n) {\n    int i=l;\n    while(i<=n)\n}\n```"},
     {"text": "以下算法的时间复杂度为()。\n```text\nvoid fun(int n) {\n    int i=1;\n    while(i<=n)\n        i=i*2;\n}\n```"},
     "修复代码：i=l→i=1，补全i=i*2；，补全括号"),
    (10, "parsed_options",
     {"A": "0(n)", "B": "0(n)", "C": "O(nlog2 n)", "D": "O(log2 n)"},
     {"A": "O(n)", "B": "O(n²)", "C": "O(nlog₂n)", "D": "O(log₂n)"},
     "修复选项：0(n)→O(n)、补全上标和正确符号"),
]

async def main():
    fixes_applied = 0
    batch_id = None

    async with async_session() as db:
        # Get batch_id from question_imports
        result = await db.execute(
            select(QuestionImport).where(QuestionImport.id == 1)
        )
        first = result.scalar_one_or_none()
        if first:
            batch_id = first.batch_id
            print(f"Batch ID: {batch_id}")

        for import_id, field, old_val, new_val, reason in FIXES:
            result = await db.execute(
                select(QuestionImport).where(QuestionImport.id == import_id)
            )
            qi = result.scalar_one_or_none()
            if not qi:
                print(f"ERROR: QuestionImport id={import_id} not found")
                continue

            # Get current value
            current = getattr(qi, field, None)
            if current:
                # Parse JSON if needed
                if isinstance(current, str):
                    current = json.loads(current)

            # Log before/after
            record = {
                "database_id": import_id,
                "batch_id": batch_id,
                "field": field,
                "value_before": current,
                "value_after": new_val,
                "reason": reason,
                "source_evidence": "OCR MCP 全文档识别",
                "mcp_evidence": "PP-OCRv6 全文档simple模式识别结果",
                "edit_api": "orm:QuestionImport",
                "edited_at": datetime.now(timezone.utc).isoformat(),
                "repair_round": 1,
            }

            # Apply fix
            setattr(qi, field, json.dumps(new_val, ensure_ascii=False) if isinstance(new_val, dict) else new_val)
            qi.updated_at = datetime.now(timezone.utc)

            print(f"  Fixing ID={import_id} field={field}")
            print(f"    Before: {str(current)[:100]}")
            print(f"    After:  {str(new_val)[:100]}")
            print(f"    Reason: {reason}")

            # Write to fix log
            os.makedirs(os.path.dirname(FIX_LOG), exist_ok=True)
            with open(FIX_LOG, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

            fixes_applied += 1

        await db.commit()
        print(f"\nFixes applied: {fixes_applied}")

    return fixes_applied

if __name__ == "__main__":
    count = asyncio.run(main())
    print(f"Done: {count} fixes applied")
