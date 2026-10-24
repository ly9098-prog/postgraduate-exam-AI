# AI 学习建议与预热执行兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限 `ai_service.generate_advice`（学习建议生成）和 `prewarm_wrong_question_analysis`（错题分析预热），不表示学习域、OCR 导入或全栈阶段 0 完成。

## 1. `generate_advice`

入口 `POST /api/v1/ai/n` → `ai_service.generate_advice(db, user_id, subject_id)`。

### 1.1 无模型回退

`resolve_llm_runtime_config(db, feature="analysis")` 返回 None → 立即返回 `get_fallback_advice()`，`from_fallback=True`、`model="fallback"`、`tokens_used=0`，不查询错题、不写 AiChat。

### 1.2 错题聚合

- 查活跃 `WrongQuestion`（user_id + is_active），limit 10。
- 查对应 `Question`，构建 `weak_points`（知识点）、`subject_stats`（科目→错题数）、`recent_wrong`（科目/错误类型/错答/正确答）。
- `build_study_advice(subject_stats, weak_points, recent_wrong)` 构建 LLM messages。

### 1.3 LLM 调用与持久化

- `chat_with_db_model(db, messages, feature="analysis")` 调用；返回 None → 抛 `RuntimeError("AI分析模型未配置")`。
- 任何异常 → 返回 `get_fallback_advice()`，`from_fallback=True`，不写 AiChat。
- 成功 → 解析 JSON（失败时回退为 `{"overall_assessment": raw_content}`），写 `AiChat(session_type="study_advice")`，commit，返回 `from_fallback=False`。

不变量：无模型或调用失败时返回确定性回退且不持久化；成功时持久化完整响应。

## 2. `prewarm_wrong_question_analysis`

入口：worker task_type=`prewarm_analysis` → `prewarm_wrong_question_analysis(wrong_question_id, user_id, expected_revision, force_regenerate, baseline_generated_at)`。

### 2.1 独立会话

使用 `async_session()` 创建独立后台 DB 会话，不共享请求事务。

### 2.2 跳过与取代

| 条件 | 返回 | 调 LLM |
| --- | --- | --- |
| 错题不存在 | `{"status":"skipped","reason":"wrong_question_not_found"}` | 否 |
| `expected_revision` ≠ `build_prewarm_revision(review_count, wrong_answer)` | `{"status":"superseded","reason":"revision_changed"}` | 否 |
| `force_regenerate` 且 `baseline_generated_at` ≠ 当前 `ai_analysis_generated_at` | `{"status":"superseded","reason":"analysis_already_regenerated","from_cache":True}` | 否 |

`build_prewarm_revision` 以 `review_count + wrong_answer` 构建版本戳，防止预热任务覆盖用户已重新作答/复习后的新状态。

### 2.3 委托 `analyze_error`

通过守卫后调用 `analyze_error(bg_db, user_id, wrong_question_id, force_regenerate)`，复用其版本守卫、缓存、认证隔离和 LLM 路径。

### 2.4 失败转换

`analyze_error` 对同步请求返回结构化回退（UI 优雅降级），但预热必须将其转为队列语义：

- `result.from_fallback=True` 或 (`cache_preserved=True` 且有 `error_code`) → 抛 `PrewarmAnalysisError`。
- `PrewarmAnalysisError` 携带 `error_code`、`retryable`、`model`，由 durable/local worker 决定重试。
- 分类：`failed_input`（vision_input_missing/vision_parse_failed/vision_unavailable，不可重试）、`retry`（可重试）、`failed_permanent`（不可重试）。
- `_prewarm_failure_from_result` 从 result 提取 error_code/retryable/model；无 error_code 时按 model 名映射默认值。

### 2.5 成功与缓存命中

- `result.from_cache=True` → `{"status":"cache_hit"}`，不额外消耗令牌。
- 否则 → `{"status":"success"}`。
- 两者都带 `model` 和 `duration_ms`。

不变量：预热不把回退当成功；取代检测防止覆盖用户新状态；force-regenerate 的恢复任务在原始 HTTP 已完成时跳过，避免二次付费。

## 3. `_resolve_healthy_analysis_runtime`

- 循环最多 `_ANALYSIS_RUNTIME_RESOLUTION_LIMIT` 次解析 analysis 能力配置。
- 跳过被认证隔离的 model_config_id（加入 excluded 集合），尝试下一个。
- 全部被隔离或无配置 → 返回 None。

## 4. 可执行基线

- `backend/tests/test_services/test_ai_prewarm_protocol.py`：9 项测试覆盖被取代版本跳过 provider、匹配版本保留结果、缺失错题不调用、已生成跳过、回退为 typed failure（retryable/non-retryable）、durable payload 到达 revision validator、worker 启动一次且 shutdown 取消任务。
- `backend/tests/test_services/test_ai_advice_compatibility.py`：新增真实 SQLite 测试覆盖无模型回退（不查错题/不写 AiChat/tokens_used=0）和有错题无模型回退。
- `backend/tests/architecture/test_ai_prewarm_boundaries.py`：3 项架构测试覆盖 revision 模块依赖、生产者/验证器导入中性协议、fresh import 不加载 worker/ai_service/database。

## 5. 未完成和未验证

- `generate_advice` 的真实 LLM 调用、AiChat 持久化和 JSON 解析回退需外部 AI 服务可用后验收。
- `prewarm` 的真实 worker dispatch、durable queue 重试和认证隔离超时恢复需 Redis 和 AI 服务可用后验收。
- `analyze_error` 完整 LLM 路径、多模态视觉证据和认证隔离已在 `AI_ANALYSIS_COMPATIBILITY.md` 登记，本文件不重复。
- SQLite 服务路径测试不等于生产 PostgreSQL/Redis 查询计划或真实 AI 调用验收。
