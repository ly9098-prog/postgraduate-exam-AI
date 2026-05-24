"""Insert sample questions for development testing."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import init_db, async_session
from app.services import question_service


SAMPLE_QUESTIONS = [
    {
        "subject": "math2",
        "question_type": "single_choice",
        "content": {"text": "设函数 $f(x) = x^2 + 1$，求 $f'(x)$ 在 $x=2$ 处的值。"},
        "options": {"A": "2", "B": "4", "C": "6", "D": "8"},
        "answer": "B",
        "analysis": "$f'(x) = 2x$，代入 $x=2$ 得 $f'(2) = 4$。",
        "knowledge_points": ["导数", "求导公式"],
        "difficulty": 1,
        "source": "自建",
    },
    {
        "subject": "math2",
        "question_type": "single_choice",
        "content": {"text": "极限 $\\lim_{x \\to 0} \\frac{\\sin x}{x} = ?$"},
        "options": {"A": "0", "B": "1", "C": r"$\infty$", "D": "不存在"},
        "answer": "B",
        "analysis": "重要极限公式 $\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1$。",
        "knowledge_points": ["极限", "重要极限"],
        "difficulty": 1,
        "source": "自建",
    },
    {
        "subject": "exam408",
        "question_type": "single_choice",
        "content": {"text": "在二叉树的先序遍历中，根节点的位置是？"},
        "options": {"A": "第一个", "B": "第二个", "C": "中间", "D": "最后一个"},
        "answer": "A",
        "analysis": "先序遍历的顺序是：根节点 → 左子树 → 右子树，所以根节点是第一个。",
        "knowledge_points": ["二叉树", "遍历"],
        "difficulty": 1,
        "source": "自建",
    },
    {
        "subject": "exam408",
        "question_type": "single_choice",
        "content": {"text": "TCP 协议工作在 OSI 模型的哪一层？"},
        "options": {"A": "网络层", "B": "传输层", "C": "应用层", "D": "数据链路层"},
        "answer": "B",
        "analysis": "TCP 是传输层协议，提供可靠的面向连接的数据传输服务。",
        "knowledge_points": ["TCP", "OSI模型", "传输层"],
        "difficulty": 1,
        "source": "自建",
    },
    {
        "subject": "english",
        "question_type": "single_choice",
        "content": {"text": "The word 'abandon' most closely means:"},
        "options": {"A": "keep", "B": "leave", "C": "find", "D": "build"},
        "answer": "B",
        "analysis": "'abandon' means to leave behind or give up entirely.",
        "knowledge_points": ["词汇", "词义"],
        "difficulty": 1,
        "source": "自建",
    },
]


async def main():
    await init_db()
    async with async_session() as db:
        for item in SAMPLE_QUESTIONS:
            q = await question_service.create(db, **item)
            print(f"  ✅ [{q.id}] {item['subject']}: {item['content']['text'][:30]}...")
    print(f"\n✅ 共导入 {len(SAMPLE_QUESTIONS)} 道题目")


if __name__ == "__main__":
    asyncio.run(main())
