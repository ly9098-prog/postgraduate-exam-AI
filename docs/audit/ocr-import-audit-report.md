# 刷题小程序 OCR 导题准确率专项审计与最小改造计划

> 审计日期：2026-06-21 | 基线：main@cc419dd

---

## 一、当前真实 OCR 导题链路

### 1.1 完整调用链

```text
管理端页面（admin-frontend）:
  POST /imports/upload  → 通过 api admin base URL 解析
  → 实际调用: POST /api/admin/v1/imports/upload

HTTP 接口（admin 侧 — 主路径）:
  POST /api/admin/v1/imports/upload        ← 新版 pipeline，非 deprecated
  GET  /api/admin/v1/imports/pipelines/{id}  ← 状态轮询
  GET  /api/admin/v1/imports/review-queue     ← 审核列表
  PUT  /api/admin/v1/imports/questions/{id}   ← 编辑题目
  POST /api/admin/v1/imports/questions/{id}/approve|reject
  POST /api/admin/v1/imports/batch-image/upload  ← 批量图片

后端主干函数:
  admin_imports.py::upload_import_file()
    → imports.py::start_import_pipeline_from_upload()
      → pipeline_orchestrator.py::ImportPipeline.run()
        1. _run_extract()          — 提取 / OCR 文本
        2. _run_normalize_text()   — ImportTextNormalizer 清洗
        3. _run_ocr_correction()   — AI OCR 纠错（Qwen-VL → DeepSeek）
        4. _run_analyze_structure() — 结构分析
        5. _run_classify_pages()   — 页面分类
        6. _run_split()            — 题目切分
        7. _run_match()            — 答案匹配
        8. _run_normalize_schema()  — 标准化
        9. _run_batch_validation()  — 批量校验
        10. _run_batch_dedup()     — 批内去重
        11. _run_repair()          — AI 修复（可选）
        12. _run_similarity_match() — 相似题匹配
        13. _run_review()          → review_service::submit_to_review()

写入表:
  question_imports（暂存区） → 审核后 → questions（正式库）
```

### 1.2 多入口分析

| 入口 | 当前路由 | 状态 | 说明 |
|------|---------|------|------|
| PDF 导入 | `POST /api/admin/v1/imports/upload` — PDF 类型 | **主路径** | 走新版 pipeline |
| 单图导入 | `POST /api/admin/v1/imports/upload` — 图片类型 | **主路径** | 走新版 pipeline（OCR + pipeline） |
| 批量图片 | `POST /api/admin/v1/imports/batch-image/upload` | **主路径** | 逐张 OCR，合并统一审核 |
| Excel 导入 | `POST /api/admin/v1/imports/upload` — Excel 类型 | **主路径** | 走新版 pipeline（direct import） |
| 文本导入 | `POST /api/admin/v1/imports/text-parse` + `text-import` | **主路径** | 粘贴文本解析 |
| AI 补全（单题） | `POST /api/admin/v1/imports/questions/{id}/complete` | **主路径** | 管理端审核页触发 |
| AI 批量补全 | `POST /api/admin/v1/imports/questions/batch-complete` | **主路径** | 管理端审核页触发 |
| AI 生成草稿 | `POST /api/v1/ai-import/generate`（miniprogram 已禁用） | **旧路径** | 已封禁，仅 admin 可通过其他方式触发 |

### 1.3 废弃但仍存在的端点

```text
POST /api/v1/import/upload              ← deprecated, Δ 返回 ImportUploadResponse
POST /api/v1/import/image/upload        ← deprecated, Δ 返回 PipelineUploadResponse
POST /api/v1/import/questions/{id}/fix  ← deprecated, 返回 403
```

→ **管理端前端未调用这些废弃接口**。前端通过 base URL `/api/admin/v1` 调用 admin 路由，
admin 路由直接调用 `start_import_pipeline_from_upload()` — 与新版 pipeline 一致。

---

## 二、管理端导入接口是否走错

### 2.1 关键发现

管理端 `tasks/page.tsx` 上传时调用 `/imports/upload`。由于 `apiRequest()` 使用
`DEFAULT_BASE_URL = "http://localhost:8000/api/admin/v1"`，最终解析到
`POST /api/admin/v1/imports/upload` — 即 **admin 路由而非 deprecated 路由**。

### 2.2 审计结论

| 问题 | 当前代码位置 | 当前行为 | 风险 | 建议改法 |
|------|------------|---------|------|---------|
| 管理端上传路径 | `tasks/page.tsx:63` → `/imports/upload` | 通过 base URL 映射到 admin 路由 | **无风险**（实际走正确路由） | 建议显式写全路径减少歧义 |
| 前端响应类型 | `ImportPipelineUploadResponse` | 匹配 `PipelineUploadResponse` schema | **无风险** | 无需修改 |
| 状态查询 | `GET /imports/pipelines/{id}` | 映射到 admin 路由 | **无风险** | 无需修改 |
| 审核接口 | `GET /imports/review-queue` | 映射到 admin 路由 | **无风险** | 无需修改 |

### 2.3 需注意点

`imports.py` 中 `/api/v1/import/upload` 标记 `deprecated=True`，但 miniprogram
（小程序端）所有审核相关接口已统一返回 403，所以未造成实际影响。

旧的 `POST /api/v1/import/upload` 调用 `svc.import_pdf()` / `svc.import_excel()`，
走的是旧路径（少 AI ocr_correction、少结构分析、少页面分类等功能）。但由于
管理端不走此路径，风险可控。

---

## 三、公式截图能力是否已经存在但未贯通

### 3.1 能力现状

| 能力 | 当前支持 | 代码位置 | 是否贯通到小程序 | 缺口 |
|------|---------|---------|----------------|------|
| 数学区域检测（PDF 文本层） | ✅ | `math_region_detector.py::detect_page()` | ❌ | 未接入新版 pipeline |
| 数学区域检测（OCR boxes） | ✅ | `math_region_detector.py::detect_from_ocr_boxes()` | ❌ | 未接入新版 pipeline |
| 公式截图 | ✅ | `formula_image_cropper.py::crop_region()` | ❌ | 未接入新版 pipeline |
| 截图上传到 OSS | ✅ | `formula_image_cropper.py::crop_and_upload()` | ❌ | 未接入新版 pipeline |
| segments 构建 | ✅ | `hybrid_content_builder.py::build()` | ❌ | 未接入新版 pipeline |
| `QuestionImport.math_regions` 字段 | ✅ | `question_import.py` | ❌ | 存在但从未在新版 pipeline 中赋值 |
| 小程序渲染 `math_image` segment | ✅ | `math-question` 组件 | ✅ | 已支持（有 render_model="segments" 分支） |
| 管理端审核页展示公式图片 | ❌ | `review/page.tsx` | ❌ | 未读取 segments 展示 |
| 旧 `import_service.import_pdf` 集成 | ✅ | `import_service.py`（旧文件） | ❌ | 旧路径已边缘化 |

### 3.2 结论

公式截图保留能力已有 **~70% 基础设施**，但关键缺口是：

1. **新版 pipeline 未集成**：`pipeline_orchestrator.py::ImportPipeline` 没有任何
   stage 调用 `math_region_detector`、`formula_image_cropper` 或
   `hybrid_content_builder`。所有公式处理能力仅存在于旧 `import_service.import_pdf`。

2. **管理端审核页未展示**：`review/page.tsx` 没有渲染 `segments` 的逻辑（虽有
   `MathFormula` 组件但只用于 LaTeX 显示）。

3. **优先级建议**：先补后端 pipeline 集成（P1），再补审核预览（P1-P2），
   因为无截图时审核页仍可展示文本。

---

## 四、高数题风险 Top 10

| 排名 | 风险 | 具体表现 | 涉及文件 | 对刷题影响 | 最小修复方案 |
|------|------|---------|---------|-----------|-------------|
| 1 | **公式区域未保护** | 新版 pipeline 没有集成 `math_region_detector` — 所有公式被当普通文本处理 | `pipeline_orchestrator.py`（缺失 stage） | 极高：积分/矩阵/分式全部失真 | 在 normalize_text 后加 stage：检测公式区域 → 截图上传 → 构建 segments |
| 2 | **公式 Unicode 转 LaTeX 未启用** | `formula_normalizer.py` 只在旧 import_service 路径调用，新版 pipeline 未使用 | `question_pipeline.py::normalize()` 仅在 `plain_math=True` 时调用 | 高：α, β, ∫, ∑ 等符号保留 Unicode 而非 LaTeX | 在 normalize_schema 阶段统一调用 |
| 3 | **AI 修复可能猜公式** | `ai_repair.py` 的 DeepSeek 调用在 confidence < 0.6 时触发，可能重写公式 | `ai_repair.py::_call_ai_for_repair()` + `prompts.py` | 极高：AI 可能生成"看起来合理但错误"的公式 | 在 repair prompt 中加入"不修改数学公式，仅修复 OCR 文本"约束；公式低置信度加 risk_flag |
| 4 | **复杂公式被压成单行** | `text_normalizer.py::normalize_ocr_text` 清洗换行/空格，可能破坏多行公式 | `text_normalizer.py` | 高：积分公式结构丢失 | 在清洗前做 math_region 检测，标记的 math 区域跳过换行清洗 |
| 5 | **上下标 Unicode 转 LaTeX 有限** | `formula_normalizer.py` 只有 `_SUPERSCRIPT_MAP` / `_SUBSCRIPT_MAP` 的字符级映射 | `formula_normalizer.py` | 中高：带上下标的变量名可能不可读 | 扩展上下标上下文识别 |
| 6 | **无低置信度公式标记** | OCR quality gate 支持检测乱码，但不专门标记公式区域 OCR 低置信度 | `ocr_quality_gate.py` | 中：用户不知道公式可能错了 | 在 ai_metadata.risk_flags 中添加 math_low_confidence |
| 7 | **不保留公式原图** | 新版 pipeline 的 `page_images` 只在 AI OCR 纠错阶段临时使用，不入库不送审 | `pipeline_orchestrator.py` -> `_run_review()` | 高：审核员无法对照原图 | 将 formula region image 上传到 OSS 并写入 math_regions |
| 8 | **公式 normalizer 幂等性风险** | `normalize_text_import_math` 和 `wrap_inline_math` 在 `question_normalizer.py` 调用时机不稳定 | `question_normalizer.py` line 180 | 中：重复调用可能导致嵌套 `$` 符号 | 统一调用点且标记已处理 |
| 9 | **KaTeX 渲染不稳定** | 管理端 `MathFormula` 组件渲染 KaTeX，但对嵌套 `$$`、混排 Unicode 渲染不可靠 | `review/page.tsx` | 中：公式可能渲染为空白 | 对复杂公式优先展示 math_image 截图 |
| 10 | **矩阵/行列式/分段函数无保护** | 这些结构依赖换行和列对齐，当前 text_normalizer 无保护逻辑 | `text_normalizer.py` | 高：矩阵变成逗号分隔的值 | 检测 `\begin{matrix}` / `\begin{cases}` 等 LaTeX 环境结构做保护 |

### 高数题原则

> 公式不确定就标红或保留截图，**不要让 AI 猜**。

---

## 五、408 题风险 Top 10

| 排名 | 风险 | 具体表现 | 涉及文件 | 对刷题影响 | 最小修复方案 |
|------|------|---------|---------|-----------|-------------|
| 1 | **C 代码缩进丢失** | `text_normalizer.py::normalize_ocr_text` 会合并/清洗换行，破坏代码块缩进 | `text_normalizer.py` | 极高：代码语义被破坏 | 检测代码块（以 `#include`/`int `/`void ` 等开头），跳过换行清洗 |
| 2 | **关键符号被误改** | `→`、`≤`、`≥`、`≠` 等被 `formula_normalizer` 转为 LaTeX 命令，在代码上下文中错误 | `formula_normalizer.py` | 高：`if (x→0)` 变成 `if (x\to0)` | 在代码块/编程上下文中跳过公式 normalizer |
| 3 | **AI 修复可能改写代码逻辑** | 低置信度题目触发 AI repair 时，DeepSeek 可能"修正"代码 | `ai_repair.py` + `ai/prompts.py` | 极高：AI 改变程序语义 | repair prompt 明确禁止修改代码逻辑；编程题自动降级为 no-AI-repair |
| 4 | **表格结构压成文本** | 进程调度表/Cache 映射表/路由表被 OCR 作为普通文本提取，行列关系丢失 | 全链路 | 极高：408 表格题数据错乱 | 新增 table_detector + table_markdown_builder（P2） |
| 5 | **选项跨列错序** | 多列排版（如 A/B 一列、C/D 一列）的选项在分割时可能左右拼接而非上下 | `question_splitter.py` | 高：选择题乱序 | 添加多列选项检测逻辑（可用 OCR boxes 的 x 坐标） |
| 6 | **`->` 箭头翻转** | PaddleOCR 将 `->` 误识为 `<-` + 随机前缀 | `text_normalizer.py` lines 117-133 | 高：指针语义反转 | ✅ **已有修复**（`_RE_POINTER_ARROW_GARBLED_KNOWN` + `_RE_POINTER_ARROW_REVERSED`） |
| 7 | **代码注释中的数学符号被误处理** | `/* solve for α */` 中的 `α` 被转为 `\alpha` | `formula_normalizer.py` + `text_normalizer.py` | 中：注释显示异常 | 代码块内跳过符号替换 |
| 8 | **无代码块预览** | 管理端审核页没有代码高亮/代码块预览 | `review/page.tsx` | 中：管理员难发现代码问题 | 添加 `pre` 或代码高亮组件 |
| 9 | **位运算/逻辑运算符号混淆** | `&`、`|`、`~`、`^` 可能被 OCR 清洗 | `text_normalizer.py` | 中高：C 位运算语义改变 | 在代码上下文中保护这些符号 |
| 10 | **SQL/伪代码无保护** | SQL 语句和算法伪代码被当普通文本清洗 | `text_normalizer.py` | 中：SQL 题/算法题可读性下降 | 扩展代码块检测覆盖 SQL 和伪代码 |

### 408 题原则

> 代码只做保真，不做美化。AI 不能改写代码逻辑。关键符号变化必须回滚或标红。

---

## 六、审核页缺口

| 缺口 | 当前代码位置 | 影响 | 最小改造方案 |
|------|------------|------|-------------|
| 不展示 `risk_flags` | `review/page.tsx` 列表和详情均未读取 | 管理员无法快速识别高风险题 | 在列表卡片的 metadata pills 区域添加 risk_flag 徽章（绿/黄/红三级） |
| 不展示 `ai_answer_flag` | `review/page.tsx` 详情 JSON 视图有但不醒目 | 管理员可能忽略 AI 猜的答案 | 在答案卡片旁加 "AI" 标签（橙色） |
| 无法按风险过滤 | `admin_imports.py::list_review_queue()` 查询中无 risk 参数 | 高风险题淹没在大量题目中 | 后端加 risk_filter 参数，前端加下拉筛选 |
| 无 OCR 原文对照 | 详情页只显示 `parsed_content`，不显示 `raw_data` | 无法快速判断 OCR 错误 | 在详情页添加 "OCR 原文" 可折叠面板 |
| 无原图区域显示 | 备选区域图片未入库，前端无从展示 | 无法对照原图审校 | P1 任务：先将原图 page image 入库 |
| 无公式图片显示 | `math_image` segment 未在前端渲染 | 无法看到公式截图 | `MathFormula` 组件已存在，需添加 `math_image` 类型渲染 |
| 无风险等级（绿/黄/红） | 后端 `ai_metadata.risk_flags` 存在但前端未解析 | 列表全部灰色无法区分 | 前端解析 `risk_flags` 数组，有高风险 flag 显示红色边框 |
| 低风险题不可批量通过 | 无 `risk_level=pending` 快速过滤 + 批量操作 | 管理员需逐题操作 | 添加 "低风险一键通过" 按钮 |
| JSON 视图中 risk_flags 在深层 | `risk_flags` 藏于 `ai_metadata` 对象内 | 需展开 JSON 才能看到 | 提取到 `AdminImportQuestionItem` 顶层字段 |

### 关键问题

**后端已有但前端未有效展示**：
- `ai_metadata.risk_flags` — 在 review_service 写入（参考 line 340），前端可访问
  `item.ai_metadata?.risk_flags`，但 **未在 UI 中渲染**
- `ai_answer_flag` — 已在前端 JSON 视图中显示，但 **无视觉指示 / 徽章**
- `ai_confidence` — 后端字段存在，前端 **未展示**

---

## 七、原图区域保留能力

| 信息 | 当前是否存在 | 存在哪里 | 是否入库 | 前端是否可用 | 缺口 |
|------|------------|---------|---------|------------|------|
| `source_file` | ✅ | `QuestionImport.source_file` | ✅ | ✅ | 无缺口 |
| `source_page` | ❌ | 无单独字段 | ❌ | ❌ | 未追踪每道题来自 PDF 哪一页 |
| OCR bbox | ✅（扫描版） | 在 pipeline 临时内存中，`extract` 阶段 raw_blocks 含 boxes | ❌ | ❌ | boxes 未关联到单题、未入库 |
| page image | ✅（渲染） | pipeline `page_images` 临时 dict，仅用于 AI OCR 纠错 | ❌ | ❌ | 渲染后用完即弃，未持久化 |
| question region image | ❌ | 不存在 | ❌ | ❌ | 无此能力 |
| formula region image | ✅（有代码） | `formula_image_cropper.py` 可生成 | ❌ | ❌ | 代码存在但未接入 pipeline |
| code region image | ❌ | 不存在 | ❌ | ❌ | 无此能力 |
| table region image | ❌ | 不存在 | ❌ | ❌ | 无此能力 |

### 判断

1. **有 bbox 但未入库**：扫描版 PDF 的 OCR boxes 在 `raw_blocks` 中临时存在，
   经过 `normalize_text` → `split` → `match` → `normalize_schema` 后丢失。
   未与最终 `QuestionImport` 记录关联。

2. **可从 OCR boxes 追踪到题目区域**：`question_splitter._run_split` 可从 boxes
   推断题号位置，但对接逻辑未实现。

3. **"左原图，右 OCR 文本" 条件**：当前不满足，因为：
   - page_images 用完即弃
   - 题目区域未从 page image 中裁剪
   - 前端无对应 UI 组件

4. **最小实现**：在 `_run_review` 阶段将 page_image 导入 OSS 并记录到
   `QuestionImport.raw_data` 或新字段 `page_image_urls`。

---

## 八、答案字段 AI 风险

| 风险 | 当前代码位置 | 当前行为 | 推荐改法 |
|------|------------|---------|---------|
| AI repair 可修改答案 | `ai_repair.py` lines 752-875 | AI 可修改 stem、options、answer | 在 repair prompt 中禁止生成/修改答案字段；答案变更需加 `risk_flag: answer_changed_by_ai` |
| AI complete 可补答案 | `question_pipeline.py` `complete_question()` | 用 AI 推断缺失的答案 | ✅ **已有 `ai_answer_flag=True` 标记**，但前端展示不足 |
| 答案缺失时系统默认处理 | `review_service.py` lines 248-248 | `parsed_answer = (q.get("answer") or "").strip() or None` | ✅ **正确答案留空而非猜测** |
| 批量 AI 补全可覆写答案 | `admin_import_service.py` `complete_import_question()` | strategy=force_overwrite 时 AI 可改写已有答案 | 限制 force_overwrite 策略禁止覆盖答案字段 |
| "题目正确但答案被 AI 猜错" | AI 可能从解析/选项反推答案 | 少量场景可能发生 | 答案 AI 补全必须设置 `ai_answer_flag=True` + 审核页醒目展示 |
| AI 从原文答案区抽取答案 | `answer_matcher.py`（纯规则） | 规则匹配，不涉及 AI | ✅ **无险** |

### 结论

- **答案抽取主要依靠规则**（`answer_matcher.py`），不调用 AI
- **AI 仅在 complete / repair 时可能涉及答案**，但已有 `ai_answer_flag` 标记
- **核心风险**是前端审核页未醒目展示 `ai_answer_flag`，管理员可能不经复核就通过
- 应禁止 AI 以 "解题" 方式推理答案

---

## 九、表格题支持情况

| 表格场景 | 当前支持 | 风险 | 最小修复方案 |
|---------|---------|------|-------------|
| 408 进程调度表 | ❌ 无独立支持 | 高：被压成无序文本 | 引入 table_detector（基于 OCR boxes 列对齐检测） + 转 Markdown 表格 |
| 计组 Cache 映射表 | ❌ 无独立支持 | 高：行列关系丢失 | 同上 |
| 计网路由表 | ❌ 无独立支持 | 高：路由条目错乱 | 同上 |
| 哈夫曼编码表 | ❌ 无独立支持 | 高：编码值对应关系丢失 | 同上 |
| 真值表 | ❌ 无独立支持 | 中：输入输出对应丢失 | 同上 |
| 高数概率统计数据表 | ❌ 无独立支持 | 中：数据错乱 | 同上 |

### 当前状态

表格无任何独立处理逻辑。OCR 使用 PaddleOCR 的 `ocr_pages_with_boxes` 可获得
box 级别的行列位置，但下游没有任何表格还原逻辑。所有表格内容被当成普通文本
逐行提取，行列关系完全丢失。

### 支持优先级

P2 任务。先解决代码/公式问题（P0/P1），表格题作为下一阶段。

---

## 十、P0/P1/P2 最小改造计划

### P0 — 高收益最小任务（1 周）

| 优先级 | 任务 | 涉及文件 | 为什么优先 | 实现要点 | 验收标准 |
|--------|------|---------|-----------|---------|---------|
| **P0-1** | 前端展示 `risk_flags` 徽章 | `review/page.tsx`, `AdminImportQuestionItem` schema, `types.ts` | 后端已有数据，前端不显示 → 浪费审核效率 | 解析 `ai_metadata.risk_flags`，列表卡片加色带/徽章（红/黄/绿三级） | 高风险题列表可见红/黄标签 |
| **P0-2** | 前端醒目展示 `ai_answer_flag` | `review/page.tsx` | AI 猜答案风险高，需标注 | 在答案卡片加 "AI 猜测" 橙色标签 | AI 补全答案的题有醒目橙色标志 |
| **P0-3** | 审核页支持按风险过滤 | `admin_imports.py` + `review/page.tsx` | 管理员需优先处理高风险题 | 后端加 `risk_filter` 查询参数，前端加筛选下拉 | 可按高/中/低风险筛选 |
| **P0-4** | repair prompt 加入公式/代码保护指令 | `ai/prompts.py` | 防止 AI 胡乱"修复"公式和代码 | 在 `build_repair_question` / `build_batch_repair_prompt` 增加约束 | 公式、代码在 AI 修复后不变 |
| **P0-5** | `formula_normalizer` 接入新版 pipeline | `pipeline_orchestrator.py` normalize_schema stage | Unicode 数学符号不转 LaTeX → 渲染异常 | 在 `_run_normalize_schema` 中调用 | ∫、∑、α 等符号转为 `\int` `\sum` `\alpha` |
| **P0-6** | 代码上下文跳过普通文本清洗 | `text_normalizer.py` | 代码缩进/符号被清洗 → 语义改变 | 检测 `#include`/`void `/`int `/`struct ` 领头行，标记为 code_block 跳过换行合并 | C 代码块缩进保留 |
| **P0-7** | 审核页详情展示 OCR raw_data | `review/page.tsx` | 无法对照 OCR 原文 → 审校效率低 | 在详情详情面板添加 "OCR 原文" 折叠区，显示 `raw_data` | 审核员可展开对比 |

### P1 — 核心体验（第 2 周）

| 优先级 | 任务 | 涉及文件 | 为什么优先 | 实现要点 |
|--------|------|---------|-----------|---------|
| **P1-1** | `math_region_detector` + `formula_image_cropper` 接入新版 pipeline | `pipeline_orchestrator.py` 新增 stage | 高数公式保护根本方案 | 在 `normalize_schema` 后 / `review` 前插入截图 stage |
| **P1-2** | 审核页展示 `math_image` segment | `review/page.tsx` | 审核员需要看到公式图片 | 读取 `parsed_content.segments` 中的 `math_image` 段渲染 |
| **P1-3** | 添加 `import_risk_level` 和 `risk_reasons` 字段 | `QuestionImport` 模型 + `review_service.py` | 后端自动评分，指导审核优先级 | 基于 risk_flags 数量/严重度计算风险等级 |
| **P1-4** | 低置信度公式标红 | `ocr_quality_gate.py` + pipeline | 用户感知公式风险 | 公式区域 OCR 置信度低于阈值时加 `low_confidence_formula` flag |
| **P1-5** | 批量过低风险题 | `review/page.tsx` + `admin_imports.py` | 低风险题无需逐题审核 | 筛选 risk_level=low 后一键全部通过 |

### P2 — 进阶优化（第 3 周）

| 优先级 | 任务 | 涉及文件 | 实现要点 |
|--------|------|---------|---------|
| **P2-1** | 多列选项错序修复 | `question_splitter.py` | 基于 OCR boxes 的 x 坐标聚类 |
| **P2-2** | 表格检测 + Markdown 还原 | 新文件 `table_detector.py` | 基于 OCR boxes 的列对齐检测 |
| **P2-3** | 原图 page image 入库供审核对照 | `pipeline_orchestrator.py` + OSS | 在 extract 阶段上传 page_image 并记录 URL |
| **P2-4** | `risk_flags` 统计仪表盘 | `review/page.tsx` | 展示每批次的 risk_flag 分布 |
| **P2-5** | 代码块语法高亮审核预览 | `review/page.tsx` | 用 `pre` + 语法高亮库 |

---

## 十一、下一轮可直接执行的 Claude Code 修改提示词

```text
请基于审计报告，执行 P0 改造。

前置约束：
- 只做 P0（7 项任务），不做大重构。
- 不改变现有 API 返回结构，只加字段不删字段。
- 不修改 miniprogram 代码。
- 不修改数据库模型，只使用已有字段。
- 修改后须运行相关测试保障不破坏现有功能。

=== P0-1: 前端展示 risk_flags 徽章 ===
修改文件：
  backend/app/schemas/admin_imports.py
  admin-frontend/src/lib/api/types.ts
  admin-frontend/src/app/(admin)/imports/review/page.tsx

要求：
  1. AdminImportQuestionItem 新增 `risk_flags: list[str] | None = None` 字段（从 ai_metadata["risk_flags"] 映射）
  2. 注意：实际数据存在 ai_metadata.risk_flags 中，新增字段需 getter 或另加
  3. 前端列表卡片在 status 标签旁添加 risk_flags 徽章（红色/黄色/灰色对应高/中/低）
  4. 前端详情页 badge row 也展示

=== P0-2: 前端醒目展示 ai_answer_flag ===
修改文件：
  admin-frontend/src/app/(admin)/imports/review/page.tsx

要求：
  1. 详情页答案卡片旁，如果 ai_answer_flag=True，显示橙色 "AI" 标签
  2. 列表卡片也显示 "AI 答案" 小标签

=== P0-3: 后端按风险过滤 + 前端风险筛选 ===
修改文件：
  backend/app/services/admin_import_service.py
  admin-frontend/src/app/(admin)/imports/review/page.tsx

要求：
  1. admin_import_service.list_review_queue 新增 risk_filter 参数（"high" / "medium" / "low"）
  2. risk_filter 逻辑：解析 ai_metadata["risk_flags"]，根据 flag 严重性过滤
  3. 前端加风险等级下拉筛选

=== P0-4: AI repair prompt 加入保护指令 ===
修改文件：
  backend/app/ai/prompts.py

要求：
  1. build_repair_question / build_batch_repair_prompt 的 system prompt 增加：
     - "不修改数学公式和 LaTeX 表达式"
     - "不修改 C 语言代码逻辑和运算符"
     - "不改动答案字段，除非原文有明显正确答案"
  2. 纯文本改动，无需测试

=== P0-5: formula_normalizer 接入新版 pipeline ===
修改文件：
  backend/app/features/pipeline_orchestrator.py (ImportPipeline::_run_normalize_schema)

要求：
  1. 在 _run_normalize_schema 中，对每道题的 stem 调用
     formula_normalizer.wrap_inline_math() 和 normalize_text_import_math()
  2. 仅在 subject 为 math2* 时执行
  3. 设置 preserve_plain_math=False（默认行为）

=== P0-6: 代码上下文跳过普通文本清洗 ===
修改文件：
  backend/app/features/text_normalizer.py

要求：
  1. ImportTextNormalizer.normalize() 或 normalize_ocr_text()
     在清洗前检测代码块行（#include, void, int main, struct, typedef 开头）
  2. 对检测到的代码块行跳过换行合并和空格压缩
  3. 不影响非代码块的普通文本

=== P0-7: 审核页详情展示 OCR raw_data ===
修改文件：
  admin-frontend/src/app/(admin)/imports/review/page.tsx

要求：
  1. 在详情页添加可折叠 "OCR 原文" 面板
  2. 显示 previewItem.raw_data 的 JSON 预览
  3. 放在 AI 补全建议 section 之前

=== 验收标准 ===
1. 导入一批含公式/代码的测试 PDF，在审核页能看到 risk_flags 徽章
2. AI 补全答案后，答案旁有橙色 "AI" 标记
3. 可按风险等级筛选审核列表
4. AI repair 不再修改公式和代码（单元测试验证）
5. Laplace 公式中的 ∫ 符号渲染为 LaTeX \int
6. C 代码 `for (int i = 0; i < n; i++)` 缩进保留
7. 展开 OCR 原文面板可看到 raw_data
```
