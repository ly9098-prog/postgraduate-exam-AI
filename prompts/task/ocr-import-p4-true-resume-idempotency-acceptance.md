# OCR 导题 P4 改造任务：真断点恢复、幂等入库与真实导题验收

## 任务背景

P0 阶段已完成：

1. OCR 主路径统一。
2. PDF / 图片 / Excel bytes 落盘释放。
3. 消除双 OCR。
4. `_pipeline_store` 瘦身。
5. OCR 清洗统一。
6. AI safety gate 接入。
7. 真实 OCR 回归基线建立。

P1 阶段已完成：

1. 管理端审核页风险展示。
2. `risk_flags` / `risk_level` / `risk_reasons` 接入。
3. `ai_answer_flag` 醒目展示。
4. OCR 原文展示。
5. `math_image` / `table_markdown` segment 渲染。
6. 低风险题批量通过。
7. 原图区域对照预览。
8. 表格 Markdown 保真。

P2 阶段已完成：

1. 真实公式截图裁剪与上传闭环。
2. page image 以 tempfile/ref 方式贯穿 math_detect stage。
3. `math_image.url` 能真实生成或 graceful fallback。
4. 低风险题跳过 AI repair。
5. AI repair skip stats。
6. PaddleOCR 结果缓存。
7. OCR 回归样本扩展。

P3 阶段已完成：

1. stage checkpoint 已记录。
2. resume 接口已创建。
3. review 阶段分批 commit 已确认。
4. complete → enrich 风险门禁已完成。
5. complete / enrich 统计已增加。
6. token budget 已统一。

P4 阶段已完成：

1. pipeline artifact store（`.backend_cache/pipeline_artifacts/`）实现。
2. artifact 真断点恢复：从 normalize_schema / repair / math_detect / table_detect artifact 恢复 questions，跳过已完成 stage。
3. 幂等入库：pipeline_id 透传 + `subject + question_hash` 去重 + `duplicates_filtered` 跟踪。
4. 导入质量报告：`quality_report` 包含风险分布 / AI 答案 / 公式 / 表格 / 缓存 / 去重统计。
5. 真实导题验收脚本：`tests/ocr_acceptance/run_acceptance.py`。
6. artifact 清理策略：`POST /cleanup/expired` 端点（completed: 24h, failed: 7d）。

但 P3 报告明确说明：

> 当前恢复时仍会重跑所有 stage。Checkpoint 主要提供进度可见性和诊断连续性，不节省计算时间。

因此 P4 的目标是把 checkpoint 从“诊断型”升级为“真恢复型”，并确保 resume 不会造成重复入库。同时增加真实导题验收报告，验证 OCR 导题是否真的减少人工返工。

---

# 本轮总目标

P4 只做三件事：

```text
1. 真断点恢复：从可恢复 stage 继续，而不是全部重跑
2. 幂等入库：resume / retry 不重复写入 question_imports
3. 真实导题验收报告：量化高数、408、表格、公式、AI 答案、低风险通过效果
```

本轮不做大规模 pipeline 拆分。

------

# 全局约束

请严格遵守：

1. 不大规模拆分 `pipeline_orchestrator.py`。
2. 不大规模拆分 `question_pipeline.py`。
3. 不重写 OCR pipeline。
4. 不改小程序端。
5. 不改变已有 API 字段含义，只允许增加兼容字段。
6. 不破坏 P0/P1/P2/P3 已完成能力：
   - risk_flags
   - risk_level
   - risk_reasons
   - ai_answer_flag
   - math_image
   - table_markdown
   - source_region
   - OCR cache
   - low-risk skip repair
   - complete → enrich 风险门禁
   - token budget diagnostics
7. 不缓存 LLM 输出。
8. 不把大对象写入 checkpoint。
9. 不因为 checkpoint 损坏导致任务无法重跑。
10. 不因为 resume 导致重复入库。
11. 修改完成后必须运行相关测试。

------

# P4-1：审计当前 checkpoint 是否能承载真恢复

## 目标

确认 P3 checkpoint 当前保存了什么，哪些 stage 能恢复，哪些 stage 只能重跑。

## 需要检查的文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/pipeline_checkpoint.py
backend/app/api/v1/admin_imports.py
backend/app/models/import_pipeline.py
backend/app/models/import_batch_job.py
backend/app/features/review_service.py
backend/app/models/question_import.py
```

如果 `pipeline_checkpoint.py` 不存在，请检查 P3 中 checkpoint 函数实际放置位置。

## 需要输出

请在最终报告中输出：

| Stage | 当前 checkpoint 内容 | 是否可恢复 | 需要新增的 ref | 是否含大对象风险 |
| ----- | -------------------- | ---------- | -------------- | ---------------- |
|       |                      |            |                |                  |

至少覆盖：

```text
extract
normalize
ocr_correction
split
match
normalize_schema
math_detect
table_detect
repair
review
```

## 判断标准

1. 如果 stage 输出只在内存中，不可恢复。
2. 如果 stage 输出有 ref/path/key，可恢复。
3. 如果 stage 输出含 bytes / PIL / numpy，不允许直接写 checkpoint。
4. 如果 stage 输出是大 JSON，必须写入 artifact 文件或 KV 存储，只在 checkpoint 里保存 ref。

------

# P4-2：新增 pipeline artifact store

## 目标

为真断点恢复提供轻量 artifact 存储，不把大对象放入 checkpoint。

## 建议新增文件

```text
backend/app/features/pipeline_artifacts.py
```

## artifact 类型

至少支持：

```text
normalized_text
ocr_corrected_text
raw_questions
matched_questions
normalized_questions
math_detected_questions
table_detected_questions
repaired_questions
review_commit_state
```

## 存储方式

优先使用文件或现有 KV，不新增复杂数据库迁移。

建议结构：

```text
.backend_cache/pipeline_artifacts/{pipeline_id}/
  extract.json
  normalize.json
  ocr_correction.json
  split.json
  match.json
  normalize_schema.json
  math_detect.json
  table_detect.json
  repair.json
  review_commit_state.json
```

## checkpoint 只保存 ref

```json
{
  "completed_stages": ["extract", "normalize", "split"],
  "stage_artifacts": {
    "normalize": ".backend_cache/pipeline_artifacts/{pipeline_id}/normalize.json",
    "split": ".backend_cache/pipeline_artifacts/{pipeline_id}/split.json"
  }
}
```

## 要求

1. 不保存 page image bytes。
2. 不保存 LLM 原始输出。
3. 不保存超大 raw PDF bytes。
4. artifact 写入失败时，pipeline 仍可继续完整执行。
5. artifact 损坏时，resume fallback 到前一安全 stage 或完整重跑。
6. artifact 文件需有 TTL / cleanup 方案。

## 验收标准

1. 每个可恢复 stage 成功写入 artifact ref。
2. checkpoint 中只保存 ref，不保存大对象。
3. artifact 损坏时不崩溃。
4. cleanup 可清理过期 artifact。

------

# P4-3：实现真 stage resume

## 目标

resume 时从最近可恢复 stage 继续，而不是全部重跑。

## 修改文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/features/pipeline_artifacts.py
backend/app/api/v1/admin_imports.py
```

## 恢复策略

从最近成功且 artifact 可读的 stage 开始恢复。

示例：

```text
如果 normalize_schema artifact 存在：
  从 math_detect 继续

如果 split artifact 存在：
  从 match 继续

如果 normalize artifact 存在：
  从 ocr_correction 或 split 继续

如果无 artifact：
  完整重跑
```

## 不建议恢复的内容

以下不建议作为直接恢复 artifact：

```text
page image bytes
PIL Image
numpy array
LLM 原始响应
未压缩大 OCR boxes
```

如果确实需要，保存为压缩文件或引用路径。

## 要求

1. resume 日志明确显示：
   - restored_stage
   - restored_artifact
   - resume_from_stage
2. 如果 artifact 不存在，明确 fallback。
3. 如果 artifact 版本不兼容，fallback。
4. resume 不应重复执行已完成且可恢复 stage。
5. 不能破坏普通首次导入。

## 验收标准

1. 人为让 pipeline 在 split 后失败，resume 后不重新 OCR。
2. 人为让 pipeline 在 normalize_schema 后失败，resume 后从 math_detect / table_detect 继续。
3. artifact 损坏时完整重跑。
4. resume diagnostics 能看到恢复来源。

------

# P4-4：review 入库幂等保护

## 目标

resume / retry 时不能重复写入 `question_imports`，也不能重复发布正式题库。

## 修改文件

```text
backend/app/features/review_service.py
backend/app/models/question_import.py
backend/app/services/admin_import_service.py
backend/app/features/question_publish_service.py
```

## 幂等键建议

优先使用：

```text
pipeline_id + question_number + content_hash
```

如果没有 pipeline_id，则使用：

```text
import_batch_id + question_number + content_hash
```

content_hash 建议基于：

```text
stem + options + answer + analysis
```

## 要求

1. submit_to_review 写入前先检查是否已存在同一幂等键。
2. 已存在则更新或跳过，不重复插入。
3. 分批 commit 中途失败后 resume，不重复写入前面成功批次。
4. 低风险批量通过不能重复 publish。
5. approve / publish 也要有幂等防护。
6. 不新增复杂迁移时，可以先用查询级幂等；如果需要唯一索引，请先说明风险。

## 验收标准

1. 同一 pipeline resume 多次，审核队列不重复。
2. review 第 2 批失败后 resume，不重复第 1 批。
3. 同一题不会重复发布到正式题库。
4. diagnostics 中记录 skipped_duplicate_count。

------

# P4-5：真实导题验收报告

## 目标

导入完成后，生成一份可读的导题质量报告，让管理员知道这批题是否值得直接刷。

## 修改文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/services/admin_import_service.py
backend/app/api/v1/admin_imports.py
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
admin-frontend/src/app/(admin)/imports/review/page.tsx
```

## 报告字段建议

```json
{
  "total_questions": 120,
  "low_risk": 82,
  "medium_risk": 28,
  "high_risk": 10,
  "requires_manual_review": 38,
  "ai_answer_count": 4,
  "math_image_count": 18,
  "table_markdown_count": 7,
  "source_region_count": 20,
  "repair_skipped": 75,
  "repair_called": 12,
  "ocr_cache_hit": 60,
  "ocr_cache_miss": 40,
  "review_duplicates_skipped": 3,
  "estimated_manual_check_rate": 0.32
}
```

## 前端展示

在任务详情或审核页顶部展示：

```text
本次导入 120 题
低风险 82 题，可批量通过
需检查 28 题
高风险 10 题
AI 答案 4 题，请重点核对
公式截图 18 个
表格 7 个
OCR 缓存命中 60 页
```

## 要求

1. 报告不影响导入流程。
2. 数据不完整时也能显示部分报告。
3. 与 P0/P1/P2/P3 diagnostics 兼容。
4. 报告字段可选，不破坏旧任务。

## 验收标准

1. 导入完成后能看到质量报告。
2. 报告能反映风险分布。
3. 报告能反映公式 / 表格 / AI 答案 / 缓存命中情况。
4. 前端 TypeScript 检查通过。

------

# P4-6：真实样本验收脚本

## 目标

用真实高数 / 408 资料验证当前 OCR 导题效果，避免只看单元测试。

## 建议新增

```text
tests/ocr_acceptance/
  cases/
  run_acceptance.py
  README.md
```

## 样本类型

至少设计以下验收 case 模板：

```text
1. 高数公式 PDF
2. 高数扫描图片
3. 线代矩阵题
4. 概率统计表格题
5. 408 C 代码题
6. 408 表格题
7. 多列选项题
8. 水印干扰题
```

## 指标

```json
{
  "question_count_recall": 0.95,
  "option_integrity": 0.98,
  "answer_match_rate": 0.96,
  "math_image_presence": 0.90,
  "code_symbol_preservation": 0.99,
  "table_structure_presence": 0.85,
  "manual_review_rate": 0.30
}
```

## 要求

1. 不能用 pipeline 当前输出当 expected。
2. expected 必须人工标注或人工确认。
3. 如果真实样本不能提交仓库，允许创建本地 ignored 目录模板。
4. 输出 acceptance report JSON。

## 验收标准

1. 可以本地跑 acceptance。
2. 能输出质量指标。
3. 指标能帮助判断是否适合真实导题。
4. 不影响 CI。

------

# P4-7：artifact / checkpoint / cache 清理策略

## 目标

避免 `.backend_cache`、pipeline artifacts、OCR cache、page image refs 越积越多。

## 修改文件

```text
backend/app/services/ocr_cache_service.py
backend/app/features/pipeline_artifacts.py
backend/app/features/pipeline_orchestrator.py
```

## 要求

1. OCR cache 继续按 TTL 清理。
2. pipeline artifacts 设置 TTL。
3. temp page images 在 run 完成后清理。
4. failed pipeline 的 artifacts 保留一段时间用于 resume。
5. completed pipeline 的 artifacts 可较快清理。
6. 提供手动 cleanup 函数或管理命令。

## 建议 TTL

```text
completed pipeline artifacts: 24h
failed pipeline artifacts: 7d
OCR cache: 14d
temp page images: run 结束立即清理
```

## 验收标准

1. completed 任务 artifact 可清理。
2. failed 任务 artifact 在 TTL 内保留。
3. cleanup 不删除仍在 running 的任务 artifact。
4. 清理日志可见。

------

# 测试要求

请至少运行或补充以下测试。

## 后端测试

1. artifact 写入成功。
2. artifact 损坏时 fallback。
3. split 后失败，resume 不重新 OCR。
4. normalize_schema 后失败，resume 从 math_detect / table_detect 继续。
5. review 分批失败后 resume 不重复写入。
6. 同一 pipeline 多次 resume 不重复写入 question_imports。
7. approve / publish 幂等。
8. 导入质量报告字段正确。
9. artifact cleanup 不删除 running 任务。
10. completed / failed artifact TTL 不同。

## 前端测试 / 类型检查

1. 任务详情展示导入质量报告。
2. 审核页展示风险统计。
3. resume 状态显示正常。
4. TypeScript 类型检查通过。

## 验收测试

至少能运行：

```bash
pytest tests/ocr_regression
```

如果新增 acceptance：

```bash
python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
```

如果环境缺少真实样本，请说明如何手动放置样本。

------

# 不做事项

本轮明确不做：

1. 不拆分 `pipeline_orchestrator.py`。
2. 不拆分 `question_pipeline.py`。
3. 不换 OCR 模型。
4. 不做复杂表格 OCR 引擎。
5. 不缓存 LLM 输出。
6. 不把 page image bytes 写入 checkpoint。
7. 不让 checkpoint 损坏阻塞完整重跑。
8. 不让 resume 重复写入审核队列。
9. 不强制把真实样本提交仓库。
10. 不改小程序端。

------

# 最终输出格式

执行完成后，请输出：

## 1. 本轮完成了哪些 P4 任务

逐项说明 P4-1 到 P4-7 是否完成。

## 2. 修改了哪些文件

用表格列出：

| 文件 | 修改内容 | 对应任务 |
| ---- | -------- | -------- |
|      |          |          |

## 3. 新增或变更字段 / metadata

说明：

| 字段 | 类型 | 来源 | 用途 | 是否兼容 |
| ---- | ---- | ---- | ---- | -------- |
|      |      |      |      |          |

## 4. 新增接口或管理命令

说明：

| 名称 | 类型 | 用途 |
| ---- | ---- | ---- |
|      |      |      |

## 5. 新增 artifact 类型

说明：

| artifact | 内容 | 是否可恢复 | TTL  |
| -------- | ---- | ---------- | ---- |
|          |      |            |      |

## 6. 幂等策略

说明：

| 场景 | 幂等键 | 行为 |
| ---- | ------ | ---- |
|      |        |      |

## 7. 新增测试

说明新增了哪些测试文件、测试函数、覆盖哪些风险。

## 8. 运行测试结果

输出实际运行命令和结果。

## 9. 性能 / 恢复效果

如果做了真 resume，请输出：

```text
failed stage:
restored stage:
skipped stages:
OCR 是否重跑:
review duplicates skipped:
resume duration:
```

## 10. 导题验收报告

输出一个示例报告 JSON。

## 11. 未完成事项

如果某项任务未完成，请说明原因和后续建议。

## 12. 风险和注意事项

说明本次修改是否可能影响：

- PDF 导入
- 图片导入
- Excel 导入
- 文本导入
- 管理端审核
- resume
- review 入库
- OCR cache
- pipeline artifacts
- `_pipeline_store` 内存体积

## 13. 下一轮建议

下一轮优先考虑：

1. `pipeline_orchestrator.py` 渐进拆分。
2. `question_pipeline.py` 拆分。
3. Qwen-VL 替代 DeepSeek 视觉回退。
4. 代码语义等价性检查。
5. 多列选项错序进一步优化。