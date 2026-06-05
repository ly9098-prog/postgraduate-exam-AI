------

# OCR Pipeline 数据生命周期审计与流式架构改造

请先进行架构审计，不要直接修改代码。

> ## 当前进度（2026-06-05）
>
> - [x] **审计阶段**：完成 → `docs/audit/ocr-pipeline-lifecycle-audit.md`
> - [x] **P0-2 区域检测 OCR 工作量降为 1/N**：完成
>   - `EXERCISE_DETECTION_SAMPLE_STEP=3` 默认采样
>   - lightweight OCR 工作量降为 1/3（**注意：这不是"消除双 OCR"** ——
>     区域检测仍是独立扫描，全量 OCR 仍从零开始；实际链路为
>     `lightweight 1/N + full(region)`，最优场景 33% + 部分页，
>     最坏场景 33% + 100%。task 文档原"消除双 OCR"措辞夸大，已修正。）
>   - region 边界 ±(step-1) 扩展 + 重叠合并
>   - max_empty_pages 在采样模式下自动放大
>   - **漏检 fallback 保护（P0 隐患修复 2026-06-05）**：当 `step>1` 检测
>     一无所获时，先退化到 `step=1` 重新探测一次再决定是否走全本 OCR。
>     避免王道教材关键词恰好落在跳过页时，整体工作量比不开检测更高。
>   - 39 个 detector 测试通过（含 7 个新增采样模式测试）
> - [x] **P0-1 PDF 字节落盘 + 闭包不持有**：完成
>   - API 入口 `_run_pipeline_with_db`：`tempfile.mkstemp` 落盘后 `del file_content`，`finally` 块 `os.unlink`
>   - 链路改造：`run_pipeline_background` / `run_import_pipeline` / `ImportPipeline.run` 接受 `file_path`
>   - 底层 `_open_pdf_doc` 统一处理 bytes/path，path 走 `fitz.open(filename)` 即 mmap
>   - `_extract_pdf_blocks` / `_ocr_scanned_pdf` / `_extract_text_blocks` / `detect_exercise_regions_from_pdf` / `_lightweight_page_ocr` 全部接受 `bytes | str`
>   - extract 完成后 `data.pop("file_content")` 和 `data.pop("file_path")`，避免后续 8+ 个 stage 持有引用
>   - 82 个相关测试通过（detector 39 + orchestrator 43），新增/已有功能均无回归
> - [x] **P0-3 `_pipeline_store` 瘦身 + diagnostics 单独存**：完成
>   - 主 store 仅保留 `_PIPELINE_STORE_FIELDS` 白名单（pipeline_id/status/source_type/source_file/current_stage/stages/stats/errors/started_at/finished_at/batch_id/raw_text_preview/question_count）
>   - 新增 `_pipeline_diagnostics_store` 内存字典 + Redis key `import:pipeline:diagnostics:{id}`，TTL 24h 与主 store 同步
>   - `_set_pipeline_store` 自动剥离 `data["diagnostics"]`，主 store / Redis 不再写大字段
>   - `_prune_store` 同步淘汰 diagnostics 内存条目，不留泄漏
>   - `get_pipeline_status` 把 diagnostics 合并回完整视图，前端无感
>   - 新增 3 个 P0-3 单元测试：strip / merge-back / prune-sync
>   - 108 个相关测试通过（pipeline_orchestrator + pipeline_upload_unified + image_import_status + exercise_region_detector），无新增回归
> - [x] **P0 隐患修复（2026-06-05 审计后）**：完成
>   - **隐患 2 修复**：`get_pipeline_status` 改为返回 `dict(data)` 防御性拷贝。
>     之前实现里 `data["ocr_progress"] = ...` 会污染 `_pipeline_store[pid]`
>     引用，破坏白名单契约。新增 `test_status_query_does_not_pollute_main_store`
>     断言主 store 字段始终是 `_PIPELINE_STORE_FIELDS` 子集。
>   - **隐患 1 修复**：见上方 P0-2 fallback 保护 + 命名修正。
> - [x] **P1-A stage 间清理 data 大字段**：完成
>   - `ImportPipeline.run` 主循环按数据生命周期 pop：
>     - `extract` 后：`file_content` / `file_path`（已有，P0-1）
>     - `normalize_text` 后：`raw_blocks`
>     - `match` 后：`normalized_blocks`（保留 `normalized_block_count` 给 stats 兜底）
>     - `normalize_schema` 后：`raw_questions` / `matched` / `unmatched`
>   - 终极效果：进入 `repair` / `ai_validation` / `similarity_match` / `review`
>     的 `data` 只剩 `questions` 一份大对象，其它阶段间产物全部释放。
>     400 页扫描 PDF 场景下，OCR 后的 `normalized_blocks`（含 boxes）
>     单独可达 50~200 MB，是仅次于 PDF 字节的内存大头。
>   - 新增 `test_p1a_large_fields_released_between_stages`：用 review 阶段
>     做哨兵，断言 review 收到的 kwargs 里不再含 raw_blocks / normalized_blocks /
>     raw_questions / matched / unmatched，且 stats.normalized 计数仍正确。
>   - 110 个相关测试通过（pipeline_orchestrator + pipeline_upload_unified +
>     image_import_status + exercise_region_detector），无新增回归。
> - [x] **P1-B review 阶段分批 commit**：完成
>   - `submit_to_review` 每 `_REVIEW_COMMIT_BATCH_SIZE=50` 道题做一次
>     `commit() + expunge_all()`，把 QuestionImport ORM 对象从 session
>     identity map 中放出来，让 GC 能回收 `raw_data` / `parsed_content` 等
>     dict（一道题约 5~30 KB，400 道累积可达 12 MB）。
>   - 收尾逻辑：尾部不满 batch 时再 commit 一次 + expunge；恰好整数倍时
>     再调一次 commit 关闭事务（无新对象，对 SQLAlchemy 是 no-op）。
>   - `seen_hashes` 只存 `hash → int`，跨 batch 不持有 ORM 引用。
>   - **未做 raw_data 瘦身**：raw_data 被 question_publish_service /
>     ai_import_helpers / import_service 多处读取，瘦身需要全链路兼容
>     评估，留到后续单独处理。
>   - 新增 2 个 P1-B 测试：105 道题断言 3 次 commit + 3 次 expunge_all；
>     恰好 50 道断言 2 次 commit（一次满 batch + 一次空收尾）+ 1 次
>     expunge_all。
>   - 144 个相关测试通过（review_service + pipeline_orchestrator +
>     pipeline_upload_unified + image_import_status + exercise_region_detector），
>     无新增回归。
> - [x] **P1 阶段审计后隐患修复（2026-06-05）**：完成
>   - **隐患①修复**：`pipeline_orchestrator.py` `stats["normalized"]` 在
>     `match` 之前的 stage（如 `analyze_structure`）失败时静默归零。
>     根因：原 fallback 链 `normalized_count → normalized_block_count →
>     len(normalized_blocks)`，前两者由 `normalize_schema` / `match` 后才
>     写入，中段失败时全部缺失，第三层在 `normalized_blocks` 已被 pop
>     的情况下永远是 0。
>     修复：每次 stage 写入 `normalized_blocks` 都同步缓存
>     `normalized_block_count`；fallback 兜底改为 `0` 而非
>     `len(已 pop 字段)`。
>     新增 `test_p1a_stats_normalized_survives_mid_pipeline_failure`：
>     断言 `analyze_structure` 失败后 `stats["normalized"]` 仍为 3。
>   - **隐患③修复**：`review_service.submit_to_review` 用
>     `db.expunge_all()` 会把整个 session 中所有 ORM 实例（包括上层调
>     用方 attach 的 watermark 规则、user 等）一并踢掉。
>     修复：维护本批 `pending_qis: list[QuestionImport]`，commit 后
>     逐条 `db.expunge(qi)`；commit 完成即 clear，避免持有引用。
>     更新两个 P1-B 测试：`expunge` 调用次数 = 写入题数；
>     `expunge_all` 不再被调用；按写入顺序断言 expunged_ids。
>   - **隐患②修复**：分批 commit 中途崩溃会留下孤儿 `batch_id` 记录
>     （前面已 commit 50 道，第二批失败后剩半截数据）。
>     修复：把整段写入循环包到 try/except，捕获异常后先 `db.rollback()`，
>     再 `DELETE FROM question_imports WHERE batch_id = ?` 做 best-effort
>     清理，最后 `raise` 把原始异常抛给调用方。任意一步清理失败只记
>     `logger.exception`，不掩盖原始异常。
>     新增 `test_p1b_mid_batch_failure_cleans_orphan_batch`：mock 第二
>     次 commit 抛错，断言 rollback 调用一次 + 触发一次 Delete 语句 +
>     RuntimeError 向上传播。
>   - 146 个相关测试通过（1 个 deselected 是 P0 阶段已存在失败，与本
>     次修复无关）。
> - [ ] **P2 region 流式编排 + 断点恢复**

## 项目背景

这是一个考研408题库导入系统。

主要导入来源：

- 扫描版PDF（核心场景）
- 批量图片导入
- Excel导入

典型文件：

- 王道408教材
- 王道习题册
- 历年真题扫描版

文件规模：

- 100~400页
- 绝大部分为扫描图片页
- 非文本PDF

当前问题：

- OCR耗时较长
- 长文档导入容易超时
- WSL环境导入大文件时出现崩溃
- 怀疑存在内存持续增长问题
- 怀疑Pipeline中存在大量中间结果长期驻留内存

未来目标：

- 稳定支持400页扫描版PDF
- 未来可扩展到1000页
- 内存占用尽量与页数无关
- 支持低配置服务器运行

------

# 核心审计目标

不要优先关注OCR识别率。

优先分析：

**当前Pipeline的数据生命周期(Data Lifecycle)是否合理。**

重点回答：

> 一页PDF数据从生成到最终入库，经历了哪些阶段？
>
> 哪些数据被长期保存在内存中？
>
> 哪些中间结果实际上已经可以提前释放？
>
> 哪些模块会导致内存随页数线性增长？

------

# 请绘制当前Pipeline

分析当前真实执行链路：

```text
PDF
↓
PDF解析
↓
OCR
↓
Normalize
↓
Structure Analysis
↓
Question Split
↓
AI Correction
↓
Question Object
↓
Database Save
```

明确说明：

每个阶段输入什么

输出什么

数据量大概多大

生命周期持续多久

------

# 数据生命周期审计

重点检查：

## 1. PDF页面生命周期

检查：

当前是否：

```python
pages = load_all_pages()
```

或者：

```python
images = convert_all_pages()
```

分析：

- PDF是否一次性全部加载
- 是否一次性生成全部图片
- 图片对象何时释放

评估：

400页扫描PDF场景下的风险。

------

## 2. OCR结果生命周期

检查：

是否存在：

```python
all_ocr_results.append(...)
```

或者：

```python
ocr_blocks = [...]
```

长期累积。

分析：

- OCR结果大小
- bbox数据大小
- layout数据大小
- 是否会随着页数持续增长

输出内存风险评估。

------

## 3. Normalize阶段

检查：

是否存在：

```python
normalized_blocks
```

作为新的完整数据副本。

分析：

- 是否复制全部OCR结果
- 是否形成第二份大对象

------

## 4. Structure Analysis阶段

检查：

是否生成：

```python
analyzed_blocks
```

并长期保留。

分析：

是否形成第三份大对象。

------

## 5. AI Correction阶段

重点审计。

检查当前是否：

```python
全部OCR完成
↓
全部AI纠错
```

还是：

```python
OCR一页
↓
AI纠错一页
```

分析：

- Token消耗
- 内存占用
- 响应时间
- 异常恢复能力

------

## 6. Question Split阶段

检查：

是否：

```python
questions = []
```

持续累积所有题目。

分析：

400页文档情况下：

- Question对象数量
- 内存占用
- 生命周期

------

## 7. 数据库存储策略

检查：

当前是否：

```python
全部处理完成
↓
统一写库
```

还是：

```python
处理一批
↓
写库一批
```

分析：

SQLite与PostgreSQL下的表现差异。

------

# 查找生命周期过长的数据

请列出：

| 对象 | 来源 | 大小 | 当前释放时机 | 是否可提前释放 |
| ---- | ---- | ---- | ------------ | -------------- |
|      |      |      |              |                |

例如：

- PDF图片
- OCR结果
- Normalize结果
- Structure结果
- AI纠错结果
- Question对象

找出：

生命周期最长的Top10对象。

------

# 查找内存增长风险

重点搜索：

```python
append(
extend(
all_results
all_pages
all_questions
cache
buffer
```

分析：

哪些容器会随着页数无限增长。

------

# Generator/Yield机会分析

检查：

哪些代码：

```python
return full_results
```

适合改成：

```python
yield page_result
```

列出：

- 高收益改造点
- 中收益改造点
- 不建议改造点

------

# 流式Pipeline设计

如果发现问题，请设计新的架构：

```text
PDF

↓ 逐页读取

Page

↓ OCR

OCR Result

↓ AI Correction

Corrected Result

↓ Question Parse

Question

↓ Database Save

Commit

↓ Memory Release

Next Page
```

或者：

```text
20页批处理

↓ OCR

↓ AI Correction

↓ Parse

↓ Save

↓ Release
```

说明：

为什么选择该方案。

------

# 断点恢复能力

分析：

当前导入过程中：

如果第287页失败：

是否需要重新处理1~286页？

设计：

```text
导入任务
↓
记录已完成页码
↓
失败
↓
从失败页恢复
```

方案。

------

# 输出要求

请输出：

## 1. 当前架构图

## 2. 数据生命周期分析

## 3. 内存风险分析

## 4. 生命周期最长对象分析

## 5. 流式改造方案

## 6. Generator/Yield改造建议

## 7. 数据库存储优化建议

## 8. 断点恢复方案

## 9. 实施优先级

请先完成审计报告，不要修改代码。

------

