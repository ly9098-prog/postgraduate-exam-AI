# OCR 导题 P0 改造任务：审核风险展示与公式/代码/答案保护

## P0 任务进度

| 任务 | 状态 | 提交 | 备注 |
|------|------|------|------|
| P0-1: 后端审核列表返回 risk_flags / risk_level | ✅ 完成 | 本期 | derive_import_risk() + AdminImportQuestionItem 新增字段 |
| P0-2: 管理端审核页展示风险徽章 | ✅ 完成 | 本期 | 列表卡展示 risk_level 红/黄/绿标签 + risk_reasons |
| P0-3: 管理端醒目展示 AI 答案标记 | ✅ 完成 | 本期 | 橙色 "AI 答案" 标签 + 详情页答案区警告 |
| P0-4: 审核页支持按风险筛选 | ✅ 完成 | 本期 | risk_level 查询参数 + 前端下拉框 |
| P0-5: 审核详情页展示 OCR 原文 raw_data | ✅ 完成 | 本期 | 可折叠 "OCR 原文 / 导入原始信息" 区域 |
| P0-6: AI repair prompt 加入保护约束 | ✅ 完成 | 本期 | question_repair 增加 12 条硬约束 + risk_flags 输出 |
| P0-7: 代码上下文保护 | ✅ 完成 | 本期 | CODE_DETECTOR_ENABLED=true，已有围栏检测激活 |
| P0-8: 公式 normalizer 安全调用 | ✅ 完成 | 本期 | safe_fix_ocr_formula() 安全辅助函数 |

> 完成日期: 2026-06-21
>
> 改动文件:
> - `backend/app/ai/prompts.py` — question_repair prompt 增加不猜答案/保护公式代码/risk_flags 约束
> - `backend/app/core/config.py` — CODE_DETECTOR_ENABLED=true
> - `backend/app/schemas/admin_imports.py` — AdminImportQuestionItem 增加 risk_flags/risk_level/risk_reasons
> - `backend/app/services/admin_import_service.py` — derive_import_risk() 函数 + _apply_risk_to_item + risk_level 过滤
> - `backend/app/api/v1/admin_imports.py` — review-queue API 增加 risk_level 查询参数
> - `backend/app/services/formula_normalizer.py` — is_math_subject() + safe_fix_ocr_formula()
> - `admin-frontend/src/lib/api/types.ts` — ImportQuestionItem 增加风险字段类型
> - `admin-frontend/src/app/(admin)/imports/review/page.tsx` — 风险徽章/AI 答案/OCR 原文/风险筛选
>
> 测试结果: 112/112 关键测试通过, TypeScript 编译无错误

## 任务背景

本项目是考研刷题小程序，包含：

- `backend`：FastAPI 后端
- `admin-frontend`：Next.js 管理端
- `miniprogram`：微信小程序用户端

OCR 功能主要用于题库导入，不需要做通用 OCR 平台。核心目标是提高高数题、408 计算机类题目的导入准确率，减少用户导入后发现"题目和原题不符"的情况。

上一轮审计结论：

1. 管理端导入接口没有走错，实际调用的是 `POST /api/admin/v1/imports/upload`，不是 deprecated 的 `/api/v1/import/upload`。
2. 公式截图能力已有基础设施，但没有贯通到新版 pipeline。
3. 当前最影响导题效率的问题之一是审核页没有把风险信息展示出来，例如 `risk_flags`、`ai_answer_flag`、OCR 原文等。
4. 高数题风险主要来自公式区域未保护、公式 normalizer 未稳定接入新版 pipeline、AI 可能猜公式。
5. 408 题风险主要来自代码缩进丢失、关键符号被误改、AI repair 可能改写代码逻辑。
6. 本轮不做完整公式截图 pipeline，不做表格结构化，不改小程序端，先做 P0 最小闭环。

## 本轮总目标

本轮目标不是重构 OCR pipeline，也不是接入完整公式截图系统，而是先解决：

1. 导入后用户难以及时发现 OCR 错误。
2. AI 可能改坏公式、代码、答案。
3. 管理端审核页不能快速筛选高风险题。
4. 408 代码题可能被普通文本清洗破坏。
5. 高数公式 normalizer 需要谨慎接入，不能影响 408 代码题。

## 全局约束

请严格遵守：

1. 只做本文件列出的 P0 任务。
2. 不做大重构。
3. 不修改 `miniprogram`。
4. 不新增复杂数据库迁移，优先复用已有字段，例如：
   - `ai_metadata`
   - `raw_data`
   - `parsed_content`
5. 不改变现有 API 的已有字段含义，只允许增加兼容字段。
6. 不接入完整公式截图 pipeline，本轮只做风险展示、保护规则和审核效率提升。
7. 修改完成后运行相关测试。
8. 输出修改文件、修改点、测试结果、未完成事项。
9. 代码要尽量局部修改，不要牵连无关导入流程。
10. 不要破坏已有 PDF、图片、Excel、文本导入功能。

---

# P0-1：后端审核列表返回顶层 risk_flags / risk_level

## 背景

审计报告指出，后端已有 `ai_metadata.risk_flags`，但管理端审核页未有效展示，导致管理员无法快速发现高风险题。

## 需要检查和修改的文件

```text
backend/app/schemas/admin_imports.py
backend/app/services/admin_import_service.py
backend/app/api/v1/admin_imports.py
admin-frontend/src/lib/api/types.ts
```

## 目标

在审核列表返回的每个题目 item 中，增加兼容字段：

```json
{
  "risk_flags": ["math_low_confidence", "ai_repaired", "answer_ai_generated"],
  "risk_level": "high",
  "risk_reasons": ["公式可能识别不准确", "答案由 AI 补全"]
}
```

## 实现要求

1. `risk_flags` 优先从 `QuestionImport.ai_metadata.risk_flags` 提取。
2. 如果 `ai_metadata` 中不存在 `risk_flags`，则返回空数组。
3. `risk_level` 根据 `risk_flags` 和 `ai_answer_flag` 计算：

   * `high`：

     * 答案 AI 生成
     * 代码符号风险
     * 公式低置信度
     * 选项数量异常
     * 答案缺失
     * AI 大幅修改
   * `medium`：

     * AI 修复
     * OCR 置信度偏低
     * 包含公式/代码/表格但未明确失败
   * `low`：

     * 无明显风险
4. `risk_reasons` 输出中文短句，方便前端直接展示。
5. 不删除原有 `ai_metadata`，只是额外展开几个顶层字段。
6. 如果现有 schema 不方便新增字段，可以在 service 层组装返回值时补充。
7. 建议新增辅助函数：

```python
def derive_import_risk(
    ai_metadata: dict | None,
    ai_answer_flag: bool | None = None,
    parsed_content: dict | None = None,
) -> dict:
    ...
```

## 验收标准

1. 审核列表接口每条记录包含：

   * `risk_flags`
   * `risk_level`
   * `risk_reasons`
2. 无风险题返回：

   * `risk_flags=[]`
   * `risk_level="low"`
3. AI 答案题至少为 `high` 或 `medium`，并包含明确 reason。
4. 不影响原有审核列表字段。
5. 不传风险筛选参数时，接口行为与原来一致。

---

# P0-2：管理端审核页展示风险徽章

## 修改文件

```text
admin-frontend/src/app/(admin)/imports/review/page.tsx
admin-frontend/src/lib/api/types.ts
```

## 目标

审核列表和详情页都要能直观看到 OCR 导入风险。

## 实现要求

1. 在题目列表卡片上展示 `risk_level`：

   * `high`：红色标签，文案"高风险"
   * `medium`：黄色/橙色标签，文案"需检查"
   * `low`：绿色/灰色标签，文案"低风险"
2. 在列表卡片上展示前 2～3 个 `risk_reasons`。
3. 在详情页顶部展示完整 `risk_flags` 和 `risk_reasons`。
4. 不要只放在 JSON 里，必须是肉眼可见的 UI 标签。
5. 如果后端暂时没有返回 `risk_level`，前端应兼容从 `ai_metadata.risk_flags` 推导，但优先使用后端字段。
6. 风险标签不能影响已有状态标签、题型标签、批次信息展示。

## 验收标准

1. 管理员打开审核页，不展开详情也能看到哪些题高风险。
2. 高风险题有明显红色标识。
3. 风险原因能用中文显示。
4. 低风险题不造成视觉干扰。
5. 页面 TypeScript 编译不报错。

---

# P0-3：管理端审核页醒目展示 AI 答案标记

## 背景

系统已有 `ai_answer_flag`，但前端展示不醒目，存在管理员忽略 AI 猜答案的风险。

## 修改文件

```text
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

## 目标

任何 `ai_answer_flag=True` 的题目，在列表和详情页都必须醒目显示。

## 实现要求

1. 列表卡片显示橙色标签："AI 答案"。
2. 详情页答案字段旁边显示橙色警告："答案由 AI 补全，请核对原题"。
3. 如果答案为空，显示红色提示："答案缺失，需人工确认"。
4. 不要把提示藏在 JSON 展开区。
5. 如果答案同时为空且 `ai_answer_flag=True`，优先显示"答案异常，需人工确认"。

## 验收标准

1. AI 补全答案题无法被用户忽略。
2. 答案缺失题明显标红。
3. 不影响正常答案显示。
4. 不影响已有编辑、通过、拒绝操作。

---

# P0-4：审核页支持按风险筛选

## 修改文件

```text
backend/app/services/admin_import_service.py
backend/app/api/v1/admin_imports.py
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

## 目标

管理员可以优先处理高风险题，低风险题可以快速批量审核。

## 实现要求

1. 后端审核列表接口新增可选查询参数：

```text
risk_level=high|medium|low
```

2. 如果不传，保持现有行为。
3. 后端根据 P0-1 的风险推导结果过滤。
4. 前端审核页增加风险筛选下拉框：

   * 全部
   * 高风险
   * 需检查
   * 低风险
5. 筛选条件改变后重新拉取列表。
6. 与现有状态筛选、分页兼容。
7. 风险筛选不应破坏现有批次筛选、状态筛选、搜索功能。

## 验收标准

1. 可以只查看高风险题。
2. 可以只查看低风险题。
3. 不影响原有 `pending` / `approved` / `rejected` 筛选。
4. 不传 `risk_level` 时行为与修改前一致。
5. 前端切换筛选后列表能正确刷新。

---

# P0-5：审核详情页展示 OCR 原文 raw_data

## 修改文件

```text
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

如果后端未返回 `raw_data`，再检查并补充：

```text
backend/app/schemas/admin_imports.py
backend/app/services/admin_import_service.py
```

## 目标

审核员能快速对照 OCR 原文，不需要盲改。

## 实现要求

1. 在题目详情页增加一个可折叠区域：

```text
OCR 原文 / 导入原始信息
```

2. 展示内容优先级：

   * `raw_data.raw_text`
   * `raw_data.ocr_text`
   * `raw_data`
   * 如果没有，则显示"暂无 OCR 原文"
3. JSON 内容需要格式化显示。
4. 默认折叠，避免页面过长。
5. 放在 AI 补全建议之前或题目详情之后。
6. 如果 raw_data 很长，需要截断预览或放入可滚动区域，避免页面卡死。

## 验收标准

1. 审核员可以展开查看 OCR 原始文本。
2. raw_data 很长时页面不会卡死。
3. 不影响编辑题目功能。
4. 没有 raw_data 时页面正常显示占位提示。

---

# P0-6：AI repair prompt 加入公式、代码、答案保护约束

## 修改文件

```text
backend/app/ai/prompts.py
```

如果 repair prompt 分散在其他文件，也一并修改对应 prompt。

## 目标

AI repair 不能擅自改写高数公式、408 代码逻辑、答案字段。

## 需要加入的硬约束

请在 repair 相关 prompt 中加入类似以下内容：

```text
你只能修复 OCR 造成的明显错字、断行、选项错位和格式问题。
不得重新解题。
不得根据题意推理答案。
不得擅自修改答案字段。
如果原文没有明确答案，请保持答案为空，并标记需要人工确认。
不得改写数学公式、LaTeX、积分、极限、矩阵、分式、上下标。
对于不确定的公式，不要猜测，保留原文。
不得改写 C 语言/伪代码/SQL 的逻辑。
不得修改代码中的关键符号：->、==、!=、<=、>=、&&、||、*、&、[]、{}、()、++、--。
如果代码或公式无法确认，请保留原文，并添加风险标记。
```

## 实现要求

1. 修改单题 repair prompt。
2. 修改批量 repair prompt。
3. 如果 AI 输出 schema 支持 `risk_flags`，请要求模型对不确定公式/代码添加 risk_flags。
4. 不要让 prompt 要求 AI "补全缺失答案"。
5. 保持现有输出 JSON 格式，不要破坏解析。
6. Prompt 修改应尽量集中，避免多处文案不一致。

## 验收标准

1. prompt 中明确禁止 AI 解题猜答案。
2. prompt 中明确保护公式和代码。
3. 现有 AI repair 输出格式不被破坏。
4. 相关 prompt 测试或快照能覆盖关键约束。

---

# P0-7：代码上下文保护，避免普通文本清洗破坏 408 代码

## 修改文件

```text
backend/app/features/text_normalizer.py
```

如果代码清洗在以下文件中另有逻辑，也需要检查，但不要大改：

```text
backend/app/features/question_pipeline.py
backend/app/features/question_splitter.py
```

## 目标

408 代码题中，代码缩进和关键符号不能被普通 OCR 文本清洗破坏。

## 实现要求

1. 在 `ImportTextNormalizer` 中增加代码块/代码行检测。
2. 检测规则至少覆盖：

   * `#include`
   * `int main`
   * `void `
   * `struct `
   * `typedef`
   * `for (`
   * `while (`
   * `if (`
   * `else`
   * `return `
   * `scanf`
   * `printf`
   * `SELECT ... FROM`
   * `WHERE`
3. 被识别为代码块的连续行：

   * 不进行普通空格压缩
   * 不进行换行合并
   * 不随意替换 `*`、`&`、`[]`、`{}`、`()`
   * 保留缩进
4. 仍允许执行非常安全的 OCR 修复，例如明显的全角符号转半角，但不能改变语义。
5. 对含代码块的文本可在 metadata/risk_flags 中增加 `contains_code` 或 `code_block_detected`。如果当前函数没有 metadata 返回，则先只保护文本，不强行改函数签名。

## 建议实现方式

可采用占位符保护：

```python
def _looks_like_code_line(line: str) -> bool:
    ...

def _protect_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    ...

def _restore_code_blocks(text: str, placeholders: dict[str, str]) -> str:
    ...
```

流程：

```text
原始文本
  ↓
识别连续代码块
  ↓
替换为占位符
  ↓
普通 OCR 清洗
  ↓
恢复代码块
```

## 验收标准

1. C 代码中的缩进不会被清洗掉。
2. `for (int i = 0; i < n; i++)` 保持可读。
3. `p->next` 不会被改坏。
4. `a[i] == b[j]` 不会被改坏。
5. 普通非代码题清洗结果不明显变化。

---

# P0-8：只在数学学科中谨慎接入 formula_normalizer，不要影响代码题

## 修改文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/services/formula_normalizer.py
```

如有必要，也可检查：

```text
backend/app/features/question_normalizer.py
backend/app/features/question_pipeline.py
```

## 背景

审计报告建议将 `formula_normalizer` 接入新版 pipeline，但必须非常谨慎。不能把 408 代码里的 `->`、`<=`、`>=`、`!=` 等符号错误转成数学 LaTeX。

## 目标

仅对明确是数学学科的题目做 formula normalizer，不要全局启用。

## 实现要求

1. 在 `normalize_schema` 或题目标准化后，对题目 subject/category 进行判断。
2. 只有明确属于高数/数学时才调用 formula normalizer，例如：

   * `subject` 包含 `math`
   * `subject` 名称包含 `数学`
   * `category/path` 中包含 `高数`
   * `category/path` 中包含 `数学`
   * 或 question metadata 明确为 math profile
3. 不要对以下题目调用 formula normalizer：

   * 408
   * 计算机
   * C 语言
   * 数据结构
   * 操作系统
   * 计算机组成原理
   * 计算机网络
   * SQL
4. 只处理 `stem` 和 `analysis` 中明显数学文本。
5. 不处理 code block。
6. 如果无法判断学科，默认不调用 formula normalizer。
7. formula normalizer 不应改变答案字段。
8. 如果当前 pipeline 无法准确拿到 subject/category，本轮只添加安全辅助函数和调用占位，不要强行全局启用。

## 验收标准

1. 高数题中的 `∫`、`∑`、`α` 可被转换成适合前端渲染的格式。
2. 408 代码题中的 `->`、`<=`、`>=` 不会被 formula normalizer 处理。
3. 不影响原有非数学题导入。
4. 答案字段不被公式 normalizer 修改。

---

# 测试要求

请至少运行或补充以下测试。

## 后端 schema/service 测试

覆盖：

1. `risk_flags` 能从 `ai_metadata` 展开。
2. `risk_level` 能正确推导。
3. `risk_level` 过滤有效。
4. `ai_answer_flag=True` 时风险等级和原因正确。

## 前端类型检查或 lint

覆盖：

1. `admin-frontend` 类型不报错。
2. `review/page.tsx` 能正常编译。
3. 新增字段在 `types.ts` 中定义完整。

## 文本清洗测试

覆盖：

1. C 代码块缩进保留。
2. `p->next` 保留。
3. `a[i] == b[j]` 保留。
4. `for (int i = 0; i < n; i++)` 保留。
5. 普通 OCR 文本清洗仍有效。

## Prompt 测试或快照

覆盖：

1. repair prompt 包含"不得猜答案"。
2. repair prompt 包含代码关键符号保护。
3. repair prompt 包含数学公式保护。

## 公式 normalizer 安全测试

覆盖：

1. 数学题中 `∫`、`∑`、`α` 能处理。
2. 408 代码题中 `p->next` 不被处理。
3. `if (a <= b && b != c)` 不被处理成数学格式。

如果当前测试体系不完整，请至少新增最小单元测试，或说明无法运行的原因。

---

# 不做事项

本轮明确不做：

1. 不接入完整公式截图 pipeline。
2. 不做表格结构化。
3. 不做原图区域裁剪入库。
4. 不改小程序端。
5. 不大规模拆分 `pipeline_orchestrator.py`。
6. 不重写 OCR pipeline。
7. 不新增复杂数据库迁移。
8. 不改变正式题库数据结构。
9. 不让 AI 自动解题生成答案。

---

# 最终输出格式

执行完成后，请输出：

## 1. 本轮完成了哪些 P0 任务

逐项说明 P0-1 到 P0-8 是否完成。

## 2. 修改了哪些文件

用表格列出：

| 文件 | 修改内容 | 对应任务 |
| ---- | -------- | -------- |

## 3. 新增或变更字段

说明：

| 字段 | 类型 | 来源 | 用途 | 是否兼容 |
| ---- | ---- | ---- | ---- | -------- |

## 4. 新增测试

说明新增了哪些测试文件、测试函数、覆盖哪些风险。

## 5. 运行测试结果

输出实际运行命令和结果。

## 6. 未完成事项

如果某项任务未完成，请说明原因和后续建议。

## 7. 风险和注意事项

说明本次修改是否可能影响：

- PDF 导入
- 图片导入
- Excel 导入
- 文本导入
- 管理端审核
- AI repair
- 高数公式
- 408 代码题

## 8. 下一轮建议

下一轮优先考虑：

1. 公式截图保留接入新版 pipeline。
2. 审核页展示 `math_image` segment。
3. 低风险题批量通过。
4. 原图区域对照预览。
5. 表格题检测与 Markdown 还原。
