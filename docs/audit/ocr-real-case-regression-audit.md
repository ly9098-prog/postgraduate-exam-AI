# OCR 真实案例回归审计

> 审计任务：`prompts/tasks/current_task.md` — OCR真实案例回归集建设
> 审计日期：2026-06-19
> 审计范围：`ocr_test/images/` 下 5 张真实图片，全链路追踪（PaddleOCR → clean_ocr_text → TextNormalizer → StructureAnalyzer → QuestionSplitter → AnswerMatcher）
> 约束：不修改业务代码，不新增规则，仅分析
> 参考：`tests/ocr_regression/cases/` 现有 11 个合成文本 case（覆盖率 21/100）

---

## 审计结论

- 结论：**高风险** — 全链路存在 3 个独立根因导致真实图片无一成功导入
- 最高风险级别：**P0**（PaddleOCR 代码符号识别 + TextNormalizer CJK 字符丢失 bug）
- 影响范围：所有 408 计算机考研真题图片导入（C 代码 + 两栏排版 + 水印场景）

---

## 证据

### 1. 全链路逐层追踪

对 `ocr_test/images/` 下 5 张图片执行了 PaddleOCR → clean_ocr_text → TextNormalizer → StructureAnalyzer → QuestionSplitter → AnswerMatcher 逐层分析，每层结果如下：

#### success/success_case.png（55,898 bytes）

| 层 | 发现 |
|----|------|
| PaddleOCR | 6 行，选项按**两栏列序**读取：B→A→D→C，而非行序 A→B→C→D |
| clean_ocr_text | 合并题干断行，无其他清洗效果 |
| TextNormalizer | `_normalize_punctuation` 丢失 CJK 字符："循环单链表"→"循环单链"、"表尾指针"→"表尾指" |
| StructureAnalyzer | 正确识别 question_header=1 |
| QuestionSplitter | 提取到 4 个选项，但**顺序错误**（B,A,D,C），且题干被截断 |
| AnswerMatcher | 无"答案"标记 → unmatched（预期行为，图片不含答案区域） |

**根因**：PaddleOCR 两栏串行 + TextNormalizer 字符丢失

#### failure/faulty_case_1.png（48,649 bytes）

| 层 | 发现 |
|----|------|
| PaddleOCR | 8 行，**C 代码指针严重乱码**：`d=xau<-s:axau<-s=xeu<-d'g`，选项 D 误识别为 "3D" |
| clean_ocr_text | 无变化 |
| TextNormalizer | 选项碎片错误合并：`s->next=q; s->next= 3D.p->next=s;s` |
| StructureAnalyzer | 正确识别 question_header=1 |
| QuestionSplitter | **仅提取到 A、C 两个选项**，B 和 D 丢失 |
| AnswerMatcher | unmatched（无答案标记） |

**根因**：PaddleOCR C 代码乱码 + QuestionSplitter 选项丢失

#### failure/faulty_case_2.png（18,264 bytes）

| 层 | 发现 |
|----|------|
| PaddleOCR | 5 行，**变量名 OCR 错误**：`cao`/`a1`/`a10o`/`aso`（应为 `a[0]`/`a[1]`/`a[100]`/`a[50]`） |
| clean_ocr_text | 无变化 |
| TextNormalizer | 丢失"中"（"表中"→"表"） |
| StructureAnalyzer | 正确识别 question_header=1 |
| QuestionSplitter | ✅ **4 个选项全部正确提取** |
| AnswerMatcher | unmatched（预期行为） |

**根因**：PaddleOCR 变量名误识别（管道逻辑可恢复，属 OCR 质量边界）

#### failure/faulty_case_3.png（82,971 bytes）

| 层 | 发现 |
|----|------|
| PaddleOCR | 7 行，**选项 D 完全乱码**：`! (d) aaxy !axau<-d=axau<-Aaxd<-d...`，`->` 指针符号全部乱码 |
| clean_ocr_text | 合并题干第 1-2 行（正确），删除 1 个换行符 |
| TextNormalizer | 丢失"点"（"结点"→"结"），D 选项乱码原样保留 |
| StructureAnalyzer | 正确识别 question_header=1 |
| QuestionSplitter | 因 D 选项乱码，选项提取受限 |
| AnswerMatcher | unmatched |

**根因**：PaddleOCR `->` 指针符号乱码 + 选项 D 完全不可读

#### failure/watermark_fail_case.png（47,004 bytes）

| 层 | 发现 |
|----|------|
| PaddleOCR | 6 行，**水印文本混入**：`axuK-dayOOeB:d=axeus`（置信度 0.51），选项 A+B 合并为一行 |
| clean_ocr_text | 无变化 |
| TextNormalizer | 水印文本与选项碎片合并，丢失 CJK 字符 |
| StructureAnalyzer | 正确识别 question_header=1 |
| QuestionSplitter | 选项受 A+B 合并和水印污染影响 |
| AnswerMatcher | unmatched |

**根因**：PaddleOCR 水印文本混入 + 选项 A+B 同行合并

---

### 2. 分层故障统计

```
Layer 1 — PaddleOCR         ████████████████████████████ 5/5 (100%)  全部有错误
Layer 2 — clean_ocr_text    ████                          1/5 (20%)   仅 faulty_case_3 有变化
Layer 3 — TextNormalizer    ██████████                    3/5 (60%)   字符丢失 + 合并错误
Layer 4 — StructureAnalyzer ░░░░                          0/5 (0%)    正确识别，无故障
Layer 5 — QuestionSplitter  ██████                        2/5 (40%)   faulty_case_1/3 选项丢失
Layer 6 — AnswerMatcher     ░░░░                          0/5 (0%)    无答案标记属预期行为
```

**核心瓶颈**：PaddleOCR（5/5），次要瓶颈：TextNormalizer（3/5）。

---

### 3. 错误归因汇总

| 图片 | 是否成功 | 错误类型 | 根因模块 |
|------|---------|---------|---------|
| success/success_case.png | ✗ | 两栏串行、选项错序、字符丢失 | PaddleOCR + TextNormalizer |
| failure/faulty_case_1.png | ✗ | C 代码乱码、选项丢失 (3D→D)、字符丢失 | PaddleOCR + QuestionSplitter |
| failure/faulty_case_2.png | ✗ | 变量名误识别 (cao/a10o/aso)、字符丢失 | PaddleOCR |
| failure/faulty_case_3.png | ✗ | → 指针乱码、选项 D 完全不可读、字符丢失 | PaddleOCR |
| failure/watermark_fail_case.png | ✗ | 水印污染、选项 A+B 同行合并、字符丢失 | PaddleOCR + TextNormalizer |

5/5 均不可成功导入为完整题目。

---

## 风险点

### 1. PaddleOCR 对 C/代码指针符号识别不稳定（P0）

- 影响：所有 408 数据结构真题（含 `->` 指针、数组下标）的 OCR 结果严重不可用
- 触发条件：特定字体/排版下 `->` 被识别为 `<-` + 随机字母序列（`xau`/`axau`/`xeu`）
- 证据：`faulty_case_1.png` 正确选项被乱码覆盖，`faulty_case_3.png` 选项 D 完全不可读

### 2. TextNormalizer._normalize_punctuation CJK 字符丢失 bug（P0）

- 影响：所有中文题干中紧跟标点的最后一个 CJK 字符被静默删除
- 触发条件：`_RE_CJK_PUNCT.sub` 第二遍调用时 lambda 只返回标点符号，丢弃 group(1) 的 CJK 字符
- 证据：`text_normalizer.py:554-560`，"单链表中"→"单链表"、"前驱结点"→"前驱结"、"表尾指针"→"表尾指"

### 3. PaddleOCR 两栏排版按列读取（P1）

- 影响：所有两栏排版的选项顺序错乱
- 触发条件：选项分为左右两栏，OCR 按列读取而非按行
- 证据：`success_case.png` 选项顺序 B→A→D→C，`ocr_service._detect_column_split` 未检测到分栏（gap 不满足 `image_width * 0.04` 阈值）

### 4. PaddleOCR 低置信度水印文本未过滤（P1）

- 影响：水印文本混入题目正文，干扰后续切分和匹配
- 触发条件：水印与正文重叠区域 OCR 置信度低至 0.51 仍被输出
- 证据：`watermark_fail_case.png` 水印文本 `axuK-dayOOeB:d=axeus` 与选项 C 合并

### 5. 现有回归体系完全无法覆盖真实 OCR 场景（P1）

- 影响：11 个合成文本 case 全部 PASS（score=100），但 5 张真实图片全部 FAIL
- 触发条件：`--baseline` 模式生成 expected.txt = 管道输出 → 测试变成同义反复
- 证据：上一轮覆盖率审计结论（21/100），且 `004`/`007` 的 `known_failure_types` 从不触发测试失败

---

## 回归集价值评估

| 图片 | 纳入价值 | 覆盖场景 | 当前回归集覆盖 |
|------|---------|---------|-------------|
| success_case.png | 高 | 两栏排版 → 选项错序 | **0** |
| faulty_case_1.png | 高 | C 代码指针 OCR 乱码 → 选项丢失 | **0** |
| faulty_case_2.png | 中 | 变量名 OCR 误识别基准 | **0** |
| faulty_case_3.png | 高 | `->` 指针完全乱码 | **0** |
| watermark_fail_case.png | 最高 | 水印污染 + 选项合并 | **0**（代码存在但零覆盖） |

全部 5 张图片建议纳入 `tests/ocr_regression/cases/010-014`。这些真实案例的 `expected.txt` 必须由人工标注 ground truth，不能用 `--baseline` 模式生成。

### 建议目录结构

```
tests/ocr_regression/cases/
├── 010_real_two_column/        # success_case.png
│   ├── meta.json               # known_failure_types: ["两栏串行","选项错序"]
│   ├── input.png
│   ├── ocr_raw.txt             # PaddleOCR 原始输出（含 bbox）
│   ├── ocr_cleaned.txt         # clean_ocr_text 输出
│   ├── normalized.txt          # TextNormalizer 输出
│   ├── split_result.json       # QuestionSplitter raw_questions
│   └── expected.txt            # 人工标注 ground truth
│
├── 011_real_code_garbling/     # faulty_case_1.png
│   ├── meta.json               # known_failure_types: ["OCR误识别","选项丢失","C代码乱码"]
│   └── ...
│
├── 012_real_var_misread/       # faulty_case_2.png
│   ├── meta.json               # known_failure_types: ["OCR误识别","变量名错误"]
│   └── ...
│
├── 013_real_pointer_garbling/  # faulty_case_3.png
│   ├── meta.json               # known_failure_types: ["OCR误识别","选项损坏","指针符号乱码"]
│   └── ...
│
└── 014_real_watermark/         # watermark_fail_case.png
    ├── meta.json               # known_failure_types: ["水印污染","选项合并","C代码乱码"]
    └── ...
```

---

## 与现有回归体系对比

| 维度 | 现有 11 个 Case | 建议新增 5 个 Case |
|------|----------------|-------------------|
| 输入类型 | 人工构造文本 | 真实 PaddleOCR 输出 |
| 覆盖层级 | normalize→split→match | OCR→clean→normalize→split→match |
| 已知失败 | 仅标记，不影响测试 | 需手工标注 ground truth |
| 两栏场景 | 0 | 1 |
| C 代码场景 | 0 | 3 |
| 水印场景 | 0（代码存在但未触发） | 1 |
| 覆盖率估计 | 21/100 | 加入后约 45/100 |

---

## 建议（不修改业务代码）

1. **P0**：人工标注 5 张图片的 ground truth（正确题干 + 选项 + 答案），写入各 case 的 `expected.txt`
2. **P0**：将 5 张图片纳入 `tests/ocr_regression/cases/010-014`，建立真实 OCR 回归基线
3. **P1**：修复 `text_normalizer.py:555` CJK 字符丢失 bug（lambda 需返回 `m.group(1) + 中文标点`）
4. **P1**：评估 PaddleOCR 对 `->` 指针符号的识别准确率，考虑是否需在 `clean_ocr_text` 层增加 `->` 修复规则
5. **P1**：在 `ocr_service._detect_column_split` 中放宽 gap 阈值或增加两栏检测回退逻辑
6. **P2**：扩展真实图片覆盖范围：英语题、表格题、跨页题、数学公式题

---

## 相关链接

- [[docs/audit/AUDIT_INDEX.md|AUDIT_INDEX]] — 审计索引
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
