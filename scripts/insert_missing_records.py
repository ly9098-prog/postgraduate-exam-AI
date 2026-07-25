"""Insert 6 missing records from Section 4 of question_imports_pdf_audit_2.md"""
import json
import sqlite3

DB_PATH = "/home/lmh/projects/postgraduate-ai/backend/postgraduate.db"
BATCH_ID = "AUDIT3_MISSING_20260722"
SOURCE_FILE = "os_sc.pdf"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Find max existing ID
cur.execute("SELECT COALESCE(MAX(id), 0) FROM question_imports")
next_id = cur.fetchone()[0] + 1
print(f"Starting ID: {next_id}")

def make_raw_data(stem, opts):
    return json.dumps({
        'stem': stem,
        'options': [{'key': k, 'text': v} for k, v in opts.items()],
        'answer': '',
        'analysis': '',
        'subject': '操作系统',
        'subject_id': 9,
        'question_type': 'single_choice',
        'source': {'file': SOURCE_FILE, 'type': 'pdf'},
        'schema_version': 'v1',
        'quality_status': 'needs_manual_review',
        'quality_blockers': ['missing_answer_for_objective_question'],
        'is_valid': False,
        'errors': ['missing_answer']
    }, ensure_ascii=False)

records = [
    {
        'source_question_no': '9',
        'source_question_label': '9.',
        'parsed_content_text': '以下算法中，()可能出现"饥饿"现象。',
        'parsed_options': {'A': '电梯调度', 'B': '最短寻找时间优先', 'C': '循环扫描算法', 'D': '先来先服务'},
        'raw_stem': '以下算法中，（）可能出现"饥饿"现象。'
    },
    {
        'source_question_no': '11',
        'source_question_label': '11.',
        'parsed_content_text': '已知某磁盘的平均转速为r秒/转，平均寻找时间为T秒，每个磁道可以存储的字节数为N，现向该磁盘读写b字节的数据，采用随机寻道的方法，每道的所有扇区组成一个簇，其平均访问时间是()。',
        'parsed_options': {'A': '(r+T)b/N', 'B': 'b/NT', 'C': '(b/N+T)r', 'D': 'bT/N+r'},
        'raw_stem': '已知某磁盘的平均转速为r秒/转，平均寻找时间为T秒，每个磁道可以存储的字节数为N，现向该磁盘读写b字节的数据，采用随机寻道的方法，每道的所有扇区组成一个簇，其平均访问时间是（）。'
    },
    {
        'source_question_no': '12',
        'source_question_label': '12.',
        'parsed_content_text': '设磁盘的转速为3000转/分，盘面划分为10个扇区，则读取一个扇区的时间为()。',
        'parsed_options': {'A': '20ms', 'B': '5ms', 'C': '2ms', 'D': '1ms'},
        'raw_stem': '设磁盘的转速为3000转/分，盘面划分为10个扇区，则读取一个扇区的时间为（）。'
    },
    {
        'source_question_no': '13',
        'source_question_label': '13.',
        'parsed_content_text': '一个磁盘的转速为7200转/分，每个磁道有160个扇区，每扇区有512B，那么理想情况下，其数据传输率为()。',
        'parsed_options': {'A': '7200×160KB/s', 'B': '7200KB/s', 'C': '9600KB/s', 'D': '19200KB/s'},
        'raw_stem': '一个磁盘的转速为7200转/分，每个磁道有160个扇区，每扇区有512B，那么理想情况下，其数据传输率为（）。'
    },
    {
        'source_question_no': '19',
        'source_question_label': '19.',
        'parsed_content_text': '【2015统考真题】某硬盘有200个磁道（最外侧磁道号为0），磁道访问请求序列为130、42、180、15、199，当前磁头位于第58号磁道并从外侧向内侧移动。按照SCAN调度方法处理完上述请求后，磁头移过的磁道数是()。',
        'parsed_options': {'A': '208', 'B': '287', 'C': '325', 'D': '382'},
        'raw_stem': '【2015统考真题】某硬盘有200个磁道（最外侧磁道号为0），磁道访问请求序列为130、42、180、15、199，当前磁头位于第58号磁道并从外侧向内侧移动。按照SCAN调度方法处理完上述请求后，磁头移过的磁道数是（）。'
    },
    {
        'source_question_no': '21',
        'source_question_label': '21.',
        'parsed_content_text': '【2017统考真题】某文件系统的簇和磁盘扇区大小分别为1KB和512B。若一个文件的大小为1026B，则系统分配给该文件的磁盘空间大小是()。',
        'parsed_options': {'A': '1026B', 'B': '1536B', 'C': '1538B', 'D': '2048B'},
        'raw_stem': '【2017统考真题】某文件系统的簇和磁盘扇区大小分别为1KB和512B。若一个文件的大小为1026B，则系统分配给该文件的磁盘空间大小是（）。'
    }
]

inserted = 0
for r in records:
    cur.execute("""
        INSERT INTO question_imports (
            id, batch_id, source_type, source_file, subject_id, question_type,
            source_question_no, source_question_label, raw_data,
            parsed_content, parsed_options, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        next_id,
        BATCH_ID,
        'pdf',
        SOURCE_FILE,
        9,
        'single_choice',
        r['source_question_no'],
        r['source_question_label'],
        make_raw_data(r['raw_stem'], r['parsed_options']),
        json.dumps({'text': r['parsed_content_text']}, ensure_ascii=False),
        json.dumps(r['parsed_options'], ensure_ascii=False),
        'pending'
    ))
    print(f"  Inserted ID {next_id}: {r['parsed_content_text'][:60]}...")
    next_id += 1
    inserted += 1

conn.commit()
print(f"\nTotal: {inserted} records inserted")

# Verification
cur.execute("""
    SELECT id, source_question_no, source_question_label
    FROM question_imports
    WHERE batch_id = ?
    ORDER BY id
""", (BATCH_ID,))
rows = cur.fetchall()
print(f"Verification: {len(rows)} records found in DB")
for row in rows:
    print(f"  ID {row['id']}: no={row['source_question_no']} label={row['source_question_label']}")

conn.close()
