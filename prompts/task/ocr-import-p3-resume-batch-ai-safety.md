# OCR 导题 P3 改造任务：断点恢复、分批提交与 AI 后处理安全

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

1. 审核页风险展示。
2. `risk_flags` / `risk_level` / `risk_reasons` 接入。
3. `ai_answer_flag` 醒目展示。
4. OCR 原文展示。
5. 公式 / 表格 segment 框架。
6. 低风险批量通过。
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

当前系统的 OCR 能力已经比较完整。P3 不再继续堆识别功能，而是提升长任务稳定性、失败恢复能力和 AI 后处理安全性。

---

# 本轮总目标

P3 只做四类高收益任务：

```text
1. 最小断点恢复
2. review 阶段分批 commit
3. complete → enrich 串联版本回退
4. AI 补全 / 丰富并行化
```

本轮不做大规模 pipeline 拆分，不重写 OCR pipeline。

------

# 全局约束

请严格遵守：

1. 不大规模拆分 `pipeline_orchestrator.py`。
2. 不大规模拆分 `question_pipeline.py`。
3. 不重写 OCR pipeline。
4. 不改小程序端。
5. 不改变已有 API 字段含义，只允许增加兼容字段。
6. 不破坏 P0/P1/P2 已完成能力：
   - risk_flags
   - risk_level
   - risk_reasons
   - math_image
   - table_markdown
   - source_region
   - OCR cache
   - low-risk skip repair
7. 不缓存 LLM 输出。
8. 不让 AI 猜答案。
9. 不让 AI 改写公式和代码。
10. 断点恢复失败时不能影响原有完整导入流程。
11. 修改完成后必须运行相关测试。

------

# P3-1：审计当前 pipeline 状态与可恢复点

## 目标

先确认当前 pipeline 每个阶段的输入、输出、状态存储位置，为最小断点恢复做准备。

## 需要检查的文件

```text
backend/app/features/pipeline_orchestrator.py
backend/app/models/import_pipeline.py
backend/app/models/import_batch_job.py
backend/app/models/question_import.py
backend/app/api/v1/imports.py
backend/app/api/v1/admin_imports.py
backend/app/services/admin_import_service.py
```

## 需要确认

1. 当前 pipeline 状态保存在哪里。
2. `_pipeline_store` 当前保存哪些字段。
3. P0/P2 后哪些大字段已经被剥离。
4. 每个 stage 的输出是否可序列化。
5. 哪些 stage 可以安全跳过重跑。
6. 哪些 stage 必须重跑。
7. pipeline 失败时当前如何标记状态。
8. 是否已有 import_batch_job / import_pipeline 相关模型可复用。
9. 是否已有 progress / diagnostics 字段可写入 checkpoint。

## 输出要求

在最终报告中输出：

| Stage | 当前输出 | 是否可 checkpoint | 是否可恢复 | 风险 |
| ----- | -------- | ----------------- | ---------- | ---- |
|       |          |                   |            |      |

------

# P3-2：实现最小断点恢复 checkpoint

## 目标

导入长 PDF 时，如果中途失败，能够从最近的安全阶段恢复，而不是整份 PDF 从头重跑。

## 修改文件

优先检查：

```text
backend/app/features/pipeline_orchestrator.py
backend/app/models/import_pipeline.py
backend/app/api/v1/imports.py
backend/app/api/v1/admin_imports.py
```

必要时新增：

```text
backend/app/features/pipeline_checkpoint.py
```

## 最小 checkpoint 阶段

至少记录以下阶段：

```text
extract_done
normalize_done
ocr_correction_done
split_done
match_done
normalize_schema_done
math_detect_done
table_detect_done
repair_done
review_done
```

## checkpoint 数据结构建议

```json
{
  "pipeline_id": "xxx",
  "completed_stages": [
    "extract",
    "normalize",
    "ocr_correction"
  ],
  "current_stage": "split",
  "stage_outputs": {
    "normalized_text_ref": "...",
    "questions_ref": "...",
    "matched_ref": "..."
  },
  "diagnostics": {
    "last_success_at": "...",
    "failed_stage": null,
    "resume_count": 0
  }
}
```

## 要求

1. 不把大对象直接写入 checkpoint。
2. 大字段只保存 ref / path / key。
3. 如果某 stage 输出不可恢复，则明确标记必须重跑。
4. 恢复时从最近安全阶段继续。
5. 如果 checkpoint 损坏，则 fallback 到完整重跑。
6. 不影响原有直接导入流程。
7. checkpoint 默认启用，但可通过配置关闭。

## 验收标准

1. pipeline 每完成一个关键 stage 后写入 checkpoint。
2. 中途失败后能看到 failed_stage。
3. 重新执行时可从最近完成 stage 恢复。
4. checkpoint 损坏时不会导致系统崩溃。
5. 大 PDF 不会因为 checkpoint 导致内存回升。

------

# P3-3：新增 resume 接口或复用现有接口

## 目标

管理员可以重试失败的导入任务，并尽量从 checkpoint 恢复。

## 修改文件

```text
backend/app/api/v1/admin_imports.py
backend/app/services/admin_import_service.py
backend/app/features/pipeline_orchestrator.py
admin-frontend/src/app/(admin)/imports/tasks/page.tsx
```

## 接口建议

```http
POST /api/admin/v1/imports/pipelines/{pipeline_id}/resume
```

或复用现有 retry 接口，如果已有。

## 要求

1. 只能对 failed / interrupted 状态任务恢复。
2. running / completed 任务不能重复 resume。
3. resume 时读取 checkpoint。
4. 如果 checkpoint 不可用，提示将完整重跑。
5. 前端任务页显示“恢复导入”按钮。
6. resume 后继续展示进度。

## 验收标准

1. failed 任务能点击恢复。
2. completed 任务不能恢复。
3. running 任务不能重复恢复。
4. checkpoint 可用时从中间阶段恢复。
5. checkpoint 不可用时可完整重跑或给出明确提示。

------

# P3-4：review 阶段分批 commit

## 目标

避免大量题目一次性写入审核表时，中途失败导致整批回滚。

## 修改文件

```text
backend/app/features/review_service.py
backend/app/features/pipeline_orchestrator.py
```

## 实现要求

1. review 阶段按批提交。
2. 默认每 50 题 commit 一次。
3. 单批失败时：
   - 记录失败 batch index。
   - 记录失败题号范围。
   - 其余批次尽量继续或允许恢复。
4. 不重复写入已成功提交的题。
5. 批量提交进度写入 diagnostics。
6. 支持配置 batch size。

## diagnostics 示例

```json
{
  "review_commit": {
    "batch_size": 50,
    "total_questions": 236,
    "committed_batches": 4,
    "failed_batches": [
      {
        "batch_index": 5,
        "question_range": [201, 236],
        "error": "..."
      }
    ]
  }
}
```

## 验收标准

1. 236 道题不会一次性单事务写入。
2. 某批失败不会导致前面批次丢失。
3. 恢复时不会重复写入已成功题。
4. diagnostics 能看到分批提交情况。

------

# P3-5：complete → enrich 串联版本回退

## 目标

防止 AI complete 阶段产生幻觉后，enrich 阶段继续基于错误结果扩展，造成二次污染。

## 修改文件

```text
backend/app/features/question_pipeline.py
backend/app/features/ai_safety.py
backend/app/features/ai_repair.py
backend/app/ai/prompts.py
```

## 风险场景

```text
原题 answer 为空
  ↓
complete 阶段 AI 猜了错误答案
  ↓
enrich 阶段基于错误答案生成知识点 / 解析 / 标签
  ↓
审核员看到内容很完整但答案错了
```

## 实现要求

1. complete 前保存 before snapshot。
2. complete 后做 diff。
3. 如果 AI 修改了以下字段，必须标记风险：
   - answer
   - stem
   - options
   - code block
   - formula / LaTeX
4. 如果 answer 是 AI 生成，必须设置：
   - `ai_answer_flag=true`
   - `answer_requires_review=true`
5. enrich 只能基于通过 safety gate 的 complete 结果。
6. 如果 complete 结果高风险，则 enrich 跳过或只做非侵入 metadata。
7. 回退时保留原始题目，并写入 risk_flags。

## 新增风险标记

```text
complete_changed_answer
complete_changed_stem
complete_changed_options
complete_high_risk_skipped_enrich
enrich_skipped_due_to_complete_risk
```

## 验收标准

1. AI complete 改答案会被标记。
2. 高风险 complete 后不会继续 enrich 正文内容。
3. 回退后原题内容不丢失。
4. 审核页能看到风险原因。

------

# P3-6：AI 补全 / 丰富并行化

## 目标

缩短管理端 AI complete / enrich 批量处理时间。

## 修改文件

```text
backend/app/features/question_pipeline.py
backend/app/features/token_budget.py
backend/app/services/admin_import_service.py
```

## 实现要求

1. 使用 `asyncio.gather` + `Semaphore`。
2. 默认并发数 3。
3. 最大不超过 5。
4. 单题失败不影响整批。
5. 保持输出顺序。
6. 记录每题成功 / 失败。
7. 写入 complete_stats / enrich_stats。
8. 支持配置关闭并行。

## stats 示例

```json
{
  "complete_stats": {
    "total": 80,
    "success": 73,
    "failed": 7,
    "concurrency": 3,
    "duration_ms": 42100
  },
  "enrich_stats": {
    "total": 80,
    "success": 70,
    "failed": 10,
    "concurrency": 3,
    "duration_ms": 46800
  }
}
```

## 验收标准

1. 批量 complete 不再串行处理所有题。
2. 单题失败不会中断整批。
3. 输出顺序与输入顺序一致。
4. 并发数可配置。
5. token budget 不被并发绕过。

------

# P3-7：统一 token budget 使用

## 目标

避免并发 complete / enrich 后绕过 token budget，或多个模块各自计数导致预算失控。

## 修改文件

```text
backend/app/features/token_budget.py
backend/app/features/llm_text_structurer.py
backend/app/features/question_pipeline.py
backend/app/features/ai_repair.py
```

## 实现要求

1. `llm_text_structurer` 不再使用完全独立的进程级预算。
2. complete / enrich / repair / structure 共用统一 token budget。
3. 并发场景下 token budget 更新要安全。
4. 超预算时 graceful fallback。
5. diagnostics 中记录预算消耗。

## 验收标准

1. 所有 LLM 调用都能进入统一预算统计。
2. 超预算不会导致系统崩溃。
3. 并发 complete 不会突破预算限制。
4. 预算统计能在 diagnostics 中看到。

------

# 测试要求

请至少运行或补充以下测试。

## 后端测试

1. checkpoint 写入成功。
2. checkpoint 损坏时 fallback。
3. failed pipeline 可以 resume。
4. completed pipeline 不能 resume。
5. review 分批 commit 不重复写入。
6. complete 改答案会触发风险。
7. complete 高风险会跳过 enrich。
8. enrich 跳过不会丢失原题。
9. complete / enrich 并发保持顺序。
10. 单题失败不影响整批。
11. token budget 并发下不失控。

## 前端测试 / 类型检查

1. 任务页显示“恢复导入”按钮。
2. running / completed 状态不显示错误操作。
3. resume 后状态轮询正常。
4. TypeScript 类型检查通过。

## 回归测试

至少运行：

```bash
pytest tests/ocr_regression
```

如果环境不支持完整 OCR，请运行不依赖 PaddleOCR 的单元测试，并说明未运行完整 OCR 的原因。

------

# 不做事项

本轮明确不做：

1. 不拆分 `pipeline_orchestrator.py`。
2. 不拆分 `question_pipeline.py`。
3. 不改小程序端。
4. 不做新 OCR 模型接入。
5. 不做复杂图像管理系统。
6. 不缓存 LLM 输出。
7. 不让 AI 猜答案。
8. 不让 AI 改写公式和代码。
9. 不因为 checkpoint 损坏导致任务无法重跑。
10. 不因为单题 AI 失败导致整批 complete / enrich 失败。

------

# 最终输出格式

执行完成后，请输出：

## 1. 本轮完成了哪些 P3 任务

逐项说明 P3-1 到 P3-7 是否完成。

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

## 4. 新增配置

说明：

| 配置项 | 默认值 | 用途 |
| ------ | ------ | ---- |
|        |        |      |

## 5. 新增接口

说明：

| 接口 | 方法 | 用途 | 权限 |
| ---- | ---- | ---- | ---- |
|      |      |      |      |

## 6. 新增 risk_flags

说明：

| risk_flag | 风险等级 | 中文原因 | 触发条件 |
| --------- | -------- | -------- | -------- |
|           |          |          |          |

## 7. 新增测试

说明新增了哪些测试文件、测试函数、覆盖哪些风险。

## 8. 运行测试结果

输出实际运行命令和结果。

## 9. 性能结果

如果做了并行化，请输出：

```text
complete duration before / after:
enrich duration before / after:
concurrency:
failed count:
```

## 10. 未完成事项

如果某项任务未完成，请说明原因和后续建议。

## 11. 风险和注意事项

说明本次修改是否可能影响：

- PDF 导入
- 图片导入
- Excel 导入
- 文本导入
- 管理端审核
- AI complete
- AI enrich
- AI repair
- token budget
- `_pipeline_store` 内存体积

## 12. 下一轮建议

下一轮优先考虑：

1. `pipeline_orchestrator.py` 渐进拆分。
2. `question_pipeline.py` 拆分。
3. Qwen-VL 替代 DeepSeek 视觉回退。
4. 代码语义等价性检查。
5. 多列选项错序进一步优化。

