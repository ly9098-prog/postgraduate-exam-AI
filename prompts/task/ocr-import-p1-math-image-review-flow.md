# OCR 导题 P1 改造任务：公式截图、审核提效与原图对照

> **状态**：✅ 已完成（commit: `c82c464`，2026-06-21）
> **测试结果**：1499 core tests passed, 19 regression passed, 58 parser passed, 30 math/formula passed; frontend TypeScript 0 errors
> **新增模块**：`math_import_profile.py` + `table_region_detector.py`
> **修改文件**：8 个（pipeline_orchestrator, review_service, publish_service, admin_import_service, admin_imports API, frontend page.tsx + types）

## 任务背景

P0 阶段已完成，当前 OCR 导入系统已经完成第一轮最小闭环，包括：

1. 后端审核列表返回顶层 `risk_flags` / `risk_level` / `risk_reasons`。
2. 管理端审核页展示风险徽章。
3. 管理端审核页醒目展示 `ai_answer_flag`。
4. 审核页支持按风险筛选。
5. 审核详情页展示 OCR 原文 `raw_data`。
6. AI repair prompt 已加入公式、代码、答案保护约束。
7. 408 代码上下文已经进行保护，避免普通文本清洗破坏代码。
8. `formula_normalizer` 已按数学学科谨慎接入，避免影响 408 代码题。

P0 的目标是先让风险可见、让 AI 不乱改、让审核员能快速发现问题。P1 的目标是在 P0 基础上继续提高导题准确率和审核效率，重点解决高数公式、原图对照、低风险批量审核、表格初步保真。

## 本轮总目标

本轮 P1 不做大重构，不拆分整个 pipeline，而是做 4 个高收益闭环：

```text
1. 公式截图保留接入新版 pipeline
2. 管理端审核页展示 math_image segment
3. 低风险题批量通过
4. 原图 / 题目区域对照预览的最小实现
5. 表格题初步检测与 Markdown 保真
```

本轮目标不是追求全自动完美识别，而是：

```text
公式不确定 → 保留截图 + 标记需核对
表格不确定 → 保留 Markdown / 原始结构 + 标记需核对
低风险题 → 快速批量通过
高风险题 → 能对照原图快速修
```

## 全局约束

请严格遵守：

1. 不大规模拆分 `pipeline_orchestrator.py`。
2. 不重写 OCR pipeline。
3. 不改小程序端，除非发现已有数据结构无法被现有组件渲染。
4. 不新增复杂数据库迁移，优先复用已有字段：
   - `QuestionImport.parsed_content`
   - `QuestionImport.raw_data`
   - `QuestionImport.ai_metadata`
   - `QuestionImport.math_regions`
   - `Question.content`
5. 不破坏 P0 已完成的：
   - `risk_flags`
   - `risk_level`
   - `risk_reasons`
   - `ai_answer_flag`
   - OCR 原文展示
   - 代码块保护
   - formula_normalizer 安全接入
6. 不让 AI 猜公式。
7. 不让 AI 根据题目内容推理答案。
8. 不让 AI 改写 408 代码逻辑。
9. 公式截图、原图上传、表格检测失败时，不允许导致整批导入失败。
10. 所有新增能力都要 graceful fallback。
11. 修改完成后必须运行相关测试。
12. 如果发现 P0 实现与本文件假设不一致，以当前真实代码为准，并在最终报告说明。

------

# P1-1：审计并确认 P0 落地后的可复用字段

## 目标

在真正接入公式截图和原图对照前，先确认 P0 后的字段和前端展示能力。

## 需要检查的文件

```text
backend/app/schemas/admin_imports.py
backend/app/services/admin_import_service.py
backend/app/api/v1/admin_imports.py
backend/app/features/review_service.py
backend/app/models/question_import.py
backend/app/models/question.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/lib/api/types.ts
```

## 需要确认

1. 审核列表 item 是否已有：
   - `risk_flags`
   - `risk_level`
   - `risk_reasons`
   - `ai_answer_flag`
   - `raw_data`
2. `risk_flags` 是否来自 `ai_metadata.risk_flags`。
3. `risk_level` 是否可根据新增风险继续推导。
4. 审核页是否已经可以显示新风险原因。
5. `QuestionImport.parsed_content` 是否能保存 `segments`。
6. `QuestionImport.math_regions` 是否可用。
7. 审核通过后 `Question.content` 是否能保留 `segments`。
8. 如果新增 `math_image`、`source_region_image`、`table_markdown` segment，前端是否能兼容。

## 输出要求

在最终报告中输出：

| 能力 | 当前是否支持 | 文件位置 | P1 是否可复用 | 缺口 |
| ---- | ------------ | -------- | ------------- | ---- |
|      |              |          |               |      |

## 验收标准

1. 明确 P1 应该把公式截图写到哪里。
2. 明确原图对照信息应该写到哪里。
3. 明确风险标记如何接入 P0 的 `risk_level`。
4. 不重复实现 P0 已完成的字段。

------

# P1-2：数学公式区域检测接入新版 pipeline

## 目标

在新版 OCR pipeline 中，为高数题检测公式区域，为后续公式截图、风险标记、审核展示做准备。

## 修改文件

优先检查并复用：

```text
backend/app/services/math_region_detector.py
backend/app/features/pipeline_orchestrator.py
backend/app/features/review_service.py
```

必要时新增轻量工具：

```text
backend/app/features/math_import_profile.py
```

## 接入位置

建议接入位置：

```text
normalize_schema 后
repair 前或 repair 后
review 入库前
```

推荐优先：

```text
normalize_schema 后、review 入库前
```

原因：

1. 题目已经标准化，可以读取 stem / analysis / subject / category。
2. P0 已经做了 formula_normalizer 安全接入，此时可以判断哪些题是数学候选题。
3. review 入库前可把 `math_regions`、`segments`、`risk_flags` 写入暂存题。
4. 不干扰 OCR 原始识别和题目切分。

## 数学候选题判断

仅对明确数学题或明显含复杂公式的题启用。

### 可以触发的信号

```text
subject 包含 math
subject 名称包含 数学
subject 名称包含 高数
category/path 包含 高数
category/path 包含 数学
题干或解析包含 ∫、∑、√、lim、frac、matrix、cases、sin、cos、tan、ln、log、dx、dy、∞、α、β
题干或解析包含 \int、\sum、\frac、\sqrt、\begin{matrix}、\begin{cases}
```

### 必须排除的信号

```text
408
计算机
C语言
C 语言
数据结构
操作系统
计算机组成原理
计组
计算机网络
计网
SQL
#include
int main
struct
typedef
for (
while (
if (
printf
scanf
SELECT
WHERE
```

## region 结构建议

```json
{
  "type": "formula",
  "page": 3,
  "bbox": [120, 340, 520, 410],
  "confidence": 0.72,
  "kind": "complex_formula",
  "source": "ocr_boxes",
  "requires_review": true
}
```

## 新增风险标记

检测到公式区域时，根据情况添加：

```text
math_region_detected
math_low_confidence
complex_formula_requires_review
```

## 要求

1. 优先复用现有 `math_region_detector.py`。
2. 如果没有 OCR boxes，不能崩溃。
3. 如果无法定位 bbox，也可以先只加风险标记。
4. 不要让数学检测影响 408 题。
5. 不要因为检测失败中断导入。
6. 风险标记必须进入 P0 的 `risk_flags` / `risk_level` 系统。

## 验收标准

1. 高数题能产生 `math_regions`。
2. 非数学题不产生 `math_regions`。
3. 408 代码题不会进入公式区域检测。
4. 低置信度或复杂公式会进入“需检查”或“高风险”。
5. 检测失败时仍能进入审核队列。

------

# P1-3：公式截图裁剪与 math_image segment 构建

## 目标

对复杂公式、低置信度公式、矩阵、分式、分段函数等区域，裁剪截图并写入 `parsed_content.segments`。

## 修改文件

优先检查并复用：

```text
backend/app/services/formula_image_cropper.py
backend/app/services/hybrid_content_builder.py
backend/app/services/storage_backend.py
backend/app/features/pipeline_orchestrator.py
backend/app/features/review_service.py
```

## 处理策略

### 简单公式

```text
保留文本
不强制截图
可继续使用 formula_normalizer 结果
```

### 复杂公式

```text
裁剪截图
写入 math_image segment
添加 complex_formula_requires_review
```

复杂公式包括：

```text
复杂分式
矩阵
行列式
分段函数
多行推导
复杂极限
复杂积分
概率统计复杂表达式
```

### 低置信度公式

```text
裁剪截图
requires_review=true
添加 math_low_confidence
```

## math_image segment 结构

```json
{
  "type": "math_image",
  "url": "https://.../formula_xxx.png",
  "alt": "公式截图",
  "source_page": 3,
  "bbox": [120, 340, 520, 410],
  "confidence": 0.72,
  "requires_review": true
}
```

## graceful fallback

如果截图失败：

```json
{
  "type": "math_image",
  "url": null,
  "alt": "公式截图生成失败",
  "source_page": 3,
  "bbox": [120, 340, 520, 410],
  "confidence": 0.72,
  "requires_review": true,
  "upload_failed": true
}
```

并添加风险：

```text
math_image_crop_failed
math_image_upload_failed
```

## 要求

1. 优先写入 `parsed_content.segments`。
2. 同步保留或补充 `math_regions`。
3. 原始 `stem` 不要删除，要作为 fallback。
4. 不要因为 OSS 不可用导致整批失败。
5. 不要影响普通文本题。
6. 不要对 408 代码题生成 `math_image`。
7. 如果当前 page image 在 pipeline 后续阶段已释放，请先实现最小可行方式：
   - 有 page image 时截图
   - 无 page image 时只写 math_region + risk_flag
   - 不要为了截图重新跑 OCR

## 验收标准

1. 复杂高数公式题能生成 `math_image` segment。
2. 低置信度公式题 `requires_review=true`。
3. 截图失败时题目仍进入审核队列。
4. `stem` 和原始文本仍保留。
5. 408 题不生成公式截图。

------

# P1-4：管理端审核页展示 math_image segment

## 目标

审核员在管理端能看到公式截图，并能快速判断公式是否需要人工核对。

## 修改文件

```text
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/lib/api/types.ts
```

## 实现要求

1. 如果 `parsed_content.render_mode == "segments"`，按 segments 渲染。
2. 至少支持以下 segment：
   - `text`
   - `math_image`
3. `math_image` 用图片展示。
4. 如果 `requires_review=true`，显示“公式需核对”标签。
5. 如果有 `confidence`，显示置信度。
6. 如果 `upload_failed=true` 或 `url` 为空，显示“公式截图生成失败，请核对 OCR 文本”。
7. 不影响普通题目详情显示。
8. 不影响题目编辑、通过、拒绝操作。
9. 不重复做 P0 的风险徽章逻辑，只复用 P0 已有展示体系。

## 验收标准

1. 审核页能看到公式截图。
2. 低置信度公式有醒目标记。
3. 截图失败时有明确提示。
4. 普通题和 408 代码题展示不受影响。
5. TypeScript 类型检查通过。

------

# P1-5：审核通过后保留 segments 到正式题库

## 目标

导入暂存题审核通过后，`math_image` segment 不应丢失。

## 修改文件

```text
backend/app/features/review_service.py
backend/app/services/admin_import_service.py
backend/app/models/question.py
```

## 检查点

请检查：

1. `QuestionImport.parsed_content` 如何写入 `Question.content`。
2. 审核通过接口是否重组了 content。
3. 是否有字段白名单导致 `render_mode` / `segments` 丢失。
4. 小程序刷题页最终读取的是 `Question.content` 还是拆开的 stem/options/analysis 字段。

## 实现要求

1. 保留 `render_mode`。
2. 保留 `segments`。
3. 保留 `math_image` segment。
4. 保留原始 `stem` 作为 fallback。
5. 不破坏旧题目结构。
6. 如果正式题库已有题不含 segments，仍按原逻辑展示。

## 验收标准

1. 审核通过后，正式题库记录中仍有 `segments`。
2. `math_image` segment 不丢失。
3. 旧题目不受影响。
4. 小程序端现有渲染逻辑不被破坏。

------

# P1-6：低风险题批量通过

## 目标

P0 已支持风险等级展示和筛选。P1 增加“低风险题批量通过”，减少人工逐题点击。

## 修改文件

```text
backend/app/api/v1/admin_imports.py
backend/app/services/admin_import_service.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/lib/api/types.ts
```

## 实现要求

1. 后端新增或扩展批量审核接口，支持只批量通过低风险题。
2. 低风险条件：
   - `risk_level == "low"`
   - `ai_answer_flag != True`
   - `answer` 不为空
   - 没有 `math_low_confidence`
   - 没有 `complex_formula_requires_review`
   - 没有 `code_symbol_risk`
   - 没有 `option_structure_corruption`
3. 前端在审核页提供按钮：
   - “批量通过低风险题”
4. 点击前弹出确认：
   - 显示即将通过数量
   - 提醒“高风险和需检查题不会被通过”
5. 批量通过后刷新列表和统计。
6. 如果没有低风险题，按钮置灰。

## 验收标准

1. 低风险题可以批量通过。
2. 高风险题不会被误通过。
3. AI 答案题不会被低风险批量通过。
4. 筛选和分页状态不会混乱。
5. 操作后列表刷新正确。

------

# P1-7：原图 / 题目区域对照预览的最小实现

## 目标

审核员能看到题目来源页面或题目区域截图，提高修题效率。

## 修改文件

优先检查：

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/review_service.py
backend/app/models/question_import.py
backend/app/services/storage_backend.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/lib/api/types.ts
```

## 最小实现策略

不要一次性做复杂图像管理系统。

优先级：

### 方案 A：page image URL

如果 pipeline 中已有 page image：

1. 上传或保存 page image。
2. 在 `raw_data` 或 `parsed_content.source_page_image` 中记录 URL。
3. 审核页展示“查看原页”。

### 方案 B：question region image

如果能从 bbox 推断题目区域：

1. 裁剪题目区域。
2. 保存 URL。
3. 写入 `parsed_content.source_region_image`。

### 方案 C：只有页码 / bbox

如果暂时不能保存图片：

1. 保留 `source_page`。
2. 保留 `bbox`。
3. 添加风险提示：“当前题有定位信息但无原图”。

## 数据结构建议

```json
{
  "source_page": 3,
  "source_region": {
    "bbox": [80, 120, 680, 420],
    "image_url": "https://.../question_region.png",
    "page_image_url": "https://.../page_3.png"
  }
}
```

## 实现要求

1. 不因为图片保存失败导致导入失败。
2. 不重复保存超大图片到 `_pipeline_store`。
3. 如果上传失败，只加 `source_image_upload_failed` risk flag。
4. 审核页默认折叠原图对照，避免页面过长。
5. 不影响普通审核流程。

## 验收标准

1. 有原图时，审核详情页能打开查看。
2. 无原图时，页面正常显示占位提示。
3. 图片保存失败不影响导入。
4. 不造成 `_pipeline_store` 大字段回流。
5. 大 PDF 导入内存不明显回升。

------

# P1-8：表格题初步检测与 Markdown 保真

## 目标

不做复杂表格 OCR 引擎，只做“表格风险检测 + Markdown 保真”的最小版本，避免 408 表格题被当普通文本完全压扁。

## 修改文件

优先检查：

```text
backend/app/services/ocr_service.py
backend/app/features/text_normalizer.py
backend/app/features/question_splitter.py
backend/app/features/review_service.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

必要时新增：

```text
backend/app/features/table_region_detector.py
```

## 表格候选场景

重点识别：

```text
进程调度表
页表
段表
Cache 映射表
路由表
真值表
哈夫曼编码表
概率统计数据表
多列数字表
```

## 检测信号

1. OCR boxes 呈现明显多列对齐。
2. 连续多行有相似 x 坐标分布。
3. 文本中存在表头词：
   - 进程
   - 到达时间
   - 服务时间
   - 页号
   - 块号
   - Cache
   - 标记
   - 路由
   - 下一跳
   - 编码
   - 频率
4. 行内出现多个用空格分隔的短 token。

## 输出结构建议

```json
{
  "type": "table_markdown",
  "markdown": "| 进程 | 到达时间 | 服务时间 |\n|---|---:|---:|\n| P1 | 0 | 3 |",
  "source_page": 2,
  "bbox": [100, 200, 620, 360],
  "confidence": 0.66,
  "requires_review": true
}
```

## 风险标记

```text
table_detected
table_requires_review
table_low_confidence
```

## 实现要求

1. 不要求完美表格识别。
2. 能保留基本行列关系即可。
3. 置信度低时进入“需检查”。
4. 管理端审核页能展示 Markdown 表格。
5. 不要影响普通选择题。
6. 表格识别失败时，保留原始文本并添加风险标记。

## 验收标准

1. 408 调度表 / Cache 表能被识别为表格候选。
2. 审核页能看到 Markdown 表格。
3. 表格低置信度题不会被批量低风险通过。
4. 普通文本题不被误判成表格。

------

# P1-9：风险等级与新增 risk_flags 联动

## 目标

P1 新增的公式、原图、表格风险必须进入 P0 的风险体系。

## 修改文件

```text
backend/app/services/admin_import_service.py
backend/app/schemas/admin_imports.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

## 新增风险映射

### high

```text
math_image_crop_failed
math_image_upload_failed
source_image_upload_failed
table_low_confidence
complex_formula_requires_review
```

### medium

```text
math_region_detected
math_image_attached
table_detected
table_requires_review
source_region_available
```

### low

无新增风险，且结构完整。

## 要求

1. `risk_level` 推导逻辑纳入这些新增 flag。
2. `risk_reasons` 增加中文解释。
3. 审核页能展示新增风险原因。
4. 低风险批量通过必须排除 high / medium 风险题。

## 验收标准

1. 公式截图失败题显示高风险。
2. 表格低置信度题显示高风险或需检查。
3. 有公式截图但正常的题至少显示需检查。
4. 低风险批量通过不会通过这些题。

------

# 测试要求

请至少运行或补充以下测试。

## 后端测试

覆盖：

1. 数学候选题识别：
   - `∫`
   - `∑`
   - `lim`
   - `\frac`
   - `\begin{matrix}`
2. 408 排除：
   - `p->next`
   - `if (a <= b && b != c)`
   - `#include <stdio.h>`
3. `math_regions` 生成：
   - 有 OCR boxes 时能生成 region。
   - 无 OCR boxes 时不崩溃。
4. `math_image` segment 构建：
   - 成功截图时有 `math_image`。
   - 截图失败时有 risk flag。
5. 发布保留：
   - `QuestionImport.parsed_content.segments` 发布后进入 `Question.content`。
6. 低风险批量通过：
   - 只通过 low。
   - 不通过 AI 答案题。
   - 不通过公式 / 表格需检查题。
7. 表格检测：
   - 408 表格候选能产生 `table_markdown`。
   - 普通文本不误判。

## 前端测试 / 类型检查

覆盖：

1. `admin-frontend` 类型不报错。
2. `review/page.tsx` 能渲染：
   - 普通文本题
   - segments 题
   - math_image segment
   - table_markdown segment
   - 原图对照区域
   - upload_failed 状态
3. 风险标签仍能展示。
4. 低风险批量通过按钮状态正确。

## 回归测试

至少运行：

```bash
pytest tests/ocr_regression
```

如果环境不支持完整 OCR，请运行不依赖 PaddleOCR 的单元测试，并说明未运行完整 OCR 的原因。

------

# 不做事项

本轮明确不做：

1. 不拆分 `pipeline_orchestrator.py`。
2. 不拆分 `question_pipeline.py`。
3. 不做 OCR 缓存。
4. 不做断点恢复。
5. 不做 AI 补全并行化。
6. 不做完整复杂表格 OCR 引擎。
7. 不做复杂图像管理系统。
8. 不修改小程序端，除非现有数据完全无法展示。
9. 不让 AI 猜答案。
10. 不让 AI 猜公式。
11. 不让公式 / 原图 / 表格处理失败中断整批导入。

------

# 最终输出格式

执行完成后，请输出：

## 1. 本轮完成了哪些 P1 任务

逐项说明 P1-1 到 P1-9 是否完成。

## 2. 修改了哪些文件

用表格列出：

| 文件 | 修改内容 | 对应任务 |
| ---- | -------- | -------- |
|      |          |          |

## 3. 新增或变更字段 / segment

说明：

| 字段或 segment | 类型 | 来源 | 用途 | 是否兼容 |
| -------------- | ---- | ---- | ---- | -------- |
|                |      |      |      |          |

## 4. 新增 risk_flags

说明：

| risk_flag | 风险等级 | 中文原因 | 触发条件 |
| --------- | -------- | -------- | -------- |
|           |          |          |          |

## 5. 新增测试

说明新增了哪些测试文件、测试函数、覆盖哪些风险。

## 6. 运行测试结果

输出实际运行命令和结果。

## 7. 未完成事项

如果某项任务未完成，请说明原因和后续建议。

## 8. 风险和注意事项

说明本次修改是否可能影响：

- PDF 导入
- 图片导入
- Excel 导入
- 文本导入
- 管理端审核
- 高数题
- 408 代码题
- 表格题
- 小程序刷题页
- `_pipeline_store` 内存体积

## 9. 下一轮建议

下一轮优先考虑：

1. AI 补全并行化。
2. 高置信度题跳过 AI repair。
3. OCR 结果缓存。
4. 断点恢复。
5. `pipeline_orchestrator.py` 渐进拆分。

