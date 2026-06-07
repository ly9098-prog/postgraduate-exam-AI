# 问题类型：多空选择题结构丢失

## 原题结构

题目包含多个填空位，每个填空位使用编号标记：

```
若系统有 n 个进程，则就绪队列中进程的个数最多有（①）个；
阻塞队列中进程的个数最多有（②）个。

① A. n+1  B. n  C. n−1  D. 1

② A. n+1  B. n  C. n−1  D. 1
```

这里：

- ① 和 ② 是两个独立子问题
- 每个子问题拥有自己对应的选项组
- 即使两组选项内容完全相同，也必须保留编号映射关系

------

## 当前错误

OCR / Normalize 后变成：

```
若系统有 n 个进程，则就绪队列中进程的个数最多有（）个；
阻塞队列中进程的个数最多有（）个。

A. n+1
B. n
C. n−1
D. 1
```

导致：

- 删除了①、②编号
- 丢失了“填空 ↔ 选项组”的对应关系
- 两个空被错误合并为共享一组选项
- 题目语义发生变化

------

## 根因

当前题目解析器默认假设：

```
题干
↓
选项
```

属于单选题结构。

但实际上该题属于：

```
题干
 ├─ 空① → 选项组①
 └─ 空② → 选项组②
```

即：

**Multiple Blank Choice Question（多空选择题）**

而非普通单选题。

------

## 修复要求

在 Structure Analysis / Question Parser 阶段增加识别规则：

### 规则1：识别空位编号

检测：

```
（①）
（②）
（③）

①
②
③
```

或：

```
(1)
(2)

Ⅰ
Ⅱ

A
B
```

等子题编号。

------

### 规则2：识别编号对应选项组

检测模式：

```
① A.xxx B.xxx C.xxx D.xxx

② A.xxx B.xxx C.xxx D.xxx
```

或者

```
①
A.xxx
B.xxx
C.xxx
D.xxx

②
A.xxx
B.xxx
C.xxx
D.xxx
```

建立映射：

```json
{
  "blank_1": {
    "marker": "①",
    "options": [...]
  },
  "blank_2": {
    "marker": "②",
    "options": [...]
  }
}
```

------

### 规则3：禁止错误合并

如果存在：

```
① ...
② ...
```

对应的多个选项组，

即使选项内容完全一致：

```
A.n+1
B.n
C.n−1
D.1
```

也不能去重合并。

因为：

```
① → A/B/C/D
② → A/B/C/D
```

是两个独立作答空间。

------

## 输出结构建议

不要输出：

```json
{
  "question": "...（）...（）...",
  "options": [...]
}
```

应输出：

```json
{
  "question": "若系统有n个进程...",
  "blanks": [
    {
      "id": "①",
      "options": [...]
    },
    {
      "id": "②",
      "options": [...]
    }
  ]
}
```

------

一句话总结：

> 修复“多空选择题结构丢失”问题。对于题干中出现①②③等空位编号，且后续存在对应编号的选项组时，必须保留“空位编号 → 选项组”的映射关系，禁止将多个编号对应的选项组合并为单组选项。即使选项内容完全相同，也应视为多个独立子题，而不是普通单选题。这样才能保证题目语义不被破坏。

------

## 当前定位结论

本轮本地审核池排查显示，问题不是单纯的前端展示缺失：受影响记录进入审核池时已经是 `single_choice`，并且 `raw_data` 与 `parsed_content` 中都没有 `blank_option_groups`。其中部分 OCR 文本已经把 `（①）（②）` 退化为多个普通 `（）`，部分文本仍保留 `(1)` / `(2)` 但未被解析为多空选择题。

因此需要同时修复两个边界：

- 后端解析链路必须在进入审核池前识别并保留多空选择结构。
- 前端审核页必须能展示 `blank_option_groups`，不能只展示扁平 `parsed_options`。

## 最小修复方案

本次只做最小闭环修复，不做大规模重构：

1. 在题目切分 / 结构解析阶段识别多空选择题。
2. 在标准化阶段输出统一结构：`question_type = "multi_blank_choice"`、`options = []`、`blank_option_groups = [...]`。
3. 在审核池入库、AI 修复、审核通过发布链路中透传 `blank_option_groups`。
4. 在小程序审核页与管理端审核页展示每个空位对应的选项组。

## 后端规则

### 1. 显式组选项必须保留

支持：

```text
① A.xxx B.xxx C.xxx D.xxx
② A.xxx B.xxx C.xxx D.xxx
```

以及：

```text
①
A.xxx
B.xxx
C.xxx
D.xxx

②
A.xxx
B.xxx
C.xxx
D.xxx
```

解析结果必须保留为独立组选项，不能将 `① A.` 误判为普通选项前缀。

### 2. 空位编号格式需要兼容

除 `①②③` 外，还需要兼容：

```text
(1) / （1）
Ⅰ / Ⅱ / Ⅲ
```

当题干中出现多个空位编号，后续存在对应组选项时，题型应为 `multi_blank_choice`。

### 3. OCR 退化场景保守兜底

当 OCR 已将 `（①）（②）` 识别为多个普通 `（）`，且后续选项块出现重复或可复制的多组选项时，应按空位顺序生成独立 `blank_option_groups`，并附加风险标记 / 警告，避免静默降级为普通单选题。

### 4. 输出结构约束

`multi_blank_choice` 的主展示选项不能依赖扁平 `options`：

```json
{
  "question_type": "multi_blank_choice",
  "stem": "题干含（①）（②）或等价空位标记",
  "options": [],
  "blank_option_groups": [
    {
      "id": "①",
      "options": [
        {"key": "A", "text": "..."},
        {"key": "B", "text": "..."}
      ]
    },
    {
      "id": "②",
      "options": [
        {"key": "A", "text": "..."},
        {"key": "B", "text": "..."}
      ]
    }
  ]
}
```

即使两组选项内容完全一致，也必须保留两个独立 group，禁止去重合并。

## 前端审核页规则

### 小程序审核页

审核列表 / 详情页需要从以下位置读取组选项：

```text
parsed_content.blank_option_groups
raw_data.blank_option_groups
```

当题型为 `multi_blank_choice` 或存在 `blank_option_groups` 时：

- 题型展示为“多空选择题”。
- 题干仍展示 `parsed_content.text`。
- 选项区按组展示：`① → A/B/C/D`、`② → A/B/C/D`。
- 不应只依赖 `parsed_options`，否则会误显示为普通单选题。

### 管理端审核页

审核详情 / Diff 中需要展示 `content.blank_option_groups`，方便确认每个空位与选项组的映射关系是否被保留。

## 验收标准

使用以下样例验证：

1. `（①）（②）` + `① A...D...` / `② A...D...`
2. `①` 单独成行 + 多行 A/B/C/D 组选项
3. OCR 退化后的两个 `（）` + 两段重复 A/B/C/D 选项
4. `(1)(2)` / `（1）（2）` 变体
5. `ⅠⅡ` 变体

所有样例应满足：

- `question_type == "multi_blank_choice"`
- `options == []` 或不作为主展示来源
- `blank_option_groups` 数量等于空位数量
- 每个 group 都保留自己的 `id` 和选项列表
- 内容相同的组选项不能被合并
- 审核池 `parsed_content.blank_option_groups` 仍存在
- 小程序审核页和管理端审核页能按组展示选项

------

## 当前完成情况（2026-06-07）

> 本段根据当前代码可见状态更新；未把未执行的真实样本导入、专项测试或真机/浏览器验证记录为已通过。

### 已完成

- [x] **任务文档已同步修复方案**：已记录后端解析、标准化、入审透传与前端审核页展示的最小闭环要求。
- [x] **文本清洗层已保护更多组选项标记**：`text_normalizer.py` 已将 circled、`(1)` / `（1）`、罗马数字等 group marker 纳入结构行判断，降低 marker 行被 OCR 断行合并吞掉的概率。
- [x] **题目切分层已增加多空选择识别能力**：`question_splitter.py` 已出现 `blank_option_groups` 输出、显式组选项解析、OCR 退化空括号兜底与 grouped options 合并保护逻辑。
- [x] **标准化层已支持多空选择输出结构**：`question_normalizer.py` 在存在 `blank_option_groups` 时输出 `question_type = "multi_blank_choice"`、`options = []`，并把组选项写回结果。
- [x] **导入/审核通过链路已透传组选项**：`question_pipeline.py` 会规范化 `blank_option_groups`，并在 `parsed_content` / 正式题 `content` 中保留；`review_service.py` 入审核池时也会把上游 `blank_option_groups` 写入 `parsed_content`。
- [x] **小程序批次审核页已增加 grouped options 展示入口**：`import-batch.js/wxml` 已读取 `parsed_content.blank_option_groups` / `raw_data.blank_option_groups`，并按“空位选项组”渲染。
- [x] **管理端正式题审核 Diff 已增加 grouped options 展示入口**：`admin-frontend/src/app/(admin)/review/page.tsx` 已出现 `blankOptionGroupsFromContent(...)` 与“空位选项组” Diff 展示。

### 未完成 / 待验证

- [ ] **最终验收尚未通过**：还需要用真实 OCR/PDF 导入样本确认审核池记录实际变为 `multi_blank_choice`，且 `parsed_content.blank_option_groups` 存在。
- [x] **`(1)` / `(2)` 边界已专项复查并修复**：`question_splitter.py` 已避免把 `(1) A...` / `(2) A...` 组选项误判成新题边界，专项单测覆盖该场景。
- [x] **OCR 退化兜底已专项样例确认**：两个普通 `（）` + 重复 A/B/C/D 选项块可生成两个独立 group，且 `option_lines` 不再作为主展示来源。
- [ ] **前端展示需真实页面验证**：小程序审核页和管理端审核页已具备代码入口，但仍需用实际导入批次检查展示、编辑、通过/拒绝流程。
- [x] **测试记录已补充**：已记录后端 smoke/专项测试与 mock 入审透传测试；前端页面验证仍待真实页面执行。

### 本轮新增修复（2026-06-07）

- [x] **修复 `(1)` / `(2)` 组选项误切题**：当括号编号后紧跟 A/B/C/D 选项标记时，不再识别为题号边界，保留在当前题的 `blank_option_groups` 中。
- [x] **补充多空选择题专项单测**：覆盖 `（①）（②）`、`(1)(2)`、OCR 退化普通 `（）` + 重复选项块、`ⅠⅡ` 罗马数字变体，以及标准化输出 `multi_blank_choice` / `options = []`。
- [x] **补充审核入池透传单测**：`review_service.submit_to_review()` 已验证 `multi_blank_choice` 入池时 `parsed_options is None`、`parsed_answer is None`，并在 `parsed_content.blank_option_groups` / `raw_data.blank_option_groups` 中保留组选项。
- [x] **执行后端验证**：`PYTHONPATH=/home/lmh/projects/postgraduate-ai/backend pytest -q /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_question_splitter.py /home/lmh/projects/postgraduate-ai/backend/tests/test_services/test_review_service.py`，结果 `114 passed, 1 warning in 1.32s`；同时用 4 类 smoke 样例验证 splitter → normalizer 输出均为 `multi_blank_choice` 且保留两组 `blank_option_groups`。

### 下一步

1. 用真实 OCR/PDF 导入样本确认审核池记录实际变为 `multi_blank_choice`，且 `parsed_content.blank_option_groups` 存在。
2. 用真实导入批次确认小程序审核页与管理端审核页展示、编辑、通过/拒绝流程。
3. 真实链路验收完成后，再将本任务状态改为“已验收”。
