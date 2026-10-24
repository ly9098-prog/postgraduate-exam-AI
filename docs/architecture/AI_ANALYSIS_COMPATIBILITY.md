# AI 分析与修复执行兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限错题 AI 复盘（`analyze_error`）、AI 修复（`repair_questions`）、令牌预算门禁和模型配置解析，不表示学习域、OCR 导入或全栈阶段 0 完成。

## 1. 错题复盘 `analyze_error`

入口 `GET /api/v1/wrong-questions/{id}/analysis` → `ai_service.analyze_error(db, user_id, wrong_question_id, force_regenerate)`。

### 1.1 版本守卫（revision guard）

教学上下文跟随当前题库投影（学习者看到的版本），但以不可变 wrong-attempt 版本做安全边界：

1. 查 `WrongQuestion`（user_id + wrong_question_id），不存在抛 `ValueError`。
2. 查当前 `Question`，不存在抛 `ValueError`。
3. 构建 `current_answer_grounding`（当前版本的 question_type/content/options/answer/user_answer）。
4. 若 `current_version_id != wrong_version_id`（版本漂移）：查 `QuestionVersion(wrong_version_id)`，构建 `historical_grounding`，比较 `grounding_fact_signature`。
5. 签名不匹配 → 返回 `revision_guard` 结果：`content=build_revision_drift_analysis()`、`model="revision_guard"`、`tokens_used=0`、`revision_guarded=True`，不调用任何 LLM。

不变量：旧答案键永不对新版本投影重新解释；版本漂移时返回确定性安全文案，不消耗令牌。

### 1.2 缓存新鲜度

- `is_ai_analysis_fresh` 检查 `ai_analysis._meta` 中的生成时间、prompt 版本和模型配置 revision。
- `force_regenerate=True` 跳过缓存。
- 缓存命中且新鲜 → 返回 `from_cache=True`，不调用 LLM。
- 缓存结构无效或字段缺失 → 视为未生成，继续 LLM 路径。

### 1.3 认证隔离（auth quarantine）

- 模型配置认证失败时，`_quarantine_analysis_runtime_auth(runtime)` 按 model_config_id+provider+model 短暂隔离该配置。
- 隔离期内 `_is_analysis_runtime_auth_quarantined` 返回真，跳过该模型并尝试下一个配置分析模型。
- 隔离避免单个失效 Key 导致所有错题复盘反复触发认证失败。

### 1.4 视觉证据

- `_collect_question_visual_sources` 收集题目图片源；`requires_visual` 决定是否走多模态输入。
- `_extract_visual_evidence` 从 LLM 响应提取 `visual_evidence`/`visualEvidence`/`image_evidence` 字段。
- `_visual_evidence_is_valid` 校验非空且非占位；无效时回退到纯文本诊断。

### 1.5 回退

- LLM 不可用或所有模型被隔离 → `get_fallback_analysis` 返回确定性回退诊断。
- 回退是 typed worker failure（`error_code="ai_analysis_failed"`、`retryable=True`），不是静默空结果。

## 2. AI 修复 `repair_questions`

入口：导入流水线 stage5 后调用 `ai_repair.repair_questions(questions, config, db, roman_diagnostics)`。

### 2.1 两阶段

- Phase 1（Roman 决策）：`enable_roman_repair_phase=True` 且有 `roman_diagnostics` 时，`_run_roman_repair_phase` 让 AI 从候选修复中做约束决策，代码机械应用修复。
- Phase 2（通用修复）：标准自由格式 AI 修复，对 Phase 1 未覆盖的低置信题目执行。

### 2.2 令牌预算门禁

`token_budget.check_token_limit(estimated_tokens, config)` 在每次 LLM 调用前检查：

- 优先读 Redis 共享计数器（daily/monthly），所有 worker 进程见同一预算。
- Redis 不可达时：生产/云画像（`_restricted()`）fail-closed 返回 False（基础设施中断不静默移除成本上限）；本地开发回退到进程内计数器。
- 超限 → 跳过该题修复，标记 `reason` 为预算超限，不调用 LLM。
- `record_token_usage` 在调用后累加；Redis 路径用 pipeline 原子 incrby+expire。

### 2.3 不可变选项保护

Layer 4 规则（`repair_questions` 内）：

1. 选项已存在 → AI 不得修改（精确匹配），任何变更（改/增/删）→ 拒绝。
2. 选项为空（解析器失败）→ AI 可从 raw_text 提取，这是有效修复。
3. 冻结题目总有非空选项 → 规则 1 覆盖。
4. 选项存在且 AI 返回空 → 拒绝（删除）。

### 2.4 能力解析

- `resolve_llm_runtime_config(db, capability=AICapability.AI_REPAIR)` 从 `admin_ai_model_configs` 解析活跃的 AI_REPAIR 能力配置。
- `db is None` → runtime=None，所有题目标记 `reason="ai_unavailable"`。
- 解析失败 → 优雅降级，不抛异常。
- AI 凭据经 `AI_CONFIG_ENCRYPT_KEY` 加密存于数据库，不经环境变量。

### 2.5 禁用与跳过

- `config["enabled"]=False` → 所有题目标记 `reason="ai_disabled"`，不调用 LLM，`total_tokens=0`。
- 高置信题目（≥ threshold）跳过；低风险跳过（`low_risk_skip_enabled`）对完整题目跳过。

## 3. 令牌预算模块

`token_budget.py`：

- `estimate_tokens(text)`：中英文混合估算（中文按字符、英文按词/4）。
- `_reset_counters_if_needed`：跨日/跨月重置进程内计数器。
- Redis 路径：`_keys()` 生成 day_key/month_key，`_redis_usage()` 读共享计数，`record_token_usage` 用 pipeline 原子写入。
- `_restricted()` 判断是否要求 Redis（生产/云画像为真）。
- Redis 恢复时记录 `"AI token budget resumed: Redis recovered"`。

## 4. 可执行基线

- `backend/tests/test_services/test_ai_repair.py`：`TestEstimateTokens`、`TestParseAIResponse`、`TestValidateRepaired`、`TestNormalizeAIOptions`、`TestShouldRepair`、`TestRepairQuestions` 覆盖令牌估算、响应解析、修复校验、选项归一化、修复判定和修复流程。
- `backend/tests/test_services/test_ai_repair_uses_admin_ai_config.py`：5 项测试覆盖 `call_ai_for_repair` 使用 `AICapability.AI_REPAIR`、无 db 回退、解析失败优雅降级、直接凭据跳过解析、批量和 Roman 路径均用 AI_REPAIR 能力。
- `backend/tests/test_services/test_ai_prewarm_protocol.py`：9 项测试覆盖被取代版本跳过 provider、匹配版本保留结果、缺失错题不调用、已生成跳过、回退为 typed failure、durable payload 到达 revision validator、worker 启动一次且 shutdown 取消任务。
- `backend/tests/test_services/test_ai_analysis_compatibility.py`：新增真实 SQLite 测试覆盖版本守卫漂移检测、签名匹配放行和缺失版本安全回退。
- `backend/tests/architecture/test_ai_prewarm_boundaries.py`：3 项架构测试覆盖 revision 模块依赖、生产者/验证器导入中性协议、fresh import 不加载 worker/ai_service/database。
- `backend/tests/architecture/test_question_ai_boundaries.py`：3 项架构测试覆盖归一化核心不导入 AI 入口、AI 模块可优先导入、AI 路由和 admin service 使用定义函数。

## 5. 未完成和未验证

- `analyze_error` 的真实 LLM 调用、多模态视觉证据输入和认证隔离超时恢复未在 SQLite 测试中覆盖，需外部 AI 服务可用后验收。
- `repair_questions` 的两阶段 Roman 决策真实执行、令牌预算 Redis 共享计数和 fail-closed 行为需 Redis 和 AI 服务可用后验收。
- `ai_service.py`（2301 行）的 `generate_advice`、`prewarm_wrong_question_analysis` 完整语义未在本文档登记，需单独基线。
- 真实外部 AI（OpenAI 兼容/DeepSeek/PaddleOCR-VL）、生产 Redis 令牌预算共享和加密凭据轮换仍待环境可用后验收。
- SQLite 服务路径测试不等于生产 PostgreSQL/Redis 查询计划或真实 AI 调用验收。
