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
- 当时结果复核/终态选择的 `review_analysis_result`、`resolve_analysis_outcome` 仍有函数预算债务，后续在第 13 节处理。真实外部 AI、多模态、生产 Redis/数据库和完整 worker 验收仍按第 5 节保留。

## 13. 结果复核、终态选择与视觉参数修复（2026-10-27）

- `analysis_result_review` 的公开异步签名保留；`_make_review` 在视觉复核之后组装结果及 ack 判定，构造器仍先于 ack 回调绑定。解析、初次有效性判断、usage 创建、视觉请求构造与 reconcile 的顺序不变，ack 读取 reconcile 更新后的同一 usage，原 result、parsed、图像与 grounding 引用不复制。
- `_OutcomeArguments` 是同模块私有 slots 数据对象，仅保存原始参数引用，不读取 review 的属性。同步 early helper 按 ack 非 None → 解析失败处理，并用独立 handled 标志保留 callback 返回 None/空字典的行为；异步 grounded helper 再选择修复或有效结果。属性读取次数、未选分支不读取、callback 先绑定再求值参数、解析失败响应先于日志及异常/取消传播保持原轨迹，不新增重试、回滚或清理。
- 本批另修复一个既有执行缺陷：原 repair/valid 分支均未向真实 `grounding_repair_outcome` / `valid_analysis_outcome` 转发必需的 `image_data_urls`，会在参数绑定时 TypeError，无法进入保存；文本空列表同样受影响。现两分支传入原列表，恢复真实 outcome、视觉计数和持久化链路。这是明确的行为修复，不能把本批整体称为纯兼容拆分。
- 新增严格真实回调签名、默认 outcome/persist 执行与隔离 SQLite 回归，包含 0/1/2 图像输入、正常两次提交及第二次提交失败后的持久性。SQLite 验证分析第一次提交仍可读，失败的聊天提交经调用方回滚后不可读；不改变原有两个提交边界。
- 修改前原实现通过 106 项时序/端口/读取契约；针对缺参的 8 项严格回归在固定原实现失败，错误为缺少 image_data_urls。后续对照参考仅向原两个调用各补这一参数，以隔离参数修复与职责提取。源码为 239 行，全部函数不超过 50 行；新增契约、数据库回归、签名/预算/依赖/原始引用捕获门禁已接入静态 CI。
- 本地重放完整静态 CI 步骤为 5,130 项通过；此后测试审查加固，最终相关回归 139 项通过，仅补两处参数的原版参考重放 124 项通过。加固包含 parse 的 None/空字典响应、中间回调原始引用以及嵌套定义重绑定负对照；5,130 项结果不代表重新执行了加固后的完整步骤。
- 上述为本地替身和隔离 SQLite 证据，不代表外部模型、多模态真实输入、生产 PostgreSQL/Redis、完整 worker 或用户端验收；这些仍按第 5 节保留。

## 14. 学习报告生成与规则降级拆分（2026-10-28）

- `ai_learning_service.generate_learning_report` 从 224 行收敛至 49 行，拆为
  `_load_learning_report_subject`（13）、`_load_learning_report_records`（22）、
  `_empty_learning_report`（13）、`_knowledge_point_accuracy_list`（26）、
  `_report_weak_points`（10）、`_report_strong_points`（10）、
  `_low_volume_learning_report`（27）、`_token_limited_learning_report`（28）、
  `_ai_fallback_learning_report`（23）、`_project_parsed_report_points`（22）、
  `_ai_learning_report`（44）、`_learning_report_metrics`（12），全部满足 300/50 预算。
- 语义保持：科目头一次读取（缺科目时代码/名称为空串）；`since = utcnow() -
  timedelta(days=days)`；记录仍只投影 `(question_id, is_correct)` 并过滤 user/subject/
  `answered_at >= since`、按 `answered_at DESC` 排序（刻意不 hydration 完整 ORM）；
  `total == 0` 直接返回空报告；accuracy 为 correct/total；知识点按记录×知识点累计后
  以 accuracy 升序排序；`total < 5` 走规则报告（weak `< 0.6` 前 3 条“数据不足…”、
  strong `>= 0.85` 前 3 条“继续保持”、tokens 0、`from_fallback=False`）；不足 5 条
  之外且 token 限额被拒时走另一套规则文案（weak `< 0.6` 前 5 条“建议重点复习该知识点”、
  两条学习建议、`from_fallback=True`）；模型返回 None 时改用全局
  `get_fallback_report()` 三列表（缺省空列表）；模型成功时解析 JSON（解析失败把回复
  文本作为唯一建议）、按原 label 记录 token 用量、weak/strong 逐项归一化（缺省
  `""`/`0`）、suggestions 原样透传、`tokens_used` 取模型返回值、`from_fallback=False`。
  各分支响应字典的字段与键序保持原字面量，不重排 JSON 输出顺序。
- 13 项固定契约在拆分前的原实现（AST 提取原函数运行，`/tmp/ai-learning-report-contracts-original.log`）
  与拆分后均通过，覆盖空记录短路与调用顺序、缺失科目、查询列/过滤/排序/窗口参数、
  低量规则文案与配额（weak 3 / strong 3）、恰好 5 条进入 AI 路径、token 拒绝规则
  文案与配额（weak 5 / strong 3）、模型不可用全局回退、AI 成功投影与用量记录、
  不可解析回复、知识点聚合排序与 prompt 入参。
- 23 个故障变体全部被拒绝（证据 `/tmp/ai-learning-report-mutants-_xweisgs`），覆盖空
  报告文案/计数/标志、查询排序/窗口/列/时间参数、weak 与 strong 阈值、两套规则配额、
  低量标志、token 阈值与入参、prompt 参数顺序、回退键选择、逐项缺省、不可解析建议、
  用量 label、最终 tokens、知识点集合与 accuracy 除法。
- 反向展开十二个 helper 并按七项已记录归一化（科目头、记录查询、空报告、指标与聚合、
  弱/强投影、三条规则分支、模型结果投影与用量持久化）后，入口函数与原实现 AST 一致；
  本模块其余定义不变（`/tmp/ai-learning-report-ast-report.json`）。
- 3 项架构门禁（`tests/architecture/test_ai_learning_report_boundaries.py`）约束十三个
  函数的预算、入口不再内联 select/db.get/记录持久化、加载与聚合顺序、两套规则文案与
  配额单点、AI 成功路径顺序，含“把 select 内联回入口”“放宽低量规则文案”两项反向
  自检。
- 定向回归：`tests/test_services/test_ai_*.py` 与 `tests/architecture/test_ai_*.py`
  合计 975 passed。严格 Ruff/format、compileall 与 diff-check 通过。
- 冻结业务、测试与 CI 清单后，本机按当前 YAML 的静态步骤精确重放 412 个测试文件：7002 passed、0 failed、64 条既有弃用 warning，449.73 秒；Mocked readiness boundary regression 69 passed；Cloud OCR profile boundary regression 30 passed。这是本地清单重放，不代表远端 CI 或生产验收。
## 15. 题目讲解、错因分析与相似推荐拆分（2026-10-28）

- `ai_explain` 从 91 行收敛至 49 行，`ai_analyze_mistake` 从 90 行收敛至 47 行，
  `recommend_similar_questions` 从 113 行收敛至 34 行。共享题目装载、题干投影、
  讲解/错因 payload、prompt 构造、向量推荐、规则推荐加载/评分/选择/投影分别拆入
  私有 helper；本模块全部函数均不超过 50 行。
- 语义保持：仅查询 active 题目，缺失时仍抛 `ValueError("题目不存在")`；dict 与旧
  content 形态的题干提取一致；讲解 token 门槛仍为 500，错因分析仍为 300；限额与
  模型不可用响应保持原字段、空列表、`tokens_used=0`、`from_fallback=True` 和原
  文案；模型成功路径仍先解析/补默认值、记录 `ai_explain` / `mistake_analysis`
  用量，再返回模型 payload；错因 label 映射与缺省 `未知` 不变。
- 相似推荐保持向量优先：仅当向量结果 `enabled` 且非空时返回
  `strategy="vector_plus_rule"`；禁用、空结果或异常均回退规则推荐，异常日志仍为
  `向量推荐异常，回退到规则推荐`。规则路径仍排除已答题目和源题，候选仍要求同
  subject family、active、approved；评分仍为 `kp_overlap * 2 + difficulty_match`
  且仅保留 `score > 0`，先按分数降序取前 N，再 `random.shuffle`；响应字段、
  `strategy="rule_based"`、`tokens_used=0` 与“同知识点 / 同难度 / 同科目”投影
  保持不变。
- 新增 `tests/test_services/test_ai_learning_detail_contract.py` 8 项契约，覆盖讲解
  成功/限额/回退、错因成功/限额、向量 envelope 与异常回退、规则查询评分投影，以及
  `_similar_recommendation_payload` 的历史“同科目”分支。该分支在公共规则入口因
  `score > 0` 前置条件实际不可达，测试直接锁定 helper 边界，不虚构公共入口行为。
- 原实现对照差分 9 组通过（`/tmp/ail-batch/differential-results.json`），覆盖讲解
  成功/限额/回退、错因成功/限额、向量命中/异常回退、规则排序与题目缺失；每组在固定
  随机种子下比较响应、异常和端口调用轨迹。8 个语义变体均产生可观察差异或异常
  （`/tmp/ail-batch/mutant-results.json`），覆盖讲解/错因文案、向量策略与回退日志、
  已答排除、评分公式、排序方向和推荐理由。AST 证明 17 个未拆分定义完全不变，原 38
  个模块语句保持原相对顺序（`/tmp/ail-batch/ast-proof.json`）。
- `tests/architecture/test_ai_learning_report_boundaries.py` 扩展为 4 项门禁，约束
  三个入口与全部新增 helper 的 50 行预算、入口委托顺序、讲解/错因/推荐入口不内联
  查询或 prompt 构造、向量开关与异常回退、已答排除、候选过滤、评分公式、排序与
  shuffle、投影字段和规则 envelope；并含内联查询、缺失 shuffle 两项反向自检。
  新契约已加入 `.github/workflows/ci.yml` 静态清单。
- 本批为本地替身契约与 AST 门禁验证，不调用真实外部模型、Redis 或生产服务；第 5
  节的外部 AI、生产 PostgreSQL/Redis、完整 worker 和真实多模态验收仍保留。

## 16. MP-16 小程序 AI 消费链保留评估（2026-10-30）

本项范围是当前小程序五条消费契约：`POST /ai/error-analysis`、`GET /ai/error-analysis/status/{id}`、`POST /ai/error-analysis/recover`、`POST /ai/408-teacher`及`POST /ai/feedback`。调用站点、可能所属页面和精确路由归属来自既有消费者映射；可能可达不等于每页实际执行。

保留既有分析准备/lease/执行/结果复核/两次持久化与发布职责。教师service拥有固定动作、考试防泄题、用户历史版本事实、知识上下文、模型调用及动作降级；已有文本清洗、结构化解析、生成题校验和响应规范化辅助函数可独立调用。1234行service及213行入口本身不构成新的结构缺陷，现阶段保留同域查询所有者和安全/调用顺序，不为历史长度继续拆分。反馈路由仅负责构造日志并提交，保持原样；没有修改业务、schema、数据库结构、客户端、helper查找或事务语义。

本轮补充两份持久化测试文件：

- `test_ai_teacher_request_contracts.py`在固定准备替身上调用真实教师入口及规范化函数，核对服务端事实、答案来源优先级、模型参数、额度拒绝、成功provider先调用用量记录再解析、格式异常/无效生成题仍计用量，以及provider取消和用量回调失败的原传播。用量证据针对回调时序，不冒称真实模型或用量数据库写入验收。
- `test_ai_consumer_contracts.py`使用专属FastAPI应用和临时SQLite；仅复用既有隔离建库工厂，自行种植canonical408科目。核对历史版本必须有当前用户练习事实（他人历史不放行）、四个答案型入口的进行中考试409、三类错题入口所有权404、缓存状态、恢复revision/force/baseline及重试参数、生成协议与反馈持久提交。provider/分析生成/队列默认失败替身，只有对应协议测试局部替换；不调用外部模型、真实Redis或开发数据库。

两份测试均加入固定CI清单。既有`test-408-ai-teacher.js`修复旧练习结果页内联API位置假设，改查现有适配层及固定版本controller；原整体展开断言改为当前复盘卡片三类手势绑定和更多动作默认收起检查，未修改UI。原`test-408-feature-integration.js`在本轮前即因storage中的旧studyStrategy源码位置失败，原文件/运行时均未改，记录至SHR-03门禁治理；不据本轮测试声称所有小程序脚本均通过。

精确测试、源码冻结、独立审查与提交状态见[结果清单](refactor-results/miniprogram-ai-retention-2026-10-30.json)。本项结论仅用于当前消费者结构处置；真实JWT/微信、多模态/外部模型、PostgreSQL/Redis并发、完整worker与生产仍在最终环境验收阶段，不由本地HTTP/SQLite/替身结果替代。

## 17. 错题详情 AI 失败后持续加载修复（2026-11-01）

用户提供的日志显示：19:42:00 发起强制生成，模型请求在 277 ms 内收到 HTTP 403，
没有可用备用模型；接口随后在约 495 ms 因 `'dict' object has no attribute 'result'`
异常结束，客户端却继续提交恢复任务并查询状态，至少持续到 19:43:15。
错题详情请求本身耗时 20 ms，日志不足以支持“模型生成慢”的结论。

- `invoke_prepared_analysis` 的成功结果是 `ProviderInvocationResult`，失败或保留缓存时
  返回已组装好的响应字典。`analysis_review_invocation` 现识别该字典并直接传递到终态，
  跳过仅适用于模型成功结果的 review/runtime 读取；外层 finally 仍负责释放租约。
  鉴权、限流、暂态故障、超时及重新生成失败保留缓存均遵守此边界。
- 小程序原先对所有请求异常无差别入队并执行 44 次状态轮询，仅轮询间隔就累计
  180 秒。现首次生成和重新生成共用纯规则 `_shouldRecoverAiRequest`：
  传输响应丢失或 HTTP 408/502/504 保留恢复，明确 HTTP 失败立即结束加载。
  重新生成失败时保留旧卡片、解析和生成时间；规则通过 Page 的能力参数传入，
  保持子模块不直接依赖传输层的架构约束。
- 回归覆盖真实 provider 调用编排、失败响应 schema、缓存保留、租约释放，以及
  隔离 FastAPI/SQLite 中的真实 `analyze_error` 服务链；模型、额度和缓存基础设施
  使用合成替身。小程序通过真实 Page 包装验证 HTTP 失败零恢复/零轮询及断网恢复。
  测试扩展在既有 CI 清单文件内，无新增测试文件。

403 是上游鉴权或权限拒绝，日志未包含可判断具体原因的供应商响应体，不能据此断定
一定是 API Key 错误。实际生成恢复仍需核对 Admin 中对应模型的凭据、Base URL
和服务调用权限。本次代码验证不等于真实模型、微信真机或生产部署验收。

## 18. 错题 AI 共享健康门禁与自动探测（2026-11-01）

在 §17 修复“明确失败后继续加载”的基础上，新增面向错题 AI 分析与 AI 老师的
共享可用性门禁。目标不是把所有模型错误永久转成前端错误，而是只在额度不足、
鉴权/权限、模型配置、限流或暂态故障使当前候选模型不可验证时停止新的模型调用；
已有分析和对话继续可读。

- 后端新增 `model_health`、`analysis_availability`、`analysis_admin_health`。
  健康状态按 `model_config_id + config_fingerprint` 存入 Redis，所有用户共享；
  配置内容或凭据变更会自然切换到新的指纹，不继承旧配置的成功状态。
- 页面首次检查或成功状态过期时执行一次真实 `chat/completions` 探测。成功状态
  共享 30 秒；临时故障退避 `30/60/120/300` 秒；额度、鉴权或模型不存在冷却
  5 分钟。并发请求通过 Redis 锁合并为一次探测，避免每个用户同时打上游模型。
- `resolve_available_runtime` 会按现有分析模型顺序寻找可用候选。已有健康备用模型
  时优先复用，不因主模型故障阻断全部用户；只有候选均不可用或正在探测时才禁用。
  页面查询还会单独检查当前用户 token 额度，`user_quota` 不改变全局模型健康状态。
- 后端首次探测返回 `checking` 时携带 `retry_after_ms=2000`，前端按 2 秒重查；页面网络
  传输自身超过 5 秒时只结束检查动画，保留禁用状态并继续自动重查，不把仍在进行的探测
  当成业务失败。成功状态由后端共享 30 秒。
- `provider_invocation` 在业务请求前再次验证当前 runtime。未通过时返回
  `ai_service_unavailable` 和同一 `availability` 状态，不发业务模型请求；真实
  调用中的额度、鉴权、限流和暂态异常继续记录到共享状态。额度不再混同普通限流。
- 错题分析缓存命中仍直接返回，不因全局禁用丢失历史内容；生成或强制重新生成不可用
  时保留旧解析并标记 `cache_preserved`。AI 老师通过同一门禁检查，不可用时返回
  HTTP 503 的结构化 `detail.code=ai_service_unavailable`；小程序老师面板直接展示
  该结构化原因，已有老师结果不被清除。
- 管理员更新会影响错题 AI 路由的已保存模型字段后立即强制探测。只有
  `POST /ai-models/test-connection` 携带相同 `model_id`，且 Base URL、API Key、
  模型名、Provider 与能力集均匹配已保存配置时，测试结果才更新共享健康状态；
  未保存表单修改不能解锁用户功能。管理员测试与错题分析使用同一候选解析链，
  不会出现测试通过但实际分析选中另一套模型顺序的情况。
- 小程序详情页加载时调用 availability API，检查动画最多 5 秒；超时只结束动画，
  action 继续禁用并按 `retry_after_ms` 自动重查。success 后恢复“生成/重新生成/
  AI 老师”，失败时显示简短原因，已有卡片、解析、老师和普通错题功能不删除。
- 新增后端可用性回归已登记到 `.github/workflows/ci.yml` 静态测试清单及
  `.github/workflows/reliability.yml` 的固定 reliability 清单。

验证边界：后端 AI 定向回归 `1083 passed`，包含共享状态、备用模型、额度/鉴权
分类、缓存保留、availability API 和老师 503；Ruff（项目已登记的
I001/F401/N818 债务除外）、compileall 与 diff-check 通过；formatter 仅报告
`ai_service.py` 既有空行差异，未在部署后改写该文件以保持源码 SHA 一致。小程序全量
`node --test tests/*.js` 为 `2557 passed`，5 个渲染 fixture 共 31 项通过。
这些测试使用替身或临时缓存，不等于真实微信开发者工具、真机、生产 Redis 或真实
上游模型成功链路验收。部署和生产探针结果另见
[结构化结果](refactor-results/wrong-detail-ai-availability-2026-11-01.json)。

## 19. 可用性实现的内聚与耦合复核（2026-11-02）

按 `docs/development/coding-style.md` 与 `development-workflow.md` 对 §18 新增代码
进行复核，并修复以下职责与行为问题：

- Admin 模型 CRUD 保留在 `admin_ai_config_service`，连接诊断移至
  `admin_ai_model_test_service`；原服务由 882 行降至 626 行。连接测试模块 325 行，
  按目标解析、凭据读取、Embedding/Paddle 分支和 Chat 探测划分小函数。
- `connection_probe` 177 行，共用 URL 校验和最小 Chat 探测；额度错误标记集中在
  `app.ai.provider_error_signals`，传输层与错误分类层复用，避免重复维护。
- Admin 探测使用公开 `list_analysis_candidates`，不再调用可用性模块的私有函数。
  配置提交后的探测为 best-effort，数据库查询或健康存储故障记录 warning，
  不改变已经完成的保存结果；实际等待时长用于 Admin 测试延迟。
- 真实业务请求遇到 `model_not_found` 时写入共享配置错误状态并冷却 5 分钟。
  非取消探测异常保留日志；`ai_service` 使用 `dataclasses.replace` 构造新准备对象，
  请求和端口构造由小函数承接，主入口只负责门禁与编排。
- 小程序检查中只更新五个可用性字段，不复制整个 Page data。结构化失败状态直接
  应用并保留重试计划；未携带 availability 的普通失败才刷新健康状态。
  禁用状态的静默定时重查持续按冷却时间排程，直到探测成功；API 错误适配只提升
  `ai_service_unavailable`，不泛化接受其他端点的 detail code。

本批新增模块均小于 800 行、新增函数均小于 50 行。既有 `ai_teacher_408_service`
1244 行、`ai_service.evaluate_cached_error_analysis` 及 Admin CRUD 长函数不在本批新增
重构范围，不宣称整个 AI 领域已满足所有文件/函数预算。匹配缓存失败响应的原地补充
是既有兼容契约，本次保留。

验证：后端相关回归 1435 项通过，小程序全量 2564 项通过，5 个渲染 fixture 共 31 项
通过；错题详情边界、页面预算、compileall、workflow YAML 和 diff-check 通过。
运行代码 Ruff 正确性检查通过；唯一保留的严格 lint 债务是 `ai_service.py` 的 21 个
既有兼容导入 F401，变更文件债务计数未增加，新增模块严格 Ruff 通过。
真实生产模型调用、微信工具编译与真机链路仍未验证，部署证据另记。

本轮代码已提交 `9742993a`，并于2026-11-02 03:17（Asia/Shanghai）完成三个后端角色部署，
运行的18份源码逐容器与提交一致，限定健康/schema检查通过，见
[本轮部署记录](../project/PRODUCTION_AI_MODEL_HEALTH_REVIEW_DEPLOY_2026-11-02.md)。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/ai/AI_PIPELINE.md|AI_PIPELINE]] — AI 管线
