#!/usr/bin/env python3
"""Apply deep-check fixes (round 2) via update_import_question (project business API).

Classes:
  A. strip embedded option lines from parsed_content.text (p111-135 block + p16 stray)
  B. restore "×" in stems (KxN / resolution / formulas)
  C. restore corrupted options (superscript/operator loss)
  D. restore "→" arrows (order semantics)
  E. value error (866 B)
  F. spelling (1060 / 753)

Options are always passed as the FULL corrected A/B/C/D dict
(update_import_question replaces the whole options dict).

Run: cd backend && .venv/bin/python /abs/apply_deep_fixes.py
"""
import asyncio, json, os, re, sys

sys.path.insert(0, "/home/lmh/projects/postgraduate-ai/backend")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
BASE = "/home/lmh/projects/postgraduate-ai"
LOG = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit/fixes-applied.jsonl")

# ---------------------------------------------------------------- stem transforms
# ids whose stem must strip trailing option lines (A./B./C./D. at end)
STRIP_OPTIONS = {603, 732, 733, 734, 735, 736, 737, 738, 740, 741, 742, 743, 744,
                 745, 746, 748, 749, 750, 751, 752, 753, 754, 755}

# id -> ordered list of (old, new) substring replacements applied to stem
STEM_REPL = {
    740: [("unsigned short usi 执行上述两条语句后", "unsigned short usi = si;\n执行上述两条语句后")],
    745: [("(R1)-(R^{2})R^{3}", "(R1)-(R^{2})→R^{3}")],
    746: [("```text\n", ""), ("\n```\n", "\n")],
    # B: ×-loss
    770: [("32K16位", "32K×16位")],
    783: [("64K32 位", "64K×32 位")],
    786: [("16K8 位", "16K×8 位"), ("64K8 位", "64K×8 位")],
    793: [("819281928 位", "8192×8192×8 位")],
    794: [("16K1位", "16K×1位"), ("64K8位", "64K×8位")],
    796: [("512K8 位", "512K×8 位")],
    800: [("32K16 位", "32K×16 位")],
    802: [("2K8位", "2K×8位"), ("4K4位", "4K×4位")],
    807: [("2K4位", "2K×4位"), ("8K8位", "8K×8位")],
    810: [("2K1位", "2K×1位")],
    1029: [("640480", "640×480")],
    1065: [("1616", "16×16")],
    1067: [("16001200", "1600×1200")],
    719: [("X=2729/32", "X=2⁷×29/32"), ("Y=\\frac{255}{8}", "Y=2⁵×5/8")],
    751: [("为251.10101", "为2⁵×1.10101")],
    711: [("N1=2mM和N=2M2", "N₁=2ᵐ×M₁和N₂=2ⁿ×M₂")],
    # D: 880 stem arrow
    880: [("若进栈操作的动作是(A)Msp, (SP)-1SP", "若进栈操作的动作是(A)→Msp, (SP)-1→SP")],
}

# ---------------------------------------------------------------- options (FULL dicts)
OPTIONS = {
    # C: option corruption
    760: {"A": "4×10⁶B/s", "B": "16MB/s", "C": "8×10⁶B/s", "D": "8×2²⁰B/s"},
    755: {"A": "-(2-25²)>2-1023", "B": "-(2-252²)×2+1023", "C": "-1×2-1024", "D": "-(1-2-52)<2+2047"},
    1003: {"A": "0.25×10⁹条指令/秒", "B": "0.97x109条指令/秒", "C": "1.0x109条指令/秒", "D": "1.03x109条指令/秒"},
    648: {"A": "2n", "B": "2^(n-1)-1", "C": "2n-1", "D": "2n-1-1"},
    # D: arrow loss
    880: {"A": "(Msp)→A, (SP)+1→SP", "B": "(SP)+1→SP, (MsP)→A",
          "C": "(SP)-1→SP, (MsP)→A", "D": "(MsP)→A, (SP)-1→SP"},
    1086: {"A": "访管→程序性→机器故障", "B": "访管→程序性→重新启动",
           "C": "外部→访管→程序性", "D": "程序性→I/O→访管"},
    1108: {"A": "内存→数据总线→数据通路→外设", "B": "内存→数据总线→DMAC→外设",
           "C": "内存→数据通路→数据总线→外设", "D": "内存→CPU→外设"},
    1091: {"A": "1→2→3→4", "B": "3→1→4→2", "C": "1→3→4→2", "D": "2→1→3→4"},
    # E: value error
    866: {"A": "224", "B": "223", "C": "222", "D": "221"},
    # F: spelling
    1060: {"A": "DMA 控制器", "B": "设备控制器", "C": "中断控制器", "D": "I/O 端口"},
    753: {"A": "在浮点加减运算的对阶操作中，若阶码减小，则尾数左移",
          "B": "在浮点加减运算的对阶操作中，若阶码增大，则尾数右移；若阶码减小，则尾数左移",
          "C": "在浮点加减运算的对阶操作中，若阶码增大，则尾数右移",
          "D": "以上都不对"},
}

REVIEW_NOTES = {
    755: "恢复上下标与×（OCR 压平，²位置需对照原页定稿）",
}


def strip_trailing_options(stem):
    lines = stem.split("\n")
    while lines and re.match(r"^[A-Da-d][\.、．·]\s*", lines[-1].strip()):
        lines.pop()
    return "\n".join(lines)


def build_fixes():
    from app.core.database import async_session
    from app.schemas.admin_imports import AdminImportQuestionUpdateRequest
    from app.services.admin_import_service import update_import_question

    async def inner():
        import sqlite3
        c = sqlite3.connect(BASE + "/backend/postgraduate.db")
        c.row_factory = sqlite3.Row
        ids = sorted(set(STRIP_OPTIONS) | set(STEM_REPL) | set(OPTIONS))
        log_lines = []
        async with async_session() as db:
            for qid in ids:
                r = c.execute("SELECT parsed_content, parsed_options FROM question_imports WHERE id=?",
                              (qid,)).fetchone()
                cur_stem = json.loads(r["parsed_content"])["text"]
                new_stem = cur_stem
                if qid in STRIP_OPTIONS:
                    new_stem = strip_trailing_options(new_stem)
                for old, new in STEM_REPL.get(qid, []):
                    assert old in new_stem, f"id={qid}: not found {old!r} in {new_stem[:120]!r}"
                    new_stem = new_stem.replace(old, new)
                data = {}
                if new_stem != cur_stem:
                    data["stem"] = new_stem
                if qid in OPTIONS:
                    data["options"] = OPTIONS[qid]
                if not data:
                    print(f"id={qid} NO CHANGE")
                    continue
                note = f"deepfix {','.join(k for k in data)}"
                if qid in REVIEW_NOTES:
                    note += f" | {REVIEW_NOTES[qid]}"
                data["review_note"] = note
                req = AdminImportQuestionUpdateRequest(**data)
                await update_import_question(db, qid, req)
                log_lines.append(json.dumps({
                    "database_id": qid, "field": "deep_fix",
                    "value_after": json.dumps(data, ensure_ascii=False),
                    "reason": note, "edit_api": "update_import_question",
                }, ensure_ascii=False))
                # verification print
                print(f"id={qid} stem_changed={new_stem!=cur_stem} options_changed={qid in OPTIONS}")
                if new_stem != cur_stem:
                    print(f"   stem BEFORE: {cur_stem[:110]!r}")
                    print(f"   stem AFTER : {new_stem[:110]!r}")
            await db.commit()
        with open(LOG, "a", encoding="utf-8") as f:
            for line in log_lines:
                f.write(line + "\n")
        print(f"applied {len(log_lines)} deep fixes; log -> {LOG}")

    asyncio.run(inner())


if __name__ == "__main__":
    build_fixes()
