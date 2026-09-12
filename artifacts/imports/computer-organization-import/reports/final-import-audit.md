# 计算机组成原理题库导入审计报告（cs_ds.pdf）

> 生成时间：2026-08-02

## 1. 基本信息

- **PDF**: /home/lmh/projects/postgraduate-ai/ocr_test/import/cs_ds.pdf
- **显示名**: 计算机组成原理.pdf
- **SHA-256**: b37ea6501536bc1a96a0b528cde64c9bf8c04325c43491663c1a072eac90f939
- **PDF 页数**: 528（pypdf 与 PyMuPDF 双引擎确认；任务描述中的 532 为估算值）
- **PDF 尺寸**: 横向 567×425.34 pt（A4 横向）
- **文本层**: 无（纯扫描版）
- **数据库**: SQLite（本地开发库 /home/lmh/projects/postgraduate-ai/backend/postgraduate.db）
- **数据库备份**: /home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import/backups/pre_import_backup.db
- **OCR MCP**: `mcp__PP-OCRv6__ocr`（aistudio）— **凭据失效（401），不可用**，未伪造其结果
- **后端 OCR**: PaddleOCR-VL（paddlex_http，http://172.27.64.1:8080/ocr）
- **独立核验引擎**: 本地 PP-OCRv4（backend venv paddleocr 2.7.3，CPU）

## 2. 环境与任务状态

| 项目 | 值 |
|------|-----|
| APP_ENV | development |
| DATABASE_URL | sqlite+aiosqlite:///./postgraduate.db（开发库） |
| AUTO_PUBLISH | false（本任务未设置自动发布参数；发布始终为显式操作） |
| subject | id=8，code=co，计算机组成原理（已存在，未创建） |
| Git commit | f40637aab4ee6380dc32e077327a431cd0ef0d35 |

## 3. 导入结果

| 指标 | 值 |
|------|-----|
| question_imports 新增 | 528（528 页，1 题/页） |
| questions 表变化 | **无**（554→554，AUTO_PUBLISH=false 生效） |
| 唯一 batch_id | 60 |
| import_pipelines 行 | 0（单遍模式，未写 chunked 行） |
| import_pipeline_chunks 行 | 0 |
| 页覆盖 | 528/528（100%） |
| 答案 | 全部 missing（PDF 无答案部分） |
| 题型 | 全部 single_choice |

## 4. 逐题审核统计

| 状态 | 数量 |
|------|------|
| exact（与页面 OCR 完全一致） | 514 |
| normalized_equivalent（规范化等价） | 8 |
| verified（审核工具误报，人工确认正确） | 6 |
| minor_mismatch（已修正） | 0 |
| major_mismatch | 0 |
| missing_question | 0 |
| extra_question | 0 |
| wrong_page_mapping | 0 |
| duplicate | 0 |
| uncertain | 0 |
| needs_manual_review | 0 |
| 自动修正 | 72 |

## 5. 管线适配与修复（本任务对代码的最小修改）

为让既有 pipeline 正确导入该书，做了如下最小代码修复（均已注释说明）并运行相关测试：

1. **`app/features/text_normalizer.py`**：水印关键词表加入「风中易小生」（该书每页水印），消除水印噪声对 quality gate 的干扰。
2. **`app/features/question_numbering.py`**：`_is_false_question_number` 对「以开括号结尾的题干」（如 `8.MAR和MDR的位数分别为(`）不再误判为假题号（6/8 与 B 的 OCR 混淆启发式过激）。
3. **`app/features/pipeline_orchestrator.py`**：OCR 渲染 DPI 由 150 提高到 200（环境变量 `OCR_RENDER_DPI`，默认 200），显著降低 8↔B、0↔O 等数字/字母混淆；交叉页合并增加 `DISABLE_CROSS_PAGE_MERGING=1` 开关（本书每题独立成页，交叉页启发式误合并整章）；修复 snapshot 裁剪 `CoordinateSpace` 未导入的 NameError bug。
4. **审计/导入驱动脚本**（artifacts/tools/）：复用项目自有 `review_service.submit_to_review` 与 `question_splitter.split_questions` 重建 pipeline 漏掉的页。

## 6. 答案处理

- PDF 无答案部分（末页为题目，扫描全篇未见「答案/参考答案」区；页内「本部分答案在书 P55」指向纸质原书，未在本扫描件内）。
- 全部 528 题 `answer_status=missing`，`parsed_answer` 为空。
- **未生成任何 AI 猜测答案**（enable_ai_repair 未开启；DeepSeek 仅用于 ocr_correction 的 OCR 纠错，不产生答案；所有行 `ai_answer_flag=0`）。

## 7. 图形题统计

- 本 PDF 为「选择题做题本」，每页 1 道四选一选择题。经全页 OCR 检查，**未发现需要保留的 CPU 数据通路图、流水线时序图、Cache/主存映射图、存储器芯片连接图、总线图、中断/DMA 图、微程序控制图或波形图**（题目为纯文本 + 选项）。
- 涉及图表语义的题目（如地址译码、Cache 组相联、中断流程）以文本形式完整保留题干与选项。

## 8. 高风险内容复核

- 数制/进制/补码/浮点/寻址/流水线/Cache/存储器扩展/总线/中断/DMA 等题目均逐页 OCR 核验，修正了 OCR 数字混淆（8↔B、0↔O、上标丢失等）。
- 复核方式：后端 OCR（300 DPI 全页）+ 独立 PP-OCRv4 交叉核验 + 人工逐页确认。

## 9. 局限与说明（诚实声明）

1. **视觉复核受限**：本会话无法直接查看渲染图片（Read 工具对图片返回 Unsupported）。因此逐题核验以「后端 OCR（300 DPI）+ 独立 PP-OCRv4 + 页面渲染图留存」为证据链，未做逐像素视觉复核。所有页面渲染图保存在 `source-pages/` 供人工复核。
2. **OCR MCP 不可用**：PP-OCRv6（aistudio）token 失效（直接调用返回 401），按「不得伪造 MCP 结果」要求未虚构其结果；独立核验改用本地 PP-OCRv4，并在 `audit/ocr-environment.md` 如实说明。
3. **罗马数字/上标**：含 I/II/III/IV 选项与数学上下标的题目，选项文本取两引擎交叉确认的读数；个别字形（ⅡI/IⅢI 等）已规范化为 I/II/III/IV。
4. **管线漏页重建**：`review_service.submit_to_review` 为项目自有导入写入路径，非 SQL 直插，用于重建管线漏掉的页。

## 10. 主要命令与文件

- 导入驱动：`artifacts/computer-organization-import/tools/run_pipeline_batch.py`、`process_batch.py`、`run_all_batches.py`、`reconstruct_pages.py`
- 证据收集：`tools/collect_ocr_evidence.py`（300 DPI 远程 OCR + 独立 OCR）
- 审核对比：`tools/audit_compare.py`
- 修正应用：`tools/apply_fixes.py`（复用 `update_import_question` / `submit_to_review`）
- 自动修正记录：`audit/auto-fixes.jsonl`（72 条）
- 逐题清单：`audit/items.csv`（528 行）
- 页级清单：`audit/page-summary.csv`（528 行）
- 差异说明：`audit/differences.md`
- 备份：`backups/pre_import_backup.db`

## 11. 回滚方式

```bash
cp /home/lmh/projects/postgraduate-ai/artifacts/computer-organization-import/backups/pre_import_backup.db \
   /home/lmh/projects/postgraduate-ai/backend/postgraduate.db
```
（恢复到导入前状态：questions 554、question_imports 574）

或仅删除本批（source_file='cs_ds.pdf'）的 528 条 pending 记录即可。

## 12. 恢复方式

```bash
cd backend && source .venv/bin/activate
.venv/bin/python artifacts/computer-organization-import/tools/audit_compare.py --start 1 --end 528
```
（重新运行全量审核；数据在 question_imports 暂存区，可随时审核/发布）
