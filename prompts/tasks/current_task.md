# 修复任务：OCR 导题流水线 BUGS.md 中栈题 / 二叉树题 / 代码题识别异常

你是一个资深 Python + FastAPI + OCR Pipeline 工程师。请基于当前项目代码，修复 `BUGS.md` 中记录的 OCR/AI 导题异常，并补充完整回归测试，确保这些问题不会再次出现。

## 一、项目背景

项目为 MemoGrad / 22408AI 刷题小程序，后端为 FastAPI，OCR 导题流水线主要位于：

- `features/question_splitter.py`
- `features/question_normalizer.py`
- `features/question_type_classifier.py`
- `features/structure_analyzer.py`
- `features/text_normalizer.py`
- `features/ai_repair.py`
- `features/code_detector.py`
- `features/code_integrity.py`
- `features/pipeline_orchestrator.py`
- `features/pipeline_stages/structure_freeze_stage.py`
- `features/pipeline_stages/normalize_schema_stage.py`
- `features/pipeline_stages/code_structure_stage.py`
- `features/ocr_fix/router.py`
- `features/ocr_fix/canonical_output.py`
- `features/ocr_vl/paddleocr_vl_adapter.py`
- `features/ocr_vl/paddleocr_vl_client.py`
- `services/ocr_service.py`
- `services/import_pipeline_service.py`
- `features/batch_image_import_service.py`

请先阅读以下文件：

- `README.md`
- `ocr-pipeline-full-engineering-audit.md`
- `BUGS.md`
- `app.zip` 解压后的后端代码
- 图片样例：
  - `false_3.png`
  - `false_4.png`
  - `false_5.png`
  - `false_1.png`
  - `ocr_code_test_2.png`

## 二、总体修复目标

修复当前 OCR 导题流水线在以下场景中的结构化解析错误：

1. 数学下标 / 序列变量识别异常  
   例如 `P_1,P_2,P_3,P_4` 被识别成 `P、P、P、P`。

2. 单行横排选项切分异常  
   例如 `A. 2,4 B. 2,1 C. 4,3 D. 3,4` 中，选项 B/D 被截断为 `2、`、`3,`。

3. 题干与选项粘连  
   例如题干末尾和 `A.` 选项之间没有换行时，当前 splitter 无法正确分离。

4. 代码片段被误切为选项  
   例如：
   ```c
   InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);

被错误拆成：

```json
{
  "A": "; Push(st,",
  "B": "; Pop(st, x); GetTop(st, x) ;"
}
```

1. C 语言结构体代码块保护不足
   例如：

   ```c
   typedef struct BiTNode {
       char data;
       struct BiTNode *lchild, *rchild;
   } BiTNode, *BiTree;
   ```

   应整体进入 `code_blocks`，不能把代码内容拆进题干或选项。

2. 连续大写字母序列保护不足
   二叉树遍历序列 `DBEAFC`、`DEBFCA`、`ABDECF` 等必须作为完整字符串保留，不能被拆字符、加空格、误判成公式或选项。

3. 答案提取 / 答案补全策略不清晰
   当图片中存在显式 `答案：A` 时，必须提取。
   当图片中没有显式答案但测试 fixture 已给出期望答案时，可以通过受控的 AI/规则推理补全，但必须打 trace 标记，不能静默伪造答案。

## 三、必须修复的回归案例

### Case 1：栈题 22，单行横排选项 + 下标丢失

输入图片：`false_3.png`

期望输出：

```json
{
  "question_type": "single_choice",
  "stem": "已知栈的入栈序列是 $1,2,3,4$，其出栈序列为 $P_1,P_2,P_3,P_4$，则 $P_2,P_4$ 不可能是（ ）。",
  "options": {
    "A": "2,4",
    "B": "2,1",
    "C": "4,3",
    "D": "3,4"
  },
  "answer": "C"
}
```

当前错误：

```json
{
  "stem": "已知栈的入栈序列是(2,3,4)，其出栈序列为P、P、P、P、，则P、P不可",
  "options": {
    "A": "2,4",
    "B": "2、",
    "C": "4,3",
    "D": "3,"
  },
  "answer": ""
}
```

修复要求：

- 恢复题干首项 `1`。
- 恢复 `P_1,P_2,P_3,P_4`。
- 单行横排选项必须正确切成 A/B/C/D。
- 选项中的逗号和数字不得丢失。
- `parsed_answer` 应为 `C`。
- `is_valid=true` 不能作为唯一成功标准，必须校验 stem/options/answer。

------

### Case 2：栈题 21，题干和选项粘连 + 选项截断

输入图片：`false_4.png`

期望输出：

```json
{
  "question_type": "single_choice",
  "stem": "若栈的输入序列是 $P_1,P_2,\\cdots,P_n$，输出序列是 $1,2,3,\\cdots,n$，若 $P_3=3$，则 $P_1$ 的值（ ）。",
  "options": {
    "A": "可能是 2",
    "B": "不可能是 1",
    "C": "一定是 1",
    "D": "一定是 2"
  },
  "answer": "A"
}
```

当前错误：

```json
{
  "stem": "若栈的输入序列是 $ P_{1}, P_{2}, \\cdots, P_{n} $，输出序列是 $ 1, 2, 3, \\cdots, n $，若 $ P_{i}=3 $，则",
  "options": {
    "A": "可能是2",
    "B": "不可能是(",
    "C": "一定是1",
    "D": "一定"
  },
  "answer": ""
}
```

修复要求：

- 将误识别的 `P_i=3` 修正为 `P_3=3`。
- 题干末尾应包含 `$P_1$ 的值（ ）。`
- 选项 B 应为 `不可能是 1`，不能截断成 `不可能是(`。
- 选项 D 应为 `一定是 2`。
- 支持题干与 `A.` 粘连时的二次 re-strip。

------

### Case 3：栈题 20，下标误修复

输入图片：`false_5.png`

期望输出：

```json
{
  "question_type": "single_choice",
  "stem": "若栈的输入序列是 $P_1,P_2,\\cdots,P_n$，输出序列是 $1,2,3,\\cdots,n$，若 $P_3=1$，则 $P_1$ 的值（ ）。",
  "options": {
    "A": "可能是 2",
    "B": "一定是 2",
    "C": "不可能是 2",
    "D": "不可能是 3"
  },
  "answer": "C"
}
```

当前错误：

```json
{
  "stem": "若栈的输入序列是 $P_1, P_2, \\ldots, P_n$，输出序列是 $1,2,3,\\ldots,n$，若 $P_1=1$，则 $P_2$ 的值( )。",
  "options": {
    "A": "可能是 2",
    "B": "一定是 2",
    "C": "不可能是 2",
    "D": "不可能是 3"
  },
  "answer": ""
}
```

修复要求：

- 不能把图片中的 `P_3=1` 错修成 `P_1=1`。
- 不能把问题对象 `$P_1$ 的值` 错修成 `$P_2$ 的值`。
- AI repair 不允许在低证据情况下改写核心下标。
- 对数学下标变更增加 safety gate：
  - 如果 AI 将 `P_3` 改为 `P_1`，必须能从 OCR/VL 原始文本或图像证据中找到依据。
  - 否则拒绝该修复，并进入视觉回退或人工审核。

------

### Case 4：栈操作代码题，代码被误切为选项

输入图片：`false_1.png`

期望输出：

```json
{
  "question_type": "single_choice",
  "stem": "经过以下栈的操作后，变量 x 的值为（ ）。\nInitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);",
  "options": {
    "A": "a",
    "B": "b",
    "C": "NULL",
    "D": "false"
  },
  "answer": "A"
}
```

当前错误：

```json
{
  "stem": "经过以下栈的操作后，变量x的值为( )。\nInitStack(st); Push(st,",
  "options": {
    "A": "; Push(st,",
    "B": "; Pop(st, x); GetTop(st, x) ;",
    "C": "NULL",
    "D": "false"
  }
}
```

修复要求：

- `Push(st, a)` 中的 `a)` 不能被识别成选项 A。

- `Push(st, b)` 中的 `b)` 不能被识别成选项 B。

- 多行断裂代码应先合并：

  ```text
  InitStack(st); Push(st,
  a); Push(st,
  b); Pop(st, x); GetTop(st, x);
  ```

  应合并为：

  ```text
  InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);
  ```

- 选项应从真正的选项区提取：

  ```text
  A. a
  B. b
  C. NULL
  D. false
  ```

- 若 OCR 输出顺序为：

  ```text
  D.false
  C.NULL
  B.b
  A.a
  ```

  系统应按 key 重排为 A/B/C/D，但不得把代码内部的 `a)`、`b)` 当选项。

------

### Case 5：二叉树遍历题，结构体代码块 + 连续字符串保护

输入图片：`ocr_code_test_2.png`

期望输出：

```json
{
  "question_type": "single_choice",
  "stem": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA，则其前序遍历序列为：",
  "code_blocks": [
    "typedef struct BiTNode {\n    char data;\n    struct BiTNode *lchild, *rchild;\n} BiTNode, *BiTree;"
  ],
  "options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "answer": "A"
}
```

修复要求：

- `typedef struct BiTNode { ... } BiTNode, *BiTree;` 必须整体识别为代码块。
- 代码块不得拆进选项。
- `DBEAFC`、`DEBFCA`、`ABDECF`、`ABDCEF`、`ABDFEC`、`ACBEDF` 必须作为连续字符串保留。
- 图片底部若存在 `答案：A`，必须提取为 `answer = "A"`。
- 不允许将连续大写字母串错误转换成数学公式、英文单词或加空格字符串。

## 四、建议修复方向

### 1. 增强 option extraction 前的代码保护

在选项抽取之前增加“代码区域隔离 / quarantine”逻辑。

建议处理位置：

- `features/question_splitter.py`
- `features/question_type_classifier.py`
- `features/code_detector.py`
- `features/code_integrity.py`
- `features/pipeline_stages/structure_freeze_stage.py`

规则建议：

- 如果一行或连续多行包含以下特征，应优先视为代码区域：
  - `InitStack(`
  - `Push(`
  - `Pop(`
  - `GetTop(`
  - `typedef`
  - `struct`
  - `{`
  - `}`
  - `;`
  - `*lchild`
  - `*rchild`
  - `->`
  - `==`
  - 函数调用形态：`\w+\s*\([^)]*$`
  - 断裂函数调用形态：`Push(st,\n a)`、`Push(st,\n b)`
- 代码区域内出现的 `a)`、`b)`、`A`、`B`、`;` 后字符，不能触发选项抽取。
- 只有符合明确选项模式的行才可作为选项：
  - `A. xxx`
  - `B. xxx`
  - `C. xxx`
  - `D. xxx`
  - `A．xxx`
  - `A、xxx`
  - `(A) xxx`
  - 且该行不在代码 quarantine 区域内。

### 2. 增强横排选项 splitter

需要支持以下格式：

```text
A. 2,4 B. 2,1 C. 4,3 D. 3,4
A. 可能是2 B. 不可能是1 C. 一定是1 D. 一定是2
A.a B.b C.NULL D.false
D.false C.NULL B.b A.a
```

要求：

- 通过 `A/B/C/D` 标签边界切分，不依赖换行。
- 保留选项内部逗号、数字、英文、NULL、false。
- 不把选项内容里的普通字母误判为下一个选项。
- 支持乱序识别后按 key 归一化为 A/B/C/D。
- 当识别到 4 个选项但题干仍包含 `A.` / `B.` 文本时，触发 stem re-strip。

### 3. 增强数学下标和序列变量保护

重点保护：

```tex
P_1, P_2, P_3, P_4
P_1, P_2, \cdots, P_n
P_3=3
P_3=1
P_1 的值
P_2,P_4
```

要求：

- OCR 原始文本中出现 `P、P、P、P`、`P,P^{2}`、`Ps=1`、`P_i=3` 等异常时，不要直接盲目 AI 修复。
- 对这类数据结构题，优先使用 PaddleOCR-VL 或视觉回退重建数学下标。
- 增加“核心下标变更 safety gate”：
  - AI repair 如果改变了题干中的核心下标，例如 `P_3` → `P_1`，必须记录 diff。
  - 如果该变更无法由 OCR/VL 原文或图像识别证据支持，应拒绝。
- 对 `P_i=3` 这类识别结果，如果图像区域实际为 `P_3=3`，应通过视觉回退修复。
- 对 `Ps=1` 这类识别结果，应结合上下文和视觉证据修复为 `P_3=1`，而不是错误修为 `P_1=1`。

### 4. 增强答案提取策略

实现明确分层：

#### 4.1 显式答案提取

如果 OCR/VL 原文中存在：

```text
答案：A
答案: A
参考答案：C
Answer: B
```

必须提取到 `answer` 字段。

#### 4.2 可推理答案补全

如果业务允许 AI 补全答案，则必须：

- 使用单独阶段，例如 `answer_inference`。

- 不得混在普通 OCR repair 里静默填充。

- 输出 trace：

  ```json
  {
    "stage": "answer_inference",
    "result": "filled",
    "source": "ai_reasoning",
    "confidence": 0.9
  }
  ```

- 当推理置信不足时，保持 `answer=""` 并进入人工审核。

- 测试 fixture 可以断言期望答案，但生产逻辑不能无 trace 地“猜答案”。

### 5. 增强连续大写字符串保护

在二叉树 / 遍历序列类题目中，以下字符串必须原样保留：

```text
DBEAFC
DEBFCA
ABDECF
ABDCEF
ABDFEC
ACBEDF
BiTNode
BiTree
```

要求：

- 不要把 `DBEAFC` 分割成 `D B E A F C`。
- 不要把 `ABDECF` 识别为多个选项或多个 token。
- 不要对 `BiTNode`、`BiTree` 做大小写归一化或错误 LaTeX 化。

## 五、必须新增的测试

请新增回归测试文件，例如：

```text
tests/ocr_regression/test_bugs_stack_and_code_cases.py
```

至少包含以下测试：

### test_false_3_stack_horizontal_options

断言：

- `question_type == "single_choice"`
- stem 包含：
  - `1,2,3,4`
  - `P_1`
  - `P_2`
  - `P_3`
  - `P_4`
  - `P_2,P_4`
- options：
  - A = `2,4`
  - B = `2,1`
  - C = `4,3`
  - D = `3,4`
- answer = `C`

### test_false_4_stack_p3_equal_3

断言：

- stem 包含 `P_3=3`
- stem 包含 `P_1 的值`
- options：
  - A = `可能是 2`
  - B = `不可能是 1`
  - C = `一定是 1`
  - D = `一定是 2`
- answer = `A`

### test_false_5_stack_p3_equal_1_no_wrong_subscript_rewrite

断言：

- stem 包含 `P_3=1`
- stem 包含 `P_1 的值`
- stem 不包含错误的 `P_1=1`
- stem 不包含错误的 `P_2 的值`
- options：
  - A = `可能是 2`
  - B = `一定是 2`
  - C = `不可能是 2`
  - D = `不可能是 3`
- answer = `C`

### test_false_1_stack_code_not_options

断言：

- stem 或 code block 中包含完整代码：

  ```text
  InitStack(st); Push(st, a); Push(st, b); Pop(st, x); GetTop(st, x);
  ```

- options：

  - A = `a`
  - B = `b`
  - C = `NULL`
  - D = `false`

- options 中不得出现：

  - `; Push(st,`
  - `; Pop(st, x); GetTop(st, x)`

- answer = `A`

### test_ocr_code_test_2_binary_tree_struct_code_block

断言：

- stem 包含：

  - `中序遍历序列为 DBEAFC`
  - `后序遍历序列为 DEBFCA`
  - `前序遍历序列`

- code_blocks 中包含：

  ```c
  typedef struct BiTNode {
      char data;
      struct BiTNode *lchild, *rchild;
  } BiTNode, *BiTree;
  ```

- options：

  - A = `ABDECF`
  - B = `ABDCEF`
  - C = `ABDFEC`
  - D = `ACBEDF`

- answer = `A`

## 六、验收标准

修复完成后必须满足：

1. `BUGS.md` 中本轮新增/补充的所有案例全部通过。
2. 不能只通过 `is_valid=true` 判断成功，必须逐字段校验：
   - stem
   - code_blocks
   - options
   - answer
   - warnings/errors/risk_flags
3. 旧有回归测试不能失败。
4. 不能通过硬编码图片文件名、题号、题干全文来修复。
5. 不能为了通过测试而关闭 OCR quality gate、AI safety gate、option immutable gate。
6. 不能让 AI repair 随意改写核心数学下标。
7. 代码题中，代码片段必须先被保护，再进入选项抽取。
8. 选项抽取必须支持：
   - 单行横排
   - 多行
   - 乱序
   - 中英文标点
   - 选项内容为单字符
   - 选项内容为连续大写字符串
9. 图片中显式答案区必须提取。
10. 若使用 AI 推理补全答案，必须带 trace，不能静默填充。

## 七、建议调试步骤

1. 解压 `app.zip`。

2. 阅读 `BUGS.md`，确认 5 个图片样例的期望输出。

3. 先单独跑现有 OCR/导入 pipeline，记录每个 case 的：

   - raw_text
   - frozen_option_registry
   - split result
   - normalize result
   - ai_repair diff
   - answer_match result
   - decision_trace

4. 定位错误发生阶段：

   - OCR 原始文本已错？
   - structure freeze 错？
   - splitter 错？
   - normalizer 错？
   - AI repair 幻觉？
   - answer matcher 未提取？

5. 先补测试，让测试复现失败。

6. 再修代码。

7. 修完后跑：

   ```bash
   pytest tests/ocr_regression -q
   pytest tests -q
   ```

8. 输出修复总结，包含：

   - 修改了哪些文件
   - 每个 case 原因是什么
   - 每个 case 如何修复
   - 新增了哪些测试
   - 是否影响旧流程
   - 是否仍有需要人工审核的边界情况

## 八、最终交付物

请提交：

1. 代码修复 diff。
2. 新增/修改的测试用例。
3. 测试运行结果。
4. 更新后的 `BUGS.md`，将对应案例标注为：
   - `✅ 已修复`
   - 修复 commit / 文件路径
   - 回归测试名称
5. 一段简短工程说明：
   - 本次修复不是硬编码样例，而是增强了代码保护、横排选项切分、数学下标安全门禁、答案提取和连续字符串保护。

日志里暴露出一个更具体的根因链：本次是 `ocr_mode=local` 批量图片导入，OCR 原始结果已经把结构体第三行识别成乱码，但同时识别到了 `答案：A`；后续 `ocr_correction` 判断 `noisy_blocks=0`，直接跳过了纠错；`structure_freeze` 虽然冻结了 4 个选项，但 split 后题干仍残留 A-D 选项文本；`normalize_schema` 已经打出 `code_garbled_text / ocr_garbled_code / low_confidence` 等风险标记，却最终仍进入 review 入库，并且答案为空。

## 九、基于 logs_1.txt 的新增定位与修复要求

本轮新增日志文件：`logs_1.txt`

请重点分析其中 `ocr_code_test_2.png` 的完整识别链路。该日志说明当前问题不是单点错误，而是多个阶段同时放行导致的“低质量结果入库”。

### 9.1 日志暴露出的实际链路

本次导入参数：

```text
POST /api/admin/v1/imports/batch-image/upload
ocr_mode=local
enable_ai_repair=true
confidence_threshold=0.6
concurrency=1
source_file=ocr_code_test_2.png
```

实际链路：

```text
batch-image/upload
→ local OCR
→ clean_ocr_text
→ pipeline.run
→ normalize_text
→ ocr_correction
→ layout_reconstruction
→ layout_router
→ structure_freeze
→ split
→ match
→ normalize_schema
→ code_language_noise_clean
→ code_structure_reconstruct
→ classify_questions
→ batch_validation
→ batch_dedup
→ repair
→ ai_validation
→ review
```

请不要只修最终入库结果，必须沿着上述阶段定位并修复。

------

## 十、日志中必须修复的关键问题

### Problem A：OCR 原始结果已经有明显代码乱码，但 ocr_correction 未触发

日志中 local OCR 原始结果：

```text
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
```

正确内容应为：

```c
typedef struct BiTNode {
    char data;
    struct BiTNode *lchild, *rchild;
} BiTNode, *BiTree;
```

当前 `ocr_correction` 指标：

```json
{
  "total_blocks": 1,
  "noisy_blocks": 0,
  "skipped_blocks": 1,
  "corrected_blocks": 0,
  "total_called": 0,
  "models": {}
}
```

这说明噪声检测 / 纠错触发条件有 bug：明明代码块存在明显乱码，却被判断为 `noisy_blocks=0`。

#### 修复要求

必须增强 noisy block detector，至少覆盖以下情况：

1. 代码块中出现异常字符密度过高：

   - 数字和英文字母混杂异常：`1typu`
   - 非法 token：`p1tysI`
   - 无意义英文串：`apo11ta`
   - 代码语义不成立但包含大量 C 语言符号：`*`, `;`, `{`, `}`

2. C 结构体代码块完整性校验失败：

   - 出现 `typedef struct`

   - 出现 `char data;`

   - 出现 `} BiTNode, *BiTree;`

   - 但缺少合理字段声明，例如：

     ```c
     struct BiTNode *lchild, *rchild;
     ```

3. 当代码块被 CodeDetector 识别出来，但内部存在 `ocr_garbled_code` 特征时，不能跳过 `ocr_correction`。

4. `ocr_correction` 对代码乱码块必须触发：

   - PaddleOCR-VL 视觉回退，优先使用原图区域；
   - 若 VL 不可用，再 DeepSeek 文本修复；
   - 若仍无法修复，则保留原始代码，但必须 `valid=false`，进入人工审核，不允许高置信入库。

新增 trace 字段：

```json
{
  "stage": "ocr_correction",
  "code_block_noisy": true,
  "reason": [
    "garbled_code_token_density_high",
    "struct_field_missing",
    "c_code_semantic_incomplete"
  ],
  "action": "vl_or_ai_repair_triggered"
}
```

------

### Problem B：clean_ocr_text 把乱码代码包进 ```text，但未触发后续强修复

日志中 `clean_ocr_text` 输出：

~~~text
```text
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
这说明系统已经知道这是一个代码块，但后续只是加了代码围栏，没有做真正纠错。

#### 修复要求

代码围栏生成后，必须增加代码质量校验：

```python
if fenced_code_block and code_quality_score < threshold:
    mark_risk("ocr_garbled_code")
    force_ocr_correction_or_vl_rebuild()
~~~

建议新增函数：

```python
detect_garbled_code_block(code: str) -> CodeGarbledResult
```

返回：

```python
@dataclass
class CodeGarbledResult:
    is_garbled: bool
    score: float
    reasons: list[str]
    expected_language: str | None
```

C 语言结构体检测规则：

```text
typedef struct Xxx {
    ...
} Xxx, *Ptr;
```

若结构体内部字段行不满足 C 声明基本形态，应打 `c_struct_body_garbled`。

------

### Problem C：structure_freeze 冻结选项后，split 题干仍残留选项文本

日志中 split 阶段显示：

```text
options=A: ABDECF, B: ABDCEF, C: ABDFEC, D: ACBEDF [FROZEN]

题干:
...
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBE
```

这说明 frozen options 虽然正确识别，但题干 re-strip 没有彻底执行，导致题干残留选项文本。

#### 修复要求

当 `structure_freeze` 成功冻结选项后，split 阶段必须从 stem 中移除所有 frozen option 原文片段。

必须支持：

```text
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
```

以及：

```text
A. ABDECF
B. ABDCEF
C. ABDFEC
D. ACBEDF
```

和单行形式：

```text
A.ABDECF B.ABDCEF C.ABDFEC D.ACBEDF
```

新增函数建议：

```python
strip_frozen_options_from_stem(stem: str, frozen_options: dict[str, str]) -> str
```

验收：

```python
assert "A.ABDECF" not in stem
assert "B.ABDCEF" not in stem
assert "C.ABDFEC" not in stem
assert "D. ACBEDF" not in stem
assert "答案" not in stem
```

注意：不能删除题干中的遍历序列 `DBEAFC`、`DEBFCA`。

------

### Problem D：显式答案 `答案：A` 已识别，但 answer 仍为空

OCR 原始结果和 clean 后结果都包含：

```text
答案：A
答案:A
```

但 normalize_schema 和最终 review 中：

```text
答案: ❌
answer=❌
```

这说明 answer matcher 没有从同一 block 的尾部提取答案，或者 split/normalize 阶段把答案丢了。

#### 修复要求

新增或修复显式答案提取逻辑：

支持：

```text
答案：A
答案:A
参考答案：A
正确答案：A
Answer: A
答案：AB
答案：A、C
```

处理位置建议：

1. split 前，从 raw block 中提取答案；
2. split 后，将答案绑定到最近题号；
3. normalize_schema 时保留；
4. repair 阶段不得清空已有显式答案。

新增函数建议：

```python
extract_explicit_answer(raw_text: str) -> ExplicitAnswerResult
```

返回：

```python
@dataclass
class ExplicitAnswerResult:
    answer: str | None
    source_span: tuple[int, int] | None
    pattern: str | None
    confidence: float
```

验收：

```python
assert question.answer == "A"
assert "explicit_answer_extracted" in question.trace
```

新增 trace：

```json
{
  "stage": "answer_extraction",
  "result": "filled",
  "source": "explicit_text",
  "pattern": "答案[:：]\\s*([A-D])",
  "answer": "A"
}
```

如果显式答案存在但最终 answer 为空，应视为 pipeline failure，不允许入库为高置信题目。

------

### Problem E：normalize_schema 已经 valid=False，但 review 仍写入 pending，且 conf=1.00

日志中 normalize_schema：

```text
valid=False
conf=0.55
risk_flags=[
  'code_garbled_text',
  'code_line_break_suspicious',
  'low_confidence',
  'ocr_garbled_code'
]
answer=❌
```

但 review 阶段：

```text
written=1
status=pending
type=single_choice
options=4
conf=1.00
answer=❌
```

这说明后续阶段把低置信 / invalid 状态覆盖成了高置信，且 review gate 没有阻止低质量题入库。

#### 修复要求

必须实现质量状态单调性原则：

```text
一旦某题出现 fatal risk 或 valid=False，
后续阶段不能无证据地把它升级为 conf=1.00。
```

新增规则：

1. 如果 normalize_schema 输出：

   - `valid=False`
   - 或 `ocr_garbled_code`
   - 或 `code_garbled_text`
   - 或 `answer_missing_for_objective_question`
   - 或 `low_confidence`

   则后续阶段必须满足以下任一条件才可解除风险：

   - OCR/VL 成功修复；
   - AI repair 通过 safety gate；
   - 显式答案提取成功；
   - code integrity check 通过。

2. 若风险未解除：

   - 可以进入人工审核；
   - 但不能显示为 `conf=1.00`；
   - 不能标记为“成功高质量解析”；
   - review item 应保留 risk_flags 和 failure_reason。

3. 如果题目是客观选择题且无 answer：

   - `is_valid` 应为 false 或 `needs_manual_review=true`；
   - 不能仅因 options=4 就认为完成。

新增质量状态字段建议：

```json
{
  "quality_status": "needs_manual_review",
  "quality_blockers": [
    "ocr_garbled_code",
    "missing_answer_for_objective_question"
  ],
  "confidence_score": 0.55
}
```

review 入库时必须保留：

```json
{
  "risk_flags": [...],
  "warnings": [...],
  "quality_status": "needs_manual_review",
  "confidence_score": 0.55
}
```

------

### Problem F：code_structure_reconstruct 只修了缩进，没有修复乱码代码

日志中 code structure reconstruct：

```text
Code structure reconstruction: 1 candidate(s) found
Code structure reconstructed: q0 (code_fixed=True, actions=['修复缩进：将第三行添加4空格缩进'])
```

但第三行仍是：

```text
(1typu*  p1tysI* apo11ta aonu2s
```

这说明 code_structure_reconstruct 只关注结构形态，不关注代码语义和乱码。

#### 修复要求

将 code_structure_reconstruct 分成两个层级：

1. structural repair：
   - 缩进
   - 括号闭合
   - 花括号闭合
   - 分号
   - 断行
2. semantic OCR repair：
   - C 结构体字段行识别错误
   - 指针声明乱码
   - 常见结构体字段名乱码
   - 代码 token 不合法

对于本 case，不能只返回：

```text
修复缩进
```

必须识别出：

```text
struct BiTNode *lchild, *rchild;
```

如果无法可靠修复，应输出：

```json
{
  "code_fixed": false,
  "reason": "garbled_code_unresolved",
  "needs_vl_rebuild": true
}
```

不能把仅修缩进当作“修复成功”。

------

## 十一、针对 ocr_code_test_2.png 的精确验收

以 `logs_1.txt` 中同一图片为准，最终输出必须为：

```json
{
  "question_type": "single_choice",
  "stem": "已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA，则其前序遍历序列为：",
  "code_blocks": [
    "typedef struct BiTNode {\n    char data;\n    struct BiTNode *lchild, *rchild;\n} BiTNode, *BiTree;"
  ],
  "options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "answer": "A",
  "quality_status": "passed",
  "confidence_score": 0.85
}
```

允许 `confidence_score` 不完全等于 0.85，但必须满足：

```python
assert confidence_score >= 0.8
assert "ocr_garbled_code" not in unresolved_risk_flags
assert answer == "A"
assert options["D"] == "ACBEDF"
assert "A.ABDECF" not in stem
assert "答案" not in stem
assert "struct BiTNode *lchild, *rchild;" in code_blocks[0]
```

如果无法修复代码乱码，则最低要求：

```json
{
  "quality_status": "needs_manual_review",
  "confidence_score": "<=0.6",
  "risk_flags": ["ocr_garbled_code"],
  "answer": "A"
}
```

绝对不允许出现：

```json
{
  "confidence_score": 1.0,
  "answer": "",
  "risk_flags": [],
  "status": "pending"
}
```

------

## 十二、必须新增日志回归测试

新增测试文件：

```text
tests/ocr_regression/test_logs_ocr_code_test_2.py
```

测试一：`test_log_replay_ocr_code_test_2_raw_text`

使用日志中的 raw OCR 文本作为输入，不依赖真实 OCR：

```python
RAW_OCR = """
2. 已知二叉树的结点结构定义如下，若一棵二叉树的中序遍历序列为 DBEAFC，后序遍历序列为 DEBFCA
则其前序遍历序列为:
typedef struct BiTNode {
char data;
(1typu*  p1tysI* apo11ta aonu2s
} BiTNode, *BiTree;
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
答案：A
"""
```

断言：

```python
assert result.answer == "A"
assert result.options["A"] == "ABDECF"
assert result.options["B"] == "ABDCEF"
assert result.options["C"] == "ABDFEC"
assert result.options["D"] == "ACBEDF"
assert "A.ABDECF" not in result.stem
assert "答案" not in result.stem
```

对于代码块：

如果启用 AI/VL：

```python
assert "struct BiTNode *lchild, *rchild;" in result.code_blocks[0]
assert result.quality_status == "passed"
```

如果测试环境禁用 AI/VL：

```python
assert result.quality_status == "needs_manual_review"
assert "ocr_garbled_code" in result.risk_flags
assert result.confidence_score <= 0.6
```

测试二：`test_explicit_answer_not_lost_after_split_and_normalize`

输入包含：

```text
D. ACBEDF
答案：A
```

断言 split、normalize、repair 后 answer 仍为 A。

测试三：`test_invalid_quality_not_upgraded_to_conf_1_without_repair`

构造带 `ocr_garbled_code` 的题目，跳过 AI/VL 修复，断言：

```python
assert result.confidence_score < 1.0
assert result.quality_status == "needs_manual_review"
assert "ocr_garbled_code" in result.risk_flags
```

测试四：`test_frozen_options_are_removed_from_stem`

构造 frozen options：

```python
{
  "A": "ABDECF",
  "B": "ABDCEF",
  "C": "ABDFEC",
  "D": "ACBEDF"
}
```

原 stem 包含：

```text
A.ABDECF
B.ABDCEF
C.ABDFEC
D. ACBEDF
答案：A
```

断言清理后 stem 不含选项和答案。

------

## 十三、必须新增诊断日志

请在以下阶段增加结构化日志，方便之后排查：

### ocr_correction

```json
{
  "stage": "ocr_correction",
  "block_id": "...",
  "has_code_block": true,
  "code_garbled_score": 0.92,
  "noisy": true,
  "model_called": "paddleocr_vl|deepseek|none",
  "skip_reason": null
}
```

如果 skipped，必须有明确原因：

```json
{
  "skipped": true,
  "skip_reason": "clean_block_no_noise_detected"
}
```

不能只输出 `noisy_blocks=0`。

### structure_freeze

```json
{
  "stage": "structure_freeze",
  "frozen_options": {
    "A": "ABDECF",
    "B": "ABDCEF",
    "C": "ABDFEC",
    "D": "ACBEDF"
  },
  "answer_candidate": "A",
  "answer_source": "explicit_text"
}
```

### split

```json
{
  "stage": "split",
  "stem_before_option_strip_len": 207,
  "stem_after_option_strip_len": 132,
  "removed_option_spans": 4,
  "removed_answer_span": true
}
```

### normalize_schema

```json
{
  "stage": "normalize_schema",
  "valid": false,
  "confidence_score": 0.55,
  "risk_flags": [
    "ocr_garbled_code",
    "missing_answer_for_objective_question"
  ],
  "quality_status": "needs_manual_review"
}
```

### review

```json
{
  "stage": "review",
  "will_write": true,
  "quality_status": "needs_manual_review",
  "confidence_score": 0.55,
  "answer": "A",
  "risk_flags": [...]
}
```

------

## 十四、修复优先级

请按以下顺序修：

### P0：必须立即修

1. 显式答案提取不丢失。
2. frozen options 从 stem 中彻底剥离。
3. invalid / low_confidence / ocr_garbled_code 不得被升级为 conf=1.00。
4. 代码乱码块必须触发 ocr_correction 或进入人工审核。
5. review 入库必须保留 risk_flags / quality_status。

### P1：随后修

1. C 结构体代码语义修复。
2. PaddleOCR-VL 对代码区域的视觉回退。
3. code_structure_reconstruct 增加 semantic repair。
4. 连续大写遍历序列保护。
5. 横排选项 + 答案尾行联合解析。

### P2：增强项

1. 日志回放测试框架。
2. 可视化 debug artifact。
3. 每阶段 JSON trace 导出。
4. OCR/VL 差异对齐工具。

------

## 十五、禁止事项

1. 禁止通过硬编码 `ocr_code_test_2.png` 文件名修复。
2. 禁止硬编码 `BiTNode` 题干全文。
3. 禁止把所有 `typedef struct` 都强行改成该案例代码。
4. 禁止在无证据情况下让 AI repair 改写代码核心语义。
5. 禁止 final review 将 `answer=""` 的单选题标记为高置信通过。
6. 禁止丢弃 `risk_flags`。
7. 禁止只在前端显示层修复，必须修后端结构化数据。
8. 禁止只改 BUGS.md，不改测试和代码。

```
请使用 `logs_1.txt` 做一次“日志回放式调试”：不要只看最终 JSON，必须标出错误首次出现在哪个阶段，并用测试锁定该阶段。
```
