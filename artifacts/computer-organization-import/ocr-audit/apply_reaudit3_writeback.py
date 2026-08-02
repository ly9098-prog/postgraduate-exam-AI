"""应用三次审计修正（audit-report-package-3）到本地 question_imports。

修正源（权威）：
  artifacts/computer-organization-import/audit-report-package-3/
    question_imports_third_audit_corrected.csv   -> stem + A/B/C/D（全 528 行）

范围：
  - 75 行有实际字段变更（高/中/低严重度，confidence=高 逐页图像核对）：更新 stem 与选项，
    重算 question_hash。（该 75 行与审计自动修正记录数一致；889/1098 多空题不在其列。）
  - 7 行源页疑似笔误（634/678/755/826/903/996/1049，severity=人工确认，auto_applied=否）：
    不改数据，仅在 review_note 追加待人工确认说明（已有 note 则追加，不覆盖）。
    * 其中 1049 同时有自动修正（题干末尾中文句号 .( -> 。()），本轮既改数据又追加 note。

特殊处理：
  - 本轮 75 行全为 single_choice（889/1098 多空题无变更），parsed_options 整组 A-D 覆盖，
    parsed_content.text/stem 更新。
  - multi_blank_choice 分支保留（防御性）：仅改 stem，选项保留在 blank_option_groups，
    parsed_options 保持 NULL，答案保持序列化。

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已应用则无变化）。
"""
import csv
import json
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
BASE = os.path.join(REPO, "artifacts/computer-organization-import/audit-report-package-3")
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/reaudit3-writeback.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_528_pre_reaudit3_20260802.jsonl")
DB = "postgraduate.db"

# 源页疑似笔误：不改数据，仅追加 review_note（severity=人工确认，auto_applied=否）
SUSPICION_NOTES = {
    634: "三次审计：题干中“M.上的”疑似“M上的”，PDF源页亦如此，未自动修改",
    678: "三次审计：源页末尾中英文句号并存，疑似排版笔误，未自动修改",
    755: "三次审计：A/D 中“>”“<”疑似应为“×”，需以权威教材/真题为准，未自动修改",
    826: "三次审计：“IMB”疑似“1MB”，但 PDF 源页亦为 IMB，未自动修改",
    903: "三次审计：“寄存器的内存”疑似“寄存器的内容”，但 PDF 源页如此，未自动修改",
    996: "三次审计：“取值”疑似“取指”，但 PDF 源页如此，未自动修改",
    1049: "三次审计：“全工同步”疑似“全双工”，但 PDF 源页如此，未改",
}

normalizer = QuestionNormalizer()


def read_corrected():
    with open(os.path.join(BASE, "question_imports_third_audit_corrected.csv"), encoding="utf-8-sig") as f:
        return {int(r["id"]): r for r in csv.DictReader(f)}


def db_options(r):
    pc = json.loads(r["parsed_content"]) if r["parsed_content"] else {}
    po = json.loads(r["parsed_options"]) if r["parsed_options"] else None
    if r["question_type"] == "multi_blank_choice":
        groups = pc.get("blank_option_groups") or []
        if groups:
            return {str(o.get("key") or "").upper(): str(o.get("text") or "") for o in groups[0].get("options") or []}
        return {}
    return {str(k).upper(): str(v) for k, v in (po or {}).items()}


def db_stem(r):
    pc = json.loads(r["parsed_content"]) if r["parsed_content"] else {}
    return pc.get("text") or pc.get("stem") or ""


def main():
    corrected = read_corrected()
    assert len(corrected) == 528

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, question_type, parsed_content, parsed_options, parsed_answer, question_hash, review_note "
        "FROM question_imports WHERE source_file='cs_ds.pdf' ORDER BY id"
    )
    rows = cur.fetchall()
    assert len(rows) == 528

    # ── 备份 ──
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    print(f"backup written: {BACKUP} ({len(rows)} rows)")

    changes = []
    data_updated = 0
    note_updated = 0

    for row in rows:
        rid = row["id"]
        c = corrected[rid]

        pc = json.loads(row["parsed_content"]) if row["parsed_content"] else {}
        old_stem = db_stem(row)
        old_opts = db_options(row)
        new_stem = c["stem"] or ""
        stem_changed = old_stem != new_stem

        # single_choice: 全量 A-D；multi_blank_choice: 选项不变
        new_opts = {k: c.get(k, old_opts.get(k, "")) for k in ("A", "B", "C", "D")}
        opt_changed_keys = [k for k in ("A", "B", "C", "D") if (old_opts.get(k) or "") != new_opts[k]]

        # 校验修正后答案字母仍为合法选项（选项只可能被修正文本，不改变字母集）
        assert set(new_opts) == {"A", "B", "C", "D"}, f"id {rid}: 选项键不完整"

        if not stem_changed and not opt_changed_keys:
            continue

        new_pc = dict(pc)
        if stem_changed:
            new_pc["text"] = new_stem
            new_pc["stem"] = new_stem

        old_hash = row["question_hash"]
        answer = row["parsed_answer"] or ""
        if row["question_type"] == "multi_blank_choice":
            # 防御性分支：仅 stem 变化；blank_option_groups 保留
            groups = new_pc.get("blank_option_groups") or []
            assert groups, f"id {rid}: multi_blank_choice 缺少 blank_option_groups"
            new_hash = normalizer.build_question_hash(new_stem, [], answer, blank_option_groups=groups)
            cur.execute(
                "UPDATE question_imports SET parsed_content=?, question_hash=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(new_pc, ensure_ascii=False), new_hash, rid),
            )
        else:
            new_hash = normalizer.build_question_hash(new_stem, new_opts, answer)
            cur.execute(
                "UPDATE question_imports SET parsed_content=?, parsed_options=?, question_hash=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    json.dumps(new_pc, ensure_ascii=False),
                    json.dumps(new_opts, ensure_ascii=False),
                    new_hash,
                    rid,
                ),
            )

        data_updated += 1
        changes.append({
            "id": rid,
            "field_changes": {
                "stem": (old_stem, new_stem) if stem_changed else None,
                "options": {k: (old_opts.get(k), new_opts[k]) for k in opt_changed_keys},
            },
            "old_hash": old_hash,
            "new_hash": new_hash,
        })

    # 源页疑似笔误：追加 review_note
    for rid, note in SUSPICION_NOTES.items():
        r = next(x for x in rows if x["id"] == rid)
        existing = r["review_note"] or ""
        new_note = f"{existing}\n{note}" if existing else note
        cur.execute(
            "UPDATE question_imports SET review_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_note, rid),
        )
        note_updated += 1
        changes.append({"id": rid, "field": "review_note_append", "note": note})

    conn.commit()

    with open(OUT_LOG, "w", encoding="utf-8") as f:
        for ch in changes:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    print(f"data rows updated: {data_updated}")
    print(f"review_note rows updated: {note_updated}")
    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


if __name__ == "__main__":
    main()
