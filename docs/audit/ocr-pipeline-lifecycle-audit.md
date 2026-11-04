# OCR Pipeline 数据生命周期审计报告

> 审计任务：`prompts/tasks/current-task.md` — OCR Pipeline 数据生命周期审计与流式架构改造
> 审计日期：2026-06-05
> 审计范围：`backend/app/features/pipeline_orchestrator.py` + 上游 OCR/解析/AI/入库链路
> 审计目标：定位长文档导入崩溃、内存持续增长、生命周期过长的对象，提出流式改造方案
> 性质：架构审计，**未修改代码**，等待实施授权

---

## 1. 当前架构图

### 1.1 真实执行链路

下面是 `ImportPipeline.run()` 的实际链路（`pipeline_orchestrator.py:931-1081`），按 PDF + OCR 路径展开：

```text
HTTP /pipeline/upload (imports.py:608)
  └─ background_tasks.add_task(_run_pipeline_with_db)
       └─ run_pipeline_background  → run_import_pipeline → ImportPipeline.run()

ImportPipeline.run() 串行执行 stages：

[1] extract                       _run_extract               (pipeline_orchestrator.py:360)
    ├─ _extract_pdf_blocks        (PyMuPDF 文本层提取)
    ├─ if total_text < 100 chars + OCR_ENABLED:
    │    ├─ EXERCISE_DETECTION_ENABLED:
    │    │    └─ detect_exercise_regions_from_pdf (72 dpi 全本轻量 OCR)
    │    │       └─ _lightweight_page_ocr  (exercise_region_detector.py:331)
    │    └─ for each region:
    │         _ocr_scanned_pdf   (150 dpi 全量 OCR, pipeline_orchestrator.py:122)
    │         ├─ for batch in pages:
    │         │    pix.tobytes("png")  → batch_images
    │         │    ocr_pages_with_boxes → results
    │         │    blocks.append({page,text,boxes,page_width,page_height})
    │         │    del batch_images; gc.collect()
    │         └─ return blocks
    └─ data["raw_blocks"] = blocks      ← 第 1 个长生命周期大对象

[2] (可选) wangdao_preprocess        水印/页眉过滤
[3] normalize_text                   ImportTextNormalizer.normalize
    └─ data["normalized_blocks"] = [...]  ← 第 2 个大对象副本（保留 boxes）

[4] (可选) ocr_correction            AI OCR 文本纠错（异步并发 3 路）
    └─ data["normalized_blocks"] = corrected_blocks  ← 第 3 个大对象副本（dict(block)）

[5] analyze_structure                结构分析（mode/answer_pages/section_markers）
    └─ data["structure"] = {...}     ← 不大，但持有 section_markers 列表

[6] classify_pages                   页面分类（QUESTION_PAGE / ANSWER_PAGE / ...）
    └─ data["normalized_blocks"] = filter_blocks_by_classification(...)
        ← 第 4 个 list 副本（仍保留 boxes 字段）

[7] split                            题目切分
    ├─ "\n".join(parts)  ← 全文一次性拼接成 full_text
    ├─ _find_question_boundaries(full_text)
    └─ data["raw_questions"] = [...]   ← 第 5 个大对象（每题含 raw_question_text）
       含 split_diagnostics["raw_questions_preview"][:20] 仍引用前 20 题

[8] match                            答案匹配（INLINE/SEPARATED）
    ├─ for each q: _collect_page_text(blocks, answer_pages)  ← O(N²) 字符串拼接
    └─ data["matched"] = [...]

[9] normalize_schema                 题目标准化（题型/置信度/hash）
    └─ data["questions"] = [...]   ← 第 6 个大对象（含 raw_text 字段）

[10] batch_validation                跨题完整性检查
[11] (可选) batch_dedup              批内 stem_hash 去重标记
[12] (可选) repair                   AI 修复（并发 3 路 DeepSeek 调用）
[13] (可选) ai_validation
[14] (可选) similarity_match         O(K×N) 相似度匹配（全 subject 题库 difflib）
[15] review                          submit_to_review
    ├─ for each q: db.add(qi); await db.flush()
    └─ await db.commit()             ← 单事务一次性 400+ 题

最后：return result（含 stages, stats, diagnostics, errors）
   ↓
run_pipeline_background 把整个 result 写入 _pipeline_store + Redis
   _PIPELINE_STATUS_TTL = 24 h
   _MAX_STORE_SIZE = 500
```

### 1.2 阶段关键属性表

| 阶段 | 输入 | 输出 | 输出规模（400页扫描PDF） | 同步/异步 |
|------|------|------|--------------------------|-----------|
| extract | `bytes`（整本PDF, 100~400 MB） | `raw_blocks: list[dict]` | ~400 dict, 含 `text`+`boxes`+尺寸; 单 dict 50–200 KB（boxes 占大头）| 阻塞线程，via `asyncio.to_thread` |
| wangdao_preprocess | raw_blocks | filtered raw_blocks | ≈ 减 5–10% | 同步 |
| normalize_text | raw_blocks | normalized_blocks（**新对象列表**，保留 boxes） | 与 raw_blocks 同量级 | 同步 |
| ocr_correction | normalized_blocks | corrected_blocks（`dict(block)` 浅拷贝 + 文本替换） | 又一份 | async + DeepSeek API |
| analyze_structure | normalized_blocks | structure dict | 小 | 同步 |
| classify_pages | normalized_blocks | filter 后的 list | 小 5%–30% | 同步 |
| split | normalized_blocks | raw_questions（含原文片段 + option_lines） | ~300–500 题 × 数 KB | 同步 |
| match | raw_questions + normalized_blocks | matched list | 与题数同量级 | 同步 |
| normalize_schema | raw_questions + matched | questions（含 raw_text、stem、options、analysis） | 与题数同量级 | 同步 |
| repair | questions | questions（替换部分项的 after） | 与题数同量级 | async + DeepSeek（并发 3） |
| similarity_match | questions | questions（附加 similarity_suggestion） | 与题数同量级，**额外加载全 subject 题库** | async + executor |
| review | questions | DB rows | N 行 question_imports，**单事务** | async + DB |

---

## 2. 数据生命周期分析

### 2.1 PDF 页面生命周期 ❶

证据：`pipeline_orchestrator.py:144`

```python
doc = fitz.open(stream=content, filetype="pdf")
total_pages = len(doc)
...
for batch_start in range(0, pages_to_process, batch_size):
    for i in range(batch_start, batch_end):
        pix = doc[page_idx].get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        ...
        del pix
        batch_images.append((page_idx + 1, png_bytes))
    results = ocr_pages_with_boxes(batch_images, skip_rotation=True)
    del batch_images
    gc.collect()
```

**评价**：

- ✔ 已经做到「批量 → OCR → 释放图像」，不存在一次性把 400 页全部转 png 留在内存的反模式。
- ✔ `pix` 用完即 `del`，PNG bytes 不复制成 PIL Image。
- ✘ **`content` 字节本身（整本 PDF）被 `fitz.open(stream=content)` 占用**，从 `_run_pipeline_with_db` 进入到 `submit_to_review` 完成都不释放（`imports.py:761`）。400 MB 的扫描版 PDF 全程驻留。
- ✘ EXERCISE_DETECTION_ENABLED 路径上同一份 `content` 被 `fitz.open` 两次（先 `_lightweight_page_ocr` 72 dpi，再 `_ocr_scanned_pdf` 150 dpi），等于**全本扫描 OCR 跑两遍**。

### 2.2 OCR 结果生命周期 ❷

证据：`pipeline_orchestrator.py:153,193`

```python
blocks: list[dict] = []
...
blocks.append({
    "page": page_idx,
    "block_index": len(blocks),
    "text": text,
    "boxes": results[page_idx].boxes,      # ← 每行一个 dict (bbox+conf)
    "page_width": pw,
    "page_height": ph,
})
```

`boxes` 字段出处 `ocr_service.py:461`：每一行 OCR 都生成 `{"bbox":[x0,y0,x1,y1], "conf":float}`。一个 A4 页通常 30–60 行，整页 boxes ~ 1.5–6 KB；400 页累计 ~ 0.6–2.4 MB（不算 text）。整列表里加上 `text`（每页 ~ 1–4 KB）和 `raw_text`（normalize 阶段会复制一份），到 normalized_blocks 已经在 4–10 MB 量级。

**关键问题**：从 `extract` 结束起，`raw_blocks` 一直挂在 `data` 里直到 `run()` 返回（之后才被 GC），跨越 8+ 个阶段。

### 2.3 Normalize 阶段 ❸

证据：`text_normalizer.py:70`

```python
def normalize(self, raw_blocks):
    normalized = []
    for i, block in enumerate(raw_blocks):
        ...
        out = {
            "page": block.get("page", 1),
            "block_index": ...,
            "raw_text": text,            # ← 保留了一份原文
            "normalized_text": cleaned,  # ← 又一份清洗后的
        }
        if "boxes" in block: out["boxes"] = block["boxes"]   # 共享引用
        ...
        normalized.append(out)
    return normalized
```

**评价**：
- `boxes` 是共享引用（不深拷贝），不成倍占内存。
- 但同时持有 `raw_text` + `normalized_text` 两份字符串，且 `raw_blocks` **没有被替换/释放**，`data` 里既有 raw_blocks 又有 normalized_blocks → 第二份大对象副本。

### 2.4 Structure Analysis 阶段 ❹

证据：`structure_analyzer.py`

`analyze_structure` 输出的 `structure` dict 比较小（mode/page 列表/section_markers），不构成内存压力。但 `section_markers` 内会存 `text[:60]` 片段，N 个标记 = 几 KB，无视。

### 2.5 AI Correction 阶段 ❺

证据：`ocr_correction.py:223,293`

```python
corrected_blocks: list[dict] = [None] * len(normalized_blocks)
...
new_block = dict(block)              # ← 浅拷贝（boxes 共享）
new_block["normalized_text"] = corrected_text
corrected_blocks[idx] = new_block
```

**模式**：`OCR 全部完成 → AI 全部纠错（并发 3）` ，**不是逐页纠错**。

**评价**：
- 浅拷贝＋仅替换 normalized_text，内存增量较小。
- ✘ 但 `data["normalized_blocks"]` 在阶段 6 (classify_pages) 又被 `filter_blocks_by_classification` 替换成 **第 4 份列表副本**（page_classifier.py:315 的列表推导）。
- ✘ 此时旧的 `corrected_blocks` 还被 `ocr_correction_diagnostics["corrections"]` 间接引用（每条 correction 含 page/block_index/score）。

### 2.6 Question Split 阶段 ❻

证据：`question_splitter.py:436`

```python
full_text = "\n".join(parts)         # ← 全文一次性拼接
boundaries = _find_question_boundaries(full_text)
...
for i, (num, start_pos) in enumerate(filtered_boundaries):
    end_pos = filtered_boundaries[i + 1][1] if ... else len(full_text)
    raw_text = full_text[start_pos:end_pos].strip()   # ← 切片产生独立 str
    ...
    questions.append({...})
```

**评价**：
- ✘ `full_text` 是一份 N 页文本的合并字符串（400 页 ~ 1–4 MB）。函数返回后 `full_text` 离开作用域，但每个 question 的 `raw_question_text` 都是独立切片字符串，**总和与 full_text 同量级**。
- ✘ orchestrator `_run_split` 把 `raw_questions[:20]` 放进 `split_diagnostics["raw_questions_preview"]`（pipeline_orchestrator.py:606），随 result 一起进入 Redis/`_pipeline_store`，**24 小时驻留**。

### 2.7 数据库存储策略 ❼

证据：`review_service.py:140-213`

```python
dup_questions = await _batch_find_duplicate_questions(db, subject_hash_pairs)  # 1 次查询
dup_imports   = await _batch_find_duplicate_imports(db, subject_hash_pairs)    # 1 次查询

for q, stem, parsed_options, qi_subject, question_hash in prepared:
    qi = QuestionImport(..., raw_data=q, ...)
    db.add(qi)
    await db.flush()                 # ← 每题 flush 一次

await db.commit()                    # ← 全 batch 一次性 commit
```

**评价**：
- ✔ 重复检测做了两次 batch 查询，不是 N+1。
- ✘ 整个流程**一个事务**：从 review 阶段开始到全部 add 完才 commit。SQLite WAL 模式下 commit 之前 .db-wal 文件持续膨胀；PostgreSQL 下长事务会卡 vacuum 与 checkpoint。
- ✘ `raw_data=q` 把整道题（含 raw_text、analysis、warnings）以 JSON 序列化进 `question_imports.raw_data` 字段，每题 1–4 KB，N 题 = 数 MB 写入。
- ✘ 任意一题失败回滚 → 全 batch 丢失，但又没有 page-level checkpoint 可恢复。

---

## 3. 内存风险分析

### 3.1 「当前已经做对的事」

| 项 | 位置 | 评价 |
|---|---|---|
| OCR 批处理释放 | `pipeline_orchestrator.py:178-187` | `del pix` / `del batch_images` / `gc.collect()` 都到位 |
| 并发上限 | OCR 4 worker（local profile）/ AI 3 路 / 重复检测 chunk 500 | 上限合理 |
| 重复检测 batch 化 | `review_service.py:39-74` | 不是 N+1 |
| 流水线状态 LRU | `pipeline_orchestrator.py:50-58` | 500 条上限 + 按 started_at 淘汰 |

### 3.2 「会让内存随页数线性增长的容器」

| 容器 | 位置 | 增长曲线 | 风险等级 |
|---|---|---|---|
| `_run_pipeline_with_db` 闭包持有的 `file_content: bytes` | `imports.py:761` | O(file_size)，整流程不释放 | **P0** |
| `data["raw_blocks"]` | `pipeline_orchestrator.py:993` | O(pages)，含 boxes | P1 |
| `data["normalized_blocks"]` | 同上 | O(pages)，与 raw_blocks 共存 | P1 |
| `data["raw_questions"]` | 同上 | O(questions)，含 raw_text 全文切片 | P1 |
| `data["matched"]` / `data["questions"]` | 同上 | O(questions) | P1 |
| `_run_split` 内 `full_text = "\n".join(parts)` | `question_splitter.py:436` | O(total_text)，瞬时翻倍 | P2 |
| `submit_to_review` 单事务 N 行 add+flush | `review_service.py:170-213` | DB-WAL O(questions) | P1 |
| `_pipeline_store` 24h × 500 条 result | `pipeline_orchestrator.py:42` | 500 × result_size，最坏 ~1.5 GB | **P0** |
| EXERCISE_DETECTION 重复 OCR | `pipeline_orchestrator.py:411-431` | O(pages) ×2 倍工作量 | **P0** |
| `similarity_matcher` 全 subject 题库一次性 load | `similarity_matcher.py:28-44` | O(题库大小)，每个 subject 一份 | P2 |
| `subject_cache` 跨题缓存 | `similarity_matcher.py:142` | 题库 ×subject 数 | P2 |
| OCR `_ocr_lock` 串行 + `with ThreadPoolExecutor(max_workers=4)` 并存 | `ocr_service.py:521` | 池启动多线程但锁让线程都等 ⇒ 实际并行度=1 | P3（性能问题，不是内存） |
| `_ocr_progress` dict | `pipeline_orchestrator.py:43` | O(并发 pipeline 数) | P3 |

### 3.3 WSL 崩溃假设

WSL 默认 `vm.swappiness=60`、不强制 OOM kill；扫描版 400 页 PDF 实测峰值（基于代码估算）：

```
file_content (PDF bytes)            ~  100–400 MB（整流程驻留）
PaddleOCR 模型                      ~  300 MB（singleton，不含进程基线）
_lightweight_page_ocr 中 PIL/np 临时 ~  50–100 MB（+ 短暂 batch_images）
_ocr_scanned_pdf 同时驻留：
   raw_blocks (boxes+text)          ~  4–10 MB
   normalized_blocks                ~  4–10 MB
   normalized_blocks 副本 (correct) ~  4–10 MB
   filtered normalized_blocks       ~  4–10 MB
   raw_questions                    ~  3–8 MB
   matched + questions              ~  3–8 MB
   full_text (split 临时)           ~  1–4 MB
result.diagnostics 各阶段           ~  1–3 MB
ocr_correction_diagnostics.corrections (每题一条) ~ 数百 KB
_pipeline_store 旧记录 (最多 500)    可达 1.5 GB
                                  ─────────
峰值预估                           450–800 MB（不算 PaddleOCR 模型）
```

如果 EXERCISE_DETECTION 触发，扫描阶段会再叠 1 次全本 OCR 工作量（虽然 lightweight 的 result 只保留 page_texts dict，~10–30 MB，但**总耗时翻倍 → 长时间高占用 → OOM 概率上升**）。

WSL 在 500 MB+ 持续占用下，page cache 压缩效率下降，gc 周期内会出现尖峰，触发 OOM-killer 或 process freeze。**与现象「WSL 大文件导入崩溃」吻合**。

---

## 4. 生命周期最长 Top10 对象

| 排名 | 对象 | 来源 | 大小（400页） | 当前释放时机 | 是否可提前释放 | 释放点建议 |
|---|---|---|---|---|---|---|
| 1 | `file_content: bytes` | `_run_pipeline_with_db` 入参 | 100–400 MB | 后台任务结束 | ✔ extract 完成后 | extract 结束后写到 tmp 文件，闭包不持有 bytes |
| 2 | `_pipeline_store[*].result` | `pipeline_orchestrator.py:42` | result 含 raw_questions_preview/diagnostics, 0.5–3 MB × 500 = 0.25–1.5 GB | 24h TTL | ✔ 立即剥离大字段 | 仅保留 stats/stages，diagnostics 移到独立 KV |
| 3 | `data["raw_blocks"]` | extract | 4–10 MB | run() 返回 | ✔ normalize 之后即可 | 阶段间清理（pop 上一阶段输入） |
| 4 | `data["normalized_blocks"]` | normalize_text | 4–10 MB | run() 返回 | ✔ split + match 完成即可 | match 后 pop |
| 5 | `data["raw_questions"]` | split | 3–8 MB | run() 返回 | ✔ normalize_schema 之后 | normalize_schema 后只保留 questions |
| 6 | `data["matched"]` | match | 1–3 MB | run() 返回 | ✔ normalize_schema 之后 | 同上 |
| 7 | `data["questions"]` | normalize_schema | 3–8 MB | review 完成 | 部分可 stream | review 内部分批发送 |
| 8 | `subject_cache` | similarity_matcher | 题库大小（按 subject） | similarity_match 阶段结束 | ✔ 阶段结束局部变量 | 已 OK |
| 9 | `ocr_correction_diagnostics["corrections"]` | ocr_correction | N 条 dict | 进入 result | ✔ 不必返回客户端 | 仅保 stats，corrections 落本地日志 |
| 10 | `split_diagnostics["raw_questions_preview"][:20]` | split | 数十 KB | result.diagnostics 24h | ✔ 改成 stem 摘要 | 改保存 stem[:80] 而非整 dict |

---

## 5. 流式改造方案

### 5.1 三种候选

#### 方案 A：完全单页流式（不推荐）

```text
PDF → 逐页 OCR → 单页 normalize → 单页 split → AI repair → DB save → 释放
```

**问题**：
- ✘ SEPARATED 模式答案在文档尾部，**单页阶段拿不到答案**（match_answers 需要 answer_pages 文本）
- ✘ 跨页选项恢复 `_recover_cross_page_options` 需要相邻题目同时在内存（splitter 设计依赖此）
- ✘ batch_dedup 跨整本去重，分页处理会失去全局视图
- ✘ exam mode 下题号连续性校验（batch_validation）按全本评估
- ✘ structure_analyzer 需要全文统计（题目密度、答案区识别）

**结论**：不能照搬到当前业务规则上。

#### 方案 B：双阶段流式（推荐）

```text
阶段 1：扫描-切分（按 region 或固定页窗）
  PDF + region 切片
    ↓ batch OCR (复用现有 _ocr_scanned_pdf)
    ↓ normalize_text
    ↓ analyze_structure（仅本 region）
    ↓ split + match（本 region 内）
    ↓ normalize_schema → questions[]
    ↓ checkpoint：questions 写 tmp jsonl + DB question_imports（事务=region）
    ↓ 释放 raw_blocks / normalized_blocks / raw_questions / matched
  next region

阶段 2：批后处理
  从 DB 加载本批所有 question_imports
    ↓ batch_dedup（基于 stem_hash，无需重读 OCR）
    ↓ AI repair（按需，分页）
    ↓ similarity_match
    ↓ 更新 DB 行
```

**收益**：
- ✓ 每个 region 处理完即释放 OCR 中间产物
- ✓ DB checkpoint 天然支持断点恢复（见 §8）
- ✓ AI repair / similarity_match 阶段可独立调度（不阻塞 OCR）
- ✓ 改动局限在 `ImportPipeline.run()` 编排层，子模块零改动

**风险**：
- batch_dedup 跨 region 后从 DB 读 stem_hash 而不是从 list（多 N 次查询，但 batch=500 已优化）
- structure_analyzer 仅看本 region → SEPARATED 模式可能误判 → 需要额外把 region 的 mode 提示传入

#### 方案 C：固定 20 页批处理（也可）

```text
20 页一批 → 同方案 B 流程 → 写库 → 释放
```

比方案 B 实现更简单（不依赖 exercise_region_detector），缺点是切到题目中间的概率较高，需要前后批之间做题号续接（_recover_cross_page_options 要跨批）。

### 5.2 推荐方案

**方案 B（按 exercise_region 分片）作为主路径，方案 C（固定 20 页）作为无 region 时的回退**。理由：

1. exercise_region_detector 已经存在并能定位习题区，复用零成本。
2. 王道教材结构清晰（每章一个 region），region 内题目数量可控（10–40 题）。
3. 试卷模式（exam mode）整本就是一个大 region，自动退化为方案 C 的等价。

### 5.3 改造代码骨架（仅示意，**未实施**）

```python
async def run_streaming(self, file_content, ...):
    regions = detect_or_fallback(file_content)  # 已存在
    summary_stats = {"total": 0, "to_review": 0, ...}

    for region in regions:
        raw_blocks = self._extract_region(file_content, region)   # 复用 _ocr_scanned_pdf
        normalized = ImportTextNormalizer().normalize(raw_blocks)
        del raw_blocks                                             # 提前释放

        if enable_ocr_correction:
            normalized = await correct_ocr_blocks(normalized, ...)["corrected_blocks"]

        structure = analyze_structure(normalized)
        normalized = filter_blocks_by_classification(normalized, classify_pages(normalized, structure["section_markers"]))
        raw_questions = split_questions(normalized, structure)
        matched = match_answers(raw_questions, normalized, structure)["matched"]
        del normalized                                             # 提前释放

        questions = normalize_questions(raw_questions, matched, source_info)["questions"]
        del raw_questions, matched

        questions = validate_batch_structure(questions)["questions"]
        await checkpoint_save(db, questions, batch_id, region)     # 单 region 一次 commit
        await mark_region_done(db, batch_id, region)
        summary_stats["to_review"] += len(questions)
        del questions
        gc.collect()

    # 阶段 2：批后处理（从 DB 读）
    await post_process_batch(db, batch_id, options)
    return summary_stats
```

---

## 6. Generator / Yield 改造建议

| 收益等级 | 改造点 | 当前 | 建议 | 注意事项 |
|---|---|---|---|---|
| **高** | `_ocr_scanned_pdf` 返回 `list[dict]` | `return blocks` | `yield page_block`（generator） | 上游必须流式消费；`_warnings` 注入逻辑要换写到首条逻辑里 |
| **高** | `_extract_pdf_blocks` 文本提取 | 一次性返回 list | `yield {page, block_index, text}` 单页 | 文本 PDF 体积小，本身收益有限，但与流式管线一致 |
| **中** | `ImportTextNormalizer.normalize` | 接 list 返回 list | 接 iterable yield iterable | 当前用 list 索引顺序，改 generator 后 OCR correction 阶段需用临时 list 收集；不算大收益 |
| **中** | `submit_to_review` 写库 | 全 batch flush + 一次 commit | 每 50 题 flush+commit；或按 region | 需要 batch_id 提前生成，不能依赖最后 commit 才落地 |
| **低** | `analyze_structure` | 一次性扫全文 | 流式扫描 | 已经一次性 O(N) 不构成瓶颈，改造收益小 |
| **不建议** | `split_questions` | full_text 全文切分 | 流式切分 | 跨页选项恢复 + 题号边界检测依赖全局；改造复杂度高，回收收益小 |
| **不建议** | `match_answers` | 全文检索答案区 | 流式匹配 | SEPARATED 模式天然要求看到答案页 |
| **不建议** | `batch_validation` / `batch_dedup` | 跨题全局 | 跨题全局 | 业务语义就是全局 |

---

## 7. 数据库存储优化建议

### 7.1 当前痛点

`review_service.submit_to_review`：

- 单事务包住整批（最坏 500+ INSERT），任意一题失败全 batch 回滚
- `raw_data=q` 把每题完整字典写入 JSON 字段（含 raw_text、warnings、knowledge_points），SQLite 下 .db-wal 持续膨胀
- 同步 `await db.flush()` 每题一次，事务长度 = OCR + 全部 N 题 IO 时间

### 7.2 建议（按改动量从小到大）

| 等级 | 改动 | 收益 | 风险 |
|---|---|---|---|
| 必做 | review 阶段每 50 题或每 region commit 一次 | DB-WAL 受控、失败粒度变小 | 需重新评估「全或无」的回滚语义；建议 batch 内允许部分成功 |
| 必做 | `raw_data=q` 瘦身：剥掉 raw_text、warnings、similarity_suggestion，只保留必要字段 | 单行体积下降 50%+ | 回查导入历史时少一份原文，但 question_imports.parsed_content 已含 stem |
| 推荐 | 新增 `import_batches` / `import_progress` 表存 batch 元信息 + region 进度 | 支持断点恢复（§8） | 新表需迁移 |
| 推荐 | SQLite 路径下显式 `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL`（如未配置） | 写入吞吐 | 与现有 SQLite 配置确认 |
| 可选 | 切到 PostgreSQL `COPY` / `executemany` | 大批写入快 5–10× | 需确认 ORM 支持 |

---

## 8. 断点恢复方案

### 8.1 当前状态

完全没有：

- `_pipeline_store[pipeline_id]` 只保结果状态，不保 OCR 中间产物
- 第 287 页 OCR 失败 → 整个流程标记 failed，重启就要从 1 页重来
- 前端 polling `/pipelines/{id}` 看到 failed 也只能让用户重传

### 8.2 推荐方案

```
import_batches:
  id (=batch_id)
  source_file, source_type, total_pages
  status (created|ocr_running|review_ready|completed|failed)
  current_region_index
  ocr_pages_done (json: [start..end] 列表)
  created_at, updated_at

import_regions:
  batch_id, region_index, start_page, end_page
  status (pending|ocr_done|reviewed)
  questions_written
  ocr_tmp_path  (tmp/ocr/{batch_id}/region_{i}.jsonl，存 raw_blocks，可选)
```

恢复流程：

```
启动后台任务时：
  if batch_id exists and status not in (completed, failed_terminal):
      load import_regions where status != reviewed
      for each pending region:
          if has ocr_tmp_path: 直接读 jsonl
          else: 重新 OCR
          正常走 normalize → split → ... → review
          mark region reviewed
      finalize batch
```

### 8.3 落地最小子集

第一版只做 region 级 checkpoint：

- 不写 OCR 中间 jsonl（第 287 页失败时仍重 OCR 该 region，但已完成的 region 不重做）
- `import_batches` + `import_regions` 两张表 + region 完成时 commit 一次
- 失败重试只需读 `import_regions WHERE status='pending'`

足够覆盖「OCR 中途崩溃 → 不丢失已写入题目」的核心需求，1000 页扩展也直接生效。

---

## 9. 实施优先级

### P0（先做，高收益低风险）

1. **PDF bytes 落盘 + 闭包不持有**
   - 入口 `imports.py:_run_pipeline_with_db` 收到 content 后写入 `tmp/import/{pipeline_id}.pdf`，传文件路径而不是 bytes
   - extract 完成后，文本 PDF 路径可直接删 tmp；扫描 PDF 路径在 OCR 全部完成后删
   - **预期降低峰值 100–400 MB**

2. **消除 EXERCISE_DETECTION 双 OCR**
   - 让 `_lightweight_page_ocr` 输出的 `page_texts` 提供给后续 `_ocr_scanned_pdf` 复用（合并成一次扫描或缓存 OCR result）
   - 至少：lightweight 阶段降到 60 dpi 的 region 级关键词扫描，**不做整页 OCR**（只匹配「习题精选/参考答案」关键词足够）
   - 或者：用 PyMuPDF `get_text()` 试图判断扫描区起点，**纯扫描 PDF 这条路本来就是 100 字符以下走 OCR**，但 lightweight 仍可以仅 OCR 前 5–10% 的页面定位起点
   - **预期减少一半的 OCR 工作量**

3. **`_pipeline_store` 剥大字段 + Redis 单独存 diagnostics**
   - `_set_pipeline_store` 只存 stats、stages、errors、started_at、batch_id
   - diagnostics（含 raw_questions_preview、ocr_correction.corrections）单独写 `import:pipeline:diagnostics:{id}`，前端按需拉取
   - **预期降低 _pipeline_store 体积 80%+**

### P1（核心改造）

4. **stage 间清理 data 大字段**
   - 在 `ImportPipeline.run()` 里，每个 stage 完成后 `data.pop("raw_blocks")` / `data.pop("normalized_blocks")` 等
   - 必须先盘点哪些后续 stage 仍引用（match 用 normalized_blocks → 不能在 split 后立刻 pop；similarity_match 不需要 normalized_blocks）
   - **预期降低稳态内存 10–25 MB / 400 页**

5. **review 阶段分批 commit**
   - submit_to_review 每 50 题一次 commit，最后总结 written/skipped
   - raw_data 瘦身

### P2（结构性改造）

6. **切换到 region 流式编排**（方案 B）
   - 实施 §5.3 骨架
   - 解锁 1000 页扩展能力

7. **断点恢复表 + region checkpoint**（§8.3 最小子集）

### P3（次要）

8. similarity_matcher 题库 LRU + 上限
9. `_ocr_lock` 串行 vs ThreadPoolExecutor 矛盾（性能问题，不影响内存）
10. ocr_correction.corrections 落日志而不是 result.diagnostics

---

## 附录 A：关键代码位置索引

| 主题 | 位置 |
|---|---|
| Pipeline 入口 | `backend/app/api/v1/imports.py:608` (`pipeline_upload`) |
| 后台任务 | `backend/app/api/v1/imports.py:772` (`_run_pipeline_with_db`) |
| Pipeline 编排 | `backend/app/features/pipeline_orchestrator.py:931` (`ImportPipeline.run`) |
| 阶段间 data 累加 | `pipeline_orchestrator.py:983-999` |
| `_pipeline_store` 状态存储 | `pipeline_orchestrator.py:42-82` |
| 扫描版 PDF 批处理 OCR | `pipeline_orchestrator.py:122-225` (`_ocr_scanned_pdf`) |
| 习题区域预扫描 | `backend/app/features/exercise_region_detector.py:331` (`_lightweight_page_ocr`) |
| OCR 单页（含 boxes） | `backend/app/services/ocr_service.py:441` (`_ocr_one_page_with_boxes`) |
| OCR PaddleOCR 锁 | `ocr_service.py:22` (`_ocr_lock`) |
| 文本标准化 | `backend/app/features/text_normalizer.py:70` |
| AI OCR 纠错 | `backend/app/features/ocr_correction.py:183` |
| 题目切分 | `backend/app/features/question_splitter.py:381` |
| 答案匹配 | `backend/app/features/answer_matcher.py:197` |
| 题目标准化 | `backend/app/features/question_normalizer.py:297` |
| 批校验 | `backend/app/features/batch_validation.py:106` |
| AI 修复 | `backend/app/features/ai_repair.py:190` |
| 相似匹配 | `backend/app/features/similarity_matcher.py:89` |
| 写库 | `backend/app/features/review_service.py:77` (`submit_to_review`) |
| Profile 配置 | `backend/app/core/ocr_profile.py` |
| 全局配置 | `backend/app/core/config.py` |

---

## 附录 B：审计未覆盖项

- 未实测 RSS 峰值（建议落地 P0 后用 `tracemalloc` / `psutil` 在 400 页样本上验证）
- 未审计 PaddleOCR 模型本身的内存（singleton ~300 MB 是常识值，未实测）
- Excel 导入路径不在本次范围
- 图片单图导入路径未审（与扫描 PDF 复用大部分代码，结论可推广）
- DeepSeek API 失败重试 / 限流策略未在内存维度评估

---

## 相关链接

- [[docs/audit/AUDIT_INDEX.md|AUDIT_INDEX]] — 审计索引
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
