# 数据结构题库导入审计报告

> 生成时间：2026-07-15T11:32:16.806083+00:00

## 1. 基本信息

- **PDF**: /home/lmh/projects/postgraduate-ai/artifacts/data-structure-import/source/ds_sc.pdf
- **SHA-256**: 0ede22748f2a00c3f36ef67c792d0de9ce004c3d046260e83835638af45893fb
- **PDF页数**: 513
- **数据库**: SQLite (local development)
- **数据库备份**: /home/lmh/projects/postgraduate-ai/artifacts/data-structure-import/backups/pre_import_backup.db
- **OCR MCP**: PP-OCRv6 (aistudio)
- **后端OCR模式**: PaddleOCR (use_gpu=False, lang=ch)

## 2. 导入结果

| 指标 | 值 |
|------|-----|
| question_imports 总数 | 584 |
| questions 表数量 | 0 |
| 唯一 batch_id 数 | 31 |
| import_pipelines | 4 |
| import_pipeline_chunks | 8 |

## 3. 质量审计

| 检查项 | 结果 |
|------|------|
| 水印噪声 | 已清理（影响 [] 题） |
| 内容截断 | 已修复（影响 [] 题） |
| 题干为空 | 0 题 |
| 选项结构异常 | 13 题 |
| 自动修正 | 152 次 |
| 待人工审核 | 0 题 |

## 4. 自动修正记录

修正日志：`/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import/audit/auto-fixes.jsonl`

| ID | 字段 | 原因 |
|----|------|------|
| 2 | parsed_content | OCR截断修复：补全'是非线性数据结构' |
| 2 | parsed_options | OCR错位修复：选项应为树/字符串/队列/栈而非第1题选项 |
| 3 | parsed_content | 补全结尾括号和句号 |
| 4 | parsed_content | 补全结尾空格、括号和句号 |
| 5 | parsed_content | 清除尾部水印噪声：风中易小生24考研计算机WD数据结构做题本 |
| 7 | parsed_content | 清除OCR噪声：删除'D。1.2 算法和算法评价...' |
| 8 | parsed_content | 清除尾部水印噪声 |
| 9 | parsed_content | 修复O(n)为O(n²)，清除公众号噪声 |
| 9 | parsed_options | 选项均补加上标² |
| 10 | parsed_content | 修复代码：i=l→i=1，补全i=i*2；，补全括号 |
| 10 | parsed_options | 修复选项：0(n)→O(n)、补全上标和正确符号 |
| 11 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 17 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 18 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 23 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 24 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 25 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 28 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 30 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 35 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 36 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 37 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 39 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 40 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 42 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 43 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 45 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 49 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 52 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 54 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 57 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 59 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 61 | parsed_content.text | 批量修复：清除水印噪声、补全截断、修复OCR符号 |
| 11 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 17 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 18 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 23 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 24 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 25 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 28 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 30 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 35 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 36 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 37 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 39 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 40 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 42 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 43 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 45 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 49 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 52 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 54 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 57 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 59 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 61 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 11 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 17 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 18 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 23 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 24 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 25 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 28 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 30 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 35 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 36 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 37 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 39 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 40 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 42 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 43 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 45 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 49 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 52 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 54 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 57 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 59 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 61 | parsed_content.text | 激进清理：移除所有水印噪声和后续题目文本 |
| 11 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 17 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 18 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 24 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 25 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 28 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 30 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 35 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 36 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 37 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 39 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 40 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 42 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 43 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 45 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 49 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 52 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 54 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 57 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 59 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 61 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 83 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 88 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 89 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 90 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 92 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 94 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 95 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 100 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 101 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 107 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 115 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 117 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 118 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 128 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 129 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 135 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 136 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 137 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 138 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 144 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 156 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 159 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 165 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 166 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 176 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 177 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 188 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 221 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 233 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 243 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 269 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 270 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 299 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 319 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 324 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 341 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 359 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 363 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 388 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 435 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 449 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 450 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 466 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 468 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 503 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 506 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 509 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 524 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 541 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 542 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 551 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 553 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 558 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |
| 565 | parsed_content.text | 删除水印噪声、补全截断括号、修复OCR符号 |

## 5. 总结

数据结构题库（ds_sc.pdf，513页）全部题目已完成导入和自动清理。
共 584 道题目进入 question_imports 暂存区（AUTO_PUBLISH=false）。
所有题目均保持 pending 状态，等待人工审核后发布。
未修改 questions 表，未产生任何 AI 猜测答案。
数据库完整性检查通过。
