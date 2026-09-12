"""为 cs_ds.pdf 导入批次补充答案（fast_fill_answer/co 批次文件）。

答案源（权威）：
  prompts/tasks/fast_fill_answer/co/questions_answers_batch_01..11.md
  每行：| 序号 | id | **字母**．选项内容 |

写入字段（仅答案相关，不动题干/选项）：
  - parsed_answer：选项字母（多空题为按空序拼接，如 889 -> "DC"）
  - answer_status: manual_filled
  - answer_source: manual_batch_input
  - question_hash: 用 QuestionNormalizer.build_question_hash(stem, options, answer) 重算
    （此前 writeback 以空答案重算过，补答后必须重算，否则 hash 与内容不一致）

执行前会先落备份：backups/backup_cs_ds_528_pre_answer_20260802.jsonl

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已填答案的 id 会跳过）。
"""
import csv
import json
import os
import re
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
BATCH_DIR = os.path.join(REPO, "prompts/tasks/fast_fill_answer/co")
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/answer-fill-writeback.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_528_pre_answer_20260802.jsonl")
DB = "postgraduate.db"

normalizer = QuestionNormalizer()


def parse_batch_file(path):
    """解析单个批次文件，返回 [(id, letters, content)]。"""
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 3 or not cells[0].isdigit():
                continue
            _idx, rid, ans = cells
            m = re.search(r"\*\*(.*?)\*\*", ans)
            letters = m.group(1) if m else ""
            entries.append((int(rid), letters))
    return entries


def load_answer_map():
    """读取全部批次文件，返回 {id: "字母串"}（多空题按空序拼接）。"""
    result = {}
    files = sorted(f for f in os.listdir(BATCH_DIR) if f.startswith("questions_answers_batch_"))
    assert files, "未找到批次文件"
    for name in files:
        for rid, letters in parse_batch_file(os.path.join(BATCH_DIR, name)):
            assert rid not in result, f"id {rid} 重复出现在 {name}"
            # "D、C" -> "DC"；单字母原样
            compact = re.sub(r"[、,，\s]", "", letters).upper()
            result[rid] = compact
    return result


def main():
    answers = load_answer_map()
    assert len(answers) == 528, f"expected 528 answers, got {len(answers)}"

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, parsed_content, parsed_options, parsed_answer, answer_status, question_hash "
        "FROM question_imports WHERE source_file='cs_ds.pdf' ORDER BY id"
    )
    rows = cur.fetchall()
    assert len(rows) == 528, f"expected 528 rows, got {len(rows)}"

    db_ids = {r["id"] for r in rows}
    assert db_ids == set(answers), (
        f"id 集合不一致: db 独有 {sorted(db_ids - set(answers))}, "
        f"答案独有 {sorted(set(answers) - db_ids)}"
    )

    # ── 备份 ──
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    print(f"backup written: {BACKUP} ({len(rows)} rows)")

    changes = []
    filled = 0
    skipped_existing = 0
    hash_changed = 0

    for row in rows:
        rid = row["id"]
        answer = answers[rid]

        old_answer = row["parsed_answer"]
        if old_answer and (old_answer.strip() or "") != "":
            skipped_existing += 1
            changes.append({
                "id": rid, "field": "parsed_answer",
                "old": old_answer, "new": answer, "action": "skip_existing",
            })
            continue

        pc = json.loads(row["parsed_content"]) if row["parsed_content"] else {}
        po = json.loads(row["parsed_options"]) if row["parsed_options"] else {}
        stem = pc.get("text") or pc.get("stem") or ""
        old_hash = row["question_hash"]
        new_hash = normalizer.build_question_hash(stem, po, answer)

        if new_hash != old_hash:
            hash_changed += 1

        changes.append({
            "id": rid, "field": "parsed_answer",
            "old": old_answer, "new": answer,
            "old_hash": old_hash, "new_hash": new_hash,
        })
        filled += 1

        cur.execute(
            "UPDATE question_imports SET parsed_answer=?, answer_status='manual_filled', "
            "answer_source='manual_batch_input', question_hash=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND (parsed_answer IS NULL OR parsed_answer='')",
            (answer, new_hash, rid),
        )

    conn.commit()

    with open(OUT_LOG, "w", encoding="utf-8") as f:
        for ch in changes:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    print(f"rows total: {len(rows)}")
    print(f"filled: {filled}, skipped_existing: {skipped_existing}, hash_changed: {hash_changed}")
    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


if __name__ == "__main__":
    main()
