"""OCR 代码回归测试用例。每个用例模拟真实 OCR 输出（含噪声）。"""

REGRESSION_CASES: list[dict] = [
    # ============================================================
    # 正例：应检测到代码块
    # ============================================================
    {
        "name": "c_for_loop",
        "description": "C for 循环 — 关键词 + 分号 + 缩进",
        "raw_text": (
            "以下程序段的时间复杂度是（ ）\n"
            "int i=1;\n"
            "while(i<=n)\n"
            "    i=i*2;\n"
            "A. O(n) B. O(n²) C. O(log n) D. O(nlog n)"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 3,
    },
    {
        "name": "c_pointer_linked_list",
        "description": "C 指针链表 — 箭头运算符 + 关键词",
        "raw_text": (
            "在单链表 L 中，指针 p 所指结点有后继结点的条件是（ ）\n"
            "typedef struct LNode {\n"
            "    int data;\n"
            "    struct LNode *next;\n"
            "} LNode;\n"
            "if(p->next!=NULL)\n"
            "A. p->next=NULL B. p->next!=NULL\n"
            "C. p!=NULL D. p->next==NULL"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 4,
    },
    {
        "name": "java_class_method",
        "description": "Java 类定义 — class 关键词 + 花括号 + public",
        "raw_text": (
            "阅读以下 Java 代码：\n"
            "public class Test {\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(\"Hello\");\n"
            "    }\n"
            "}\n"
            "程序的输出结果为（ ）"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 4,
    },
    {
        "name": "python_def_loop",
        "description": "Python 函数 — def 关键词 + 缩进块",
        "raw_text": (
            "以下 Python 代码的输出是：\n"
            "def func(n):\n"
            "    s = 0\n"
            "    for i in range(1, n+1):\n"
            "        s += i\n"
            "    return s\n"
            "print(func(5))\n"
            "A. 10 B. 15 C. 20 D. 25"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 5,
    },
    {
        "name": "sql_select_query",
        "description": "SQL SELECT — 大写关键词 + 多行",
        "raw_text": (
            "学生表 Student(Sno, Sname, Sage, Sdept)，查询计算机系年龄大于 20 的学生：\n"
            "SELECT Sno, Sname\n"
            "FROM Student\n"
            "WHERE Sdept = 'CS' AND Sage > 20;\n"
            "上述 SQL 查询的结果包含哪些列（ ）"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 3,
    },
    {
        "name": "html_div_tag",
        "description": "HTML 标签 — 尖括号结构",
        "raw_text": (
            "以下 HTML 片段中，div 的 class 属性值为（ ）\n"
            "<div class=\"container\">\n"
            "    <p>Hello World</p>\n"
            "    <span>test</span>\n"
            "</div>\n"
            "A. container B. wrapper C. main D. box"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 3,
    },
    {
        "name": "cpp_class_inheritance",
        "description": "C++ 类继承 — class + 冒号 + public",
        "raw_text": (
            "有如下 C++ 程序：\n"
            "class Base {\n"
            "public:\n"
            "    virtual void f() { }\n"
            "};\n"
            "class Derived : public Base {\n"
            "public:\n"
            "    void f() override { }\n"
            "};\n"
            "下列关于上述代码描述正确的是（ ）"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 6,
    },
    {
        "name": "javascript_function",
        "description": "JavaScript — function + var + 分号",
        "raw_text": (
            "以下 JavaScript 代码的输出为：\n"
            "var x = 10;\n"
            "function foo() {\n"
            "    var x = 20;\n"
            "    console.log(x);\n"
            "}\n"
            "foo();\n"
            "A. 10 B. 20 C. undefined D. ReferenceError"
        ),
        "expected_has_fence": True,
        "expected_min_code_lines": 5,
    },

    # ============================================================
    # 负例：不应触发围栏
    # ============================================================
    {
        "name": "negative_math_derivative",
        "description": "数学求导题 — 含 'f' 但不是 for 关键词",
        "raw_text": (
            "设函数 f(x)=x²+1，求 f'(x)\n"
            "A. 2x B. x² C. 2x+1 D. x"
        ),
        "expected_has_fence": False,
    },
    {
        "name": "negative_cjk_choice",
        "description": "中文选择题 — 含 'if'/'for' 子串但不触发",
        "raw_text": (
            "下列选项中正确的是（ ）\n"
            "对于以下说法，正确的有\n"
            "A. 选择排序是稳定的\n"
            "B. 冒泡排序是稳定的\n"
            "C. 快速排序是稳定的\n"
            "D. 堆排序是稳定的"
        ),
        "expected_has_fence": False,
    },
    {
        "name": "negative_single_line_code",
        "description": "单行代码 — 不满足 ≥2 连续行条件",
        "raw_text": (
            "时间复杂度为 O(n²) 的排序算法是（ ）\n"
            "A. 冒泡排序 B. 快速排序 C. 归并排序 D. 基数排序"
        ),
        "expected_has_fence": False,
    },
    {
        "name": "negative_pure_chinese_stem",
        "description": "纯中文题干 — 无任何代码结构",
        "raw_text": (
            "已知一棵二叉树的前序遍历序列为 ABCDEF，中序遍历序列为 CBAEDF，"
            "则其后序遍历序列为（ ）\n"
            "A. CBEFDA B. FEDCBA C. CBEDFA D. 不确定"
        ),
        "expected_has_fence": False,
    },
    {
        "name": "negative_latex_formula",
        "description": "LaTeX 公式 — 不触发代码检测",
        "raw_text": (
            "计算下列极限：\n"
            "lim_{x→0} (sin x)/x = ?\n"
            "lim_{n→∞} (1+1/n)^n = ?\n"
            "A. 0, e B. 1, e C. 1, 1 D. 0, 1"
        ),
        "expected_has_fence": False,
    },
]
