# 阶段 8：OCR 扫描版 PDF 支持 ✅

**目标**：在已有导入系统基础上增加 OCR 能力，实现对扫描版 PDF 的自动识别。

> **注意**：代码已实现，但端到端未在实际环境中完整跑通（本地无 paddlepaddle 环境，依赖体积 ~500MB+）。

## 架构

```
PDF → PDF分类 → 文本提取 / OCR → 文本清洗 → 原有 LLM 结构化 → 入库
```

### PDF 分类
- `pdf_classifier.py`：判断 PDF 页面是否为图片型（文本极少或无文本）
- 仅对图片型页面执行 OCR，不浪费性能

### OCR 处理
- `ocr_service.py`：基于 PaddleOCR，支持 CPU 模式
- 并发处理（`ThreadPoolExecutor`）
- 文本清洗：去除乱码、合并断行、修复换行断裂

## 关键文件

```
backend/app/services/pdf_classifier.py  # PDF 页面分类
backend/app/services/ocr_service.py     # OCR 识别 + 文本清洗
```

## 配置项

```bash
OCR_ENABLED=true          # 可用 false 完全关闭，退化为原有行为
OCR_MAX_WORKERS=4
OCR_LANGUAGE=ch
OCR_USE_GPU=false
```

## 验收标准

- [x] 代码实现：PDF 分类 + OCR 识别 + 文本清洗 + 接入导入流程
- [ ] E2E 验证：需在有 paddlepaddle 环境的容器中验证完整流程
- [ ] 回归：原有 Excel / 文本 PDF / AI 生成导入不受影响

详细流程见 `/docs/OCR_FLOW.md`。

---

## 相关链接

- [[docs/INDEX.md|INDEX]] — 文档总索引
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
