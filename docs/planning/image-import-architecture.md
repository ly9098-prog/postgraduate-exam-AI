# 图片题目导入技术架构设计

> 目标：新增图片题目导入能力，使手机拍照、截图、试卷图片、课本图片可通过本地 PaddleOCR 提取原始文本，并进入现有解析、审核、入库链路。
> 修订说明：根据 Auditor 审计，本方案收敛为唯一主路径：图片 OCR → raw_text → ImportPipeline TXT 分支 → question_imports 审核队列。

## 1. 设计原则

1. OCR 只做“图片 → 原始文本”。
2. 题目结构化、题型识别、答案匹配、AI 修复继续复用现有解析链路。
3. 不绕过 `question_imports`。
4. 不影响现有 Excel/PDF 导入。
5. 第一版只支持单图或少量图片导入，不追求复杂版面还原。
6. OCR 结果必须可被用户查看和纠错。
7. 失败要可解释、可重试、可审计。
8. 第一版不新增数据库字段、不新增独立审核页、不拆独立 OCR 微服务。

## 2. 总体架构图

```text
小程序导入页
  ├─ Excel/PDF：保持现有 /api/v1/import/upload
  └─ 图片：选择/上传 jpg|jpeg|png|webp
        ↓
后端图片上传入口
        ↓
文件基础校验
  ├─ 扩展名/Content-Type
  ├─ 文件大小
  └─ 图片尺寸
        ↓
临时文件存储
        ↓
OCR 任务
  ├─ PaddleOCR 本地服务
  ├─ clean_ocr_text 文本清洗
  ├─ OCR 结果缓存
  └─ 审计日志记录
        ↓
原始文本 raw_text
        ↓
现有解析入口
  └─ 唯一路径：包装为 UTF-8 txt bytes → ImportPipeline(source_type="txt")
        ↓
review_service.submit_to_review()
        ↓
question_imports(pending)
        ↓
小程序批次审核页
        ↓
人工确认 / AI 补全 / 拒绝
        ↓
questions 正式题库
```

## 3. 上传入口

### 3.1 前端入口

建议在现有导入页增加图片类型选择，而不是新增独立页面：

- Excel/PDF 继续走原有按钮和原有接口。
- 图片走新增上传入口。
- 页面展示上使用同一批次列表和同一批次详情页。

原因：

- 复用现有审核体验。
- 减少用户理解成本。
- 避免新增审核 UI。

### 3.2 后端入口

建议新增图片专用入口，避免污染现有 `/import/upload`：

```text
POST /api/v1/import/image/upload
```

接收：

- `UploadFile file`
- 可选 `subject`
- 可选 `enable_ai_repair`
- 可选 `confidence_threshold`

返回：

```json
{
  "pipeline_id": "pl_img_xxx",
  "status": "ocr_pending"
}
```

后续通过现有或扩展的 pipeline 状态查询接口查看进度。

为什么不直接扩展 `/import/upload`：

- 图片 OCR 是长耗时任务，和现有同步 Excel/PDF 行为不同。
- 保持现有 PDF 导入流程稳定。
- 便于单独限制图片大小、格式、并发和错误码。

## 4. 文件存储

### 4.1 第一阶段建议

第一版只做临时存储，默认不长期保存原图：

```text
uploads/import-images/{date}/{image_id}.{ext}
```

存储内容：

- 原始图片：仅用于 OCR、失败排查和短期人工对照。
- 可选压缩后的 OCR 输入图：仅用于本次 OCR。
- OCR 原始文本缓存：按图片 hash 保存。

建议生命周期：

- 原始图片和压缩图：默认 7 天内清理。
- OCR cache：默认 30 天内清理，或按存储上限淘汰。
- 数据库只保存 `image_hash`、`raw_text` 摘要、错误码、OCR 元数据，不保存 base64 图片。

### 4.2 不建议第一版做的事情

- 不把原图长期绑定到题目内容。
- 不把每个 OCR 检测框都持久化到数据库新字段。
- 不新增对象存储依赖，除非现有项目已有统一文件存储。

原因：当前需求是“图片 → 文本 → 现有解析”，不是“题目带图入库”。长期图片题可后续单独设计。

## 5. OCR 服务

### 5.1 服务边界

PaddleOCR 服务输入：

```text
image bytes / image path
```

输出：

```json
{
  "raw_text": "识别出的原始文本",
  "lines": [
    {"text": "...", "confidence": 0.92, "bbox": [x0, y0, x1, y1]}
  ],
  "duration_ms": 1234
}
```

其中第一阶段真正进入解析链路的只应是 `raw_text`。

### 5.2 复用现有 PaddleOCR 封装

现有 `backend/app/services/ocr_service.py` 已有：

- OCR 单例懒加载。
- 多页 OCR 并发。
- `ocr_pages()`。
- `ocr_pages_with_boxes()`。
- `clean_ocr_text()`。

图片导入可在后续开发阶段增加“单图 OCR 包装函数”，但不改变现有 PDF OCR 行为。

### 5.3 OCR 运行方式

第一版建议以应用内本地调用为主：

```text
FastAPI BackgroundTasks
  → 调用 PaddleOCR
  → 生成 raw_text
  → 进入 ImportPipeline
```

不建议第一版拆独立 OCR 微服务，除非实际压测证明 CPU 占用影响主 API。

## 6. OCR 结果缓存

### 6.1 缓存目标

避免同一张图片重复 OCR，降低 CPU 消耗并提升重试体验。

### 6.2 缓存键

```text
sha256(image_bytes) + ocr_config_version
```

### 6.3 缓存内容

```json
{
  "image_hash": "...",
  "raw_text": "...",
  "lines": [...],
  "engine": "paddleocr",
  "engine_version": "...",
  "language": "ch",
  "created_at": "..."
}
```

### 6.4 第一版落地方式

优先使用文件缓存或现有可用缓存：

```text
uploads/import-images/cache/{hash}.json
```

如果后续已有 Redis，可把 OCR 状态和短期结果放 Redis；不为第一版强制引入 Redis。

## 7. AI 解析入口

唯一主路径：

```text
OCR raw_text
  → 包装为 UTF-8 txt bytes
  → run_import_pipeline(source_type="txt")
  → normalize_text/split/match/normalize_schema/repair/review
  → review_service.submit_to_review()
  → question_imports(status="pending")
```

来源语义处理：

- pipeline 内部可复用 `source_type="txt"` 的抽取逻辑。
- 写入审核队列时应在 `batch_meta` 或 `raw_data` 中保留真实来源 `image`、`source_file`、`image_hash`。
- 前端批次列表展示应以真实来源为准，避免用户看到“txt 导入”产生困惑。

原因：

- `ImportPipeline` 已支持 TXT。
- 它天然会进入 `review_service.submit_to_review()`。
- 能复用低置信度 AI repair。
- 不需要把图片 OCR 强行伪装成 PDF。
- 避免复制 `question_pipeline._parse_pdf()` 的旧切题逻辑，降低维护成本。

## 8. 错误处理机制

### 8.1 上传阶段

- 非图片格式：返回 400。
- 文件过大：返回 413 或 400。
- 图片无法解码：返回 400。
- 未授权：沿用 `require_app_permission("import:write")`。

### 8.2 OCR 阶段

- PaddleOCR 未启用或依赖缺失：任务失败，提示“图片 OCR 服务不可用”。
- OCR 超时：任务失败，可重试。
- OCR 空文本：不进入 AI 解析，提示用户换清晰图片或手动录入。
- 部分图片失败：第一版建议整个批次失败并给出失败图片；多图部分成功可后续做。

### 8.3 解析阶段

- 切不出题：进入失败状态，保留 raw_text 供用户查看。
- 答案缺失：允许进入审核队列，由人工补充。
- 低置信度：进入审核队列并标记 warnings，不阻断。

## 9. 审计日志

第一版必须至少记录以下结构化应用日志事件：

```text
image_upload_received
image_validation_failed
image_stored
ocr_started
ocr_cache_hit
ocr_completed
ocr_failed
pipeline_started
pipeline_completed
pipeline_failed
review_items_created
```

最小日志字段：

- `trace_id` / `pipeline_id`
- `user_id` 或管理员 ID
- `source_file`
- `image_hash`
- `file_size`
- `width` / `height`
- `ocr_duration_ms`
- `raw_text_length`
- `question_count`
- `error_code`

第一版可先用结构化应用日志，不强制新增数据库审计表。

## 10. 与现有流程的关系

| 模块 | 图片导入处理方式 |
|---|---|
| Excel/PDF 上传 | 不改现有行为 |
| PDF OCR | 不复用为图片入口，只复用 PaddleOCR 底层能力 |
| AI 解析 | 唯一接入 `ImportPipeline` TXT 分支，再进入 review stage |
| 审核 | 复用 `question_imports` 和批次详情页 |
| 入库 | 复用现有人工审核后入库 |
| 数据库 | 第一版不新增字段，必要元数据放 `raw_data`/`ai_metadata` |

---

## 相关链接

- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/MVP_SCOPE.md|MVP_SCOPE]] — MVP 范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
