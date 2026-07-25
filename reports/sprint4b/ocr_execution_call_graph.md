# OCR 执行调用图审计 — Sprint 4B

> 审计时间：2026-07-17 · 目的：明确全部 OCR 入口和调用路径，确定生产端 Paddle 加载面

---

## 一、OCR 入口汇总

| # | 文件 | 函数 | 生产 Web 进程 | 加载 Paddle | PDF 渲染 | Artifact Resume |
|---|------|------|:---:|:---:|:---:|:---:|
| 1 | `services/ocr_service.py` | `_get_ocr()` | ✅ | ✅ | ❌ | ❌ |
| 2 | `services/ocr_service.py` | `ocr_image()` | ✅ | ✅ | ❌ | ❌ |
| 3 | `services/ocr_service.py` | `ocr_pages()` | ✅ | ✅ | ❌ | ❌ |
| 4 | `services/ocr_service.py` | `ocr_pages_with_boxes()` | ✅ | ✅ | ❌ | ❌ |
| 5 | `services/ocr_service.py` | `_ocr_one_page_with_boxes()` | ✅ | ✅ | ❌ | ❌ |
| 6 | `pipeline_orchestrator.py` | `_ocr_scanned_pdf()` | ✅ | ✅ | ✅ (150dpi) | ❌ |
| 7 | `pipeline_orchestrator.py` | `_blocks_to_document_ir()` | ✅ | ❌ | ❌ | ❌ |
| 8 | `ocr_adapter.py` | `PaddleOCRLocalAdapter.process()` | ✅ | ✅ | ✅ | ❌ |
| 9 | `ocr_adapter.py` | `PaddleOCRVLDocumentAdapter.process()` | ✅ | ❌ | ❌ | ❌ |
| 10 | `paddleocr_vl_client.py` | `PaddleOCRVLClient.ocr_image()` | ✅ | ❌ | ❌ | ❌ |
| 11 | `ocr_fix/router.py` | `OCRFixRouter.fix()` | ✅ | ❌ | ❌ | ❌ |
| 12 | `batch_image_import_service.py` | `_run_vl_ocr()` | ✅ | ❌ | ❌ | ❌ |
| 13 | `pipeline_orchestrator.py` | `_run_vl_rebuild_blocks()` | ✅ | ❌ | ✅ (150dpi) | ❌ |

## 二、Paddle 加载链

**唯一 Paddle 导入点：**

```
backend/app/services/ocr_service.py:118
  from paddleocr import PaddleOCR  # 延迟导入
```

**调用链：**
```
生产 API 请求
  → pipeline_orchestrator._run_extract()
    → _ocr_scanned_pdf()
      → ocr_service.ocr_pages_with_boxes() / ocr_process_pool
        → _get_ocr()
          → from paddleocr import PaddleOCR  ← Paddle/Torch 在此加载
```

## 三、Adapter 生产调用点

| 组件 | 生产调用点 |
|------|:---------:|
| `OcrAdapter` (protocol) | **0** |
| `PaddleOCRLocalAdapter` | **0** |
| `PaddleOCRVLDocumentAdapter` | **0** |
| `AdapterRegistry` | **0** |
| `AdapterSelector` | **0** |
| `CircuitBreaker` (embedded) | **0** |
| `ModuleResult[DocumentIR]` | **0** |

## 四、缺少的关键组件

| 组件 | 状态 |
|------|------|
| `app/ocr_worker/` | ❌ 不存在 |
| OCR Job 数据模型 | ❌ 不存在 |
| OCR 状态机 | ❌ 不存在 |
| Claim/Lease 原子操作 | ❌ 不存在 |
| Worker API | ❌ 不存在 |
| Worker 认证 | ❌ 不存在 |
| Production Thin Mode guard | ❌ 未实现 |
| OCR Artifact Resume | ❌ extract/ocr_correction 未加入可恢复阶段 |
| CircuitBreaker 独立类 | ❌ 仅嵌入 AdapterSelector，无生产调用 |

## 五、直接读取 Paddle 私有字段

| 位置 | 行 | 访问模式 |
|------|:--:|----------|
| `ocr_service.py` | 409 | `line[1][0]`, `line[1][1]` |
| `ocr_service.py` | 477 | `line[0]`, `line[1][0]`, `line[1][1]` |
| `ocr_service.py` | 793 | `line_info[1][0]` |

## 六、关键发现

1. **PaddleOCR 在生产 Web 进程内加载** — 当 `OCR_ENABLED=true` 时，首次 OCR 请求会把 paddle/torch 加载到 uvicorn worker 内存中
2. **Adapter 零生产调用点** — `PaddleOCRLocalAdapter`, `AdapterRegistry`, `AdapterSelector` 均已定义但无生产路径使用
3. **无独立 CircuitBreaker** — 仅嵌入 AdapterSelector，但 AdapterSelector 从未被调用
4. **无 OCR Job 数据库模型** — 无法实现数据库任务队列
5. **无 Worker Daemon** — `app/ocr_worker/` 目录不存在
6. **OCR 不可从 Artifact Resume** — extract 和 ocr_correction 阶段不在可恢复阶段列表中
7. **生产 Thin Mode 未实现** — `PRODUCTION_THIN_MODE` 检查尚未实现
