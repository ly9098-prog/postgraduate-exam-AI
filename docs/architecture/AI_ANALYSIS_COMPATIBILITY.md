# AI 分析与修复执行兼容基线

2026-10-27 补充原因：登记模型故障分类与题目版本守卫的判定边界；先前分析结果投影与两次提交边界继续有效，区分本地替身/SQLite 证据和真实模型/生产验收。

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限错题 AI 复盘（`analyze_error`）、AI 修复（`repair_questions`）、令牌预算门禁和模型配置解析，不表示学习域、OCR 导入或全栈阶段 0 完成。

## 1. 错题复盘 `analyze_error`

入口 `GET /api/v1/wrong-questions/{id}/analysis` → `ai_service.analyze_error(db, user_id, wrong_question_id, force_regenerate)`。

### 1.1 版本守卫（revision guard）

教学上下文跟随当前题库投影（学习者看到的版本），但以不可变 wrong-attempt 版本做安全边界：

1. 查 `WrongQuestion`（user_id + wrong_question_id），不存在抛 `ValueError`。
2. 查当前 `Question`，不存在抛 `ValueError`。
3. 构建 `current_answer_grounding`（当前版本的 question_type/content/options/answer/user_answer）。
4. 两个版本 ID 分别按 `int(value or 0)` 转换，均非零且不相等时查历史版本；查询同时要求 `QuestionVersion.id == wrong_version_id` 与 `QuestionVersion.question_id == wrong_question.question_id`。构建 `historical_grounding`，比较 `grounding_fact_signature`。
5. 历史版本缺失或签名不匹配 → 返回 `revision_guard` 结果：`content=build_revision_drift_analysis()`、`model="revision_guard"`、`tokens_used=0`、`revision_guarded=True`，不调用任何 LLM。

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
- `generate_advice`、`prewarm_wrong_question_analysis` 的独立基线见 `AI_ADVICE_PREWARM_COMPATIBILITY.md`；其中真实模型与生产环境未验收项仍适用。
- 真实外部 AI（OpenAI 兼容/DeepSeek/PaddleOCR-VL）、生产 Redis 令牌预算共享和加密凭据轮换仍待环境可用后验收。
- SQLite 服务路径测试不等于生产 PostgreSQL/Redis 查询计划或真实 AI 调用验收。

## 6. 分析执行拆分与回归入口（2026-10-26）

- `ai_service.analyze_error` 保留准备阶段及原服务端口，随后进入 `analysis_orchestration.execute_locked_analysis`。编排先获取生成 lease，无法获取时返回生成中响应；获取成功后依次复查锁内缓存、准备输入、调用 provider、复核结果和选择终态，finally 释放生成状态及 lease。
- `analysis_review_invocation.py` 分开装配调用、结果复核和终态选择；实际 runtime、模型签名、图像、答案 grounding、usage、失败响应和持久化回调继续来自原 request。历史公开导入和 monkeypatch 入口保留，拆分不改变缓存、鉴权隔离或结果入库规则。
- CI static 清单已包含 analysis content、execution、invocation、outcomes、preparation、response contracts、result review、validation，以及 prewarm execution/transition 测试。它们覆盖本地替身执行契约，不调用真实模型。
- `test_ai_prewarm_boundaries.py` 的真实生产者集合跟随批量提交编排移至 `practice.batch_submission_flow`，仍要求所有生产者使用 `app.ai.prewarm_revision` 中性协议，并禁止从 worker 导入该协议。
- 服务与新编排入口经 AST 复核均不超过当前批次的 80 行预算，不表示所有内部模块均达到 50 行规范。真实模型、多模态和 Redis 故障恢复等验收项仍按第 5 节记录。

## 7. 响应内容递归解析（2026-10-26）

- `analysis_content._extract_analysis_fields` 从 84 行拆为形状分派、列表择优、字段内嵌结构解析和字典候选编排，均留在原模块，递归仍动态调用原模块入口。辅助函数不增加递归深度；原公开导入的函数身份保持不变。
- 保留深度上限 6、字段别名顺序、同分首项、列表及内嵌字段完整遍历；嵌套字典仍先快照 wrapper 与其他字段，再递归搜索，首次取得三字段完整结果时停止。内嵌结构优先于直接文本，不合并来自不同候选的字段。
- 新增 53 项刻画与原兼容 43 项在拆分前后均通过；输出差分 10,500 次、原有解析与校验端口调用轨迹 250 组一致。包含缓存、视觉缓存、响应和 SQLite 兼容的相关测试 186 项通过；另补自动架构检查，约束全部函数不超过 50 行、仅导入标准解析模块及 fresh import 不初始化模型/数据库/AI 服务。
- 本批没有调用外部 AI。当时文件仍为 411 行，超过 300 行文件规范；该文件预算在后续第 8 节处理，完成函数拆分不能作为整个 AI 域或全栈预算门禁完成的依据。

## 8. 文本语法与作答核对职责（2026-10-26）

- `analysis_content.py` 保留内容候选择优、历史函数定义及原模块 globals；`analysis_text_syntax.py` 承接代码围栏、结构化文本探测/解码及标题解析，`analysis_answer_check.py` 承接作答核对遍历、答案归一及比对。三个业务模块分别为 270/95/111 行，最长函数 40/33/42 行。
- helper 通过原模块实时端口读取解析器、别名、递归函数和校验函数，保持遍历中途 monkeypatch 的生效时点；历史导入身份、`__module__`、函数 globals、深度上限 6、原结果引用、字段优先级和缺失端口的 `NameError` 保持原语义。门禁同时约束三个模块的尺寸、导入和 fresh import。
- 新增 41 项刻画；修改前首次 135 项通过，最终专属契约在保存的原实现重放 137 项通过，新版相关解析/缓存/视觉缓存/执行/架构回归 244 项通过。作者原/新对照 10,522 组结果与异常、630 组动态端口轨迹一致；未调用真实外部 AI，不据此认定整个分析执行域验收完成。

## 9. 分析结果投影与持久化边界（2026-10-26）

- `analysis_persistence.persist_repaired_analysis` / `persist_valid_analysis` 保留原 async 签名、历史导入和原模块 globals；结果/元数据装配及 snapshot 扩展移入 `analysis_persistence_projection`，原入口继续持有 ORM 赋值、第一次 commit 和 `_append_analysis_chat` 调用，后者仍负责 add AiChat 及第二次 commit。没有合并事务、增加 rollback 或改变异常/取消传播。
- valid 在调用方传入的 parsed 上原地合并 mistake_diagnosis 并覆盖 `_meta`，随后将同一对象赋给 WrongQuestion；repair 使用 grounding builder 返回的 safe 对象，保留 grounding_guard/source_model/reason 及 generated_at 返回约定。时钟、元数据、grounding merge、snapshot 等历史端口仍按原表达式时点读取，repair 的 grounding builder 仍为函数内导入。
- 第一次提交成功后才构造 snapshot 和 AiChat；后续 snapshot、构造、add 或第二次提交失败不撤销第一次提交。本函数不替调用方回滚。metadata、视觉输入计数/证据/重试、签名、force、token 和耗时字段保持原投影。
- `build_context_snapshot` 是 `dict(context)` 浅复制，再覆盖四个视觉观察字段，并非主动过滤 base64/URL 的安全清洗器；调用方须保持原上下文输入边界。本次不新增过滤策略，也不声称原注释已实现任意上下文的敏感内容过滤。repair 的 guard 快照保留 expected/actual answer check 的原引用。
- 新增 persistence contract/ports/database 三组测试与架构门禁接入静态 CI。fake DB 刻画引用、动态替换、求值顺序和失败/取消；隔离 SQLite 验证成功写入及第二次提交失败后调用方回滚仍可读到已提交分析、无已提交聊天记录。它们不调用真实模型，不代表生产 PostgreSQL、Redis、凭据轮换或完整 worker 验收。

## 10. 持久化后的日志与响应发布（2026-10-26）

- `analysis_outcomes.grounding_repair_outcome` / `valid_analysis_outcome` 保留原 async 签名、定义时绑定的默认 persist 回调和 await 参数求值；仅在保存成功后进入 `analysis_publication` 的同步日志与响应组装。保存失败或取消时不发布，不新增重试、事务或回滚。
- 发布继续读取保存回调修改过的 usage、result、parsed、grounding 和图像列表，保留 safe、generated_at 及 parsed 等对象引用。日志方法先绑定，再求值视觉校验和字段观察参数；校验回调可修改后续观察值，日志回调可替换本次响应构造器。原模块 bool、len 和响应函数端口按原表达式时点读取，并保留 globals 到 builtins 的查找行为。
- 日志或响应构造失败继续向调用方传播；已经成功完成的保存不会由发布函数撤销。真实保存的两个提交边界仍由第 9 节的持久化入口负责。
- 新增 publication contract/ports 与架构门禁接入静态 CI，覆盖失败、实际任务取消、回调修改、端口替换和无数据库/运行时导入副作用。原实现重放和本地替身回归用于兼容性验证，不代表真实外部模型、完整 worker 或生产验收。

## 11. 模型故障与版本漂移判定（2026-10-27）

- `provider_exception.classify_ai_provider_exception` 保留公开签名，在原模块内分别提取认证、限流、暂态故障的判定函数。仍先转换文本、读取 error_kind/retryable 并解析状态，再按 auth → rate limit → transient → model not found → request incompatible → vision → generic 的顺序选择完整三元组；类型、状态和文本信号冲突时也遵守此顺序，不新增重试或模型调用。
- 有效 typed status 优先于消息中的状态码；仅状态转换的 TypeError/ValueError 回退正则，其余错误传播。已知分类不对 typed retryable 做 bool 转换；只有 generic 分支使用它。判定 helper 使用布尔分支返回字面 True/False，保持短路和每个自定义比较结果仅一次真假判断；`_contains_any` 等原模块端口仍在对应表达式处实时读取。
- `revision_guard.check_analysis_revision_drift` 继续持有 logger 获取、current grounding、版本转换、唯一历史查询和 warning；历史语义比较及完整守卫响应留在同模块的私有 helper。current grounding 在查询前形成，历史字段、当前题型回退及 wrong_answer 在查询返回后读取。两次 grounding signature 仍分别查找函数；历史版本是否存在用 `is not None`。
- 语义不匹配时先 warning，再调用文案 builder，最后取 UTC 时间；这些回调替换后续端口的行为保留。响应 content 保留原返回对象引用。取消、数据库查询或 builder/signature/logger/clock 错误均传播，不新增 session、事务提交、回滚或异常吞并。
- 新增故障分类、版本守卫和动态端口契约，并将它们、架构门禁及既有 provider classification/invocation 测试接入静态 CI。门禁约束两模块的函数预算、原签名、依赖与逐函数调用权限，禁止判定/响应 helper 查询、写库或修改调用方对象。合成分类组合、隔离 SQLite 和任务取消证据不等于外部模型、生产数据库、凭据隔离超时或完整 worker 验收。

## 12. 准备阶段与持锁执行职责（2026-10-27）

- `analysis_preparation.prepare_analysis` 保留错题/题目查询、版本守卫和缺图短路；同模块 `_prepare_material_analysis` 承接材料加载、grounding、输入/模型签名、初次缓存决策和准备结果。知识点仍先于 runtime，runtime 先于 grounding，缓存回调和日志之后才读取最终 force 值；传入内容、选项、知识点、视觉源与返回对象保留原引用。
- `analysis_orchestration._execute_with_lease` 保留锁内缓存和输入的两处提前返回、原 context 的 `answer_grounding` 写入以及 invoke→resolve 顺序；同模块 helper 分别装配锁内缓存复查和输入准备参数。原函数、模块 globals 和异步签名保留，锁内刷新后的签名继续传给 provider 与结果处理。
- 外层 `execute_locked_analysis` 仍独占 lease 获取与 finally 释放；获取失败或返回 `None` 不进入清理，获取成功后各阶段失败/取消仍清理。finally 按执行到清理时的 request 读取 ID、generating 和 cache，不新增快照、shield、重试、提交或回滚。清理异常覆盖原失败并保留异常上下文的行为也未改变。
- 两模块分别为 249/162 行，全部函数不超过 50 行。新增准备时序、持锁串联契约及预算/依赖/调用门禁接入静态 CI；原版重放 56 项通过，覆盖 falsey 提前响应、参数/引用、端口晚替换、普通异常、取消和真实任务取消。原 force 测试改为调用前安装缓存失败哨兵，实际证明强制生成不访问缓存。
- 无回调修改的串联测试在执行前固定参数预期并保存 request 字段引用，防止错误改写 request 后连预期一起漂移；允许的 runtime 替换使用显式预期。门禁拒绝受信调用名的局部重绑定、导入别名及非原 context 写入，并用数据库提交伪装、request.db 覆盖等负对照验证拒绝能力。
- 结果复核/终态选择的 `review_analysis_result`、`resolve_analysis_outcome` 仍有函数预算债务，未在本批修改。真实外部 AI、多模态、生产 Redis/数据库和完整 worker 验收仍按第 5 节保留。
