# OCR & 题目导入流程

> 本项目不做复杂 OCR。当前支持 **Excel**、**可复制文本型 PDF** 和 **图片 OCR 导入**。图片 OCR 仅做文本提取，结果仍进入导入管线并保留人工审核；扫描版 PDF 仍不直接处理，除非后续扩展为图片导入路径。

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

图片导入状态写入顺序为“先内存、后 Redis best-effort”，Redis TTL 为 86400 秒。

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
    → 写入 QuestionImport 表（status=pending）
    → 返回 {batch_id, count}

PUT /api/v1/import/questions/{id}          ← 单题审批/拒绝
POST /api/v1/import/batches/{id}/approve  ← 批量审批
```

### 数据流（规划中 — 导入管线）

```
文件上传 → 解析模块
  → ImportTextNormalizer（文本标准化）
    → DocumentStructureAnalyzer（结构分析）
      → QuestionSplitter（题目切分）
        → AnswerMatcher（答案匹配）
          → QuestionNormalizer（Schema 标准化）
            → AIRepairService（AI 修复，可选）
              → 审核队列 → question_imports
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

关键字段：`batch_id` / `source_type` / `source_file` / `raw_data`(JSON) / `parsed_content`(JSON) / `parsed_options`(JSON) / `status`(pending/approved/rejected) / `question_id`(审批后关联)

### 批量审批 (`batch_approve`)

- 检查 subject / question_type / parsed_content / parsed_answer 必填
- 缺少必填字段的跳过，记录跳过的题目 ID 和原因
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

1. **图片 OCR 导入仍属于可选扩展** — 当前已支持图片 OCR 文本提取，但扫描版 PDF 仍不会直接走 OCR 解析，除非先转成图片导入或后续显式扩展该路径
2. **PDF 科目猜测不稳定** — 简单关键词打分，混合科目文档（如数学卷子带英文题）可能猜错
3. **PDF 切题准确率不高** — 依赖题号正则，遇到"1."和"1、"混用、分页断行等情况容易漏切或错切
4. **同步解析** — 大文件（几百道题）在 HTTP 请求中同步解析，用户体验差（无进度反馈）
5. **Excel 列名容错有限** — 目前写死的列名映射表，用户用了中文缩写（如"题号""题型""答案"的不同变体）可能匹配不上
6. **无图片嵌入** — `Question.content.images` 字段存在但导入模块不会填充，所有导入题无图
7. **导入重复检测** — 同一文件重复上传会新建 batch_id，没有基于内容哈希的去重

---

## 下一阶段扩展方案

### Phase 1 — 体验提升（1 天，优先做人能做的事）

- **Excel 列名智能匹配**：不再用死映射表，改为遍历 Excel 列名，用模糊匹配（包含关系 / 拼音首字母 / 常见别称）找到最可能的字段
- **大文件异步提示**：上传接口先返回 `{batch_id, status: "parsing"}`，后台用 `BackgroundTasks` 解析，前端轮询 `GET /batches/{id}` 获取进度

### Phase 2 — 去重（0.5 天）

- 新增 `import_service.check_duplicate(content_hash)`：
  - 上传前计算文件内容的 SHA256
  - 查 `Question.source_file` + `raw_content` 判断是否已导入
  - 已导入文件在前端提示"该文件已导入过（batch_id: xxx）"

### Phase 3 — 可选 OCR 接入（当确实需要时）

> 明确需求场景：用户有大量**扫描版纸质题集**需要导入。在此之前不值得做。

- 使用 DeepSeek VL 或类似 API 识别图片中的题目文字
- 不引入本地 OCR 模型（Tesseract / PaddleOCR），太重
- 方案：前端或后端将 PDF 页面转为图片，调用 AI API 提取文本
- 结果回填到 `_parse_pdf` 的文本提取逻辑中

```
触发条件
  上传 PDF → pypdf 提取文本 → 文本为空 / <100字符？
    └─YES→ AI 图片识别降级 → 解析结果 → 进入 QuestionImport
    └─NO → 现有文本解析逻辑
```

- AI 图片识别出错不影响正常流程（仍然报错提示用户手动输入）
- 识别结果同样需要人工确认

### 明确不做的

- ❌ 手写识别 / 复杂 OCR pipeline
- ❌ 全自动 OCR 入库（始终需要人工审核）
- ❌ 拍照搜题
- ❌ PDF 表格结构化识别
- ❌ 公式识别（LaTeX 仍需手动校正）
- ❌ 本地 OCR 模型部署
