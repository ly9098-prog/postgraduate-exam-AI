"""Import 30 pages that PaddleOCR couldn't read, using MCP OCR results."""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import async_session
from app.features.review_service import submit_to_review

SUBJECT_ID = 7

# MCP OCR results for all 30 empty pages
# Format: {page_num: ocr_text}
MCP_RESULTS = {
    138: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n3.设主串的长度为n,子串的长度为m,则简单的模式匹配算法的时间复杂度为( ),KMP算法的时间复杂度为()。\nA. O(m)\nB.O(n)\nC.O(mn)\nD.O(m+n)',
    141: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n6.串\'ababaaababaa\'的 next 数组为()。\nA.-1,0,1,2,3,4,5,6,7,8,8,8\nB.-1,0,1,0,1,0,0,0,0,1,0,1\nC.-1,0,0,1,2,3,1,1,2,3,4,5\nD.-1,0,1,2,-1,0,1,2,1,1,2,3',
    142: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n7.串\'ababaaababaa\'的nextval 数组为()。\nA.0,1,0,1,1,2,0,1,0,1,0,2\nB.0,1,0,1,1,4,1,1,0,1,0,2\nC.0,1,0,1,0,4,2,1,0,1,0,4\nD.0,1,1,1,0,2,1,1,0,1,0,4',
    143: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n8.【2015 统考真题】已知字符串 S 为\'abaabaabacacaabaabcc\',模式串 t 为\' abaabc\'.采用 KMP 算法进行匹配，第一次出现"失配"(s[i]≠t[j])时，i=j=5，则下次开始匹配时，i和j的值分别是()。\nA.i=1,j=0\nB.i=5,j=0\nC. i=5,j=2\nD.i=6,j=2',
    144: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n9.【2019 统考真题】设主串 T=\'abaabaabcabaabc\'，模式串 S=\'abaabc\',采用 KMP 算法进行模式匹配，到匹配成功时为止，在匹配过程中进行的单个字符间的比较次数是()。\nA.9\nB.10\nC.12\nD.15',
    147: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n3.树的路径长度是从树根到每个结点的路径长度的()。\nA.总和\nB.最小值\nC.最大值\nD.平均值',
    148: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n4. 对于一棵具有n 个结点、度为 4的树来说，()。\nA.树的高度至多是n-3\nB.树的高度至多是n-4\nC.第i层上至多有4(i-1)个结点\nD.至少在某一层上正好有4个结点',
    149: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n5.度为4、高度为h的树，()。\nA.至少有 h+3 个结点\nB.至多有4h-1个结点\nC.至多有4h个结点\nD.至少有 h+4个结点',
    211: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n2.利用二叉链表存储森林时，根结点的右指针是()。\nA.指向最左兄弟\nB.指向最右兄弟\nC.一定为空\nD.不一定为空',
    212: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n3.设森林F中有3棵树，第一、第二、第三棵树的结点个数分别为M1,M和M3。与森林F对应的二叉树根结点的右子树上的结点个数是()。\nA.M1\nB.M1+M2\nC.M3\nD.M2+M3',
    213: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n4. 设森林 F 对应的二叉树为 B,它有 m 个结点，B 的根为 p, p 的右子树结点个数为 n,森林 F 中第一棵树的结点个数是( )。\nA. m-n\nB. m-n-1\nC. n+1\nD. 条件不足，无法确定',
    215: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n6.设F是一个森林，B 是由F 变换来的二叉树。若F中有n个非终端结点，则B 中右指针域为空的结点有()个。\nA. n-1\nB.n\nC. n+1\nD.n+2',
    217: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n8.某二叉树结点的中序序列为BDAECF,后序序列为DBEFCA,则该二叉树对应的森林包括( )棵树。\nA.1\nB.2\nC.3\nD.4',
    221: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n12.【2011 统考真题】已知一棵有2011个结点的树，其叶结点个数为116，该树对应的二叉树中无右孩子的结点个数是( )。\nA.115\nB.116\nC.1895\nD.1896',
    222: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n13.【2014 统考真题】将森林 F 转换为对应的二叉树 T,F 中叶结点的个数等于( )。\nA. T中叶结点的个数\nB.T中度为1的结点个数\nC.T中左孩子指针为空的结点个数\nD.T中右孩子指针为空的结点个数',
    224: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n15.【2019 统考真题】若将一棵树 T 转化为对应的二叉树 BT，则下列对 BT 的遍历中，其遍历序列与T的后根遍历序列相同的是( )。\nA.先序遍历\nB.中序遍历\nC.后序遍历\nD.按层遍历',
    225: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n16.【2020 统考真题】已知森林 F 及与之对应的二叉树 T,若 F 的先根遍历序列是 a,b,c,d,e,f，中根遍历序列是b,a,d,f,e,c，则T的后根遍历序列是()。\nA. b,a,d,f,e,c.\nB. b,d,f,e,c,a\nC. b,f,e,d,c,a.\nD. f,e,d,c,b,a',
    226: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n17.【2021 统考真题】某森林 F 对应的二叉树为 T,若 T 的先序遍历序列是 a,b,d,c,e,g,f,中序遍历序列是b,d,a,e,g,c,f,则F中树的棵数是()。\nA.1\nB.2\nC.3\nD.4',
    231: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n4.设哈夫曼编码的长度不超过4，若已对两个字符编码为1和01，则还最多可对( )个字符编码。\nA.2\nB.3\nC.4\nD.5',
    235: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n8. 并查集的结构是一种()。\nA.二叉链表存储的二叉树\nB.双亲表示法存储的树\nC.顺序存储的二叉树\nD.孩子表示法存储的树',
    239: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n12.【2014 统考真题】5个字符有如下4种编码方案，不是前缀编码的是( )。\nA.01,0000,0001,001,1\nB.011,000,001,010,1\nC.000,001,010,011,100\nD.0,100,110,1110,1100',
    241: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n14.【2017 统考真题】已知字符集{a,b,c,d,e,f,g,h},若各字符的哈夫曼编码依次是0100,10,0000,0101,001,011,11,0001,则编码序列0100011001001011110101 的译码结果是()。\nA. Acgabfh\nB. adbagbb\nC. afbeagd.\nD. afeefgd',
    243: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n?.\n13.下列排序算法中，平均时间复杂度为 O(n log,n)且空间复杂度为 O(1)的是()。\nA.快速排序\n插入排序\nC.归并排序\nD.堆排序',
    244: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n?.\n9.下列排序算法中，()算法可能会出现下面情况:在最后一趟开始之前，所有元素都不在最终位置上。\nA.堆排序\nB.冒泡排序\nC.直接插入排序\nD.快速排序',
    252: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n7.对于一个有 n 个顶点的图:若是连通无向图，其边的个数至少为( );若是强连通有向图，其边的个数至少为()。\nA. n-1,n\nB. n-1,n(n-1)\nC. n,n\nD. n,n(n-1)',
    259: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n14.【2009 统考真题】下列关于无向连通图特性的叙述中，正确的是( )。\nI. 所有顶点的度之和为偶数\nII. 边数大于顶点个数减1\nIII. 至少有一个顶点的度为1\nA.只有Ⅰ\nB.只有Ⅱ\nC.I和Ⅱ\nD.I 和 III',
    478: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n03.在下列排序算法中，平均情况下空间复杂度为 O(n)的是( );最坏情况下空间复杂度为 O(n)的是( )。\nI. 希尔排序\nII. 堆排序\nIII. 冒泡排序\nIV. 归并排序\nV. 快速排序\nVI. 基数排序\nA.I、IV、VI\nB.II、V\nC. IV、V\nD. IV',
    488: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n13.【2017 统考真题】在内部排序时，若选择了归并排序而未选择插入排序，则可能的理由是()。\nI.归并排序的程序代码更短\nII.归并排序的占用空间更少\nIII.归并排序的运行效率更高\nA.仅Ⅱ\nB.仅Ⅲ\nC.仅I、Ⅱ\nD.仅I、III',
    493: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n3.设被排序的结点序列共有N个结点，在该序列中的结点已十分接近有序的情况下，用直接插入排序、归并排序和快速排序对其进行排序，这些算法的时间复杂度应为()。\nA. O(N),O(N),O(N)\nB. O(N), O(N log2 N),O(N log2N)\nC. O(N),O(N log2 N),O(N2)\nD. O(N2),O(N log2 N), O(N2)',
    494: '风中易小生·24考研计算机WD数据结构做题本【选择题】\n4.下列排序算法中属于稳定排序的是(①),平均时间复杂度为 O(nlogn)的是(②),在最好的情况下，时间复杂度可以达到线性时间的有(③)。\nI.冒泡排序\nII.堆排序\nIII.选择排序\nIV.直接插入排序\nV.希尔排序\nVI.归并排序\nVII.快速排序',
}

OPTION_RE = re.compile(r'^\s*([A-Da-d])\s*[.．、:：)）\s]\s*(.*)')
WATERMARK_RE = re.compile(r'风中易小生|做题本|微信公众号|选择题】|^[?？]\.$')

def parse_question(text: str, page: int) -> dict | None:
    if not text.strip():
        return None

    lines = text.strip().split('\n')
    stem_lines = []
    options = []
    in_stem = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if WATERMARK_RE.search(stripped) and not OPTION_RE.match(stripped):
            continue
        # Skip standalone "?." lines (OCR artifacts)
        if re.match(r'^[?？]\s*\.\s*$', stripped):
            continue
        opt_match = OPTION_RE.match(stripped)
        if opt_match:
            key = opt_match.group(1).upper()
            val = opt_match.group(2).strip()
            options.append({"key": key, "text": val})
            in_stem = False
            continue
        stem_lines.append(stripped)
        in_stem = True

    stem = ' '.join(s for s in stem_lines if s).strip()
    if not stem:
        return None

    stem = re.sub(r'\s+', ' ', stem)
    qtype = "single_choice" if len(options) >= 2 else "unknown"

    return {
        "stem": stem,
        "options": options,
        "question_type": qtype,
        "source": {"source_page_start": page},
        "answer": None,
        "answer_source": "unknown",
    }

async def main():
    questions = []
    for page, text in sorted(MCP_RESULTS.items()):
        q = parse_question(text, page)
        if q:
            questions.append(q)
            print(f'Page {page}: parsed OK ({len(q["stem"])} chars, {len(q["options"])} options)')
        else:
            print(f'Page {page}: FAILED to parse')

    print(f'\nTotal questions to import: {len(questions)}')

    # Submit in batches
    written_total = 0
    for i in range(0, len(questions), 50):
        batch = questions[i:i+50]
        async with async_session() as db:
            result = await submit_to_review(
                db, batch,
                {"source_type": "pdf", "source_file": "ds_sc.pdf", "subject_id": SUBJECT_ID},
                skip_existing=True,
            )
            await db.commit()
            written_total += result["written"]
            print(f'Batch {i//50 + 1}: written={result["written"]}, skipped={result["skipped"]}')

    print(f'\nTotal written: {written_total}')

    # Final count
    import sqlite3
    sdb = sqlite3.connect('postgraduate.db')
    cnt = sdb.execute('SELECT COUNT(*) FROM question_imports').fetchone()[0]
    print(f'Final question_imports: {cnt}')
    sdb.close()

asyncio.run(main())
