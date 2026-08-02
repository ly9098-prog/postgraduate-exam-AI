"""Fidelity check: 发布规范化后的选项 vs 源 question_imports.parsed_options。
对 cs_ds.pdf 524 行逐一跑官方 normalize，比较选项文本，报告意外差异。只读。
"""
import json
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402


def strip_math_wrap(s: str) -> str:
    return (s.replace("\\\\", "").replace("\\$", "").replace("$", "")
             .replace("\\", "").replace("{", "").replace("}", ""))


def main():
    conn = sqlite3.connect("postgraduate.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, question_type, parsed_content, parsed_options, parsed_answer "
        "FROM question_imports WHERE source_file='cs_ds.pdf' ORDER BY id"
    )
    rows = cur.fetchall()
    n = QuestionNormalizer()
    diffs = []
    checked = 0
    for r in rows:
        pc = json.loads(r["parsed_content"]) if r["parsed_content"] else {}
        po = json.loads(r["parsed_options"]) if r["parsed_options"] else None
        out = n.normalize(
            {"subject": "co", "question_type": r["question_type"],
             "parsed_content": pc, "parsed_options": po,
             "parsed_answer": r["parsed_answer"]},
            {},
        )
        if r["question_type"] == "multi_blank_choice":
            continue
        checked += 1
        norm = {o["key"]: o["text"] for o in (out.get("options") or [])}
        src = {str(k).upper(): str(v) for k, v in (po or {}).items()}
        for k in ("A", "B", "C", "D"):
            s = src.get(k, "")
            nv = norm.get(k, "")
            if s != nv and strip_math_wrap(nv) != s:
                diffs.append((r["id"], k, s, nv))
    print(f"single_choice rows checked: {checked}")
    print(f"option fidelity diffs: {len(diffs)}")
    for d in diffs[:60]:
        print(f"  id={d[0]} {d[1]} | src={d[2]!r} -> norm={d[3]!r}")
    conn.close()


if __name__ == "__main__":
    main()
