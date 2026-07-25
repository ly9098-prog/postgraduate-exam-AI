"""
Apply fixes from docs/audit/question_imports_pdf_audit_4.md (fourth audit report).
Fixes:
  - 6 content mismatches: verify superseded targets (269→268, 359→357, 392→389, 422→421, 495→fix URL, 576→439)
  - 3 option order risks: 131, 132, 360 → reorder to A,B,C,D
  - 3 format cleanups: 407 (quote), 456 (quotes), 494 (quotes)
  - 1 asset metadata: 560 (region_type table→diagram)
"""
import json
import sqlite3

DB_PATH = "/home/lmh/projects/postgraduate-ai/backend/postgraduate.db"
BATCH_PREFIX = "AUDIT4_20260723"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def update_record(id_val, content_obj=None, options_obj=None):
    parts = []
    params = []
    if content_obj is not None:
        parts.append("parsed_content = ?")
        params.append(json.dumps(content_obj, ensure_ascii=False))
    if options_obj is not None:
        parts.append("parsed_options = ?")
        params.append(json.dumps(options_obj, ensure_ascii=False))
    if parts:
        parts.append("updated_at = CURRENT_TIMESTAMP")
        params.append(id_val)
        cur.execute(f"UPDATE question_imports SET {', '.join(parts)} WHERE id = ?", params)


def update_superseded_target(id_val, new_note, new_batch=None):
    parts = ["review_note = ?", "updated_at = CURRENT_TIMESTAMP"]
    params = [new_note]
    if new_batch:
        parts.append("superseded_by_batch_id = ?")
        params.append(new_batch)
    params.append(id_val)
    cur.execute(f"UPDATE question_imports SET {', '.join(parts)} WHERE id = ?", params)


# ═══════════════════════════════════════════════════════════════════
# 1. Option key order fixes (131, 132, 360)
# ═══════════════════════════════════════════════════════════════════
print("=== 1. Fixing option key order (131, 132, 360) ===")

# ID 131 - current order: B,A,C,D → fix to A,B,C,D
update_record(131, options_obj={
    "A": "多个用户能及时干预系统",
    "B": "使系统变得高效",
    "C": "优先级较高的进程得到及时响应",
    "D": "需要CPU时间最少的进程最先做"
})
print("  131: option keys reordered B,A,C,D → A,B,C,D")

# ID 132 - current order: B,A,D,C → fix to A,B,C,D
update_record(132, options_obj={
    "A": "进程相应的代码长度",
    "B": "进程总共需要运行的时间",
    "C": "进程特点和进程调度策略",
    "D": "进程完成什么功能"
})
print("  132: option keys reordered B,A,D,C → A,B,C,D")

# ID 360 - current order: D,A,B,C → fix to A,B,C,D
update_record(360, options_obj={
    "A": "隐式链接",
    "B": "顺序存放",
    "C": "索引存放",
    "D": "显式链接"
})
print("  360: option keys reordered D,A,B,C → A,B,C,D")


# ═══════════════════════════════════════════════════════════════════
# 2. Fix wrong merge targets for superseded records
# ═══════════════════════════════════════════════════════════════════
print("\n=== 2. Fixing wrong merge targets ===")

# ID 359: was merged-into-358, should be merged-into-357
update_superseded_target(359,
    "superseded-merged-into-357",
    BATCH_PREFIX)
print("  359: merge target corrected 358→357")

# ID 392: was merged-into-391, should be merged-into-389
update_superseded_target(392,
    "superseded-merged-into-389",
    BATCH_PREFIX)
print("  392: merge target corrected 391→389")

# ID 422: was superseded-423-has-complete-version, should be merged-into-421
update_superseded_target(422,
    "superseded-merged-into-421",
    BATCH_PREFIX)
print("  422: merge target corrected 423→421")


# ═══════════════════════════════════════════════════════════════════
# 3. Format cleanup: quote fixes
# ═══════════════════════════════════════════════════════════════════
print("\n=== 3. Format cleanup: quote fixes ===")

# ID 407: option A missing left Chinese quote
update_record(407, options_obj={
    "A": "CPU执行“启动I/O”指令而被通道拒绝接收",
    "B": "通道接收了CPU的启动请求",
    "C": "通道完成了通道程序的执行",
    "D": "通道在执行通道程序的过程中"
})
print("  407: option A quote fixed")

# ID 456: options B, D mismatched Chinese/ASCII quotes
update_record(456, options_obj={
    "A": "“访存时缺页”属于中断",
    "B": "“整数除以0”属于异常",
    "C": "“DMA传送结束”属于中断",
    "D": "“存储保护错”属于异常"
})
print("  456: options B, D quotes fixed (unified to Chinese quotes)")

# ID 494: all four options have mismatched quotes around "饥饿"
LQ = "“"
RQ = "”"
update_record(494, options_obj={
    "A": f"不能保证进程互斥进入临界区，会出现{LQ}饥饿{RQ}现象",
    "B": f"不能保证进程互斥进入临界区，不会出现{LQ}饥饿{RQ}现象",
    "C": f"能保证进程互斥进入临界区，会出现{LQ}饥饿{RQ}现象",
    "D": f"能保证进程互斥进入临界区，不会出现{LQ}饥饿{RQ}现象"
})
print("  494: all option quotes around '饥饿' fixed")


# ═══════════════════════════════════════════════════════════════════
# 4. ID 495: fix code_image URL (still points to Peterson code)
# ═══════════════════════════════════════════════════════════════════
print("\n=== 4. ID 495: fix code_image URL ===")

# Current content from audit 3: url=/static/question-assets/code_region_216_peterson.webp, source_page=216
# This is wrong — should point to the 加1/减1 instruction sequence at page 217
# Since we don't have the correct WebP image, convert to text-based code segment
update_record(495, content_obj={
    "text": "42.【2011统考真题】有两个并发执行的进程P1和进程P2，共享初值为1的变量x。P1对x加1，P2对x减1。加1和减1操作的指令序列如下。两个操作完成后，x的值( )。",
    "render_mode": "segments",
    "segments": [
        {"type": "text", "text": "42.【2011统考真题】有两个并发执行的进程P1和进程P2，共享初值为1的变量x。P1对x加1，P2对x减1。加1和减1操作的指令序列如下。"},
        {"type": "newline"},
        {"type": "code", "language": "assembly",
         "code": "// 加1操作\nload  R1, x     // 取x到寄存器R1\ninc   R1\nstore x, R1     // 将R1的内容存入x\n\n// 减1操作\nload  R2, x     // 取x到寄存器R2\ndec   R2\nstore x, R2     // 将R2的内容存入x",
         "alt": "P1加1和P2减1的机器指令序列"},
        {"type": "newline"},
        {"type": "text", "text": "两个操作完成后，x的值( )。"}
    ]
})
print("  495: code_image replaced with text-based code segment")


# ═══════════════════════════════════════════════════════════════════
# 5. ID 560: fix region_type (table→diagram)
# ═══════════════════════════════════════════════════════════════════
print("\n=== 5. ID 560: fix region_type ===")

# Read current content to preserve everything except the region_type
for row in cur.execute("SELECT parsed_content FROM question_imports WHERE id = 560"):
    pc = json.loads(row["parsed_content"])
    segs = pc.get("segments", [])
    for seg in segs:
        if seg.get("type") in ("image",) and seg.get("region_type") == "table":
            seg["region_type"] = "diagram"
            print(f"  560: seg region_type changed table→diagram, url={seg.get('url','')}")
    update_record(560, content_obj=pc)
    print("  560: region_type fixed")


conn.commit()

# ═══════════════════════════════════════════════════════════════════
# Verification
# ═══════════════════════════════════════════════════════════════════
print("\n=== Verification ===")

ids_to_check = [131, 132, 269, 359, 360, 392, 407, 422, 456, 494, 495, 560, 576]
for row in cur.execute(f"""
    SELECT id, status, source_question_no,
           substr(parsed_content, 1, 80) as content_start,
           substr(parsed_options, 1, 80) as options_start,
           review_note
    FROM question_imports
    WHERE id IN ({','.join('?'*len(ids_to_check))})
    ORDER BY id
""", ids_to_check):
    note = f" note={row['review_note']}" if row['review_note'] else ""
    print(f"  ID {row['id']} (Q{row['source_question_no']}) [{row['status']}]{note}")
    print(f"    content: {str(row['content_start'])[:70]}")
    print(f"    options: {str(row['options_start'])[:70]}")

print("\nDone: audit 4 fixes applied.")
conn.close()
