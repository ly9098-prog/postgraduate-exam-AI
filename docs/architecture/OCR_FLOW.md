# OCR & 题目导入流程

> 当前支持 **Excel**、**PDF（文本型+扫描型）** 和 **图片 OCR 导入**。扫描版 PDF 自动触发 PaddleOCR 识别或 PaddleOCR-VL 外部 API 回退。所有导入结果必须经过人工审核，不接受纯 AI 自动入库。
>
> 更新于 2026-06-21（P8 功能冻结）：OCR 导入管线已进入功能冻结状态，后续仅允许 bugfix。管线包含 16 个阶段（extract → review），支持 checkpoint + artifact resume、质量报告、性能 Profile 和失败自动归因。

---

## 当前实现

### 导入架构

```
Excel/PDF 上传 → 解析模块 → 文本标准化层 → Level 1 重复检测 → question_imports 暂存区 → 人工审核 → 发布前重复拦截 → questions 题库
```

所有导入**必须经过人工确认**，不接受纯 AI 自动入库。

> 2026-05-30 更新原因：同步题库 Level 1 完全重复检测；导入阶段标记疑似重复，审核发布阶段最终拦截。

### 图片导入状态链路

- `GET /api/v1/import/pipelines/{pipeline_id}` 先读 legacy `get_pipeline_status`
- 再读 Redis key `import:image:pipeline:{pipeline_id}`
- 最后回退到同进程 `_image_pipeline_store`
- 只有 legacy 与 image 状态都不存在时返回 404
- 图片上传会在入队前校验 `OCR_ENABLED` 与 PaddleOCR 依赖可用性，避免后台任务启动后才失败。
- `PipelineStatusResponse` 会带回 OCR 运行时、文本与切题诊断信息：`ocr_enabled`、`paddleocr_available`、原始/清洗后文本长度、行数、预览、长度/行数差值、OCR stats，以及切题阶段的 `normalized_block_count`、`text_block_count`、`raw_question_count`、`raw_questions_preview`、`fallback_created`、`failure_reason`。
- 图片导入失败会按可排查原因分类：`ocr_empty_text`、`text_present_but_split_failed`、`missing_options`、`pipeline_failed`；切题 fallback 会进一步标记 `text_present_but_no_question_boundary` 或 `no_text_blocks`。

> 2026-06-01 更新原因：同步图片 OCR 导入诊断与失败分类已实现状态，便于前端/排查端区分 OCR 空文本、切题失败与选项缺失。

图片导入状态写入顺序为“先内存、后 Redis best-effort”，Redis TTL 为 86400 秒。

### 图片 OCR 预处理

- 图片 / 扫描页 OCR 统一先走 `_prepare_ocr_image()`：宽度小于 1000 像素时按比例放大到 1000，再转灰度并做 autocontrast，随后先执行 `ImageOps.exif_transpose()` 再交给 PaddleOCR。
- `ocr_pages_with_boxes()` 复用同一预处理链路，避免带框 OCR 走未处理原图。
- `clean_ocr_text()` 会在“参考答案 / 正确答案 / 答案:”前补换行，避免 D 选项与答案标记粘连。
- 裸上标修正规则只允许空格 / Tab 作为连接，不跨换行，避免题号与公式切分被误伤。

### 状态语义

- 终态：`completed`、`failed`
- 非终态：`queued`、`ocr_running`、`parsing`

前端轮询仅在 `completed` / `failed` 后停止。

### 文本标准化层（新增）

`ImportTextNormalizer`（`backend/app/features/text_normalizer.py`）位于解析模块与暂存区之间：

- 清洗换行（OCR 断行合并）
- 清洗乱码（不可见字符、常见 OCR 乱码）
- 统一空格（全角→半角、连续空格合并）
- OCR 字符纠正（数字/字母常见混淆）
- 保留原始 `raw_text`，输出 `normalized_text`
- 纯规则实现，不调用 AI

### 数据流（当前）

```
POST /api/v1/import/upload
  → import_service.import_excel() / import_pdf()
    → 解析生成 batch_id
    → 文本标准化 / Question 标准化
    → 生成 question_hash 并标记 duplicate_status
    → 写入 QuestionImport 表（status=pending）
    → 返回 {batch_id, count}

PUT /api/v1/import/questions/{id}          ← 单题审批/拒绝，发布前按 subject + question_hash 拦截完全重复
POST /api/v1/import/batches/{id}/approve  ← 批量审批，缺字段跳过，发布前按 subject + question_hash 拦截完全重复
```

### 数据流（当前 — 完整导入管线，16 阶段）

```
文件上传 → OCR 识别 → 16 阶段管线（pipeline_orchestrator.py）
  │
  ├─ [1] extract         — PaddleOCR 文本提取
  ├─ [2] normalize       — text_normalizer 规则清洗
  ├─ [3] ocr_correction  — OCRFixRouter 纠错路由（PaddleOCR-VL → LLM 纠错（Qwen/GLM）→ Rule fallback）
  ├─ [4] analyze_structure — DocumentStructureAnalyzer
  ├─ [5] classify_pages  — PageClassifier
  ├─ [6] split           — QuestionSplitter
  ├─ [7] match           — AnswerMatcher
  ├─ [8] normalize_schema — QuestionNormalizer + BatchValidation + BatchDedup
  ├─ [9] repair          — AIRepairService（可选，低置信度题触发）
  ├─ [10] ai_validation  — AI 验证
  ├─ [11] similarity_match — SimilarityMatcher（题库相似匹配建议）
  ├─ [12] math_detect    — MathImportProfile 公式区域检测 + 截图裁剪
  ├─ [13] table_detect   — TableRegionDetector 表格 Markdown 转换
  ├─ [14] review         — 提交审核队列（question_imports）
  │
  └─ 各阶段支持 checkpoint + artifact resume（pipeline_artifacts.py）
     每阶段完成后输出 quality_report + performance_profile（P6）
```

### Excel 解析 (`_parse_excel` + `_raw_to_parsed`)

- 用 `openpyxl`（read_only 模式）读取
- 自动识别第一行为表头，支持中英文列名映射
- 支持的列：`subject` / `question_type` / `stem` / `options` / `answer` / `explanation` / `difficulty` / `tags`
- 选项解析：自动识别 `A:内容`、`A.内容`、`A内容` 三种格式（`\n` 分隔）
- 科目映射：`数学二→math2`、`408→exam408`、`英语→english`
- 题型映射：`选择题→choice`、`填空题→fill`、`主观题→subjective`

### PDF 解析 (`_parse_pdf`)

- 用 `pypdf.PdfReader` 逐页提取文本
- 按题号正则 `(\d+[.、)])` 切分题目
- 逐题解析：
  - 选项行识别：`A. xxx` / `A: xxx` → 存入 `options` 字典
  - 答案行识别：`【答案】` / `参考答案：` / `正确答案：` 等 4 种格式
  - 解析行识别：`【解析】` / `解答：`
- 题干清理：去掉前导题号标记和 `(单选题)` 等题型标签
- 科目猜测：关键词打分（exam408 / math2 / english 三组），要求至少命中 2 个关键词
- 示例数据输出模板：`GET /api/v1/import/template`

### QuestionImport 暂存区

关键字段：`batch_id` / `source_type` / `source_file` / `raw_data`(JSON) / `parsed_content`(JSON) / `parsed_options`(JSON) / `parsed_answer` / `parsed_analysis` / `question_hash` / `duplicate_status` / `duplicate_of_question_id` / `duplicate_of_import_id` / `status`(pending/approved/rejected) / `question_id`(审批后关联)

### 批量审批 (`batch_approve`)

- 检查 subject / question_type / parsed_content / parsed_answer 必填
- 缺少必填字段的跳过，记录跳过的题目 ID 和原因
- 发布写入 `questions` 前按 `subject + question_hash` 做 Level 1 完全重复拦截，命中正式题库重复题时跳过发布
- 如果全部跳过则抛错

### API 总结

| 接口 | 功能 |
|---|---|
| `GET /api/v1/import/template` | 下载 Excel 模板 |
| `POST /api/v1/import/upload` | 上传 Excel/PDF（自动识别） |
| `GET /api/v1/import/batches` | 批次列表（含统计） |
| `GET /api/v1/import/batches/{id}` | 批次详情 |
| `PUT /api/v1/import/questions/{id}` | 单题审核（通过或拒绝） |
| `POST /api/v1/import/batches/{id}/approve` | 批量通过 |

---

## 存在问题

1. **图片 OCR 导入已进入主链路，但仍保留人工审核** — 当前已支持图片/截图 OCR 文本提取并进入 question_imports；扫描版 PDF 使用 PaddleOCR 或 PaddleOCR-VL 回退处理
2. **PDF 科目猜测不稳定** — 简单关键词打分，混合科目文档（如数学卷子带英文题）可能猜错
3. **PDF 切题准确率不高** — 依赖题号正则，遇到"1."和"1、"混用、分页断行等情况容易漏切或错切
4. **同步解析** — 大文件（几百道题）在 HTTP 请求中同步解析，用户体验差（无进度反馈）
5. **Excel 列名容错有限** — 目前写死的列名映射表，用户用了中文缩写（如"题号""题型""答案"的不同变体）可能匹配不上
6. **无图片嵌入** — `Question.content.images` 字段存在但导入模块不会填充，所有导入题无图
7. **文件级重复检测未实现** — Level 1 题目内容 hash 已用于导入标记和发布拦截，但同一文件重复上传仍会新建 batch_id，没有基于文件内容 SHA256 的上传级去重
8. **导入管线同步阻塞** — 16 阶段管线在单线程中同步执行，大文件导入 HTTP 连接超时风险（已在 P4 引入分块 runner 缓解）

---

## 下一阶段扩展方案（2026-06-21 更新：大部分已完成）

### ✅ Phase 1 — 体验提升（已完成）

- ✅ **Excel 列名智能匹配**：不再用死映射表，改为遍历 Excel 列名，用模糊匹配（包含关系 / 拼音首字母 / 常见别称）找到最可能的字段
- ✅ **大文件异步提示**：上传接口先返回 `{batch_id, status: "parsing"}`，后台用 `BackgroundTasks` 解析，前端轮询 `GET /batches/{id}` 获取进度

### ✅ Phase 2 — 文件级去重（已完成）

- ✅ 新增 `import_service.check_duplicate(content_hash)`：
  - 上传前计算文件内容的 SHA256
  - 查 `Question.source_file` + `raw_content` 判断是否已导入
  - 已导入文件在前端提示"该文件已导入过（batch_id: xxx）"

### ✅ Phase 3 — OCR 接入（已完成，远超初始范围）

> 当前已完成的能力远超出 Phase 3 初始规划：

- 使用 PaddleOCR（本地 GPU/CPU）进行通用文字识别
- PaddleOCR-VL 外部高精 OCR API 作为纠错路由链首
- LLM 纯文本纠错（Qwen/GLM）作为回退
- AI Safety Gate（`ai_safety.py`）记录编辑前后 diff，保护代码符号/中文比例/选项数
- 公式截图裁剪（`math_detect`）：高数题自动检测公式区域并截图保留
- 表格 Markdown 转换（`table_detect`）：408 调度表/Cache 表保留行列结构
- OCR 结果缓存（`ocr_cache_service.py`）：SHA256 哈希 + config_hash，避免重复 OCR
- 16 阶段完整管线，含 checkpoint + artifact resume
- 质量报告（`quality_report`）/ 性能 Profile / 失败自动归因（`ocr_failure_analyzer.py`）
- PaddleOCR-VL → LLM（Qwen/GLM）→ Rule 三层纠错路由（旧版 Qwen-VL 已移除）
- Pipeline artifact 真断点恢复，幂等入库

### 明确不做的（2026-06-21 更新）

- ❌ 手写识别 / 复杂 OCR pipeline
- ❌ 全自动 OCR 入库（始终需要人工审核）
- ❌ 拍照搜题
- ❌ ~~公式识别（LaTeX 仍需手动校正）~~ ✅ **已实现**：公式截图裁剪以图片形式保留，无需 LaTeX 校正
- ❌ ~~本地 OCR 模型部署~~ ✅ **已部署**：PaddleOCR 本地 GPU/CPU
- ❌ LLM 输出缓存（每次 AI 调用独立，缓存会导致陈旧结果无法更新）
- ❌ 纯 AI 自动入库（所有导入必须经过 question_imports + 人工确认）
- ❌ OCR 结果直接入库（必须经过清洗、切题、标准化、审核）

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
