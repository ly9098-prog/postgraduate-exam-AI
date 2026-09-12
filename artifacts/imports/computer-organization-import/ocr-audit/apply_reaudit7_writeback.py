"""应用第七次深度审计：6 条自动修正 + 新疑点/答案口径 note。

范围：
  A. 6 条自动修正（auto_corrected=是），逐行重算 question_hash：
     648  answer B->D  n位有符号定点整数最大值=2^(n-1)-1（数值位 n-1）
     856  answer A->D  虚页号82H 存在位0 -> 缺页异常
     678  stem   题干末尾“。.”重复标点清理为“。”
     730  opts   B 末尾英文句点、D 开头英文句点清理
     884  opts   C 项“条件转”截断补全为“条件转移”
     1031 opts   C 项“16MB/s .”规范为“16MB/s”
  B. review_note（七次审计前缀）：
     - 6 条修正行记录修正动作
     - 991（新源页疑点）与 1105（答案口径疑义）追加 note
     - 其余 9 条源页疑点与 8 条公式渲染在第六次审计已记 note，本次不再重复追加

背景：
  第七次审计 auto_corrected_records=6/fields=7；answer_key_errors_corrected=2（648/856）；
  answer_ambiguity_records=1（1105，未自动修改）；source_page_suspicion_records=10（9 条延续 + 991 新增）。
  13 条历史媒体行 DB 均已含 media_files（第六次审计已核验），无需改动。

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已应用则跳过）。
"""
import json
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/reaudit7-writeback.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_524_pre_reaudit7_20260802.jsonl")
DB = "postgraduate.db"

normalizer = QuestionNormalizer()

# (id, {answer?, stem_pairs?, opts?})  opts 为整组 A-D 精确替换；stem_pairs 为有序替换
FIXES = {
    648: {"answer": "D", "note": "七次审计：答案键错误修正，n位有符号定点整数最大值=2^(n-1)-1，B→D（2026-08-02）"},
    856: {"answer": "D", "note": "七次审计：答案键错误修正，虚页号82H 存在位0→缺页异常，A→D（2026-08-02）"},
    678: {
        "stem_pairs": [("()。.", "()。")],
        "note": "七次审计：题干末尾“。.”重复标点清理为“。”（2026-08-02）",
    },
    730: {
        "opts": {"A": "随机存取存储器(RAM)", "B": "只读存储器(ROM)", "C": "顺序存取存储器(SAM)", "D": "直接存取存储器(DAM)"},
        "note": "七次审计：B项末尾、D项开头混入英文句点已清理（2026-08-02）",
    },
    884: {
        "opts": {"A": "程序浮动", "B": "程序的无条件浮动和条件浮动", "C": "程序的无条件转移和条件转移", "D": "程序的调用"},
        "note": "七次审计：C项“条件转”截断补全为“条件转移”（2026-08-02）",
    },
    1031: {
        "opts": {"A": "4MB/s", "B": "40MB/s", "C": "16MB/s", "D": "64MB/s"},
        "note": "七次审计：C项“16MB/s .”规范为“16MB/s”（2026-08-02）",
    },
}

# 仅追加 note（无内容改动）
NOTE_ONLY = {
    991: "七次审计：源页疑点复核，C项“同时执行多个处理器”疑似“同时执行多条指令”，源页如此，未自动修改（2026-08-02）",
    1105: "七次审计：答案口径疑义，DMA/通道控制是否属“非程序控制方式”依教材分类口径，当前答案 C 未自动修改（2026-08-02）",
}


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    all_ids = list(FIXES.keys()) + list(NOTE_ONLY.keys())
    q = ",".join("?" * len(all_ids))
    cur.execute(
        f"SELECT id, question_type, parsed_content, parsed_options, parsed_answer, question_hash, status, review_note "
        f"FROM question_imports WHERE id IN ({q}) ORDER BY id",
        tuple(all_ids),
    )
    rows = cur.fetchall()
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in all_ids if i not in by_id]
    assert not missing, f"缺失 ids: {missing}"
    assert len(rows) == len(set(all_ids)), "存在重复 id"

    # ── 备份 ──
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    print(f"backup written: {BACKUP} ({len(rows)} rows)")

    changes = []

    # ── A. 内容/答案修正 + hash + note ──
    for rid, spec in FIXES.items():
        r = by_id[rid]
        assert r["question_type"] == "single_choice", f"id {rid} 非 single_choice"
        pc = json.loads(r["parsed_content"]) if r["parsed_content"] else {}
        po = json.loads(r["parsed_options"]) if r["parsed_options"] else None
        stem = pc.get("text") or pc.get("stem") or ""
        opts = {str(k).upper(): str(v) for k, v in (po or {}).items()}
        assert set(opts) == {"A", "B", "C", "D"}, f"id {rid} 选项键不完整: {set(opts)}"
        answer = r["parsed_answer"] or ""

        new_stem, new_opts, new_answer = stem, dict(opts), answer
        changed = []

        if spec.get("stem_pairs"):
            for old, new in spec["stem_pairs"]:
                assert old in new_stem, f"id {rid}: stem 未找到 {old!r}: {new_stem!r}"
                new_stem = new_stem.replace(old, new)
            if new_stem != stem:
                changed.append("stem")
        if spec.get("opts"):
            new_opts = {k: spec["opts"].get(k, opts.get(k, "")) for k in ("A", "B", "C", "D")}
            for k in ("A", "B", "C", "D"):
                if opts[k] != new_opts[k]:
                    changed.append(f"opt_{k}")
        if spec.get("answer") and answer != spec["answer"]:
            new_answer = spec["answer"]
            changed.append("answer")

        if not changed:
            print(f"id {rid}: 已是最新，跳过")
            continue

        old_hash = r["question_hash"]
        new_hash = normalizer.build_question_hash(new_stem, new_opts, new_answer)
        new_pc = dict(pc)
        if "stem" in changed:
            new_pc["text"] = new_stem
            new_pc["stem"] = new_stem
        cur.execute(
            "UPDATE question_imports SET parsed_content=?, parsed_options=?, parsed_answer=?, question_hash=?, "
            "review_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                json.dumps(new_pc, ensure_ascii=False),
                json.dumps(new_opts, ensure_ascii=False),
                new_answer,
                new_hash,
                append_note(r["review_note"], spec["note"]),
                rid,
            ),
        )
        changes.append({"id": rid, "fields": changed, "old_hash": old_hash, "new_hash": new_hash,
                        "note": spec["note"]})
        print(f"id {rid}: changed {changed}, hash {old_hash[:8]} -> {new_hash[:8]}")

    # ── B. 仅 note 追加 ──
    for rid, note in NOTE_ONLY.items():
        r = by_id[rid]
        existing = r["review_note"] or ""
        if "七次审计" in existing:
            print(f"id {rid}: 已有七次审计 note，跳过")
            continue
        cur.execute(
            "UPDATE question_imports SET review_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (append_note(existing, note), rid),
        )
        changes.append({"id": rid, "field": "review_note_append", "note": note})
        print(f"id {rid}: note appended")

    conn.commit()

    with open(OUT_LOG, "w", encoding="utf-8") as f:
        for ch in changes:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


def append_note(existing, note):
    return f"{existing}\n{note}" if existing else note


if __name__ == "__main__":
    main()
