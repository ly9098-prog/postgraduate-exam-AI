# OCR 导入运维手册

## 导入流程概述

```
源文件 → [extract] → [normalize] → [ocr_correction] → [analyze_structure]
  → [classify_pages] → [split] → [match] → [normalize_schema]
  → [batch_validation] → [batch_dedup] → [repair] → [ai_validation]
  → [similarity_match] → [math_detect] → [table_detect] → [review]
```

详见 `docs/architecture/OCR_FLOW.md`。

---

## 质量报告字段说明

| 字段 | 含义 | 判断标准 |
|------|------|----------|
| `total_questions` | 总识别题数 | 无 |
| `low_risk` | 低风险题数 | 无 risk_flag |
| `medium_risk` | 需检查题数 | 有 risk_flag 但不含高危 flag |
| `high_risk` | 高风险题数 | 含高危 risk_flag（如 answer_ai_generated） |
| `requires_manual_review` | 需人工审核 = medium + high | > 50% total 时触发告警 |
| `ai_answer_count` | AI 辅助生成答案数 | > 10 时触发告警 |
| `math_image_count` | 数学公式截图数 | 对比 expected_math_image_count |
| `table_markdown_count` | 表格 Markdown 数 | 对比 expected_table_count |
| `ocr_cache_hit_rate` | OCR 缓存命中率 | < 20% 时触发 info 告警 |
| `slowest_stage` | 最慢阶段名称 | 辅助性能调优 |
| `estimated_manual_check_rate` | 预估人工审核率 | > 50% 时触发告警 |

---

## Dashboard 指标

| 指标 | 来源 | 用途 |
|------|------|------|
| 导入成功率 | `/imports/pipelines` 最近 N 条 | 整体健康度 |
| 平均耗时 | performance_summary.total_duration_ms | 性能基准 |
| 总导入题数 | quality_report.total_questions | 产能跟踪 |
| 高风险题比例 | quality_report.high_risk / total | 质量门禁 |
| 最常见 failure types | 各 failure 类型计数 | 持续改进方向 |
| OCR 缓存命中率 | quality_report.ocr_cache_hit_rate | 缓存效率 |

---

## 告警规则

| code | level | 触发条件 | 建议操作 |
|------|-------|----------|----------|
| `import_failed` | error | pipeline status = failed | 查看错误日志 |
| `high_risk_ratio_too_high` | warning | high_risk / total > 40% | 打开高风险筛选逐题确认 |
| `manual_review_rate_too_high` | warning | (medium+high) / total > 50% | 检查源文件质量 |
| `ai_answer_count_too_high` | warning | ai_answer_count > 10 | 重点核对 AI 答案 |
| `ocr_cache_hit_rate_too_low` | info | hit / (hit+miss) < 20% | 首次导入正常；若重复导入仍低则检查缓存目录 |
| `pipeline_duration_too_long` | warning | duration > 5 min | 检查页数/AI 调用 |
| `ocr_failed_page_ratio_too_high` | warning | OCR 失败页 / 总页 > 30% | 检查 PDF 质量 |

---

## 清理流程

### 前置条件
- 清理分两步：先 dry-run → 确认后执行
- dry-run **不删除任何文件**

### 执行清理
```bash
# 1. Dry-Run（仅扫描）
POST /api/admin/v1/imports/maintenance/cleanup
{"target": "all", "dry_run": true}

# 2. 检查结果后执行真实清理
POST /api/admin/v1/imports/maintenance/cleanup
{"target": "all", "dry_run": false}
```

### 清理对象

| 目标 | 内容 | TTL | 保护规则 |
|------|------|-----|----------|
| artifacts | pipeline stage artifacts | completed: 24h, failed: 7d | running 跳过 |
| ocr_cache | PaddleOCR 缓存 | 14 天 | 无 |
| db_rows | 导入历史记录 | — | 当前版本不实现 |

### 管理端操作
浏览器访问 **导入管理 → 运维** 标签页：
1. 点击「运行 Dry-Run」
2. 查看结果表格
3. 点击「确认清理」→ 再次确认 → 执行

---

## 失败样本导出

### 单题导出
```bash
POST /api/admin/v1/imports/questions/{import_id}/export-case
```
返回 JSON 包含：
- `case_id`: `failure_{日期}_{import_id}`
- `source_file`: 文件名（不含路径）
- `raw_data`: 截断至 2000 字符
- `risk_flags`, `failure_types`
- `expected_template`: 全部为空，需人工填写

### 批量导出
```bash
POST /api/admin/v1/imports/batches/{batch_id}/export-failure-cases?failure_type=answer_missing
```

> **重要**: expected_template 所有字段必须人工填写，禁止使用 AI 生成答案。

### 导出后处理
导出的 JSON 可放置到 `tests/ocr_acceptance/local_cases/` 目录作为新的验收用例。人工补充 expected 后即可被 acceptance runner 识别。

---

## 验收测试

```bash
# 标准模式（需放置真实样本）
python tests/ocr_acceptance/run_acceptance.py

# 严格模式（发布前）
python tests/ocr_acceptance/run_acceptance.py --strict

# 输出报告
python tests/ocr_acceptance/run_acceptance.py --report report.json
```

---

## 发布前检查

```bash
# 离线检查（默认，无需后端）
python scripts/ocr_preflight_check.py

# 详细模式
python scripts/ocr_preflight_check.py --verbose

# 含在线检查
python scripts/ocr_preflight_check.py --api-base-url http://localhost:8000/api/admin/v1

# JSON 格式输出
python scripts/ocr_preflight_check.py --json
```

---

## 恢复失败的导入

1. 检查失败原因（管理端 → 导入任务 → 错误日志）
2. 确认源文件未更改（sha256 校验）
3. 使用 resume 接口恢复：
```bash
POST /api/admin/v1/imports/pipelines/{pipeline_id}/resume
```
4. artfact 存在时自动跳过已完成 stage

---

## 目录安全

| 目录 | 能否手动删除 | 说明 |
|------|-------------|------|
| `.backend_cache/ocr/` | 可（自动重建） | OCR 图片缓存，删除后重新 OCR |
| `.backend_cache/pipeline_artifacts/` | 建议用 API | 正在运行中的 pipeline artifact 被删会导致 resume 失败 |
| `ocr_test/` | 不可 | 回归测试样本，删除后回归无法执行 |
