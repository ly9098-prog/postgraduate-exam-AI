# BUGS

##### 原题

```tex
下列关于线性表的说法，正确的是()。
I.顺序存储方式只能用于存储线性结构 
II.在一个设有头指针和尾指针的单链表，删除表尾元素的时间复杂度与表长无关 
III.带头结点的循环单链表中不存在空指针 
IV.在一个长度为 n 的有序单链表中插入一个新结点并仍保持有序的时间复杂度为 O(n) V.若用单链表来表示队，则应该选用带尾指针的循环链表


A. I、II
B. I、III、IV、V
C. IV、 V
D. II、IV、V
```

##### 前端内容显示

```tex
下列关于线性表的说法，正确的是()。I.顺序存储方式只能用于存储线性结构 II.在一个设有头指针和尾指针的单链表，删除表尾元素的时间复杂度与表长无关 III.带头结点的循环单链表中不存在空指针 IV.在一个长度为 n 的有序单链表中插入一个新结点并仍保持有序的时间复杂度为 O(n) V.若用单链表来表示队，则应该选用带尾指针的循环链表


A. 1、I
B. I、II、IV、V
C. IV、 V
D. II、IV、V
```

##### 解析结果

```json
{
  "parsed_content": {
    "text": "下列关于线性表的说法，正确的是()。I.顺序存储方式只能用于存储线性结构 II.在一个设有头指针和尾指针的单链表，删除表尾元素的时间复杂度与表长无关 III.带头结点的循环单链表中不存在空指针 IV.在一个长度为 n 的有序单链表中插入一个新结点并仍保持有序的时间复杂度为 O(n) V.若用单链表来表示队，则应该选用带尾指针的循环链表"
  },
  "parsed_options": {
    "A": "1、I",
    "B": "I、II、IV、V",
    "C": "IV、 V",
    "D": "II、IV、V"
  },
  "parsed_answer": "D",
  "parsed_analysis": null
}
```

##### OCR解析结果

```json
{
  "raw_data": {
    "schema_version": "v1",
    "subject": "",
    "question_type": "single_choice",
    "stem": "下列关于线性表的说法，正确的是()。I.顺序存储方式只能用于存储线性结构 II.在一个设有头指针和尾指针的单链表，删除表尾元素的时间复杂度与表长无关 III.带头结点的循环单链表中不存在空指针 IV.在一个长度为 n 的有序单链表中插入一个新结点并仍保持有序的时间复杂度为 O(n) V.若用单链表来表示队，则应该选用带尾指针的循环链表",
    "options": [
      {
        "key": "A",
        "text": "1、I"
      },
      {
        "key": "B",
        "text": "I、II、IV、V"
      },
      {
        "key": "C",
        "text": "IV、 V"
      },
      {
        "key": "D",
        "text": "II、IV、V"
      }
    ],
    "blank_option_groups": [],
    "answer": "D",
    "analysis": "",
    "raw_text": "04.下列关于线性表的说法，正确的是()。\nI.顺序存储方式只能用于存储线性结构\nII.在一个设有头指针和尾指针的单链表，删除表尾元素的时间复杂度与表长无关\nII.带头结点的循环单链表中不存在空指针\nIV. 在一个长度为 n 的有序单链表中插入一个新结点并仍保持有序的时间复杂度为 O(n)\nV.若用单链表来表示队，则应该选用带尾指针的循环链表\nB. I、II、IV、V\nA. 1、I\nD. II、IV、V\nC. IV、 V",
    "knowledge_points": [],
    "difficulty": 3,
    "source": {
      "file": "1.png",
      "page": 1,
      "type": "txt"
    },
    "is_valid": true,
    "errors": [],
    "warnings": [
      "missing_answer_for_objective_question"
    ],
    "stem_hash": "cc2010b3",
    "confidence_score": 0.85,
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
    "stem_hash": "cc2010b3",
    "risk_flags": null
  }
}
```

### 问题描述

#### 问题现象

OCR 导题后，题干中的罗马编号（`I、II、III、IV、V`）被错误识别和处理，导致：

1. 题干内容丢失换行结构，所有判断项被拼接成一行。
2. 原本的 `III.` 被 OCR 识别成 `II.`。
3. 选项 A 中应为 `I、II`，却被错误解析为 `1、I`（数字 1 替换了罗马数字 I）。
4. 最终前端展示内容与原题不一致，影响题目正确性。

------

#### 原题内容

```text
下列关于线性表的说法，正确的是()。

I. 顺序存储方式只能用于存储线性结构
II. 在一个设有头指针和尾指针的单链表，删除表尾元素的时间复杂度与表长无关
III. 带头结点的循环单链表中不存在空指针
IV. 在一个长度为 n 的有序单链表中插入一个新结点并仍保持有序的时间复杂度为 O(n)
V. 若用单链表来表示队，则应该选用带尾指针的循环链表

A. I、II
B. I、III、IV、V
C. IV、V
D. II、IV、V
```

------

#### 实际导题结果

```text
下列关于线性表的说法，正确的是()。I.顺序存储方式只能用于存储线性结构 II.在一个设有头指针和尾指针的单链表，删除表尾元素的时间复杂度与表长无关 III.带头结点的循环单链表中不存在空指针 IV.在一个长度为 n 的有序单链表中插入一个新结点并仍保持有序的时间复杂度为 O(n) V.若用单链表来表示队，则应该选用带尾指针的循环链表

A. 1、I
B. I、II、IV、V
C. IV、V
D. II、IV、V
```

------

#### OCR 输出分析

OCR 原始结果中已经出现识别错误：

```text
I.
II.
II.   ← 实际应为 III.
IV.
V.
```

同时选项区域被识别为：

```text
A. 1、I
```

实际应为：

```text
A. I、II
```

说明 OCR 阶段已将部分罗马数字 `I` 错误识别为阿拉伯数字 `1`，并将 `III` 错误识别为 `II`。

------

#### 根因分析

当前导题链路缺少对罗马数字序号的校验与纠错机制：

1. **OCR 识别错误**
   - `III` → `II`
   - `I` → `1`
2. **解析阶段未进行语义校验**
   - 未检测题干中罗马编号序列是否连续（I、II、III、IV、V）。
   - 未检测选项内容与题干中的编号集合是否匹配。
3. **后处理阶段缺少规则修复**
   - 未对常见 OCR 错误（`1 ↔ I`、`II ↔ III`）进行自动纠正。
   - 未利用上下文推断缺失的罗马数字。

------

#### 期望结果

系统应能够正确识别并保留罗马数字编号：

```text
I.
II.
III.
IV.
V.
```

选项应解析为：

```json
{
  "A": "I、II",
  "B": "I、III、IV、V",
  "C": "IV、V",
  "D": "II、IV、V"
}
```

前端最终展示内容应与原题保持一致，避免因 OCR 对罗马数字的误识别导致题目语义发生变化。

------

#### 建议排查方向

1. OCR 纠错层增加罗马数字专项修复规则。
2. 建立罗马数字序列完整性校验（I→II→III→IV→V）。
3. 在 AI OCR 校验阶段增加：
   - 罗马数字与阿拉伯数字混淆检测。
   - 选项引用编号合法性检测。
4. 在结构化解析阶段增加题干与选项交叉验证，发现异常时自动修正或标记高风险题目。

---

### 修复评估（2026-06-18）

对 `text_normalizer.py` 修复（`_RE_STRUCTURE_LINE` 增加罗马数字匹配）后的全面评估。

#### 已修复

| 问题 | 措施 |
|------|------|
| 题干罗马数字枚举行合并 | `_RE_STRUCTURE_LINE` 增加 `_ROMAN_SUBITEM_TOKEN` 匹配 |
| 罗马数字序列完整性校验 | `batch_validation._check_roman_numeral_sequence()` 检测序列断裂并追加 warning |
| 跳号检测 | 条件从 `<=` 改为 `- != 1`，捕获 I→II→III→V 类缺失项 |
| 选项文本罗马数字检测 | `_check_roman_numeral_sequence()` 扩展到扫描选项文本，识别选项中的非连续序列 |
| 选项数字 1 与罗马数字混淆 | 新增 `_check_option_roman_digit_confusion()` 检测选项中出现阿拉伯数字 1 的罗马数字上下文 |
| AI 修复感知罗马数字混淆 | `ai_repair` prompt 增加规则 7，指示 LLM 修正 III→II 和 1→I |
| 测试防护 | 13 batch_validation passed，全量 1132 passed（27 预存失败，与本次修复无关） |

#### 短期未修复（需 AI 修复阶段处理）

**`III.` → `II.` OCR 误识 — 规则层无法可靠修复**

PaddleOCR 将 `III.` 识别为 `II.`。规则层无法区分合法 `II.` 与被误识的 `II.`，二者文本相同。已在 `batch_validation` 增加序列断裂检测（I→II→II→IV→V），触发 `broken_roman_numeral_sequence` warning；AI repair 阶段会收到该信号并尝试修正。

**选项 `1、I` → `I、II` — 规则层仅能检测，无法自动修正**

选项 A 文本 `1、I` 已可被 `_check_option_roman_digit_confusion()` 检测并标记 `option_roman_digit_confusion` warning。但规则层无法确定 `1` 应替换为哪个罗马数字（`I` 还是 `II` 等），依赖 AI repair 阶段（prompt 规则 7）利用语义理解修正。

**预存在测试失败 `test_grouped_circled_option_rows_preserve_stem_placeholders`**

`_normalize_punctuation()` 将全角 `（` 转为半角 `(`，破坏对全角占位符 `（ ）` 的预期。与本次修复无关。

---

### 修复评估（2026-06-18 第二轮 — 最小规则层修复）

在现有检测能力基础上，增加规则层自动修复，减少对 AI repair 阶段的硬依赖。

#### 新增修复

| 问题 | 措施 | 覆盖范围 |
|------|------|----------|
| `III.` → `II.` 行首枚举重复 | `_fix_roman_numeral_duplicates()` — 检测行首罗马枚举序列中的重复值，自动递增修复（II→II→IV → II→III→IV） | 仅行首枚举标记（`I.`/`II.`/…），选项内引用不参与 |
| 选项 `1、I` 数字混淆 | `_fix_option_roman_digit_confusion()` — 罗马上下文中的 `1、` → `I、` | 选项行（`A-D` 前缀）内容 |
| 全角括号 `（①）` 被转半角 | `_normalize_punctuation()` — 圈号占位符 `（①）` 在全角→半角转换前暂存保护 | 所有 `（①）`-`（⑳）` 形式 |

#### 仍无法规则层修复

| 问题 | 原因 | 处理方式 |
|------|------|----------|
| 选项 `I→II`缺失（`1、I` → `I、I`仅修复了数字混淆，未补全缺失的 II） | 规则层无法判断选项引用的正确罗马编号集合 | 仍依赖 AI repair |
| 非行首 `III→II`（如选项内容 `I、II、IV、V` 应为 `I、III、IV、V`） | 选项内罗马数字是引用而非枚举，规则层无法区分 | batch_validation 检测 + AI repair |
| 跳号（I→II→IV→V）未修复 | 无法确定是 II 误识还是 IV 误识 | batch_validation 检测 + AI repair |

#### 测试结果

- text_normalizer: 45/45 passed（含之前失败的 `test_grouped_circled_option_rows_preserve_stem_placeholders`）
- batch_validation: 13/13 passed
- 全量回归: 398 passed, 1 failed（`test_ai_unavailable_graceful` — 预存异步 mock 问题，与本次无关）

#### 长期风险

**选项文本内容合理性校验仍不完整**

`batch_validation` 新增了 `_check_option_roman_digit_confusion()` 检测常见罗马数字混淆，但仅限于 `1` 与罗马数字混用场景。其他选项文本内容异常（如拼写错误、语义冲突、结构错乱）仍无规则层校验。
