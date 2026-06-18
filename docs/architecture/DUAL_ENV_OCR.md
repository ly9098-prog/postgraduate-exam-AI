# 双环境 OCR 架构 — 实现记录

## 目标

根据 `APP_ENV` 自动加载对应环境的 OCR 配置档案：

- **本地开发**（i7 + RTX3060）：GPU 高精度，大文件批量处理，旋转检测开启
- **服务器生产**（2C2G）：CPU 轻量，单文件快速响应，旋转检测关闭，施加上传限制

## 设计方案

采用 **配置档案（Profile）+ 上传验证器** 模式。保持一套 OCR 引擎代码，不拆分类、不引入抽象工厂。

## 新增文件

### `app/core/ocr_profile.py`

定义 `OCRProfile` frozen dataclass，包含：

| 字段 | 说明 |
|------|------|
| use_gpu | GPU 推理开关 |
| max_workers | OCR 并发线程数 |
| timeout_seconds | 单次 OCR 超时 |
| min_image_width | 图片最小宽度（小于此值会放大） |
| enable_rotation | 旋转候选检测开关 |
| enable_ai_correction | AI 纠错开关（预留） |
| allowed_source_types | 允许的文件类型 |
| max_pdf_pages | PDF 最大页数限制（0=不限） |
| max_upload_bytes | 单文件上传大小限制 |
| max_batch_files | 批量上传文件数限制（0=不限） |

两套预设档案通过 `get_ocr_profile()` 按环境选择：

| 参数 | local/development | production |
|------|-------------------|------------|
| use_gpu | True | False |
| max_workers | 4 | 2 |
| timeout_seconds | 1200 | 300 |
| min_image_width | 1500 | 1200 |
| enable_rotation | True | False |
| allowed_source_types | pdf, excel, image, txt | pdf, image, txt |
| max_pdf_pages | 不限 | 30 |
| max_upload_bytes | 100MB | 5MB |
| max_batch_files | 不限 | 1 |

选择逻辑：优先读 `DEPLOY_PROFILE`，为空则跟随 `APP_ENV`。

### `app/services/upload_validator.py`

`UploadValidator` 类提供三个验证方法：

- `validate_file(filename, size, content_type)` — 验证文件类型和大小
- `validate_pdf_pages(total_pages)` — 验证 PDF 页数
- `validate_batch_size(file_count)` — 验证批量数量

超限返回 HTTP 400，提示"建议在本地导入后同步至云端"。

## 修改文件

| 文件 | 变更 |
|------|------|
| `app/core/config.py` | 新增 `DEPLOY_PROFILE` 字段 |
| `app/api/v1/imports.py` | `pipeline_upload` 入口接入验证器（文件类型/大小/PDF页数） |
| `app/features/pipeline_orchestrator.py` | `_ocr_scanned_pdf` 使用 profile.timeout_seconds 和 profile.max_workers |
| `app/services/ocr_service.py` | `_get_ocr()` 用 profile.use_gpu；`_resize_for_ocr()` 用 profile.min_image_width；`ocr_pages()` / `ocr_pages_with_boxes()` 用 profile.max_workers；`_ocr_with_rotation_candidates()` 受 enable_rotation 控制 |
| `app/main.py` | 启动日志打印 profile 信息 |

## 审计修复

初始实现后经审计发现 3 个问题并已修复：

1. **P0**：`_ocr_with_rotation_candidates()` 未读取 `enable_rotation`，production 环境仍执行旋转（每张图多 3 次推理）。修复：函数头判断 profile 开关，关闭时直接返回首次结果。
2. **P1**：`ocr_pages()` 和 `ocr_pages_with_boxes()` 的 `max_workers` 仍读 `settings.OCR_MAX_WORKERS`。修复：改为 `get_ocr_profile().max_workers`。
3. **P1**：图片分支中 `settings.IMAGE_IMPORT_MAX_BYTES` 与 validator 重复检查。修复：删除冗余硬编码检查。

## 已知遗留

- `enable_ai_correction` 字段未被消费（pipeline 使用 `options.enable_ai_repair`，由用户选择控制）
- deprecated `image_upload` 旧入口未接入验证器（计划废弃）
- OCR 检测阈值参数（det_db_thresh 等）未纳入 profile（两环境当前用相同值）

## 验证方式

- `APP_ENV=development` → local profile，上传大 PDF 不受限，OCR 4 线程 + GPU + 旋转检测
- `APP_ENV=production` → production profile，>5MB 文件/31页 PDF/.xlsx 均被拒绝，OCR 2 线程 + CPU + 无旋转
- 测试套件 554 passed（1 pre-existing failure 为测试顺序污染，非本次引入）
