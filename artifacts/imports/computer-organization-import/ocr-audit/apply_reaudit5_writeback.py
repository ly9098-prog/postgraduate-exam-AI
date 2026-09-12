"""应用五次深度审计修正（audit-report-package-5）到本地 question_imports。

修正源（权威）：
  artifacts/computer-organization-import/audit-report-package-5/
    question_imports_fifth_deep_audit_corrected.csv   -> stem + A/B/C/D（全 528 行）

范围：
  - 仅 1 行有实际字段变更（id 822，critical omission，confidence=高 源页截图确认）：
      题干补回 20 项页面访问地址流（1 8 1 7 8 2 7 2 1 8 3 8 2 1 3 1 7 1 3 7），
      答案 A(30%) 不变，重算 question_hash。
  - 19 行不改数据，仅在 review_note 追加五次审计说明（已有 note 则追加，不覆盖）：
      * 10 行源页疑似笔误（634/677/678/755/826/903/996/1049 延续 + 1037/966 新增，
        auto_applied=否）
      * 5 行公式保真复核（672/684/685/686/1111，auto_applied=否，仅建议下标 LaTeX 化）
      * 4 行重复组（610/947 EXACT-1，757/866 NEAR-1；业务决策，不删除，仅标记）

特殊处理：
  - 数据循环沿用前几轮：全 528 行比对，仅实际差异行更新（本轮仅 822）。
  - multi_blank_choice 分支保留（防御性）；本轮无 multi_blank 变更。

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已应用则无变化）。
"""
import csv
import json
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
BASE = os.path.join(REPO, "artifacts/computer-organization-import/audit-report-package-5")
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/reaudit5-writeback.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_528_pre_reaudit5_20260802.jsonl")
DB = "postgraduate.db"

# 源页疑似笔误：不改数据，仅追加 review_note（severity=人工确认，auto_applied=否）
SUSPICION_NOTES = {
    634: "五次审计：题干中“M.上的”疑似“M上的”，PDF源页亦如此，未自动修改",
    677: "五次审计：B项“010010101”为9位，而该题为8位补码定点整数，A/C/D均为8位，PDF源页亦如此，未自动修改",
    678: "五次审计：源页末尾中英文句号并存，疑似排版笔误，未自动修改",
    755: "五次审计：A/D 中“>”“<”疑似应为“×”，需以权威教材/真题为准，未自动修改",
    826: "五次审计：“IMB”疑似“1MB”，但 PDF 源页亦为 IMB，未自动修改",
    903: "五次审计：“寄存器的内存”疑似“寄存器的内容”，但 PDF 源页如此，未自动修改",
    996: "五次审计：“取值”疑似“取指”，但 PDF 源页如此，未自动修改",
    1049: "五次审计：“全工同步”疑似“全双工”，但 PDF 源页如此，未改",
    1037: "五次审计：B项“VESA.EISA”疑似“VESA、EISA”，PDF源页以英文句点分隔，疑似排版错误，不影响答案D，未自动修改",
    966: "五次审计：D项“可以相处容错”语义不通，疑似“可以相互容错”等表述，PDF源页如此，需权威题本确认，未自动修改",
}

# 公式保真复核：auto_applied=否，仅建议下标 LaTeX 化，追加 note 指向复核表
FORMULA_NOTES = {
    672: "五次审计：公式保真复核建议 A-D 下标 LaTeX 化（如 X_i⊕Y_i），未自动修改，详见 formula_fidelity_review_v5",
    684: "五次审计：公式保真复核建议“C0、C1”改为下标“C_0、C_1”，未自动修改，详见 formula_fidelity_review_v5",
    685: "五次审计：公式保真复核建议复合下标“S_s1S_s2”改为“S_{s1}S_{s2}”，未自动修改，详见 formula_fidelity_review_v5",
    686: "五次审计：公式保真复核建议 [X]补 及 X0、X1 等下标 LaTeX 化（X_0X_1X_2…X_n），未自动修改，详见 formula_fidelity_review_v5",
    1111: "五次审计：公式保真复核建议 L4~L0、M4M3M2M1M0、Mi、Li 下标 LaTeX 化，未自动修改，详见 formula_fidelity_review_v5",
}

# 重复组：业务决策，不删除，仅标记重复关系
DUP_NOTES = {
    610: "五次审计：与 id 947 完全重复（2009 统考真题：CPU 区分指令与数据存放依据，题干仅空格差异），建议按业务规则决定是否合并，未自动处理",
    947: "五次审计：与 id 610 完全重复（2009 统考真题：CPU 区分指令与数据存放依据，题干仅空格差异），建议按业务规则决定是否合并，未自动处理",
    757: "五次审计：与 id 866 近似重复（机器字长32位16MB半字寻址可寻址单元数，题意/选项/答案相同，仅“可寻址的/寻址”及句末标点差异），建议合并或标记同源，未自动处理",
    866: "五次审计：与 id 757 近似重复（机器字长32位16MB半字寻址可寻址单元数，题意/选项/答案相同，仅“可寻址的/寻址”及句末标点差异），建议合并或标记同源，未自动处理",
}

normalizer = QuestionNormalizer()


def read_corrected():
    with open(os.path.join(BASE, "question_imports_fifth_deep_audit_corrected.csv"), encoding="utf-8-sig") as f:
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

    # 追加 review_note（幂等：已含"五次审计"则跳过），保留既有 note
    all_notes = {}
    all_notes.update(SUSPICION_NOTES)
    all_notes.update(FORMULA_NOTES)
    all_notes.update(DUP_NOTES)
    for rid, note in sorted(all_notes.items()):
        r = next(x for x in rows if x["id"] == rid)
        existing = r["review_note"] or ""
        if "五次审计" in existing:
            print(f"id {rid}: 已有五次审计 note，跳过")
            continue
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
