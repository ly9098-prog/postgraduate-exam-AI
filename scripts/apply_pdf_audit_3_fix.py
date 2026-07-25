"""
Apply fixes from question_imports_pdf_audit_2.md (third audit report).
Fixes ~62 IDs: options, content, merges, and fill missing I-IV statements.
"""
import json
import sqlite3
import uuid
from datetime import datetime

DB_PATH = "/home/lmh/projects/postgraduate-ai/backend/postgraduate.db"
BATCH_PREFIX = "AUDIT3_20260722"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def make_content(text, segments=None, render_mode=None):
    obj = {"text": text}
    if render_mode:
        obj["render_mode"] = render_mode
    if segments:
        obj["segments"] = segments
    return json.dumps(obj, ensure_ascii=False)

def make_options(opts):
    return json.dumps(opts, ensure_ascii=False)

def update_record(id_val, content_obj, options_obj, batch_id=None, requires_review=None):
    """Update parsed_content, parsed_options for a single ID."""
    content_json = json.dumps(content_obj, ensure_ascii=False) if isinstance(content_obj, dict) else content_obj
    options_json = json.dumps(options_obj, ensure_ascii=False) if isinstance(options_obj, dict) else options_obj

    parts = [
        "parsed_content = ?",
        "parsed_options = ?",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    params = [content_json, options_json]

    if batch_id:
        parts.append("batch_id = ?")
        params.append(batch_id)

    params.append(id_val)
    cur.execute(f"UPDATE question_imports SET {', '.join(parts)} WHERE id = ?", params)

def supersede_record(id_val, reason="superseded-merge"):
    """Mark a record as superseded (duplicate/fragment)."""
    cur.execute("""
        UPDATE question_imports
        SET status = 'superseded',
            superseded_by_batch_id = ?,
            updated_at = CURRENT_TIMESTAMP,
            review_note = ?
        WHERE id = ?
    """, (BATCH_PREFIX, reason, id_val))

def set_hold(id_val, reason):
    """Set a record to hold status."""
    cur.execute("""
        UPDATE question_imports
        SET requires_review = 1,
            review_note = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (reason, id_val))

print("=== Fixing Section 2: Options/Content fixes ===")

# === ID 16 === fix options C, D
update_record(16,
    {"text": "【2009 统考真题】单处理机系统中，可并行的是()。\n\nI. 进程与进程 \nII. 处理机与设备 \nIII. 处理机与通道 \nIV. 设备与设备"},
    {"A": "I、II、III", "B": "I、II、IV", "C": "I、III、IV", "D": "II、III、IV"})
print("  16: fixed options C, D")

# === ID 88 === fix options
update_record(88,
    {"text": "在单处理器系统中，若同时存在10个进程，则处于就绪队列中的进程最多有()个。"},
    {"A": "1", "B": "8", "C": "9", "D": "10"})
print("  88: fixed options")

# === ID 112 === fix options
update_record(112,
    {"text": "当()时，进程从执行状态转变为就绪态。"},
    {"A": "进程被调度程序选中", "B": "时间片到", "C": "等待某一事件", "D": "等待的事件发生"})
print("  112: fixed options")

# === ID 115 === fix options
update_record(115,
    {"text": "进程处于()时，它处于非阻塞态。"},
    {"A": "等待从键盘输入数据", "B": "等待协作进程的一个信号", "C": "等待操作系统分配CPU时间", "D": "等待网络数据进入内存"})
print("  115: fixed options")

# === ID 137 === fix options (content is correct)
update_record(137,
    {"text": "现在有三个同时到达的作业J1、J2和J3，它们的执行时间分别是T1、T2、T3，且T1<T2<T3。系统按单道方式运行且采用短作业优先调度算法，则平均周转时间是()。"},
    {"A": "T1+T2+T3", "B": "(3T1+2T2+T3)/3", "C": "(T1+T2+T3)/3", "D": "(T1+2T2+3T3)/3"})
print("  137: fixed options")

# === ID 138 === fix options
update_record(138,
    {"text": "设有三个作业，其运行时间分别是 2h,5h,3h,假定它们同时到达，并在同一台处理器上以单道方式运行，则平均周转时间最小的执行顺序是()。"},
    {"A": "J1、J2、J3", "B": "J3、J2、J1", "C": "J2、J1、J3", "D": "J1、J3、J2"})
print("  138: fixed options")

# === ID 139 === fix options (content is correct)
update_record(139,
    {"text": "采用时间片轮转调度算法分配CPU时，当处于运行态的进程用完一个时间片后，它的状态是()状态。"},
    {"A": "阻塞", "B": "运行", "C": "就绪", "D": "消亡"})
print("  139: fixed options")

# === ID 140 === fix options
update_record(140,
    {"text": "一个作业 8:00 到达系统，估计运行时间为 1h。若 10:00 开始执行该作业，其响应比是()。"},
    {"A": "2", "B": "1", "C": "3", "D": "0.5"})
print("  140: fixed options")

# === ID 147 === fix options (content is correct)
update_record(147,
    {"text": "在进程调度算法中，对短进程不利的是()。"},
    {"A": "短进程优先调度算法", "B": "先来先服务调度算法", "C": "高响应比优先调度算法", "D": "多级反馈队列调度算法"})
print("  147: fixed options")

# === ID 148 === fix options (content needs minor cleanup too)
update_record(148,
    {"text": "假设系统中所有进程同时到达，则使进程平均周转时间最短的是()调度算法。"},
    {"A": "先来先服务", "B": "短进程优先", "C": "时间片轮转", "D": "优先级"})
print("  148: fixed options and content cleanup")

# === ID 151 === fix options (content already has embedded table data)
update_record(151,
    {"text": "【2013 统考真题】某系统正在执行三个进程P1、P2和P3，各进程的计算(CPU)时间和I/O时间比例如下表所示。为提高系统资源利用率，合理的进程优先级设置应为()。\n表格：P1(计算时间90%，I/O时间10%)；P2(计算时间50%，I/O时间50%)；P3(计算时间15%，I/O时间85%)。"},
    {"A": "P1>P2>P3", "B": "P3>P2>P1", "C": "P2>P1=P3", "D": "P1>P2=P3"})
print("  151: fixed options")

# === ID 152 === fix options (content correct: 不可能导致饥饿)
update_record(152,
    {"text": "【2014 统考真题】下列调度算法中，不可能导致饥饿现象的是()。"},
    {"A": "时间片轮转", "B": "静态优先数调度", "C": "非抢占式短任务优先", "D": "抢占式短任务优先"})
print("  152: fixed options")

# === ID 153 === fix options (content has embedded table data, ok)
update_record(153,
    {"text": "【2017 统考真题】假设4个作业到达系统的时刻和运行时间如下表所示。系统在t=2时开始作业调度。若分别采用先来先服务和短作业优先调度算法，则选中的作业分别是()。\n表格：J1(到达时刻0，运行时间3)；J2(1，3)；J3(1，2)；J4(3，1)。"},
    {"A": "J2、J3", "B": "J1、J4", "C": "J2、J4", "D": "J1、J3"})
print("  153: fixed options")

# === ID 155 === fix options
update_record(155,
    {"text": "【2018 统考真题】某系统采用基于优先权的非抢占式进程调度策略，完成一次进程调度和进程切换的系统时间开销为1μs。在T时刻就绪队列中有3个进程P1、P2和P3，其在就绪队列中的等待时间、需要的CPU时间和优先权如下表所示。若优先权值大的进程优先获得CPU，从T时刻起系统开始进程调度，则系统的平均周转时间为()。\n表格：P1(等待时间30μs，需要的CPU时间12μs，优先权10)；P2(15μs，24μs，30)；P3(18μs，36μs，20)。"},
    {"A": "54μs", "B": "73μs", "C": "74μs", "D": "75μs"})
print("  155: fixed options")

# === ID 158 === fix option C (仅I、II → 仅I、II、III)
update_record(158,
    {"text": "【2021 统考真题】在下列内核的数据结构或程序中，分时系统实现时间片轮转调度需要使用的是()。\nI.进程控制块\nII.时钟中断处理程序\nIII.进程就绪队列\nIV.进程阻塞队列"},
    {"A": "仅II、III", "B": "仅I、IV", "C": "仅I、II、III", "D": "仅I、II、IV"})
print("  158: fixed option C")

# === ID 190 === fix options; content needs III/IV corrected
update_record(190,
    {"text": "下列关于 PV 操作的说法中，正确的是()。\nI.PV操作是一种系统调用命令\nII.PV操作是一种低级进程通信原语\nIII.PV操作是由一个不可被中断的过程组成\nIV.PV操作是由两个不可被中断的过程组成"},
    {"A": "I、III", "B": "II、IV", "C": "I、II、IV", "D": "I、IV"})
print("  190: fixed options, content III/IV may need review")

# === ID 245 === fix options (content is correct with image reference)
update_record(245,
    {"text": "设内存的分配情况如下图所示。若要申请一块40KB的内存空间，采用最佳适应算法，则所得到的分区首址为()。"},
    {"A": "100K", "B": "190K", "C": "330K", "D": "410K"})
print("  245: fixed options")

# === ID 247 === fix options
update_record(247,
    {"text": "动态重定位是在作业的()中进行的。"},
    {"A": "编译过程", "B": "装入过程", "C": "链接过程", "D": "执行过程"})
print("  247: fixed options")

# === ID 248 === fix options
update_record(248,
    {"text": "下面的存储管理方案中,()方式可以采用静态重定位。"},
    {"A": "固定分区", "B": "可变分区", "C": "页式", "D": "段式"})
print("  248: fixed options")

# === ID 249 === fix options
update_record(249,
    {"text": "在可变分区管理中，采用拼接技术的目的是()。"},
    {"A": "合并空闲区", "B": "合并分配区", "C": "增加主存容量", "D": "便于地址转换"})
print("  249: fixed options")

# === ID 251 === fix options
update_record(251,
    {"text": "不会产生内部碎片的存储管理是()。"},
    {"A": "分页式存储管理", "B": "分段式存储管理", "C": "固定分区式存储管理", "D": "段页式存储管理"})
print("  251: fixed options")

# === ID 253 === fix options
update_record(253,
    {"text": "分区管理中采用最佳适应分配算法时，把空闲区按()次序登记在空闲区表中。"},
    {"A": "长度递增", "B": "长度递减", "C": "地址递增", "D": "地址递减"})
print("  253: fixed options")

# === ID 255 === fix options
update_record(255,
    {"text": "采用分页或分段管理后，提供给用户的物理地址空间()。"},
    {"A": "分页支持更大的物理地址空间", "B": "分段支持更大的物理地址空间", "C": "不能确定", "D": "一样大"})
print("  255: fixed options")

# === ID 256 === fix options
update_record(256,
    {"text": "分页系统中的页面是为()。"},
    {"A": "用户所感知的", "B": "操作系统所感知的", "C": "编译系统所感知的", "D": "连接装配程序所感知的"})
print("  256: fixed options")

# === ID 257 === fix options
update_record(257,
    {"text": "页式存储管理中，页表的始地址存放在()中。"},
    {"A": "内存", "B": "存储页表", "C": "快表", "D": "寄存器"})
print("  257: fixed options")

# === ID 259 === fix options
update_record(259,
    {"text": "采用段式存储管理时，一个程序如何分段是在()时决定的。"},
    {"A": "分配主存", "B": "用户编程", "C": "装作业", "D": "程序执行"})
print("  259: fixed options")

# === ID 263 === fix options
update_record(263,
    {"text": "可重入程序是通过()方法来改善系统性能的。"},
    {"A": "改变时间片长度", "B": "改变用户数", "C": "提高对换速度", "D": "减少对换数量"})
print("  263: fixed options")

# === ID 306 === fix option C (2^32 not 232)
update_record(306,
    {"text": "设主存容量为1MB，外存容量为400MB，计算机系统的地址寄存器有32位，那么虚拟存储器的最大容量是()。"},
    {"A": "1MB", "B": "401MB", "C": "1MB+2^32MB", "D": "232B"})
print("  306: fixed option C (2^32)")

# === ID 307 === fix completely (wrong options shifted from 306)
update_record(307,
    {"text": "虚拟存储器的最大容量()"},
    {"A": "为内外存容量之和", "B": "由计算机的地址结构决定", "C": "是任意的", "D": "由作业的地址空间决定"})
print("  307: fixed options")

# === ID 313 === fix options
update_record(313,
    {"text": "请求分页存储管理的主要特点是()。"},
    {"A": "消除了页内零头", "B": "扩充了内存", "C": "便于动态链接", "D": "便于信息共享"})
print("  313: fixed options")

# === ID 340 === fix options
update_record(340,
    {"text": "文件系统在创建一个文件时，为它建立一个()。"},
    {"A": "文件目录项", "B": "目录文件", "C": "逻辑结构", "D": "逻辑空间"})
print("  340: fixed options")

# === ID 347 === fix options
update_record(347,
    {"text": "对一个文件的访问，常由()共同限制。"},
    {"A": "用户访问权限和文件属性", "B": "用户访问权限和用户优先级", "C": "优先级和文件属性", "D": "文件属性和口令"})
print("  347: fixed options")

# === ID 350 === fix options
update_record(350,
    {"text": "下列说法中,()属于文件的逻辑结构的范畴。"},
    {"A": "连续文件", "B": "系统文件", "C": "链接文件", "D": "流式文件"})
print("  350: fixed options")

# === ID 352 === fix options
update_record(352,
    {"text": "索引文件由逻辑文件和()组成。"},
    {"A": "符号表", "B": "索引表", "C": "交叉访问表", "D": "链接表"})
print("  352: fixed options")

# === ID 357 === fix options
update_record(357,
    {"text": "在以下文件的物理结构中，不利于文件长度动态增长的是()。"},
    {"A": "连续结构", "B": "链接结构", "C": "索引结构", "D": "散列结构"})
print("  357: fixed options")

# === ID 361 === fix options
update_record(361,
    {"text": "文件系统采用两级索引分配方式。若每个磁盘块的大小为1KB,每个盘块号占4B,则该系统中，单个文件的最大长度是()。"},
    {"A": "64MB", "B": "128MB", "C": "32MB", "D": "以上答案都不对"})
print("  361: fixed options")

# === ID 362 === fix options
update_record(362,
    {"text": "设有一个记录文件，采用链接分配方式，逻辑记录的固定长度为100B,在磁盘上存储时采用记录成组分解技术。盘块长度为512B。若该文件的目录项已经读入内存，则对第22个逻辑记录完成修改后，共启动了磁盘()次。"},
    {"A": "3", "B": "4", "C": "5", "D": "6"})
print("  362: fixed options")

# === ID 400 === fix options
update_record(400,
    {"text": "在操作系统中,()指的是一种硬件机制。"},
    {"A": "通道技术", "B": "缓冲池", "C": "SPOOLing技术", "D": "内存覆盖技术"})
print("  400: fixed options")

# === ID 418 === fix options
update_record(418,
    {"text": "设从磁盘将一块数据传送到缓冲区所用的时间为80μs,将缓冲区中的数据传送到用户区所用的时间为40μs,CPU处理一块数据所用的时间为30μs。若有多块数据需要处理，并采用单缓冲区传送某磁盘数据，则处理一块数据所用的总时间为()。"},
    {"A": "120μs", "B": "110μs", "C": "150μs", "D": "70μs"})
print("  418: fixed options and content cleanup")

# === ID 426 === fix options
update_record(426,
    {"text": "下面设备中属于共享设备的是()。"},
    {"A": "打印机", "B": "磁带机", "C": "磁盘", "D": "磁带机和磁盘"})
print("  426: fixed options and content cleanup")

# === ID 434 === fix options
update_record(434,
    {"text": "设一个磁道访问请求序列为55,58,39,18,90,160,150,38,184,磁头的起始位置为100,若采用SSTF(最短寻道时间优先)算法，则磁头移动()个磁道。"},
    {"A": "55", "B": "184", "C": "200", "D": "248"})
print("  434: fixed options and content cleanup")

# === ID 436 === fix options
update_record(436,
    {"text": "下列关于固态硬盘(SSD)的说法中，错误的是()。"},
    {"A": "基于闪存的存储技术", "B": "随机读写性能明显高于磁盘", "C": "随机写比较慢", "D": "不易磨损"})
print("  436: fixed options")

print("")
print("=== Section 3: Content merges, full replacements, I-IV fills ===")

# === 3.1 ID 79: Full replacement ===
update_record(79,
    {"text": "下列关于虚拟机的说法中，正确的是()。\nI. 虚拟机可以用软件实现\nII. 虚拟机可以用硬件实现\nIII. 多台虚拟机可同时运行在同一物理机器上，它实现了真正的并行"},
    {"A": "I和II", "B": "I和III", "C": "仅I", "D": "I、II和III"})
print("  79: full replacement")

# === 3.2-3.3 ID 121+122: Merge into 121, supersede 122 ===
update_record(121,
    {"text": "【2010统考真题】下列选项中，导致创建新进程的操作是()。\nI. 用户登录成功\nII. 设备分配\nIII. 启动程序执行"},
    {"A": "仅I和II", "B": "仅II和III", "C": "仅I和III", "D": "I、II、III"})
supersede_record(122, "superseded-merged-into-121")
print("  121: updated with full content and options, 122 superseded")

# === 3.4 ID 134: Full replacement ===
update_record(134,
    {"text": "进程（线程）调度的时机有()。\nI. 运行的进程（线程）运行完毕\nII. 运行的进程（线程）所需资源未准备好\nIII. 运行的进程（线程）的时间片用完\nIV. 运行的进程（线程）自我阻塞\nV. 运行的进程（线程）出现错误"},
    {"A": "II、III、IV和V", "B": "I和III", "C": "II、IV和V", "D": "全部都是"})
print("  134: full replacement")

# === 3.5 ID 145: Full replacement ===
update_record(145,
    {"text": "有以下的进程需要调度执行（见下表）：\nP1：到达时间0.0，运行时间9\nP2：到达时间0.4，运行时间4\nP3：到达时间1.0，运行时间1\nP4：到达时间5.5，运行时间4\nP5：到达时间7，运行时间2\n1）若用非抢占式短进程优先调度算法，问这5个进程的平均周转时间是多少？\n2）若采用抢占式短进程优先调度算法，问这5个进程的平均周转时间是多少？"},
    {"A": "8.62；6.34", "B": "8.62；6.8", "C": "10.62；6.34", "D": "10.62；6.8"})
print("  145: full replacement with table data")

# === 3.6 ID 156: Full replacement ===
update_record(156,
    {"text": "【2019统考真题】系统采用二级反馈队列调度算法进行进程调度。就绪队列Q1采用时间片轮转调度算法，时间片为10ms；就绪队列Q2采用短进程优先调度算法；系统优先调度Q1队列中的进程，当Q1为空时系统才会调度Q2中的进程；新创建的进程首先进入Q1；Q1中的进程执行一个时间片后，若未结束，则转入Q2。若当前Q1、Q2为空，系统依次创建进程P1、P2后即开始进程调度，P1、P2需要的CPU时间分别为30ms和20ms，则进程P1、P2在系统中的平均等待时间为()。"},
    {"A": "25ms", "B": "20ms", "C": "15ms", "D": "10ms"})
print("  156: full replacement")

# === 3.7 ID 159: Full replacement ===
update_record(159,
    {"text": "【2021统考真题】下列事件中，可能引起进程调度程序执行的是()。\nI. 中断处理结束\nII. 进程阻塞\nIII. 进程执行结束\nIV. 进程的时间片用完"},
    {"A": "仅I、III", "B": "仅II、IV", "C": "仅III、IV", "D": "II、III和IV"})
print("  159: full replacement")

# === 3.8 ID 160: Full replacement ===
update_record(160,
    {"text": "【2022统考真题】进程P0、P1、P2和P3进入就绪队列的时刻、优先级（值越小优先权越高）及CPU执行时间如下：\nP0：0ms，优先级15，CPU执行时间100ms\nP1：10ms，优先级20，CPU执行时间60ms\nP2：10ms，优先级10，CPU执行时间20ms\nP3：15ms，优先级6，CPU执行时间10ms\n若系统采用基于优先权的抢占式进程调度算法，则从0ms时刻开始调度，到4个进程都运行结束为止，发生进程调度的总次数为()。"},
    {"A": "4", "B": "5", "C": "6", "D": "7"})
print("  160: full replacement")

# === 3.9 ID 204: Full replacement ===
update_record(204,
    {"text": "【2020统考真题】下列准则中，实现临界区互斥机制必须遵循的是()。\nI. 两个进程不能同时进入临界区\nII. 允许进程访问空闲的临界资源\nIII. 进程等待进入临界区的时间是有限的\nIV. 不能进入临界区的执行态进程立即放弃CPU"},
    {"A": "仅I、IV", "B": "仅II、III", "C": "仅I、II、III", "D": "仅I、III、IV"})
print("  204: full replacement")

# === 3.10 ID 224: Full replacement ===
update_record(224,
    {"text": "系统的资源分配图在下列情况下，无法判断是否处于死锁状态的有()。\nI. 出现了环路\nII. 没有环路\nIII. 每种资源只有一个，并出现环路\nIV. 每个进程结点至少有一条请求边"},
    {"A": "I、II、III、IV", "B": "I、III、IV", "C": "I、IV", "D": "以上答案都不正确"})
print("  224: full replacement")

# === 3.11-3.12 ID 268+269: Merge into 268, supersede 269 ===
update_record(268,
    {"text": "在页式存储管理中选择页面的大小，需要考虑下列()因素。\nI. 页面大的好处是页表比较少\nII. 页面小的好处是可以减少由内碎片引起的内存浪费\nIII. 影响磁盘访问时间的主要因素通常不是页面大小，所以使用时优先考虑较大的页面"},
    {"A": "I和III", "B": "II和III", "C": "I和II", "D": "I、II和III"})
supersede_record(269, "superseded-merged-into-268")
print("  268: updated with full content, 269 superseded")

# === 3.13-3.14 ID 358+359: Merge into 358, supersede 359 ===
update_record(358,
    {"text": "文件系统中若文件的物理结构采用连续结构，则FCB中有关文件的物理位置的信息应包括()。\nI. 首块地址\nII. 文件长度\nIII. 索引表地址"},
    {"A": "仅I", "B": "I、II", "C": "II、III", "D": "I、III"})
supersede_record(359, "superseded-merged-into-358")
print("  358: updated with full content, 359 superseded")

# === 3.15-3.16 ID 391+392: Merge into 391, supersede 392 ===
update_record(391,
    {"text": "【2019统考真题】下列选项中，可用于文件系统管理空闲磁盘块的数据结构是()。\nI. 位图\nII. 索引结点\nIII. 空闲磁盘块链\nIV. 文件分配表（FAT）"},
    {"A": "仅I、II", "B": "仅I、III、IV", "C": "仅I、III", "D": "仅II、III、IV"})
supersede_record(392, "superseded-merged-into-391")
print("  391: updated with full content, 392 superseded")

# === 3.17 ID 422: Supersede (423 has the complete version) ===
supersede_record(422, "superseded-423-has-complete-version")
print("  422: superseded (423 is complete)")

# === 3.18 ID 439: Add I-IV statements ===
update_record(439,
    {"text": "【2017统考真题】下列选项中，磁盘逻辑格式化程序所做的工作是()。\nI. 对磁盘进行分区\nII. 建立文件系统的根目录\nIII. 确定磁盘扇区校验码所占位数\nIV. 对保存空闲磁盘块信息的数据结构进行初始化"},
    {"A": "仅II", "B": "仅II、IV", "C": "仅III、IV", "D": "仅I、II、IV"})
print("  439: added I-IV statements")

# === 3.19 ID 471: Add I-III statements ===
update_record(471,
    {"text": "【2019统考真题】下列选项中，可能会将进程唤醒的事件是()。\nI. I/O结束\nII. 某进程退出临界区\nIII. 当前进程的时间片用完"},
    {"A": "仅I", "B": "仅II", "C": "仅I、II", "D": "I、II、III"})
print("  471: added I-III statements")

# === 3.20 ID 576: Supersede (duplicate of 439, keep 439) ===
# parsed_content currently has "20." prefix which is page number artifact
# Mark as superseded, keep 439
supersede_record(576, "superseded-duplicate-of-439")
print("  576: superseded (duplicate of 439)")

print("")
print("=== Section 2 continued: Fixes with content changes ===")

# Some IDs from section 2 also need content updates that were noted

# ID 148 - already fixed above
# ID 155 - already fixed above
# ID 156 - already fixed as full replacement

# The chain-shift for IDs 245-263 has been fixed above

# Fix the content of 418 (the slope/backslash issue)
# Already handled above with content cleanup

print("")
print("=== All fixes applied ===")

conn.commit()

# Verification
print("")
print("=== Verification: count fixes ===")
for row in cur.execute("SELECT id, status FROM question_imports WHERE id IN (122, 269, 359, 392, 422, 576)"):
    print(f"  ID {row['id']}: status={row['status']}")

print("")
print("Records updated:")
for row in cur.execute("""
    SELECT COUNT(*) as cnt FROM question_imports
    WHERE batch_id = ? AND status = 'pending'
""", (BATCH_PREFIX,)):
    print(f"  {row['cnt']} records with batch_id={BATCH_PREFIX}")

print("")
print("Superseded records:")
for row in cur.execute("""
    SELECT id, status, review_note FROM question_imports
    WHERE superseded_by_batch_id = ?
""", (BATCH_PREFIX,)):
    print(f"  ID {row['id']}: {row['status']} - {row['review_note']}")

conn.close()
