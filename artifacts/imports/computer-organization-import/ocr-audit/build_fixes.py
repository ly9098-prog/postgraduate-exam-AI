#!/usr/bin/env python3
"""Build ocr-audit/fixes.json — the full set of confirmed OCR fixes for cs_ds.

Each entry: {"id": <question_imports id>, "stem"|"options"|"source_page_end"|"review_note": ...}
Only fields that change are present. Watermark-only pages are cleaned programmatically
(verified clean above); special pages carry hand-derived stems from OCR ground truth.
"""
import json
import os
import re
import sqlite3

BASE = "/home/lmh/projects/postgraduate-ai"
c = sqlite3.connect(BASE + "/backend/postgraduate.db")
c.row_factory = sqlite3.Row

id_of_page = {r["source_page_start"]: r["id"] for r in c.execute(
    "SELECT id, source_page_start FROM question_imports WHERE subject_id=8")}


def get_stem(pg):
    r = c.execute("SELECT parsed_content FROM question_imports WHERE source_page_start=?", (pg,)).fetchone()
    return json.loads(r["parsed_content"])["text"]


# ---------------------------------------------------------------- watermark strip
def clean_wm(st):
    s = re.sub(r"\s*[【\[]\s*公众号\s*[:：]\s*风中易小生\s*[】\]]", "", st)
    s = re.sub(r"\(\s*\n\s*\)\s*。", "()。", s)
    s = re.sub(r"\(\s*\n\s*\)", "()", s)
    s = s.rstrip()
    return s


WM_ONLY = [23, 36, 52, 68, 88, 103, 166, 174, 183, 194, 224, 251, 306, 314, 339,
           348, 355, 358, 370, 386, 402, 428, 447, 469, 475, 483]

fixes = []
for pg in WM_ONLY:
    st = get_stem(pg)
    cl = clean_wm(st)
    if cl != st:
        fixes.append({"id": id_of_page[pg], "stem": cl,
                      "review_note": "剥离页脚水印【公众号:风中易小生】"})


# ---------------------------------------------------------------- special stems
def add(pg, stem=None, options=None, page_end=None, note=None):
    e = {"id": id_of_page[pg]}
    if stem is not None:
        e["stem"] = stem
    if options is not None:
        e["options"] = options
    if page_end is not None:
        e["source_page_end"] = page_end
    if note:
        e["review_note"] = note
    fixes.append(e)


# ---- C4: roman item fixes (stems) ----
add(17, stem="只有当程序执行时才将源程序翻译成机器语言，并且一次只能翻译一行语句，边翻译边执行的是()程序，把汇编语言源程序转变为机器语言程序的过程是()。\n"
              "I.编译\nII.目标\nIII.汇编\nIV.解释", note="罗马序号 III.汇编 由 OCR ⅢI 恢复")
add(25, stem="【2015 统考真题】计算机硬件能够直接执行的是(\nI.机器语言程序\nII.汇编语言程序\nIII.硬件描述语言程序",
    note="罗马序号 III.硬件描述语言程序 恢复")
add(31, stem="下列关于机器字长、指令字长和存储字长的说法中，正确的是(\n"
              "I.三者在数值上总是相等的\nII.三者在数值上可能不等\nIII.存储字长是存放在一个存储单元中的二进制代码位数\nIV.数据字长就是MDR的位数",
    note="罗马序号 III.存储字长 恢复")
add(48, stem="【2020 统考真题】下列给出的部件中，其位数(宽度)一定与机器字长相同的是(\n"
              "I.ALU\nII.指令寄存器\nIII.通用寄存器\nIV.浮点寄存器",
    options={"A": "仅I、II", "B": "仅I、III", "C": "仅II、III", "D": "仅II、III、IV"},
    note="罗马序号 II.指令寄存器 恢复；删除尾部答案线索 I、/III、IV；选项 B/C/D 按 OCR 恢复")
add(79, stem="【2018 统考真题】冯诺依曼结构计算机中的数据采用二进制编码表示，其主要原因是(\n"
              "I.二进制的运算规则简单\nII.制造两个稳态的物理器件较容易\nIII.便于用逻辑门电路实现算术运算",
    options={"A": "仅I、II", "B": "仅I、III", "C": "仅II、III", "D": "I、II和III"},
    note="罗马序号 II/III 恢复；选项 B/C/D 按 OCR 恢复")
add(140, stem="下列说法中，正确的是()。\n"
              "I.在计算机中，表示的数有时会发生溢出，根本原因是计算机的字长有限\nII.8421码就是二进制数\n"
              "III.一个正数的补码和这个数的原码表示一样，而正数的反码是原码各位取反\n"
              "IV.设有两个正的规格化浮点数N1=2mM和N=2M2,若m>n,则有N1>N2",
    note="罗马序号 III.一个正数的补码 恢复")
add(147, stem="下列关于舍入的说法，正确的是(\n"
              "I.不仅仅只有浮点数需要舍入，定点数在运算时也可能要舍入\nII.在浮点数舍入中，只有左规格化时可能要舍入\n"
              "III.在浮点数舍入中，只有右规格化时可能要舍入\nIV.在浮点数舍入中，左、右规格化均可能要舍入\nV.舍入不一定产生误差.",
    note="罗马序号 III.在浮点数舍入中…右规格化 恢复")
add(154, stem="【2015 统考真题】下列有关浮点数加减运算的叙述中，正确的是(\n"
              "I.对阶操作不会引起阶码上溢或下溢\nII.右规和尾数舍入都可能引起阶码上溢\n"
              "III.左规时可能引起阶码下溢\nIV.尾数溢出时结果不一定溢出.",
    note="罗马序号 II/III 恢复；删除尾部答案线索 I、/III、IV")
add(186, stem="下列(\n)是动态半导体存储器的特点。\nI.在工作中存储器内容会产生变化\n"
              "II.每隔一定时间，需要根据原存内容重新写入一遍\nIII.一次完整的刷新过程需要占用两个存储周期\n"
              "IV.一次完整的刷新过程只需要占用一个存储周期",
    options={"D": "只有III"}, note="罗马序号 II/III 恢复；选项D 只有III 恢复")
add(220, stem="【2013 统考真题】下列选项中，用于提高RAID可靠性的措施有(\n"
              "I.磁盘镜像\nII.条带化\nIII.奇偶校验\nIV.增加Cache机制",
    options={"A": "仅I、II", "B": "仅I、III", "C": "仅I、III和IV", "D": "仅II、III和IV"},
    note="罗马序号 III.奇偶校验 恢复；选项 A/B/C/D 按 OCR 恢复")
add(372, stem="在微程序控制方式中，以下说法正确的是(\n"
              "I.采用微程序控制器的处理器称为微处理器\nII.每条机器指令由一段微程序来解释执行\n"
              "III.在微指令的编码中，效率最低的是直接编码方式\nIV.水平型微指令能充分利用数据通路的并行结构",
    options={"A": "I、II"}, note="罗马序号 III 恢复；选项A I、II 恢复")
add(382, stem="【2019 统考真题】某指令功能为R[r2]←R[r1]+M[R[r0]]，其两个源操作数分别采用寄存器、寄存器间接寻址方式。对于下列给定部件，该指令在取数及执行过程中需要用到的是()。\n"
              "I.通用寄存器组(GPRs)\nII.算术逻辑单元(ALU)\nIII.存储器(Memory)\nIV.指令译码器(ID)",
    options={"A": "仅I、II", "B": "仅I、II、III", "C": "仅II、II、IV", "D": "仅I、III、IV"},
    note="删除尾部答案线索 II、/III、IV；选项 B/C/D 按 OCR 恢复；C 选项 OCR 原样为 仅II、II、IV（源页字形待核）")
add(435, stem="微机中控制总线上完整传输的信号有(\n"
               "I.存储器和I/O设备的地址码\nII.所有存储器和I/O设备的时序信号与控制信号\nIII.来自I/O设备和存储器的响应信号",
    note="罗马序号 III.来自I/O设备和存储器的响应信号 恢复")
add(450, stem="【2018统考真题】下列选项中，可提高同步总线数据传输率的是(\n"
               "I.增加总线宽度\nII.提高总线工作频率\nIII.支持突发传输\nIV.采用地址/数据线复用",
    note="罗马序号 III.支持突发传输 恢复；删除尾部答案线索 I、/II、III")
add(513, stem="【2010统考真题】单级中断系统中，中断服务程序内的执行顺序是(\n"
               "I.保护现场\nII.开中断\nIII.关中断\nIV.保存断点\nV.中断事件处理\nVI.恢复现场\nVII.中断返回",
    note="罗马序号 II.开中断 / III.关中断 恢复（原 I../II. 误读）")

# ---- C4 circle + C1 special stems ----
add(307, stem="假设P为调用过程，Q为被调用过程，程序在32位x86处理器上执行，以下是C语言程序中过程调用所涉及的操作:\n"
              "①过程Q保存P的现场，并为非静态局部变量分配空间\n②过程P将实参存放到Q能访问到的地方\n"
              "③过程P将返回地址存放到特定处，并转跳到Q执行\n④过程Q取出返回地址，并转跳回到过程P执行\n"
              "⑤过程Q恢复P的现场，并释放局部变量所占空间\n⑥执行过程Q的函数体\n过程调用的正确执行步骤是(",
    options={"A": "②→③→④→①→⑤→⑥", "B": "②→③→①→④→⑥→⑤",
             "C": "②→③→①→⑥→⑤→④", "D": "②→③→①→⑤→⑥"},
    note="补回⑤项标记；选项恢复 ②→ 顺序箭头")
add(76, stem="计算机内部的定点数大多用补码表示，以下是一些关于补码特点的叙述:\n"
              "I.零的表示是唯一的\nII.符号位可以和数值部分一起参加运算\nIII.和其真值的对应关系简单、直观\n"
              "IV.减法可用加法来实现\n在以上叙述中，()是补码表示的特点。",
    note="修复 IV 项与提问语尾的粘连及孤立')'")
add(141, stem="在浮点运算中，下溢指的是()。", note="剥离水印并修复重复空括号(\\n()")
add(118, stem="37.【2014 统考真题】若x=103，y=-25，则下列表达式采用8位定点补码运算实现时，会发生溢出的是()。",
    note="剥离水印并删除误嵌入题干的 4 个选项行")
add(205, stem="地址总线A0(高位)~A15(低位)，用4K×4位的存储芯片组成16KB存储器，则产生片选信号的译码器的输入地址线应该是()。",
    note="剥离水印；修复 A0/A15/4K×4 与重复空括号")
add(209, stem="如下图所示，若低位地址(A0~A11)接在内存芯片地址引脚上，高位地址(A12~A19)进行片选译码(其中A14和A16未参加译码)，且片选信号低电平有效，则对图中所示的译码电路，不属于此译码空间的地址是()。",
    options={"A": "AB000H~ABFFFH", "B": "BB000H~BBFFFH", "C": "EF000H~EFFFFH", "D": "FE000H~FEFFFH"},
    note="删除尾部图片标签'译码输出'；地址 0/O 修正；译码电路图为图片未截取，需人工补图")
add(415, stem="下列关于超线程(HT)技术的描述中，正确的是()。", note="修复重复空括号(\\n()")

# ---- C5 options ----
add(16, options={"A": "II、III"}, note="选项A II、III 恢复")
add(91, options={"A": "10010100 1", "B": "10010101 0", "C": "10010101 1", "D": "10010100 0"},
    note="选项恢复'寄存器值+进位标志'两列；D 的标志位为推断值(原页OCR未捕获末位)，需人工核对")
add(98, options={"A": "I和II"}, note="选项A I和II 恢复")
add(108, options={"B": "仅II", "C": "只有III"}, note="选项B 仅II、C 只有III 恢复")
add(171, options={"A": "仅I", "B": "仅I和II", "C": "I、II和III", "D": "仅II"}, note="选项 B/C/D 按 OCR 恢复")
add(252, options={"A": "I、III、IV", "C": "I、II、IV"}, note="选项 A/C 按 OCR 恢复(原II/III互换)")
add(283, options={"A": "((PC)+A)", "C": "(X)+(A)"}, note="选项 A/C 截断修复")
add(289, options={"B": "2002H,2040H", "C": "2002H,2042H", "D": "2000H,2040H"}, note="选项 B/C/D 第二值跨行截断修复")
add(383, options={"A": "仅I、II"}, note="选项A 仅I、II 恢复")
add(408, options={"A": "仅I、II", "B": "仅I、III", "C": "仅II、III", "D": "I、II和III"}, note="选项 A/B/C/D 按 OCR 恢复")
add(412, options={"B": "仅I、III"}, note="选项B 仅I、III 恢复")
add(420, options={"B": "I和II", "C": "I和III", "D": "I、II和III"}, note="选项 B/C/D 罗马恢复")
add(440, options={"D": "ISA、EISA、PCI、PCI-Express"}, note="选项D 截断修复")
add(485, options={"D": "I、III和V"}, note="选项D I、III和V 恢复")
add(486, stem="关于程序中断方式和DMA方式的叙述，错误的是(\n"
               "I.DMA的优先级比程序中断的优先级要高\nII.程序中断方式需要保护现场，DMA方式不需要保护现场\n"
               "III.程序中断方式的中断请求是为了报告CPU数据的传输结束，而DMA方式的中断请求完全是为了传送数据",
    options={"A": "仅II", "C": "仅III", "D": "I、II"},
    note="剥离水印；选项 A/C/D 罗马恢复")
add(488, options={"B": "仅III"}, note="选项B 仅III 恢复")
add(524, options={"D": "I、II和III"}, note="选项D I、II和III 恢复")

# ---- C3 tables ----
add(45, stem="【2013统考真题】某计算机的主频为1.2GHz，其指令分为4类，它们在基准程序中所占比例及CPI如下表所示。\n"
              "指令类型  所占比例  CPI\nA  50%  2\nB  20%  3\nC  10%  4\nD  20%  5\n该机的MIPS数是()。",
    note="恢复 CPI 表格数据")
add(255, stem="【2013 统考真题】某计算机主存地址空间大小为256MB，按字节编址。虚拟地址空间大小为4GB，采用页式存储管理，页面大小为4KB，TLB(快表)采用全相联映射，有4个页表项，内容如下表所示。\n"
              "有效位  标记  页框号\n?  FF180H  0002H\n?  3FFF1H  0035H\n?  02FF3H  0351H\n?  03FFFH  0153H\n"
              "则对虚拟地址03FFF180H进行虚实地址变换的结果是(",
    note="恢复 TLB 标记/页框号两列(0002H/0035H/0351H/0153H)；有效位列 OCR 乱码(00/主年/日)，标?待人工核对")
add(260, stem="【2022 统考真题】某计算机主存地址为24位，采用分页虚拟存储管理方式，虚拟地址空间大小为4GB，页大小为4KB，按字节编址。某进程的页表部分内容如下表所示。\n"
              "虚页号  实页号(页框号)  存在位\n082H  024H  ?\n129H  180H  ?\n130H  018H  ?\n"
              "当CPU访问虚拟地址0008 2840H时，虚-实地址转换的结果是()。",
    note="恢复页表虚页号/实页号两列(024H/180H/018H)；存在位列 OCR 乱码(=+=*)，标?待人工核对")

# ---- C6 contamination ----
add(126, stem="45.【2020 统考真题】在按字节编址，采用小端方式的32位计算机中，按边界对齐方式为以下C语言结构型变量a分配存储空间。\n"
              "struct recordl\nshort x1;\nint x2;\na;\n"
              "若a的首地址为2020 FE00H，a的成员变量x2的机器数为1234 0000H，则其中34H所在存储单元的地址是(",
    page_end=126, note="截断题干：删除误嵌入的本页选项与下一页(p127)整题；source_page_end 127→126")

# ---------------------------------------------------------------- write
path = os.path.join(BASE, "artifacts/computer-organization-import/ocr-audit/fixes.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(fixes, f, ensure_ascii=False, indent=1)
print("Wrote", len(fixes), "fixes ->", path)
