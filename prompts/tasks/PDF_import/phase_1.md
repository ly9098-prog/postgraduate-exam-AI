你是本项目的资深全栈工程师。请直接在当前代码仓库中实现下面的修复，不要只给方案，不要留下 TODO，也不要要求人工确认。

开始前先阅读根目录 `CLAUDE.md`、项目说明、现有测试约定和相关代码，遵守现有架构、类型风格、日志规范与错误处理方式。只修改与本任务有关的代码，避免无关重构。

# 任务名称

修复并优化后台管理端 PDF 指定页码范围导入，实现前后端参数真正生效、范围校验、按范围渲染、范围内分块、状态回显及自动化测试。

# 一、已确认的现状和缺陷

## 1. 前端上传配置目前被后端静默忽略

文件：

```text
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
```

当前前端把以下参数全部写入 `FormData`：

```text
subject_id
import_mode
enable_ai_repair
confidence_threshold
ocr_mode
page_start
page_end
```

然后请求：

```text
POST /api/admin/v1/imports/upload
```

后端接口位于：

```text
backend/app/api/v1/admin_imports.py
backend/app/api/v1/imports.py
```

后端除 `file` 外，其他简单参数当前均按照 URL Query 参数解析，不是 multipart 表单字段。

因此目前实际效果很可能是：

- 文件上传成功；
- 起止页被忽略；
- 科目被忽略；
- 导入模式被忽略；
- AI 修复开关被忽略；
- 置信度被忽略；
- 后端继续使用默认配置。

此外，统一导入接口没有接收或使用 `ocr_mode`，但前端仍显示 OCR 模式选择器并发送该字段，属于虚假生效的 UI 控件。

## 2. 后端核心页码提取已经存在

后端已经支持：

```text
page_start
page_end
```

语义是：

- 物理页码；
- 从 1 开始；
- 起始页和结束页都包含在处理范围内；
- 只传 `page_start`：从该页处理到末页；
- 只传 `page_end`：从第 1 页处理到该页。

文本 PDF 的 `_extract_pdf_blocks()` 和扫描 PDF 的 `_ocr_scanned_pdf()` 已经按照范围处理，不要破坏该语义。

## 3. 当前仍存在以下后端问题

涉及：

```text
backend/app/services/import_pipeline_service.py
backend/app/features/pipeline_orchestrator.py
backend/app/schemas/import_review.py
```

问题包括：

1. 只校验页码大于等于 1 和结束页不小于开始页，没有根据 PDF 总页数严格校验。
2. 当 `page_start` 超过总页数时，最终只会出现通用的“未提取到文本”，错误不明确。
3. `_render_page_images()` 仍渲染整份 PDF。
4. `_render_page_image_refs()` 仍渲染整份 PDF。
5. 用户指定页码范围后，`_plan_chunks()` 直接禁用分块。
6. 大范围导入因此会退化为 single-pass，失去 chunk 级进度、失败隔离和恢复能力。
7. OCR 页数截断警告使用整份 PDF 页数判断，而不是选中范围页数。
8. 上传响应和状态响应没有返回实际生效页码范围。
9. 前端把类似 `"3/10 pages"` 的 `ocr_progress` 直接作为 CSS width，生成无效样式。
10. 前端没有完整验证页码是否为整数，以及起始页是否小于等于结束页。
11. 非 PDF 文件仍然显示并提交 PDF 页码字段。

# 二、实现原则

## 1. 保持现有上传接口的 Query 参数契约

不要为了适配当前前端而把所有后端参数改成 `Form()`。

本项目其他上传接口也在使用“multipart 文件 + Query 配置参数”的模式。此次优先修正前端，使请求符合后端现有契约，降低 API 破坏风险。

最终请求形式应类似：

```text
POST /api/admin/v1/imports/upload
  ?subject_id=1
  &import_mode=book
  &enable_ai_repair=true
  &confidence_threshold=0.6
  &page_start=10
  &page_end=20
```

请求体中的 `FormData` 只放：

```text
file
```

使用已有工具：

```text
admin-frontend/src/lib/api/client.ts
```

中的：

```typescript
toQuery(...)
```

不要手写字符串拼接。

## 2. 保持向后兼容

以下字段应保持可选：

```text
page_start
page_end
page_range
```

未传页码范围时，行为必须保持为整份 PDF 导入。

不要修改已有题目来源页码语义：

```text
source_page_start
source_page_end
```

它们必须继续保存原始 PDF 的物理页码，而不是相对于选中范围重新从 1 编号。

## 3. 不允许静默忽略用户输入

以下情况必须明确报错或明确隐藏不支持的配置：

- 页码用于非 PDF 文件；
- 起始页大于结束页；
- 起始页或结束页超过 PDF 总页数；
- 页码不是正整数；
- 置信度不在合法范围；
- UI 显示了后端实际不支持的配置。

# 三、前端修复要求

主要文件：

```text
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
admin-frontend/src/lib/api/types.ts
```

必要时可以新增小型工具文件或测试文件，但不要进行大规模页面重构。

## 1. 修复上传参数传输

将上传逻辑改为：

```typescript
const formData = new FormData();
formData.set("file", file);

const query = toQuery({
  subject_id: subjectId || undefined,
  import_mode: importMode,
  enable_ai_repair: enableAiRepair,
  confidence_threshold: parsedConfidenceThreshold,
  page_start: isPdf ? parsedPageStart : undefined,
  page_end: isPdf ? parsedPageEnd : undefined,
});

return apiRequest<ImportPipelineUploadResponse>(
  `/imports/upload${query}`,
  {
    method: "POST",
    body: formData,
  },
);
```

要求：

- 不再把配置参数写入 `FormData`；
- `page_start/page_end` 只在文件是 PDF 时发送；
- 空值不要进入 Query；
- 布尔值和数值必须按正确类型构造；
- 不要把 `"undefined"`、`"null"` 或空字符串发送给后端。

## 2. 文件类型识别

根据文件扩展名或 MIME 类型判断当前是否为 PDF。

建议提供清晰变量：

```typescript
const isPdfFile = ...
```

当用户切换为非 PDF 文件时：

- 隐藏或禁用页码范围输入；
- 清除之前填写的 `pageStart/pageEnd`；
- 不向后端发送页码参数。

## 3. 页码输入校验

提交前进行校验：

- 留空合法；
- 非空时必须是正整数；
- 不接受小数；
- 不接受 0；
- 不接受负数；
- 同时填写时，`pageStart <= pageEnd`。

错误信息必须对用户可理解，例如：

```text
起始页必须是大于等于 1 的整数
结束页必须是大于等于 1 的整数
结束页不能小于起始页
页码范围仅适用于 PDF 文件
```

校验失败时：

- 不发送请求；
- 在当前页面显示错误；
- 不切换到进度页。

可以通过派生状态控制提交按钮，但后端仍必须保留独立校验。

## 4. 置信度校验

确保 `confidence_threshold`：

- 是有效数字；
- 范围为 `0–1`；
- 不允许 NaN；
- 不允许仅依赖 HTML 的 `min/max`。

## 5. 处理虚假的 OCR 模式控件

当前统一导入接口没有端到端支持 `ocr_mode`。

本任务不要仅仅给后端增加一个未使用的参数。

请采用以下处理：

- 从统一导入任务页 `imports/tasks/page.tsx` 移除 `OcrModeSelector` 和 `useImportConfig` 的使用；
- 不删除共享组件和 Hook，因为批量图片导入页面仍然使用它们；
- 在 PDF 页码配置附近增加简短说明：

```text
文本型 PDF 将直接提取文字；扫描型 PDF 会由后端自动触发 OCR。
```

- 对单张或批量图片需要手动选择 OCR 模式的场景，引导用户使用现有“批量图片导入”页面。

不要在统一任务页继续发送 `ocr_mode`。

## 6. 页面交互优化

导入运行期间，应禁用：

- 文件选择；
- 科目选择；
- 导入模式；
- 置信度；
- 起止页；
- AI 修复开关；
- 提交按钮。

当前起止页和置信度输入未完整禁用，请补齐。

## 7. 响应类型和范围回显

扩展前端类型，兼容后端新增的可选范围字段。

建议定义：

```typescript
export type PdfPageRangeInfo = {
  requested_start?: number | null;
  requested_end?: number | null;
  effective_start: number;
  effective_end: number;
  selected_page_count: number;
  total_pages: number;
};
```

在以下响应中增加：

```typescript
page_range?: PdfPageRangeInfo | null;
```

涉及：

```text
ImportPipelineUploadResponse
ImportPipelineStatusResponse
```

上传成功后，PDF 应显示类似：

```text
导入任务已提交：第 10–20 页，共选中 11 页；PDF 共 120 页
```

进度页面增加“识别范围”展示，例如：

```text
第 10–20 页 / 共 120 页
```

非 PDF 不显示该项。

## 8. 修复 OCR 进度条宽度

当前可能收到：

```text
3/10 pages
30%
```

请实现一个纯函数，将其转换为合法的 `0–100` 数值：

```typescript
parseProgressPercent(value?: string): number
```

至少支持：

- `"3/10 pages"` → `30`
- `"3/10"` → `30`
- `"30%"` → `30`
- 空值或非法值 → `0`
- 自动限制在 `0–100`

CSS width 必须是：

```typescript
style={{ width: `${progressPercent}%` }}
```

显示文本仍可以保留后端原始进度内容。

为该纯函数补充测试。

# 四、后端修复要求

主要文件：

```text
backend/app/api/v1/admin_imports.py
backend/app/api/v1/imports.py
backend/app/services/import_pipeline_service.py
backend/app/features/pipeline_orchestrator.py
backend/app/schemas/import_review.py
```

## 1. 建立统一页码范围解析函数

新增一个可复用的纯函数，名称可根据项目风格决定，例如：

```python
resolve_pdf_page_range(
    total_pages: int,
    page_start: int | None,
    page_end: int | None,
) -> PdfPageRange
```

返回至少包含：

```text
requested_start
requested_end
effective_start
effective_end
selected_page_count
total_pages
```

规则：

```text
page_start 默认 1
page_end 默认 total_pages
```

严格校验：

- `total_pages >= 1`
- `page_start >= 1`
- `page_end >= 1`
- `page_start <= page_end`
- `page_start <= total_pages`
- `page_end <= total_pages`

页码超过总页数时不要静默截断，返回明确错误，例如：

```text
起始页 130 超出 PDF 总页数 120
结束页 130 超出 PDF 总页数 120
```

API 层应返回与项目现有上传错误风格一致的 400 或 422，不要返回 500。

## 2. 非 PDF 禁止使用页码范围

如果文件不是 PDF，但请求传入：

```text
page_start
page_end
```

应返回明确错误：

```text
page_start/page_end 仅适用于 PDF 文件
```

不要静默忽略。

## 3. 在上传阶段完成 PDF 页数和范围校验

`start_import_pipeline()` 当前已经打开 PDF 检查总页数。

请在同一次打开中：

1. 获取 `total_pages`；
2. 执行上传限制校验；
3. 计算并验证有效范围；
4. 避免为同一目的重复打开 PDF。

不要吞掉页码校验异常。

现有类似：

```python
except Exception:
    pass
```

的容错不能把“合法 PDF 但页码越界”吞掉。只允许对确实无法解析 PDF 的异常按照现有上传校验策略处理。

## 4. 扩展上传和状态响应

在：

```text
backend/app/schemas/import_review.py
```

增加页码范围响应模型，例如：

```python
class PdfPageRangeInfo(BaseModel):
    requested_start: int | None = None
    requested_end: int | None = None
    effective_start: int
    effective_end: int
    selected_page_count: int
    total_pages: int
```

然后在以下响应增加可选字段：

```python
page_range: PdfPageRangeInfo | None = None
```

涉及：

```text
PipelineUploadResponse
PipelineStatusResponse
```

要求：

- 非 PDF 返回 `null` 或省略；
- PDF 整份导入也返回实际范围，例如 `1–120`；
- 字段必须在任务处理期间和终态状态中保持存在；
- 进度更新、失败更新、完成更新时不能把该元数据丢失。

可以将它作为顶层轻量字段保存，但需要同步加入 pipeline store 的白名单，并确保 `_set_pipeline_store()` 的覆盖式更新不会丢失。

也可以通过统一的状态基础元数据合并函数实现。

不要把整个 options 原样暴露给前端。

## 5. 只渲染选中的 PDF 页面

修改：

```python
_render_page_images(...)
_render_page_image_refs(...)
```

使它们接收：

```text
page_start
page_end
```

并只遍历有效范围。

要求：

- 输入仍然是 1-based 闭区间；
- 返回字典的 key 仍然是原 PDF 的物理页码；
- 例如选中 100–105 页，返回 key 必须是 `100...105`，不能变成 `1...6`；
- 不再渲染范围外页面；
- `fitz.Document` 必须在 `finally` 中关闭；
- 临时图片仍按原物理页码命名，例如 `page_100.png`。

在 `PipelineOrchestrator.run()` 调用时传入有效范围。

未指定范围时保持渲染全部页面。

## 6. 指定范围后仍允许分块

移除当前逻辑：

```python
if opts.get("page_start") or opts.get("page_end"):
    return []
```

新增范围分块函数，例如：

```python
split_page_range(start_page, end_page, chunk_size)
```

示例：

```text
start=101, end=220, chunk_size=40
```

应产生：

```text
101–140
141–180
181–220
```

要求：

- 选中页数小于等于 chunk size 时可以继续走 single-pass；
- 选中页数大于 chunk size 时必须走 chunked；
- chunk 中的页码继续使用原 PDF 物理页码；
- chunk overlap 逻辑继续有效；
- chunk checkpoint、失败隔离和 resume 能继续工作；
- 不得把 `effective_end` 错当成“选中页数”；
- 区分以下概念：

```text
PDF 总页数
选中页数
范围起始物理页
范围结束物理页
```

调整 chunked 统计，使：

```text
stats.total / stats.extracted
```

反映选中范围页数，而不是结束页码。

诊断信息中保留：

```text
pdf_total_pages
selected_page_count
effective_page_start
effective_page_end
```

## 7. 修复 OCR 页数限制判断

当前 `_ocr_scanned_pdf()` 的截断警告基于：

```python
total_pages > max_pages
```

应改为基于：

```python
pages_in_range > max_pages
```

警告应描述选中范围，例如：

```text
ocr_pages_truncated: processed 20/51 selected pages
```

不要在“整份 PDF 很大，但用户只选了 10 页且全部识别完成”时误报截断。

同时处理空范围防御：

```text
pages_in_range <= 0
```

正常情况下应在上传阶段被阻止，但底层函数仍要安全。

## 8. 日志和诊断

上传接受日志和 pipeline plan 日志增加轻量字段：

```text
pdf_total_pages
page_start
page_end
selected_page_count
```

不得记录文件内容或敏感数据。

错误信息需可区分：

- PDF 无效；
- 页码越界；
- OCR 未识别到文本；
- 所选页没有可提取文字。

当所选范围确实没有文字时，可返回：

```text
指定页码范围内未提取到可识别文本
```

不要继续使用容易误导为整份 PDF 失败的通用错误。

# 五、API 契约

后台端：

```text
POST /api/admin/v1/imports/upload
```

公共端：

```text
POST /api/v1/import/pipeline/upload
```

两者必须保持一致的页码语义、校验和响应结构。

参数继续使用 Query：

```text
subject
subject_id
import_mode
enable_ai_repair
confidence_threshold
page_start
page_end
```

文件继续使用 multipart：

```text
file
```

建议为 Query 参数补充约束和 OpenAPI 描述，例如：

```python
Query(None, ge=1, description="PDF 起始物理页码，1-based，包含该页")
```

但不能仅依赖 Query 校验，总页数相关校验仍必须在 service 层完成。

# 六、测试要求

优先复用项目已有 pytest、前端测试和 fixture 约定。若项目已有测试目录，请按现有布局增加测试，不要创建另一套测试体系。

## 后端至少覆盖

### 页码范围纯函数

1. 5 页 PDF，不传范围 → `1–5`，选中 5 页。
2. `page_start=2` → `2–5`。
3. `page_end=3` → `1–3`。
4. `page_start=2,page_end=4` → `2–4`。
5. `page_start=0` → 错误。
6. `page_end=0` → 错误。
7. `page_start=4,page_end=3` → 错误。
8. 5 页 PDF，`page_start=6` → 明确越界错误。
9. 5 页 PDF，`page_end=6` → 明确越界错误。

### 文本 PDF

创建一个多页测试 PDF，每页包含唯一文本。

验证：

```text
page_start=2,page_end=4
```

只返回第 2、3、4 页内容，且 block 的 page 字段为：

```text
2, 3, 4
```

### 扫描 PDF OCR

通过 mock 验证：

- 选择 2–4 页时只渲染和 OCR 三页；
- 原始页码保持为 2、3、4；
- 范围外页面不会进入 OCR；
- `MAX_OCR_PAGES` 基于选中范围计算；
- 完整处理小范围时不产生错误截断警告。

### 页面渲染

验证：

- `_render_page_images()` 只返回指定范围 key；
- `_render_page_image_refs()` 只生成指定范围文件；
- 临时文件名保留物理页码。

### 范围分块

验证：

```text
101–220，chunk_size=40
```

生成：

```text
101–140
141–180
181–220
```

并验证：

- 总选中页数是 120；
- 不是 220；
- single-pass 和 chunked 的边界正确。

### API

验证 multipart 文件加 Query 参数时：

- `page_start/page_end` 被正确收到；
- `subject_id/import_mode/enable_ai_repair/confidence_threshold` 被正确传入 service；
- 页码用于非 PDF 时返回明确错误；
- 上传响应带 `page_range`；
- 状态响应在 processing、failed、completed 状态均保留 `page_range`。

## 前端至少覆盖

如项目已有 Vitest/Jest/React Testing Library：

1. `parseProgressPercent("3/10 pages") === 30`
2. `parseProgressPercent("30%") === 30`
3. 非法值返回 0。
4. 超范围值被限制在 0–100。
5. 页码整数校验。
6. `pageStart > pageEnd` 被拒绝。
7. PDF 请求把配置放在 URL Query，FormData 只含 file。
8. 非 PDF 请求不包含 `page_start/page_end`。
9. 统一任务页不再发送 `ocr_mode`。

若暂时没有前端测试基础设施，至少：

- 将页码解析、验证、进度解析和请求参数构造提取成纯函数；
- 为纯函数使用项目现有最轻量的测试方式；
- 不要为了单个测试引入大型依赖。

# 七、验收标准

完成后必须满足：

1. 管理端选择 PDF，填写第 10–20 页，后端实际只提取和 OCR 第 10–20 页。
2. 上传请求中的科目、导入模式、AI 修复、置信度和页码配置真实生效。
3. 处理第 10–20 页时，不渲染第 1–9 页和第 21 页之后的页面。
4. 选择 101–220 页且范围大于 chunk size 时，仍然按该范围分块。
5. 所有题目的来源页码仍是原 PDF 物理页码。
6. 页码越界时，用户看到明确错误，而不是“OCR 无文本”。
7. 非 PDF 文件不显示、不发送页码范围。
8. 统一任务页不再展示实际无效的 OCR 模式选择器。
9. 上传响应和进度页都能显示实际生效范围。
10. 进度条 CSS width 始终是合法百分比。
11. 原有不指定范围的整份 PDF 导入行为不回归。
12. 原有 TXT、Excel、图片导入不回归。
13. 后台端和公共端的页码行为一致。
14. 新增测试全部通过。
15. 类型检查、lint 和构建通过。

# 八、执行和交付要求

完成修改后，实际运行项目可用的检查命令，包括但不限于：

```text
后端单元测试
后端相关导入测试
前端类型检查
前端 lint
前端测试
前端生产构建
```

根据仓库实际脚本选择正确命令，不要假设不存在的脚本。

最终回复必须包含：

1. 根因总结；
2. 修改的文件列表；
3. 关键实现说明；
4. API 请求示例；
5. 新增测试列表；
6. 实际执行过的测试和结果；
7. 未解决的限制或风险。

不要只输出代码片段。请直接完成代码修改、测试和验证。