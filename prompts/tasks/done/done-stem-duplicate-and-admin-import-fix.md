# 小程序题干重复问题&admin前端审核通过破坏题目结构问题 — 已修复

**状态**：全部案例已修复（2026-06-20）

#### 案例一（小程序渲染）

```c
【2022 统考真题】下列程序段的时间复杂度是( )。

int sum = 0;
for(int i = 1; i<n; i * =2)
   for(int j = 0; j<i; j + +) 
      sum + +;
【2022 统考真题】下列程序段的时间复杂度是( )。

int sum = 0;
for(int i = 1; i<n; i * =2)
   for(int j = 0; j<i; j + +) 
      sum + +;
```

> **问题描述**：题干完整重复出现两次，包括题号、题目描述和代码块。这是 AI 标准化后最常见的重复模式——整段内容原样复制。
>
> **修复任务**：在 AI 标准化后或入库前，检测并去重完全相同的题干内容。对于连续出现两次的相同文本块，只保留第一份。

#### 案例二（小程序渲染）

```C
下列程序段的时间复杂度为( )。

if (n>=0) {
    for (int i = 0; i<n; i + +) 
      for (int j = 0; j<n; j + +)  
         printf("输入数据大于或等于零\n");
}else {
    for (int j = 0; j<n; j + +) 
       printf("输入数据小于零\n");
}

下列程序段的时间复杂度为( )。

if (n>=0) {
    for (int i = 0; i<n; i + +) 
      for (int j = 0; j<n; j + +)  
         printf("输入数据大于或等于零\n");
}else {
    for (int j = 0; j<n; j + +) 
       printf("输入数据小于零\n");
}
```

> **问题描述**：与案例一相同，题干（含代码块）完整重复两次。特征为连续两个完全相同的内容块，中间无任何分隔或变化。
>
> **修复任务**：全等检测——对连续两个文本块进行逐字符或语义等价比较，若完全相同则去重。注意保留格式（缩进、换行）的一致性。

#### 案例三（小程序渲染）

```tex
下列关于线性表的存储结构的描述，正确的是()。
I.线性表的顺序存储结构优于其链式存储结构
II.链式存储结构比顺序存储结构能更方便地表示各种逻辑结构
III.若频繁使用插入和删除结点操作，则顺序存储结构更优于链式存储结构
IV.顺序存储结构和链式存储结构都可以进行顺序存取

下列关于线性表的存储结构的描述，正确的是()。
I.线性表的顺序存储结构优于其链式存储结构
II.链式存储结构比顺序存储结构能更方便地表示各种逻辑结构
III.若频繁使用插入和删除结点操作，则顺序存储结构更优于链式存储结构
IV.顺序存储结构和链式存储结构都可以进行顺序存取
```

> **问题描述**：纯文本（TeX）题干完整重复两次。与代码类题目不同，此处没有代码块，重复内容为纯文字描述。I-IV 选项完全一致。
>
> **修复任务**：纯文本类题干的去重，同样基于连续相同文本块检测。注意列表项（I. II. III. IV.）的换行和标点细微差异，确保全等匹配不受空白字符干扰。

#### 案例四（小程序渲染）

```c
【2014 统考真题】下列程序段的时间复杂度是( )。

count = 0;
for (k = 1; k <= n; k + =2)
  for (j = 1; j <= n; j + =1)  
    count + +;

【2014 统考真题】下列程序段的时间复杂度是( )。

count = 0;
for (k = 1; k <= n; k + =2)
  for (j = 1; j <= n; j + =1)  
    count + +;
```

> **问题描述**：含题号的题干完整重复两次。案例一和案例四均带 "【年份 统考真题】" 前缀，说明去重不应依赖题号格式（题号格式在各题中不统一），而应基于内容本身。
>
> **修复任务**：✅ 已修复 — `deduplicate_repeated_text()` 在 AI 标准化后、入库前对所有 stem 做行级折叠 + 整体半折叠 + 逐行去重（2026-06-20）。

#### 案例五（admin前端）

原题图片路径："ocr_test/images/example/ocr_code_test_1.png"

##### 原题

```c
设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
int F(int n) {
	if (n <= 1) return n;
    return F(n - 1) + F(n - 2);
}
```

##### 导入后通过审核前

```c
设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
int F(int n) {
if (n <= 1) return n;
}
```

##### 待审核题目JSON(解析数据)

```json
{
  "parsed_content": {
    "text": "设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:\nint F(int n) {\nif (n <= 1) return n;"
  },
  "parsed_options": {
    "A": "15",
    "B": "14",
    "C": "9",
    "D": "5"
  },
  "parsed_answer": "A",
  "parsed_analysis": "设递归调用次数函数为C(n)，则有C(0)=1, C(1)=1, C(n)=1+C(n-1)+C(n-2)。计算得C(2)=3, C(3)=5, C(4)=9, C(5)=15。因此F(5)递归调用总次数为15。"
}
```

##### 待审核题目JSON(OCR / AI 原始数据)

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:\nint F(int n) {\nif (n <= 1) return n;",
    "options": [
      {
        "key": "A",
        "text": "15"
      },
      {
        "key": "B",
        "text": "14"
      },
      {
        "key": "C",
        "text": "9"
      },
      {
        "key": "D",
        "text": "5"
      }
    ],
    "blank_option_groups": [],
    "answer": "A",
    "analysis": "设递归调用次数函数为C(n)，则有C(0)=1, C(1)=1, C(n)=1+C(n-1)+C(n-2)。计算得C(2)=3, C(3)=5, C(4)=9, C(5)=15。因此F(5)递归调用总次数为15。",
    "raw_text": "1. 设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:\nint F(int n) {\nif (n <= 1) return n;\nA. 15\nB. 14\nC. 9\nD. 5",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_1.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "5ea32066",
    "confidence_score": 0.9,
    "risk_flags": [],
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "5ea32066",
    "risk_flags": null
  }
}
```

##### 通过审核导入题库后

```c
设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
int F(int n) {
if (n <= 
1) return n;
}
```

##### 小程序显示

```c
设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
int F(int n) {
if (n <= 
1) return n;
}

设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
int F(int n) {
if (n <= 
1) return n;
}
```

> **问题描述**：三阶段退化链，从 OCR 识别到入库到小程序渲染逐步恶化。
> 1. **OCR 识别阶段 — 行遗漏 + 缩进去除**：对比原题与 `raw_data.raw_text` 可知，PaddleOCR 完全未识别出单独成行的 `}` 和 `return F(n - 1) + F(n - 2);` 这两行，导致 `raw_text` 直接从 `if (n <= 1) return n;` 跳到下一行 `A. 15`。同时，原题代码行首的 4 空格缩进在 `raw_text` 中全部消失（`    if` → `if`）。这两个问题均发生在 OCR 识别/后处理阶段，而非 pipeline 的 stem 提取环节——`parsed_content.text` 与 `raw_text` 一致，说明 stem 提取本身是正确的。
> 2. **审核通过阶段 — `<=` 被断行**：`parsed_content.text` 中 `if (n <= 1) return n;` 在入库后变为 `if (n <=\n1) return n;`，`<=` 比较运算符与右操作数 `1` 分离到两行。由于 stem 在审核前的 JSON 中仍为单行，断行必定发生在 `approve → publish_single_question → process_question_pipeline → clean_text` 链路中，最可能是 `_normalize_code_newlines` 或 `_merge_broken_lines` 的合并/拆分逻辑对"以比较运算符结尾的行 + 以数字开头的续行"这一组合处理不当。
> 3. **小程序显示阶段 — 题干整段重复**：断行后的题干在小程序端完整出现两次（含中文描述、代码框架和已断裂的 `if` 语句），与案例一～四的整段重复模式相同。推测入库时 `questions.content.text` 中 stem 已被写入两份，或小程序渲染层对 stem 做了二次拼接。
>
> **修复任务**：
> 1. **OCR 阶段**：排查 `ocr_service.py` 的 `clean_ocr_text()` — 历史修复（2026-06-19）已将 `line.strip()` 改为 `line.rstrip()`，需用该原图验证缩进是否仍丢失。对于 OCR 行遗漏问题，检查 PaddleOCR 对该图片的原始输出（`}` 和 `return` 行是否完全未被检测到，还是被后处理过滤），必要时调整 OCR 文本行过滤策略或在 fence block 检测后对代码块内行做保守保留（不因"看起来像噪声"而丢弃，见 ADR-001）。
> 2. **审核通过阶段**：在 `question_pipeline.py` 的 `clean_text()` 中增加比较运算符断行修复正则 `(<=|>=|==|!=)\s*\n\s*` → `\1 `，在 `_normalize_code_newlines` 之前运行。同时审查 `_normalize_code_newlines` 的 `_line_ends_broken` / `_line_starts_continuation` 对 `<=` 结尾行 + 数字开头续行的合并逻辑是否正确触发。排查 admin 前端 `PUT /imports/questions/{id}` 的 `<textarea>` 是否有 `wrap="hard"` 或 EOL 转换问题。
> 3. **入库/发布前 + 所有 stem 写入路径去重**：✅ 已修复 — `deduplicate_repeated_text()` 覆盖全部 stem 写入路径（2026-06-20）。
>
> **修复记录**：
> - ✅ 案例五 fix #1: OCR 缩进保留（`ocr_service.py` 使用 `line.rstrip()`），fence block 检测已就绪（ADR-001，2026-06-19）。
> - ✅ 案例五 fix #2: 比较运算符断行修复 `(<=|>=|==|!=)\\s*\\n\\s*` → `\\1 ` 已添加到 `question_pipeline.py:367`（2026-06-20）；`_should_merge` 逗号修复同上。
> - ✅ 案例五 fix #3: `deduplicate_repeated_text()` 已添加到 `admin_import_service.py:119`、`review_service.py:533`、`question_pipeline.py:365,2227`（2026-06-20）。

#### 案例六（admin前端）

原题图片路径："ocr_test/images/example/ocr_code_test_2.png"

##### 原题

```c
设有一个递归函数如下，其功能是计算斐波那契数列的第n项。若执行 F(5),则函数内部发生递归调用的总次数(含初始调用)为:
int F(int n) {
	if (n <= 1) return n;
    return F(n - 1) + F(n - 2);
}
```

##### 导入后通过审核前

```c
已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA
则其前序遍历序列为:
typedef struct BiTNode {
char data;
(1typu * p1tysI * apo11ta aonu2s
```

##### 待审核题目JSON(解析数据)

```json
{
  "parsed_content": {
    "text": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA\n则其前序遍历序列为:\ntypedef struct BiTNode {\nchar data;\n(1typu* p1tysI* apo11ta aonu2s"
  },
  "parsed_options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "parsed_answer": "A",
  "parsed_analysis": null
}
重
```

##### 待审核题目JSON(OCR / AI 原始数据)

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA\n则其前序遍历序列为:\ntypedef struct BiTNode {\nchar data;\n(1typu* p1tysI* apo11ta aonu2s",
    "options": [
      {
        "key": "A",
        "text": "ABDECF"
      },
      {
        "key": "B",
        "text": "ABDCEF"
      },
      {
        "key": "C",
        "text": "ABDFEC"
      },
      {
        "key": "D",
        "text": "ACBEDF"
      }
    ],
    "answer": "A",
    "analysis": "",
    "raw_text": "2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA\n则其前序遍历序列为:\ntypedef struct BiTNode {\nchar data;\n(1typu* p1tysI* apo11ta aonu2s\nA.ABDECF\nB.ABDCEF\nC.ABDFEC\nD. ACBEDF\n答案:A",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "ocr_code_test_2.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "stem_hash": "68348daa",
    "confidence_score": 1,
    "validation_status": "passed",
    "failure_reason": [],
    "retry_recommended": false,
    "ocr_quality_flags": [
      "watermark_noise_detected"
    ],
    "ai_validation": {
      "is_valid": true,
      "issues": [],
      "severity": "none"
    }
  },
  "ai_metadata": {
    "is_valid": true,
    "errors": [],
    "warnings": [],
    "knowledge_points": [],
    "difficulty": 3,
    "stem_hash": "68348daa",
    "risk_flags": null
  }
}
```

##### 通过审核导入题库后

```c
已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA则其前序遍历序列为:
typedef struct BiTNode {
char data;
(1typu * p1tysI * apo11ta aonu2s
```

##### 小程序显示

```c
已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA
则其前序遍历序列为:
typedef struct BiTNode {
char data;
(1typu * p1tysI * apo11ta aonu2s
 
已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC,后序遍历序列为 DEBFCA
则其前序遍历序列为:
typedef struct BiTNode {
char data;
(1typu * p1tysI * apo11ta aonu2s
```

> **问题描述**：三阶段退化链，核心问题为 OCR 乱码 + 换行合并 + 题干重复。
> 1. **OCR 识别阶段 — 代码行严重乱码**：原题 `struct BiTNode *lchild, *rchild;` 被 PaddleOCR 识别为 `(1typu* p1tysI* apo11ta aonu2s`，`struct` → `(1typu`，`*lchild` → `*p1tysI`，`*rchild` → `*apo11ta`，`;` → `a` 后缀。这是典型的代码/符号密集型行的 OCR 误识别，`struct` 关键字和 `*` 指针符号的组合超出了 PaddleOCR 的泛化能力。同时，代码缩进（4 空格）全部丢失，`}` 和 `} BiTNode;` 结尾行被完全遗漏。`raw_data.raw_text` 末尾还混入了 `答案:A` 的答案标记文本。
> 2. **审核通过阶段 — 换行符被合并**：`parsed_content.text` 中 `DBEAFC,后序遍历序列为 DEBFCA\n则其前序遍历序列为:` 在入库后变为 `DEBFCA则其前序遍历序列为:`（换行符消失，两句连成一行）。这是 `_merge_broken_lines` 的 `_should_merge` 将逗号结尾行与下一行汉字开头的行判定为"视觉断行"而合并的结果。与案例五的 `<=` 断行不同，此处是反向问题——本该保留的换行被误合并。
> 3. **小程序显示阶段 — 题干整段重复**：乱码后的题干在小程序端完整出现两次，中间以空行分隔。与案例一～五的整段重复模式一致，区别在于两次副本之间存在一个空行（可能是入库时拼接了两份 stem，中间的 `\n` 产生了空行）。
>
> **修复任务**：
> 1. **OCR 阶段 — 代码块保护与乱码标记**：排查 `ocr_service.py` 的 `clean_ocr_text()` 对 `struct`、`typedef` 等 C 语言关键字的识别率。对于已检测到的代码块（fence block 检测已就绪，见 ADR-001），在 AI 标准化前对块内行做保守保留，不因"低置信度"或"非自然语言"而丢弃。同时，`raw_text` 中混入的 `答案:A` 文本应被 `_extract_stem()` 的答案行过滤剥离（检查是否因紧跟前一行而未被识别为独立答案行）。OCR 严重乱码的题目应在 `ai_metadata.risk_flags` 中标记 `ocr_garbled_code`，提醒人工审核。
> 2. **审核通过阶段 — 换行合并回退**：审查 `_should_merge` 对"逗号结尾行 + 汉字开头续行"的合并规则。当前规则 `prev[-1] in "。！？；…"` 不包含逗号 `，`，导致逗号结尾行被当作可合并行。应在 `_should_merge` 中将中文逗号 `，`、英文逗号 `,` 也加入不可合并的结尾字符列表，防止"遍历序列为 DBEAFC,\n 则其前序遍历"类正确换行被吞并。
> 3. **入库/发布前去重**：✅ 已修复 — `deduplicate_repeated_text()` 行级折叠（2026-06-20）。
>
> **修复记录**：
> - ✅ 案例六 fix #1: `ocr_garbled_code` risk_flag 映射已添加（`pipeline_orchestrator.py:2090-2091`，2026-06-20）。当 `ocr_quality_flags` 包含 `garbled_text_detected` 时，自动向 `risk_flags` 追加 `ocr_garbled_code`，前端审核页据此显示风险徽章。
> - ✅ 案例六 fix #2: `_should_merge` 逗号已加入 `SENTENCE_END`（`pdf_text_normalizer.py:44`、`question_pipeline.py:584`，2026-06-20）。
> - ✅ 案例六 fix #3: `deduplicate_repeated_text()` 已覆盖所有 stem 写入路径（2026-06-20）。

