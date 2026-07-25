#!/usr/bin/env python3
"""Fix 10 misclassified subjective questions + fix 2 auto-fixed with bad stems."""
import hashlib
import json
import sqlite3
import os

DB = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "postgraduate.db")
SUBJECT_ID = 9


def make_raw_data(stem, options_list, qno, page, raw_text):
    return {
        "stem": stem, "code_blocks": [], "options": options_list,
        "answer": "", "analysis": "", "subject": "", "subject_id": SUBJECT_ID,
        "question_type": "single_choice", "raw_text": raw_text,
        "knowledge_points": [], "difficulty": 3,
        "source": {"file": "os_sc.pdf", "page": page, "type": "pdf"},
        "is_valid": False,
        "stem_hash": hashlib.md5(stem.encode()).hexdigest()[:8],
        "confidence_score": 0.7, "validation_status": "passed",
        "failure_reason": ["missing_answer_for_objective_question"],
        "retry_recommended": False, "ocr_quality_flags": [],
        "risk_flags": ["reimported_missing_page"],
        "is_frozen": True, "options_classified": True,
        "options_classify_reason": "direct_parsed", "schema_version": "v1",
        "quality_status": "needs_manual_review",
        "quality_blockers": ["missing_answer_for_objective_question"],
        "page_start": page, "page_end": page,
        "source_question_no": qno, "source_question_label": f"{qno}.",
        "ai_validation": {"is_valid": True, "issues": [], "severity": "none"},
    }


def update(db, id, page, stem, options_dict, qno, raw_text):
    opts_list = [{"key": k, "text": v} for k, v in sorted(options_dict.items())]
    rd = make_raw_data(stem, opts_list, qno, page, raw_text)
    pc = {"text": stem}
    po = {k: v for k, v in sorted(options_dict.items())}
    qh = hashlib.md5(f"{stem}|{json.dumps(po, sort_keys=True)}".encode()).hexdigest()[:16]

    db.execute("""UPDATE question_imports SET
        question_type=?, raw_data=?, parsed_content=?,
        parsed_options=?, source_question_no=?
        WHERE id=?""",
        ("single_choice", json.dumps(rd, ensure_ascii=False),
         json.dumps(pc, ensure_ascii=False), json.dumps(po, ensure_ascii=False),
         qno, id))
    print(f"  OK   ID={id:>4} (p{page:>3}): qno={qno} {stem[:60]}")


def main():
    db = sqlite3.connect(DB)
    rows = dict(db.execute(
        "SELECT id, raw_data FROM question_imports WHERE subject_id=? AND question_type='subjective'",
        (SUBJECT_ID,)).fetchall())
    # Also re-fix 465 and 495 (auto-fixed with bad stems)
    rows.update(dict(db.execute(
        "SELECT id, raw_data FROM question_imports WHERE id IN (465,495)"
    ).fetchall()))

    raw_texts = {}
    for id, rd_json in rows.items():
        rd = json.loads(rd_json)
        raw_texts[id] = rd.get("raw_text", "")

    fixes = [
        # (id, page, stem, options_dict, qno)
        (448, 29,
         "10.分时系统追求的目标是（）。",
         {"A": "充分利用I/O设备", "B": "比较快速响应用户",
          "C": "提高系统吞吐率", "D": "充分利用内存"},
         "10"),

        (462, 85,
         "5.下面的叙述中，正确的是（）。",
         {"A": "进程获得处理器运行是通过调度得到的",
          "B": "优先级是进程调度的重要依据，一旦确定不能改动",
          "C": "在单处理器系统中，任何时刻都只有一个进程处于运行态",
          "D": "进程申请处理器而得不到满足时，其状态变为阻塞态"},
         "5"),

        (465, 118,
         "38.（）必会引起进程切换。",
         {"A": "一个进程创建后，进入就绪态",
          "B": "一个进程从运行态变为就绪态",
          "C": "一个进程从阻塞态变为就绪态",
          "D": "以上答案都不对"},
         "38"),

        (466, 120,
         "40.一个进程被唤醒，意味着（）。",
         {"A": "该进程可以重新竞争CPU", "B": "优先级变大",
          "C": "PCB移动到就绪队列之首", "D": "进程变为运行态"},
         "40"),

        (480, 160,
         "22.下列说法中，正确的是（）。"
         "I.分时系统的时间片固定，因此用户数越多，响应时间越长。"
         "II.UNIX是一个强大的多用户、多任务操作系统，支持多种处理器架构，"
         "按照操作系统分类，属于分时操作系统。"
         "III.中断向量地址是中断服务例行程序的入口地址。"
         "IV.中断发生时，由硬件保护并更新程序计数器（PC），而不是由软件完成，"
         "主要是为了提高处理速度。",
         {"A": "I、II", "B": "II、III", "C": "III、IV", "D": "仅 IV"},
         "22"),

        (483, 173,
         "下列选项中，属于操作系统内核功能的是（）。"
         "I.进程控制块 II.时钟中断处理程序 III.进程就绪队列 IV.进程阻塞队列",
         {"A": "仅II、III", "B": "仅I、IV", "C": "仅I、II、III", "D": "仅I、II、IV"},
         "2"),

        (495, 217,
         "43.【2016统考真题】进程P1和P2均包含并发执行的线程，部分伪代码描述如下所示。"
         "加1和减1操作的指令序列分别如下："
         "//加1操作 load R1,x inc R1 store x,R1 "
         "//减1操作 load R2,x dec R2 store x,R2 "
         "两个操作完成后，x的值（）。",
         {"A": "可能为-1或3", "B": "只能为1",
          "C": "可能为0、1或2", "D": "可能为-1、0、1或2"},
         "43"),

        (507, 293,
         "32.对主存储器的访问，（）。",
         {"A": "以块（即页）或段为单位", "B": "以字节或字为单位",
          "C": "随存储器的管理方案不同而异", "D": "以用户的逻辑记录为单位"},
         "32"),

        (547, 455,
         "10.以下（）不属于设备管理数据结构。",
         {"A": "PCB", "B": "DCT", "C": "COCT", "D": "CHCT"},
         "10"),

        (574, 492,
         "现有3000个逻辑记录需要存储，存储这些记录需要长度为（）的磁带，磁带利用率是（）。",
         {"A": "1500英寸，33.3%", "B": "1500英寸，43.5%",
          "C": "1800英寸，33.3%", "D": "1800英寸，43.5%"},
         "5"),
    ]

    for id, page, stem, opts_dict, qno in fixes:
        rt = raw_texts.get(id, "")
        update(db, id, page, stem, opts_dict, qno, rt)

    db.commit()

    cnt = dict(db.execute(
        "SELECT question_type, COUNT(*) FROM question_imports WHERE subject_id=? GROUP BY question_type",
        (SUBJECT_ID,)).fetchall())
    db.close()
    print(f"\n--- Result ---")
    for k, v in sorted(cnt.items()):
        print(f"  {k}: {v}")
    print(f"  total: {sum(cnt.values())}")


if __name__ == "__main__":
    main()
