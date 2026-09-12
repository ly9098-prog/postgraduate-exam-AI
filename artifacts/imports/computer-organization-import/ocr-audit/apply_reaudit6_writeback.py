"""应用第六次深度审计：id 685 内容更正 + 去重删除 + 源页疑点/公式渲染复核 note。

范围：
  A. id 685 内容更正：两位符号位 S_1S_2 -> S_{s1}S_{s2}（源页第99页，本地 OCR 读得 Ss1Ss2），
     重算 question_hash，追加 review_note。
  B. 去重：硬删除 916、1092（跨章节近似重复的后者），保留 621、861（源序先出现者）并追加去重 note。
  C. 10 条源页疑点（634/677/678/755/826/903/996/1049/1037/966）追加六次审计复核 note（均未自动修改）。
  D. 公式渲染复核 note：672/684/686/1111 确认下标已正确；713/880/894 追加发布端渲染建议。

背景：
  第六次审计 confirmed_new_error_ids=[685]；near_duplicate_groups_remaining=2（NEAR-V6-1/2）；
  source_page_suspicion_records=10（与第五次相同，均 auto_applied=否）；
  formula_rendering_review_records=8。13 条历史媒体行 DB 均已含 media_files，无需改动。
  685 此前为用户第五轮手动改为 S_1S_2，经源页证据与本地 OCR 确认正确形式为 S_{s1}S_{s2}，
  已征得用户同意更正。

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已应用则跳过）。
"""
import json
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/reaudit6-writeback.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_526_pre_reaudit6_20260802.jsonl")
DB = "postgraduate.db"

normalizer = QuestionNormalizer()

# ── id 685 内容更正 ──
FIX_685 = {"old": "S_1S_2", "new": "S_{s1}S_{s2}"}

# ── 去重：被删的后者 / 保留的先出现者 note ──
DELETE_IDS = [916, 1092]
KEEP_NOTES = {
    621: "六次审计：与 id 916 同义重复（CPU寄存器对用户透明题，选项顺序不同），已按业务规则硬删除 916，本行保留（2026-08-02）",
    861: "六次审计：与 id 1092 近似重复（不属于程序控制指令题，仅措辞差异），已按业务规则硬删除 1092，本行保留（2026-08-02）",
}

# ── 源页疑点 note（六次审计复核，未自动修改）──
SUSPICION_NOTES = {
    634: "六次审计：源页疑点复核，PDF第46页“M.上的”疑似多余句点，未自动修改（2026-08-02）",
    677: "六次审计：源页疑点复核，B项 010010101 为9位与8位题矛盾，未自动修改（2026-08-02）",
    678: "六次审计：源页疑点复核，题干末“。.”双标点疑似排版笔误，未自动修改（2026-08-02）",
    755: "六次审计：源页疑点复核(高)，A/D 中“>”“<”可能应为“×”，需权威题本确认，未自动修改（2026-08-02）",
    826: "六次审计：源页疑点复核，“IMB”疑似“1MB”但源页亦为 IMB，未自动修改（2026-08-02）",
    903: "六次审计：源页疑点复核，“寄存器的内存”疑似“寄存器的内容”，源页如此，未自动修改（2026-08-02）",
    996: "六次审计：源页疑点复核，“t取值”疑似“t取指”，源页如此，未自动修改（2026-08-02）",
    1049: "六次审计：源页疑点复核，“全工同步”疑似“全双工”，源页如此，未自动修改（2026-08-02）",
    1037: "六次审计：源页疑点复核，B项“VESA.EISA”句点疑似排版，不影响答案D，未自动修改（2026-08-02）",
    966: "六次审计：源页疑点复核，“可以相处容错”语义不通，需权威题本确认，未自动修改（2026-08-02）",
}

# ── 公式渲染复核 note ──
FORMULA_NOTES = {
    672: "六次审计：公式渲染复核确认 A-D 下标已正确（X_i⊕Y_i 等）（2026-08-02）",
    684: "六次审计：公式渲染复核确认 stem C_0/C_1 下标已正确（2026-08-02）",
    686: "六次审计：公式渲染复核确认 stem/A-D 下标已正确（X_0、X_1 等）（2026-08-02）",
    1111: "六次审计：公式渲染复核确认 stem 下标已正确（L_4~L_0、M_4…M_0 等）（2026-08-02）",
    713: "六次审计：公式渲染复核，_10/^10 需发布端渲染为下标/上标，库内纯文本正确（2026-08-02）",
    880: "六次审计：公式渲染复核，M_SP 建议发布端显示 M_{SP}，库内纯文本正确（2026-08-02）",
    894: "六次审计：公式渲染复核(高)，\\overline{...} 需确认 LaTeX/公式渲染，库内已含上划线（2026-08-02）",
}

NOTE_685 = "六次审计：源页(第99页)两位符号位为 S_{s1}S_{s2}，已纠正 S_1S_2 并重算 hash（2026-08-02）"


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    all_ids = [685] + DELETE_IDS + list(KEEP_NOTES.keys()) + list(SUSPICION_NOTES.keys()) + list(FORMULA_NOTES.keys())
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

    # ── A. id 685 内容更正 + hash + note ──
    r685 = by_id[685]
    pc = json.loads(r685["parsed_content"]) if r685["parsed_content"] else {}
    po = json.loads(r685["parsed_options"]) if r685["parsed_options"] else None
    stem = pc.get("text") or pc.get("stem") or ""
    assert r685["question_type"] == "single_choice", "id 685 非 single_choice"
    assert FIX_685["old"] in stem, f"id 685 stem 未找到 {FIX_685['old']!r}: {stem!r}"
    if FIX_685["new"] in stem:
        print("id 685: 已是 S_{s1}S_{s2}，跳过内容更正")
    else:
        new_stem = stem.replace(FIX_685["old"], FIX_685["new"])
        new_opts = {str(k).upper(): str(v) for k, v in (po or {}).items()}
        assert set(new_opts) == {"A", "B", "C", "D"}, f"id 685 选项键不完整: {set(new_opts)}"
        old_hash = r685["question_hash"]
        new_hash = normalizer.build_question_hash(new_stem, new_opts, r685["parsed_answer"] or "")
        new_pc = dict(pc)
        new_pc["text"] = new_stem
        new_pc["stem"] = new_stem
        cur.execute(
            "UPDATE question_imports SET parsed_content=?, question_hash=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (json.dumps(new_pc, ensure_ascii=False), new_hash, 685),
        )
        changes.append({"id": 685, "field": "stem_fix", "old": stem, "new": new_stem,
                        "old_hash": old_hash, "new_hash": new_hash})
        print(f"id 685: stem 已更正，hash {old_hash[:8]} -> {new_hash[:8]}")
        # 685 的 note 单独追加
        cur.execute(
            "UPDATE question_imports SET review_note=? WHERE id=?",
            (append_note(r685["review_note"], NOTE_685), 685),
        )
        changes.append({"id": 685, "field": "review_note_append", "note": NOTE_685})

    # ── B. 去重：保留行 note + 硬删除 ──
    for rid, note in KEEP_NOTES.items():
        r = by_id[rid]
        existing = r["review_note"] or ""
        if "六次审计" in existing and "硬删除" in existing:
            print(f"id {rid}: 已有六次审计去重 note，跳过")
            continue
        cur.execute(
            "UPDATE question_imports SET review_note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (append_note(existing, note), rid),
        )
        changes.append({"id": rid, "field": "review_note_append_keep", "note": note})
        print(f"id {rid}: keeper note appended")
    for rid in DELETE_IDS:
        r = by_id[rid]
        cur.execute("DELETE FROM question_imports WHERE id=?", (rid,))
        if cur.rowcount != 1:
            raise RuntimeError(f"id {rid}: DELETE rowcount={cur.rowcount}")
        changes.append({"id": rid, "field": "hard_delete", "status": r["status"], "hash": r["question_hash"]})
        print(f"id {rid}: hard deleted (was {r['status']})")

    # ── C/D. 源页疑点 + 公式渲染复核 note ──
    for rid, note in {**SUSPICION_NOTES, **FORMULA_NOTES}.items():
        r = by_id[rid]
        existing = r["review_note"] or ""
        if "六次审计" in existing:
            print(f"id {rid}: 已有六次审计 note，跳过")
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

    cur.execute("SELECT COUNT(*) AS n FROM question_imports WHERE source_file='cs_ds.pdf'")
    n = cur.fetchone()["n"]
    print(f"cs_ds.pdf remaining rows: {n} (was 526 -> expected 524)")
    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


def append_note(existing, note):
    return f"{existing}\n{note}" if existing else note


if __name__ == "__main__":
    main()
