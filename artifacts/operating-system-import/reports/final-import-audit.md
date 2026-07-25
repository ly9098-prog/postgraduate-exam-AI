# 操作系统题库导入最终报告 v2

## 任务状态：SUCCESS

- **原始导入时间**：2026-07-19 15:25-17:03
- **缺失页面重导入时间**：2026-07-19 18:10-18:30
- **PDF 路径**：`/home/lmh/projects/postgraduate-ai/ocr_test/import/os_sc.pdf`
- **PDF 页数**：500
- **数据库**：SQLite `/home/lmh/projects/postgraduate-ai/backend/postgraduate.db`

---

## 导入结果总览

| 指标 | v1 (原始) | v2 (补全后) |
|------|-----------|-------------|
| 总题数 | 442 | 575 |
| 覆盖页数 (1-497) | 364/497 | **497/497** |
| 缺失页面 | 134 | **0** |
| 单选题 | 437 | 560 |
| 多空选择题 | 5 | 5 |
| 主观题 (无选项) | 0 | 10 |
| 已发布 | 0 | 0 |
| 答案状态 | missing | missing |

---

## 问题类型分布

- `single_choice`：560（97.4%）
- `multi_blank_choice`：5（0.9%）
- `subjective`：10（1.7%）— 部分页面 OCR 选项提取不完整

---

## 补全操作

### 缺失页面重导入（134 页）

**原因**：原始 Pipeline 的 25 页分批处理中，split 阶段对部分页面无法提取题目。日志显示所有批次状态均为 `completed`，但有 134 页产生了 0 道题。

**方法**：编写 `artifacts/operating-system-import/reimport_missing.py` 脚本，逐页从 PDF 提取图片 → 远程 PaddleOCR GPU（通过 Windows httpx 代理 → paddlex_http）→ 直接解析 OCR 文本 → 插入 `question_imports`。

**结果**：134 页全部成功导入，0 解析失败。

### 修复原始导入的 5 道污染题（ids 429-433）

**问题**：原始批量 461-485 中，5 道题的 `raw_text` 来自本页（磁盘调度/固态硬盘章节），但 `parsed_options` 被批次内其他页的 SPOOLing 题目选项污染。这是 Pipeline 的跨页选项提取 bug。

**操作**：
1. 删除 5 条污染记录（ids 429-433）
2. 重新导入对应的 4 个页面（461、462、464、465 — 463 已在重导入中正确导入）
3. 验证选项与题干匹配

**验证**：通过 OCR MCP 抽样核验，选项与原始页面一致。

---

## 代码修改总结

| 文件 | 修改 | 原因 |
|------|------|------|
| `app/core/ocr_types.py` | 添加 `boxes` 字段到 `OcrPageResult` | Legacy OCR 路径缺失 `boxes` 参数 |
| `app/features/ocr_fix/interfaces.py` | 添加 `source` 字段到 `OCRFixResult` | OCRFixRouter 访问 `result.source` 时 AttributeError |
| `app/features/pipeline_orchestrator.py` | 修复 `_merge_cross_page_blocks` 异常分支元组长度 | 跨页检测失败时 ValueError |
| `app/features/pipeline_orchestrator.py` | 添加 `logger.exception` | 增强错误诊断 |

---

## 已知问题

1. **10 道主观题**：OCR 输出中未识别到标准 A/B/C/D 选项，标记为 `subjective`。需人工审核补全。
2. **3 道 NULL 页面题**：原始导入中 `source_page_start` 为 NULL，可能是 Pipeline 跨页合并产生的孤儿题。存在于 `question_imports` 中但未关联页面。
3. **72 页有 2+ 题目**：部分页面的 OCR 输出被 Pipeline 拆分为多题，或该页确实有多个题目。需人工确认。
4. **答案全部缺失**：原 PDF 为习题集（不含答案），所有题目 `answer_status=missing`。
5. **OCR 非确定性**：远程 PaddleOCR GPU 对相同页面多次调用可能返回不同结果（已验证）。所有题目均使用单页独立 OCR，避免跨页交叉污染。

---

## 恢复方式

如需回滚至原始状态：
```bash
sqlite3 backend/postgraduate.db ".restore artifacts/operating-system-import/backups/pre_import_backup.db"
```

如需查看待审核题目：
```bash
sqlite3 backend/postgraduate.db "SELECT id, source_page_start, question_type, substr(json_extract(parsed_content,'$.text'),1,50) FROM question_imports WHERE status='pending' LIMIT 20;"
```
