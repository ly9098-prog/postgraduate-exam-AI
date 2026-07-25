"""
Apply fixes from docs/audit/question_imports_audit_3.md (third audit report).
Fixes 22 IDs: content/option fixes, I-IV/V statements, superscript cleanups, restores.
"""
import json
import sqlite3

DB_PATH = "/home/lmh/projects/postgraduate-ai/backend/postgraduate.db"
BATCH_PREFIX = "AUDIT3_V2_20260723"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def update_record(id_val, content_obj, options_obj=None, segments_override=None):
    content_json = json.dumps(content_obj, ensure_ascii=False) if isinstance(content_obj, dict) else content_obj
    parts = ["parsed_content = ?", "updated_at = CURRENT_TIMESTAMP"]
    params = [content_json]
    if options_obj is not None:
        options_json = json.dumps(options_obj, ensure_ascii=False) if isinstance(options_obj, dict) else options_obj
        parts.append("parsed_options = ?")
        params.append(options_json)
    if segments_override is not None:
        obj = json.loads(content_json)
        obj["segments"] = segments_override
        obj["render_mode"] = "segments"
        parts[0] = "parsed_content = ?"
        params[0] = json.dumps(obj, ensure_ascii=False)
    params.append(id_val)
    cur.execute(f"UPDATE question_imports SET {', '.join(parts)} WHERE id = ?", params)

def restore_record(id_val):
    cur.execute("""
        UPDATE question_imports
        SET status = 'pending',
            superseded_by_batch_id = NULL,
            superseded_at = NULL,
            review_note = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (id_val,))

def set_clean_segments(id_val, text_content):
    """Remove empty/broken segments, keep only text segment."""
    obj = {"text": text_content}
    update_record(id_val, obj)

def make_content_obj(text):
    return {"text": text}

def make_options_obj(opts):
    return opts

def make_content_with_segments(text):
    return {
        "text": text,
        "render_mode": "segments",
        "segments": [{"type": "text", "text": text}]
    }

print("=== 1. Fixing ID 71: statement order swap + option B ===")
update_record(71,
    {"text": "对于以下四种服务，在采用微内核结构的操作系统中，()不宜放在微内核中。\nI.进程间通信机制\nII.低级I/O\nIII.低级进程管理和调度\nIV.中断和陷入处理\nV.文件系统服务"},
    {"A": "I、II和III", "B": "II和V", "C": "仅V", "D": "IV和V"})
print("  71: fixed II/III order swap, option B→II和V")

print("\n=== 2. Fixing ID 72: wrong options (shifted from previous question) ===")
update_record(72, None,
    {"A": "I、III、IV", "B": "I、II、IV", "C": "II、IV", "D": "I、IV"})
print("  72: fixed options")

print("\n=== 3. Fixing ID 104: broken parentheses ===")
update_record(104,
    {"text": "PCB 是进程存在的唯一标志，下列( )不属于PCB。"})
print("  104: fixed parentheses")

print("\n=== 4. Fixing ID 122: restore from superseded + replace content ===")
restore_record(122)
update_record(122,
    {"text": "下面关于用户级线程和内核级线程的描述中，错误的是( )。",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "下面关于用户级线程和内核级线程的描述中，错误的是( )。"}]},
    {"A": "采用轮转调度算法，进程中设置内核级线程和用户级线程的效果完全不同",
     "B": "跨进程的用户级线程调度也不需要内核参与，控制简单",
     "C": "用户级线程可以在任何操作系统中运行",
     "D": "若系统中只有用户级线程，则处理机的调度对象是进程"})
print("  122: restored + content replaced with user-level thread question")

print("\n=== 5. Fixing ID 189: B-D options replaced ===")
update_record(189, None,
    {"A": "S.value < 0", "B": "S.value <= 0", "C": "S.value > 0", "D": "S.value >= 0"})
print("  189: fixed options")

print("\n=== 6. Fixing ID 195: tail missing words ===")
update_record(195, {"text": "信箱通信是一种( )通信方式。"})
print("  195: added missing tail")

print("\n=== 7. Fixing ID 234: superscripts in options ===")
update_record(234, None,
    {"A": "P0,P2,P4,P1,P3", "B": "P1,P0,P3,P4,P2",
     "C": "P2,P1,P0,P3,P4", "D": "P3,P4,P2,P1,P0"})
print("  234: fixed superscripts in options")

print("\n=== 8. Fixing ID 236: add I-III statements ===")
update_record(236,
    {"text": "31.【2015统考真题】若系统S1采用死锁避免方法，S2采用死锁检测方法。下列叙述中，正确的是（ ）。\nI. S1会限制用户申请资源的顺序，而S2不会\nII. S1需要进程运行所需的资源总量信息，而S2不需要\nIII. S1不会给可能导致死锁的进程分配资源，而S2会"})
print("  236: added I-III statements")

print("\n=== 9. Fixing ID 237: superscripts in content and options ===")
update_record(237,
    {"text": "【2018统考真题】假设系统中有4个同类资源，进程P1、P2和P3需要的资源数分别为4、3和1，P1、P2和P3已申请到的资源数分别为2、1和0，则执行安全性检测算法的结果是( )。",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "【2018统考真题】假设系统中有4个同类资源，进程P1、P2和P3需要的资源数分别为4、3和1，P1、P2和P3已申请到的资源数分别为2、1和0，则执行安全性检测算法的结果是( )。"}]},
    {"A": "不存在安全序列，系统处于不安全状态",
     "B": "存在多个安全序列，系统处于安全状态",
     "C": "存在唯一安全序列P3、P1、P2，系统处于安全状态",
     "D": "存在唯一安全序列P3、P2、P1，系统处于安全状态"})
print("  237: fixed superscripts in content and options, removed empty segments")

print("\n=== 10. Fixing ID 245: add memory partition table data ===")
update_record(245,
    {"text": "设内存的分配情况如下图所示。若要申请一块40KB的内存空间，采用最佳适应算法，则所得到的分区首址为( )。\n内存分区：0-100K(操作系统) 100K-180K(空闲) 180K-190K(占用) 190K-280K(空闲) 280K-330K(占用) 330K-390K(空闲) 390K-410K(占用) 410K-512K(空闲)",
     "render_mode": "segments",
     "segments": [
         {"type": "text", "text": "设内存的分配情况如下图所示。若要申请一块40KB的内存空间，采用最佳适应算法，则所得到的分区首址为( )。"},
         {"type": "newline"},
         {"type": "table_data", "data": [
             ["地址范围", "状态"],
             ["0-100K", "操作系统"],
             ["100K-180K", "空闲"],
             ["180K-190K", "占用"],
             ["190K-280K", "空闲"],
             ["280K-330K", "占用"],
             ["330K-390K", "空闲"],
             ["390K-410K", "占用"],
             ["410K-512K", "空闲"]
         ]}
     ]})
print("  245: added partition table data")

print("\n=== 11. Fixing ID 294: virtual address field order ===")
update_record(294,
    {"text": "【2019统考真题】某计算机主存按字节编址，采用二级分页存储管理，地址结构如下：页目录号(10位) | 页号(10位) | 页内偏移(12位)。虚拟地址20501225H对应的页目录号、页号分别是( )。",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "【2019统考真题】某计算机主存按字节编址，采用二级分页存储管理，地址结构如下：页目录号(10位) | 页号(10位) | 页内偏移(12位)。虚拟地址20501225H对应的页目录号、页号分别是( )。"}]})
print("  294: fixed address field order, removed empty segments")

print("\n=== 12. Fixing ID 330: statement order + option A ===")
update_record(330,
    {"text": "【2014统考真题】在页式虚拟存储管理系统中，采用某些页面置换算法会出现Belady异常现象，即进程的缺页次数会随着分配给该进程的页框个数的增加而增加。下列算法中，可能出现Belady异常现象的是( )。\nI. LRU算法\nII. FIFO算法\nIII. OPT算法",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "【2014统考真题】在页式虚拟存储管理系统中，采用某些页面置换算法会出现Belady异常现象，即进程的缺页次数会随着分配给该进程的页框个数的增加而增加。下列算法中，可能出现Belady异常现象的是( )。\nI. LRU算法\nII. FIFO算法\nIII. OPT算法"}]},
    {"A": "仅II", "B": "仅I、II", "C": "仅I、III", "D": "仅II、III"})
print("  330: fixed statement order and option A (仅I→仅II), removed empty segments")

print("\n=== 13. Fixing ID 336: scrambled statements replaced ===")
update_record(336,
    {"text": "【2020统考真题】下列因素中，影响请求分页系统有效(平均)访存时间的是( )。\nI.缺页率\nII.磁盘读写时间\nIII.内存访问时间\nIV.执行缺页处理程序的CPU时间"})
print("  336: replaced with clean I-IV statements")

print("\n=== 14. Fixing ID 337: table column order + modified bit fix ===")
update_record(337,
    {"text": "41.【2021统考真题】某请求分页存储系统的页大小为4KB，按字节编址。系统给进程P分配2个固定的页框，并采用改进型Clock置换算法，进程P页表的部分内容见下表。\n页号  页框号  存在位  访问位  修改位\n2    20H    0      0      0\n3    60H    1      1      0\n4    80H    1      1      1\n存在位：1=存在、0=不存在；访问位：1=访问、0=未访问；修改位：1=修改、0=未修改。\n若P访问虚拟地址为02A01H的存储单元，则经地址变换后得到的物理地址是( )。",
     "stem": "【2021统考真题】某请求分页存储系统的页大小为4KB，按字节编址。系统给进程P分配2个固定的页框，并采用改进型Clock置换算法。若P访问虚拟地址为02A01H的存储单元，则经地址变换后得到的物理地址是( )。",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "41.【2021统考真题】某请求分页存储系统的页大小为4KB，按字节编址。系统给进程P分配2个固定的页框，并采用改进型Clock置换算法，进程P页表的部分内容见下表。"},
         {"type": "newline"},
         {"type": "table_data", "data": [
             ["页号", "页框号", "存在位", "访问位", "修改位"],
             ["2", "20H", "0", "0", "0"],
             ["3", "60H", "1", "1", "0"],
             ["4", "80H", "1", "1", "1"]
         ]},
         {"type": "newline"},
         {"type": "text", "text": "存在位：1=存在、0=不存在；访问位：1=访问、0=未访问；修改位：1=修改、0=未修改。"},
         {"type": "newline"},
         {"type": "text", "text": "若P访问虚拟地址为02A01H的存储单元，则经地址变换后得到的物理地址是( )。"}]})
print("  337: fixed table column order and page 4 modified bit")

print("\n=== 15. Fixing ID 384: F² superscript → F2 ===")
update_record(384,
    {"text": "【2009统考真题】设文件F1的当前引用计数值为1，先建立文件F1的符号链接(软链接)文件F2，再建立文件F1的硬链接文件F3，然后删除文件F1。此时，文件F2和文件F3的引用计数值分别是( )。",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "【2009统考真题】设文件F1的当前引用计数值为1，先建立文件F1的符号链接(软链接)文件F2，再建立文件F1的硬链接文件F3，然后删除文件F1。此时，文件F2和文件F3的引用计数值分别是( )。"}]})
print("  384: fixed F²→F2, removed empty segments")

print("\n=== 16. Fixing ID 446: duplicate parentheses ===")
update_record(446, {"text": "3.下列选项中，不属于多道程序设计的基本特征的是( )。"})
print("  446: fixed double parentheses")

print("\n=== 17. Fixing ID 447: add I-VI application scenarios ===")
update_record(447,
    {"text": "8.下列( )应用工作最好采用实时操作系统平台。\nI.航空订票\nII.办公自动化\nIII.机床控制\nIV.AutoCAD\nV.工资管理系统\nVI.股票交易系统",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "8.下列( )应用工作最好采用实时操作系统平台。\nI.航空订票\nII.办公自动化\nIII.机床控制\nIV.AutoCAD\nV.工资管理系统\nVI.股票交易系统"}]})
print("  447: added I-VI statements")

print("\n=== 18. Fixing ID 495: two questions concatenated → restore to Q42 ===")
update_record(495,
    {"text": "42.【2011统考真题】有两个并发执行的进程P1和进程P2，共享初值为1的变量x。P1对x加1，P2对x减1。加1和减1操作的指令序列如下。两个操作完成后，x的值( )。",
     "render_mode": "segments",
     "segments": [
         {"type": "text", "text": "42.【2011统考真题】有两个并发执行的进程P1和进程P2，共享初值为1的变量x。P1对x加1，P2对x减1。加1和减1操作的指令序列如下。"},
         {"type": "newline"},
         {"type": "code_image", "url": "/static/question-assets/code_region_216_peterson.webp",
          "alt": "加1和减1操作的指令序列", "display": True, "region_type": "code",
          "source_page": 216, "requires_review": False},
         {"type": "newline"},
         {"type": "text", "text": "两个操作完成后，x的值( )。"}
     ]})
print("  495: restored to Q42 (2011 shared variable)")

print("\n=== 19. Fixing ID 513: lost exponential notation and address structure ===")
update_record(513,
    {"text": "47.【2010统考真题】某计算机采用二级页表的分页存储管理方式，按字节编址，页大小为2^10B，页表项大小为2B，逻辑地址结构为\"页目录号 | 页号 | 页内偏移量\"，逻辑地址空间大小为2^16页，则表示整个逻辑地址空间的页目录表中包含表项的个数至少是( )。"})
print("  513: fixed exponential notation and address structure")

print("\n=== 20. Fixing ID 531: add I-III statements ===")
update_record(531,
    {"text": "9.【2017统考真题】若文件f1的硬链接为f2，两个进程分别打开f1和f2，获得对应的文件描述符为fd1和fd2，则下列叙述中正确的是( )。\nI. f1和f2的读写指针位置保持相同\nII. f1和f2共享同一个内存索引结点\nIII. fd1和fd2分别指向各自的用户打开文件表中的一项",
     "render_mode": "segments",
     "segments": [{"type": "text", "text": "9.【2017统考真题】若文件f1的硬链接为f2，两个进程分别打开f1和f2，获得对应的文件描述符为fd1和fd2，则下列叙述中正确的是( )。\nI. f1和f2的读写指针位置保持相同\nII. f1和f2共享同一个内存索引结点\nIII. fd1和fd2分别指向各自的用户打开文件表中的一项"}]})
print("  531: added I-III statements")

print("\n=== 21. Fixing ID 540: single character misrecognition ===")
update_record(540, None,
    {"A": "设备控制器和通道可以分别控制设备",
     "B": "对于同一组输入/输出命令，设备控制器、通道和设备可以并行工作",
     "C": "通道控制设备控制器、设备控制器控制设备工作",
     "D": "以上答案都不对"})
print("  540: fixed option A (按制→控制)")

print("\n=== 22. Fixing ID 548: duplicate parentheses ===")
update_record(548,
    {"text": "12.下面设备中属于共享设备的是( )。"})
print("  548: fixed double parentheses")

conn.commit()

print("\n=== Verification ===")
for row in cur.execute("""
    SELECT id, status, source_question_no,
           substr(parsed_content, 1, 80) as content_start
    FROM question_imports
    WHERE id IN (71, 72, 104, 122, 189, 195, 234, 236, 237, 245, 294,
                 330, 336, 337, 384, 446, 447, 495, 513, 531, 540, 548)
    ORDER BY id
"""):
    print(f"  ID {row['id']} (Q{row['source_question_no']}): {row['status']} — {row['content_start'][:60]}")

print("\nKept superseded (merge targets verified):")
for row in cur.execute("""
    SELECT id, status, review_note
    FROM question_imports
    WHERE id IN (269, 359, 392, 422, 576)
    ORDER BY id
"""):
    print(f"  ID {row['id']}: {row['status']} — {row['review_note']}")

conn.close()
print("\nDone: 22 IDs fixed, 5 kept superseded.")
