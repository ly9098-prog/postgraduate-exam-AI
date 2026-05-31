# 图片题目导入分阶段实施计划

> 当前文档仅为规划。未经批准前，不执行开发、不安装 PaddleOCR、不改数据库、不改现有导入逻辑、不新增接口。
> 修订说明：根据 Auditor 审计，实施主路径固定为“图片 OCR → raw_text → ImportPipeline TXT 分支 → question_imports 审核队列”。

## Phase 1：图片上传

### 目标

建立图片导入入口，完成图片文件选择、基础校验、上传任务创建和状态反馈。此阶段不要求 OCR 成功，只确保图片可以被安全接收并进入后台任务框架。

### 涉及文件

- `miniprogram/pages/import/import.js`
- `miniprogram/pages/import/import.wxml`
- `miniprogram/pages/import/import.wxss`
- `backend/app/api/v1/imports.py`
- `backend/app/core/config.py`
- 可能新增：图片上传临时存储配置相关文件

### 主要工作

1. 前端增加图片导入入口。
2. 支持 `jpg/jpeg/png/webp` 文件选择。
3. 后端新增图片上传专用入口。
4. 校验扩展名、Content-Type、文件大小。
5. 生成 `pipeline_id`，状态语义对齐现有 pipeline 查询接口。
6. 返回任务状态，而不是同步返回题目数量。
7. 不修改 `/import/upload` 的 Excel/PDF 分支。

### 风险

- 微信小程序不同来源图片的临时路径、文件名和扩展名可能不一致。
- 大图直接上传可能造成请求过慢。
- 如果复用 `/import/upload`，容易影响现有 Excel/PDF 行为。

### 验证方案

- 上传合法 PNG/JPG，后端返回任务 ID。
- 上传 PDF/Excel 仍走原链路且行为不变。
- 上传非法格式返回明确错误。
- 上传超大图片返回明确错误。
- 未授权用户无法上传。

## Phase 2：PaddleOCR 服务接入

### 目标

将图片转换为 OCR 原始文本。OCR 不做题目结构化，不判断题型，不写题库。

### 涉及文件

- `backend/app/services/ocr_service.py`
- `backend/app/api/v1/imports.py`
- `backend/app/core/config.py`
- 可能新增：`backend/app/features/image_import_service.py`

### 主要工作

1. 基于现有 PaddleOCR 封装增加单图 OCR 包装。
2. 对图片做解码、尺寸读取、必要压缩或旋转处理。
3. 调用 PaddleOCR 输出文本和可选检测框。
4. 使用 `clean_ocr_text()` 清洗 OCR 原始文本。
5. 记录 OCR 耗时、文本长度、失败原因。
6. 支持 OCR 结果缓存，缓存键使用图片 hash + OCR 配置版本。
7. 原图和压缩图默认仅短期临时保存，OCR cache 设置过期策略。

### 风险

- PaddleOCR 初始化慢，会影响首次请求。
- CPU 占用高，可能影响主 API。
- 依赖缺失时服务启动或首次 OCR 失败。
- 图片方向、模糊、阴影、压缩导致识别质量不稳定。

### 验证方案

- 清晰中文题目图片可输出 raw_text。
- 模糊图片失败时有明确错误。
- OCR 关闭或依赖缺失时返回“服务不可用”，不影响 Excel/PDF。
- 同一图片重复上传命中缓存。
- 并发上传不会让服务崩溃。

## Phase 3：OCR结果展示

### 目标

让用户能看到 OCR 原始文本和解析状态，避免“黑盒导入”。

### 涉及文件

- `miniprogram/pages/import/import.js`
- `miniprogram/pages/import-batch/import-batch.js`
- `miniprogram/pages/import-batch/import-batch.wxml`
- `backend/app/api/v1/imports.py`
- 可能新增：任务状态响应 schema

### 主要工作

1. 在上传后展示 OCR/解析进度。
2. 状态字段对齐现有 pipeline 状态查询语义，避免前端维护两套轮询逻辑。
3. 状态包括：上传完成、OCR 中、OCR 完成、解析中、进入审核、失败。
4. OCR 失败时显示错误原因，不进入审核队列。
5. OCR 成功但解析失败时展示 raw_text 预览。
6. 已进入审核后跳转现有批次详情页。

### 风险

- 小程序轮询过频造成后端压力。
- raw_text 过长时一次性 `setData` 可能导致真机卡顿。
- 失败状态如果不保留 raw_text，会难以排查。

### 验证方案

- 正常图片从上传到进入审核有可见进度。
- OCR 空文本显示可理解提示。
- 超长 raw_text 只展示截断预览。
- 真机上进度页不卡顿。

## Phase 4：接入现有AI解析

### 目标

将 OCR raw_text 接入现有解析流程，生成待审核题目。

### 涉及文件

- `backend/app/features/pipeline_orchestrator.py`
- `backend/app/features/text_normalizer.py`
- `backend/app/features/question_splitter.py`
- `backend/app/features/answer_matcher.py`
- `backend/app/features/question_normalizer.py`
- `backend/app/features/ai_repair.py`
- `backend/app/features/review_service.py`

### 主要工作

1. 将 OCR raw_text 包装为 UTF-8 TXT 输入。
2. 调用现有 `run_import_pipeline(source_type="txt")` 或等价内部流程。
3. Pipeline 内部复用 TXT 分支，写入审核队列时在 `batch_meta` 或 `raw_data` 中保留真实来源 `image`、原文件名和 `image_hash`。
4. 低置信度题目进入 AI repair。
5. 最终只写入 `question_imports(status=pending)`，不得直接写入 `questions`。

### 风险

- `source_type="txt"` 与真实来源 `image` 的语义不一致。
- OCR 文本缺少页结构，切题和答案匹配准确率低于 PDF。
- AI repair 可能修复出不符合 schema 的字段，必须仍走审核。

### 验证方案

- 单选题图片进入审核队列。
- 无答案图片进入审核队列并要求人工补答案。
- 多题图片可切出多条待审核记录。
- AI 不可用时仍可进入人工审核或给出可理解失败。
- `questions` 表无未审核新增数据。

## Phase 5：审核流程联调

### 目标

确保图片导入的题目能被现有审核页处理，并最终由人工确认入库。

### 涉及文件

- `miniprogram/pages/import-batch/import-batch.js`
- `miniprogram/pages/import-batch/import-batch.wxml`
- `backend/app/api/v1/imports.py`
- `backend/app/features/question_pipeline.py`
- `backend/app/features/review_service.py`
- `backend/app/features/question_publish_service.py`
- `backend/app/models/question_import.py`

### 主要工作

1. 批次列表正确展示图片来源。
2. 批次详情能展示 OCR 解析后的题干、选项、答案、解析。
3. 缺少科目/答案时允许人工补充。
4. 单题通过、拒绝、批量通过行为与 PDF/Excel 一致。
5. 重复检测正常工作。

### 风险

- 旧审核链路“通过即 published”和新发布链路状态语义并存。
- 图片来源题目的 `raw_data`/`ai_metadata` 可能过大，影响接口响应。
- 如果 OCR 原文含特殊字符，前端渲染可能异常。

### 验证方案

- 图片导入后批次统计 pending/approved/rejected 正确。
- 单题审核后正式题库出现对应题目。
- 拒绝题目不会入库。
- 重复图片导入能标记疑似重复。
- 前端真机审核页面可正常展开和提交。

## Phase 6：性能优化

### 目标

降低大图片、并发 OCR、重复上传对服务的影响。

### 涉及文件

- `backend/app/services/ocr_service.py`
- `backend/app/api/v1/imports.py`
- `backend/app/core/config.py`
- 可能新增：任务队列/限流/缓存模块

### 主要工作

1. 限制图片最大尺寸和最大文件大小。
2. OCR 前压缩过大图片。
3. 限制 OCR 并发数。
4. 完善 OCR 缓存和过期清理。
5. 记录 OCR 耗时和失败率。
6. 根据压测结果决定是否拆分独立 OCR worker。

### 风险

- CPU 密集任务拖慢 FastAPI 主进程。
- 多用户同时上传会导致 OCR 队列堆积。
- 图片缓存长期保存会增加存储成本。
- 过度优化会偏离当前“先实现功能”的项目理念。

### 验证方案

- 典型 2-5MB 图片可在可接受时间内完成 OCR。
- 超大图片被压缩或拒绝。
- 连续重复上传同图命中缓存。
- 并发 OCR 时 Excel/PDF 导入和普通 API 仍可用。
- 日志能定位慢请求和失败原因。
