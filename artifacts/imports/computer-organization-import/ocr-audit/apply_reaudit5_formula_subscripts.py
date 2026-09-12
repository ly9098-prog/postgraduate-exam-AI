"""应用第五次审计公式保真复核：672/684/686/1111 下标 LaTeX 化，685 修正过期 hash。

背景（重要）：
  五次审计 formula_fidelity_review_v5 建议 672/684/685/686/1111 下标 LaTeX 化，
  auto_applied=否。用户确认按建议应用。
  其中 685 库内内容已被外部进程（运行中的 uvicorn PROCESS_ROLE=all / 管理端）从
  "S_s1S_s2" 改为 "S_1S_2"（两位符号位 S1、S2，语义正确），但 question_hash 未重算
  （仍为 "S_s1S_s2" 对应的 388987a6）。本脚本不覆盖 685 内容，仅重算其 hash。
  （注：审计建议的 S_{s1}S_{s2} 是对 OCR 误识别的 S_s1S_s2 的照搬，非正确形式，
   正确的两位符号位下标即为 S_1S_2。）

替换规则（按建议 + 同题一致性）：
  id 672 options:  Xi⊕Yi->X_i⊕Y_i；XiYi->X_iY_i；XiYiCi->X_iY_iC_i；Xi+Yi+Ci->X_i+Y_i+C_i
  id 684 stem:     C0->C_0，C1->C_1（全部出现处，均为进位位下标）
  id 686 stem:     X0X1X2…Xn->X_0X_1X_2…X_n；X0为符号位->X_0为符号位；X1为最高数位->X_1为最高数位
       options:     X0=X1->X_0=X_1；X0≠X1->X_0≠X_1；X1=0->X_1=0；X1=1->X_1=1
  id 1111 stem:    L4~L0->L_4~L_0；M4M3M2M1M0->M_4M_3M_2M_1M_0；Mi=1->M_i=1；Li级->L_i级；
                   L4→L0→L2→L1→L3->L_4→L_0→L_2→L_1→L_3；L1的中断处理程序->L_1的中断处理程序
  id 685:          仅重算 hash（内容保持 S_1S_2）。

Usage: 从 backend/ 用 backend/.venv/bin/python 运行。幂等（已应用则无变化）。
"""
import json
import os
import sqlite3

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./postgraduate.db")

from app.features.question_pipeline import QuestionNormalizer  # noqa: E402

REPO = "/home/lmh/projects/postgraduate-ai"
OUT_LOG = os.path.join(REPO, "artifacts/computer-organization-import/ocr-audit/reaudit5-formula-subscripts.jsonl")
BACKUP = os.path.join(REPO, "artifacts/computer-organization-import/backups/backup_cs_ds_528_pre_formula_subscripts_20260802.jsonl")
DB = "postgraduate.db"

normalizer = QuestionNormalizer()


def sub_all(text, pairs):
    for old, new in pairs:
        assert old in text, f"pattern {old!r} not found in: {text!r}"
        text = text.replace(old, new)
    return text


# (id, field, pairs)  field in {stem, opts}  opts 为整组 A-D 精确替换
FORMULA = {
    # options: 精确替换整组
    672: {
        "opts": {
            "A": "X_i⊕Y_i", "B": "X_iY_i", "C": "X_iY_iC_i", "D": "X_i+Y_i+C_i",
        },
        "stem_pairs": [],
    },
    684: {
        "opts": None,
        "stem_pairs": [("C0", "C_0"), ("C1", "C_1")],
    },
    686: {
        "opts": {
            "A": "X_0=X_1", "B": "X_0≠X_1", "C": "X_1=0", "D": "X_1=1",
        },
        "stem_pairs": [
            ("X0X1X2…Xn", "X_0X_1X_2…X_n"),
            ("X0为符号位", "X_0为符号位"),
            ("X1为最高数位", "X_1为最高数位"),
        ],
    },
    1111: {
        "opts": None,
        "stem_pairs": [
            ("M4M3M2M1M0", "M_4M_3M_2M_1M_0"),
            ("L4~L0", "L_4~L_0"),
            ("L4→L0→L2→L1→L3", "L_4→L_0→L_2→L_1→L_3"),
            ("Mi=1", "M_i=1"),
            ("Li级", "L_i级"),
            ("L1的中断处理程序", "L_1的中断处理程序"),
        ],
    },
}

# 685：仅重算 hash，内容不动
HASH_ONLY = {685}


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    ids = list(FORMULA.keys()) + list(HASH_ONLY)
    q = ",".join("?" * len(ids))
    cur.execute(
        f"SELECT id, question_type, parsed_content, parsed_options, parsed_answer, question_hash, review_note "
        f"FROM question_imports WHERE id IN ({q}) ORDER BY id",
        tuple(ids),
    )
    rows = cur.fetchall()
    assert len(rows) == len(ids), f"expected {len(ids)} rows, got {len(rows)}"

    # ── 备份 ──
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
    print(f"backup written: {BACKUP} ({len(rows)} rows)")

    changes = []
    for row in rows:
        rid = row["id"]
        pc = json.loads(row["parsed_content"]) if row["parsed_content"] else {}
        po = json.loads(row["parsed_options"]) if row["parsed_options"] else None
        stem = pc.get("text") or pc.get("stem") or ""
        old_opts = {str(k).upper(): str(v) for k, v in (po or {}).items()}
        old_hash = row["question_hash"]
        answer = row["parsed_answer"] or ""

        new_stem = stem
        new_opts = dict(old_opts)
        changed = {"stem": False, "opts": []}

        if rid in FORMULA:
            spec = FORMULA[rid]
            for old, new in spec["stem_pairs"]:
                assert old in new_stem, f"id {rid}: pattern {old!r} not in stem"
                new_stem = new_stem.replace(old, new)
            if new_stem != stem:
                changed["stem"] = True
            if spec["opts"]:
                new_opts = {k: spec["opts"].get(k, old_opts.get(k, "")) for k in ("A", "B", "C", "D")}
                changed["opts"] = [k for k in ("A", "B", "C", "D") if (old_opts.get(k) or "") != new_opts[k]]
                assert set(new_opts) == {"A", "B", "C", "D"}, f"id {rid}: 选项键不完整"
        # rid in HASH_ONLY: 内容不变，仅重算 hash

        # 校验答案字母仍合法（single_choice）
        assert row["question_type"] == "single_choice", f"id {rid}: 非 single_choice"

        new_hash = normalizer.build_question_hash(new_stem, new_opts, answer)
        new_pc = dict(pc)
        if new_stem != stem:
            new_pc["text"] = new_stem
            new_pc["stem"] = new_stem
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
        changes.append({
            "id": rid,
            "hash_only": rid in HASH_ONLY and not changed["stem"] and not changed["opts"],
            "stem_changed": changed["stem"],
            "options_changed": changed["opts"],
            "old_hash": old_hash,
            "new_hash": new_hash,
        })
        print(f"id {rid}: stem_changed={changed['stem']} opts_changed={changed['opts']} "
              f"hash {old_hash[:8]} -> {new_hash[:8]}")

    conn.commit()
    with open(OUT_LOG, "w", encoding="utf-8") as f:
        for ch in changes:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")
    print(f"changes logged: {len(changes)} -> {OUT_LOG}")
    conn.close()


if __name__ == "__main__":
    main()
