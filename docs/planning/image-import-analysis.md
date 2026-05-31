# 图片题目导入现状调研分析

> 范围：仅分析规划，不开发 OCR 代码、不修改现有导入逻辑、不新增接口。
> 修订说明：根据 Auditor 审计，后续实施建议收敛为唯一主路径：图片 OCR → raw_text → ImportPipeline TXT 分支 → question_imports 审核队列。

## 1. 当前导入链路总览

当前系统已经存在两条并行导入链路：

```text
旧链路：Excel/PDF → question_pipeline → question_imports(pending) → 小程序审核 → questions
新链路：PDF/TXT → ImportPipeline Stage 1-7 → review_service → question_imports(pending) → 审核/发布接口
```

项目长期约束要求所有导入必须进入 `question_imports` 并人工确认后才可进入正式题库，因此图片导入不能直接写入 `questions`。

## 2. 前端上传流程

关键文件：

- `miniprogram/pages/import/import.js`
- `miniprogram/pages/import-batch/import-batch.js`

现状：

1. 导入页通过 `wx.chooseMessageFile` 选择文件。
2. 当前白名单仅允许 `xlsx`、`xls`、`pdf`。
3. 上传统一调用 `POST /import/upload`。
4. 上传成功后刷新批次列表。
5. 批次详情页读取 `GET /import/batches/{batch_id}`。
6. 用户可在批次详情中执行单题通过、拒绝、批量通过、AI 补全、公式预览等操作。

限制：

- 目前没有图片选择入口。
- 当前导入入口提示文案和扩展名校验都不支持 `jpg/jpeg/png/webp`。
- 现有上传成功文案假设导入已同步完成，不适合长耗时 OCR。

## 3. 后端导入流程

关键文件：

- `backend/app/api/v1/imports.py`
- `backend/app/features/question_pipeline.py`
- `backend/app/features/pipeline_orchestrator.py`
- `backend/app/features/review_service.py`

### 3.1 旧链路 `/api/v1/import/upload`

`imports.py` 中 `upload_file()` 当前只接受 Excel/PDF：

```text
UploadFile
  → 判断 .xlsx/.xls/.pdf
  → PDF: svc.import_pdf()
  → Excel: svc.import_excel()
  → 返回 batch_id/total/source_type/source_file
```

`question_pipeline.import_excel()` 与 `import_pdf()` 会：

1. 解析为 raw rows。
2. 调 `process_question_pipeline()` 标准化。
3. 写入 `question_imports`，状态为 `pending`。
4. 等待小程序人工审核。

### 3.2 新链路 `/api/v1/import/pipeline/upload`

`pipeline_upload()` 当前只接受 `.pdf/.txt`：

```text
PDF/TXT bytes
  → 后台任务 run_pipeline_background
  → extract
  → normalize_text
  → split
  → match
  → normalize_schema
  → repair(optional)
  → review
```

该链路最终通过 `review_service.submit_to_review()` 写入 `question_imports`，天然符合“先审核再入库”的约束。

## 4. OCR 相关现状

关键文件：

- `backend/app/services/ocr_service.py`
- `backend/app/features/ocr_service.py`
- `backend/app/services/pdf_classifier.py`

当前 OCR 相关能力分为两类：

1. `app/services/ocr_service.py`
   - 基于 PaddleOCR。
   - 通过懒加载单例初始化 OCR 实例。
   - 提供 `ocr_pages()`、`ocr_pages_with_boxes()`、`clean_ocr_text()`。
   - 当前主要被 PDF 扫描页识别使用。
2. `app/features/ocr_service.py`
   - 偏 AI 视觉 OCR fallback。
   - 设计为扫描版 PDF 的补充方案。
   - 与本次“优先本地部署、不依赖收费 OCR”的要求不完全匹配。

现状说明：代码中已有 PaddleOCR 服务封装，但图片文件作为独立上传来源尚未接入；规划阶段不安装、不验证 PaddleOCR 运行环境。

## 5. AI 解析流程

关键文件：

- `backend/app/features/question_pipeline.py`
- `backend/app/features/ai_repair.py`
- `backend/app/features/question_normalizer.py`
- `backend/app/ai/client.py`
- `backend/app/ai/prompts.py`

AI 在当前链路中的定位：

- 不负责 OCR。
- 不直接写题库。
- 用于题目补全、低置信度修复、知识点/难度辅助。
- AI 不可用时不应阻断核心人工审核流程。

图片导入应保持边界：

```text
PaddleOCR：图片 → 原始文本
现有解析链路：原始文本 → 切题/答案匹配/结构化
AI：低置信度修复或补全
人工审核：最终确认
```

## 6. 审核流程

关键文件：

- `miniprogram/pages/import-batch/import-batch.js`
- `backend/app/api/v1/imports.py`
- `backend/app/features/question_pipeline.py`
- `backend/app/features/review_service.py`
- `backend/app/features/question_publish_service.py`

审核现状：

1. 小程序批次详情页展示 `question_imports`。
2. 单题通过调用 `PUT /import/questions/{id}`。
3. 拒绝同样调用 `PUT /import/questions/{id}`，状态为 `rejected`。
4. 批量通过调用 `POST /import/batches/{batch_id}/approve`。
5. `question_pipeline.approve_question()` 当前是“审核通过即写入 questions，并将导入记录置为 published”。
6. 另有 `question_publish_service.py` 支持 approved → published 的发布流，和旧链路存在状态语义并存。

图片导入应优先复用当前小程序已经稳定使用的批次审核页面，避免新增第三套审核 UI。

## 7. 题库入库流程

当前正式入库发生在审核通过后：

```text
question_imports(status=pending)
  → 审核通过
  → process_question_pipeline(raw, manual)
  → 重复检测
  → 新建或关联 questions
  → question_imports.status=published
```

关键风险是：新增图片导入不能为了“快速导入”绕过 `question_imports`，也不能让 OCR 结果直接成为正式题库数据。

## 8. 图片导入可复用点

建议优先复用：

1. 前端批次列表和批次详情页。
2. `question_imports` 暂存表。
3. `review_service.submit_to_review()`。
4. `pipeline_orchestrator` 的 TXT 输入链路。
5. 现有 AI repair / AI complete / AI enrich。
6. 现有审核通过、拒绝、批量通过流程。

明确不建议第一版复用旧 PDF 切题逻辑或新增独立审核 UI。

## 9. 图片导入冲突点

1. 前端文件白名单不支持图片。
2. `/import/upload` 不支持图片扩展名。
3. `/import/pipeline/upload` 不支持图片扩展名。
4. `question_pipeline._parse_pdf()` 只接收 PDF bytes，不能直接解析图片 bytes。
5. PaddleOCR 输出是“原始文本”，而不是题目结构，必须接入现有 TXT/解析链路。
6. 审核发布状态存在旧链路“通过即 published”和新链路“approved/published”并存，图片导入要明确只复用现有稳定路径，不引入新状态。
7. OCR 耗时明显长于 Excel/PDF 文本解析，不适合同步阻塞过久。
8. 图片任务状态若不对齐现有 pipeline 状态查询语义，前端会被迫维护额外轮询分支。
9. 原图和 OCR cache 若没有生命周期，会带来存储和隐私边界风险。
