# 重构执行记录 · 第 03 卷

> 原记录编号：§205–§304；100/100 批次。保留原编号和原文顺序，合并标题按覆盖编号计数。历史状态不代表当前验收结论。

[任务入口](../current_task.md) · [原计划](plan.md) · [上一卷](history-02.md) · [下一卷](history-04.md)

<!-- original-history:start -->

## 二百零五—二百一十：批次副作用/响应清理/导入失败/预热取代/遗留薄弱向量（2026-10-26）

六批连续提交：

1. `6d1bd9ef` + `612c8c88` — 新增 `app/services/practice/batch_persistence.py`：PracticeRecord 创建与 flush、错题入库、诊断 payload、投影 outbox 的事务内副作用由 ports 承接；service 保留事务边界与回滚。新增 2 项契约测试，88 项 practice/API/顺序预约测试通过。
2. `272979a2` — 新增 `batch_response.py` 与 `batch_reservation_cleanup.py`：canonical 响应构造/顺序预约清理条件独立；4 项契约测试，88 项相关测试通过，`batch_submit_answers` 298→248 行。
3. `8e0bac3e` — 新增 `app/services/import_background_failure.py`：通用导入后台崩溃后的 checkpoint、pipeline store 与 Sentry 捕获统一；2 项契约测试，50 项导入/admission/architecture 测试通过，`_run_pipeline_with_db` 124→104 行。
4. `ab8aa016` — `prewarm_transition` 新增 `revision_changed` / `recovery_regenerated`；3 项取代判断测试，15 项 prewarm/architecture 测试通过。
5. `1d3f124f` — 新增 `app/services/practice/legacy_weakness_vector.py`：legacy weakness-vector 分支的薄弱知识点、向量召回、策略重排、KP/random 补齐与 finalize 迁移为 ports 编排；service 保留同名薄入口。3 项新契约 + 既有 smart weakness/pipeline/service/API 测试共 89 项通过，`practice_service` 超限项 4→3，262 行 legacy 方法清零。

- 当前后端剩余超限：`ai_service.analyze_error` 427、`prewarm_wrong_question_analysis` 93、`practice.get_smart_practice_questions` 113、`get_smart_scored_questions` 183（受 5 个 AST 架构门禁固定入口）、`batch_submit_answers` 248、`import._run_image_pipeline_with_db` 177、`_run_pipeline_with_db` 104。
- 本轮所有测试均为本地 SQLite/mock/单元证据；未推送、未部署、未操作数据库。真实微信、外部 OCR/AI、生产 Admin、Redis 故障恢复、完整 worker、备份恢复演练仍未验证。

## 二百一十一、AI/学习/导入续作批次（2026-10-26）

- 本轮延续兼容重构并本地提交 9 批：`8ffbb264` 预热执行、`22e7f6a6` 分析准备、`cf24cdb2` 导入来源摘要、`e89d805e` 智能分支适配器、`5d3d98b1` 通用导入后台执行、`9212b73c`/`a85dbfd9`/`2651cffa`/`08d96e4d` 图片导入准备、流水线、完成与失败持久化。
- 新契约均使用注入端口保留原调用方/日志/事务语义：预热执行保留 service 属性 monkeypatch 与函数内 `async_session` 导入；分析准备保留 revision guard、视觉 fail-closed、缓存命中/miss 与 force 日志；图片导入保留双 checkpoint、OCR 状态、pipeline 会话、完成/失败投影和资源清理归属。
- 验证通过：AI 相关 54 项、practice/smart 95 项、导入/admission/architecture 56 项；相关 Ruff、新文件 format、compileall、`git diff --check` 均通过。现有剩余超限：`analyze_error` 365、`get_smart_scored_questions` 183、`batch_submit_answers` 248、`get_smart_practice_questions` 83、`_run_image_pipeline_with_db` 158。
- 本轮未修改小程序页面本体、管理端页面和任务队列实现；真实微信、外部 OCR/AI、生产 Admin、Redis 故障恢复、完整 worker、备份恢复演练仍未验证，不能以本地 mock/静态测试冒充。


## 二百一十二、AI/学习/导入续作与页面预算门禁（2026-10-26）

- 本轮继续按用户优先级推进并本地提交 8 批：`86cdf211` 分析结果收尾、`ec718ee4` 分析生成执行、`9c9a4027` 提供方失败回退、`1248e8f6` 练习批量 claim/commit、`192d7c73` 图片阶段执行、`6e161853` 学习/考试/统计页面预算门禁、`2bda924f` 学习闭环文档状态同步、`8ea6bd44` 分析结果复核。
- AI 契约新增 `analysis_outcomes.py`（视觉 ACK 失败、grounding repair、成功持久化与结果日志）、`analysis_execution.py`（本地/跨进程生成锁、锁后缓存复核、锁后输入准备）、`analysis_provider_failure.py`（force 失败保留旧缓存/普通 fallback）。`GroundingValidation` 正式携带 `answer_grounding`。`analyze_error` 365→258→192 行；provider 后解析、视觉校验与终态选择进一步迁至 `analysis_result_review.py`。
- 练习域新增 `batch_claim.py`（request_id 快速重放、savepoint claim、唯一冲突 winner 重放）与 `batch_commit.py`（记录持久化、响应构建、顺序预约清理、commit/rollback 编排）。保留原 `PracticeSubmissionConflictError` 重放语义。`batch_submit_answers` 248→223 行。
- 图片导入新增 `execute_image_pipeline_stages`：OCR→fast 策略→既有 pipeline 组合，返回原始/清洗文本与 OCR 诊断。`_run_image_pipeline_with_db` 158→144 行。
- 小程序 11 个核心页面（番茄钟、刷题/结果、错题本/详情、今日复习、考试 runner/result/paper/history、统计）AST 复核均无 >50 行函数；新增 `page-budgets.js` 固化函数与文件预算并接入 reliability。注意：practice/review 个别旧 utils 仍有 51-67 行函数，未声称已治理。
- 验证：最终新增 `analysis_result_review.py` 后 AI 相关 41 项；原各批次验证：AI 40 项；练习/API/架构 95 项；导入/admission/architecture 59 项；page budget 3 项 + Pomodoro boundaries；Ruff、新文件 format、compileall、YAML 解析和 `git diff --check` 均通过。
- 真实微信开发者工具/模拟器/真机、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker、备份恢复演练仍未验证。

## 二百一十三、图片导入生命周期与批量提交编排（2026-10-26）

1. `45b17641 refactor(import): 拆分图片导入生命周期契约` — 新增 `app/services/import_image_lifecycle.py`：图片导入成功路径组合 OCR/pipeline 阶段、完成投影与状态落库；异常路径拆出日志/Sentry 记录与失败状态持久化。`_run_image_pipeline_with_db` 保留绑定日志、checkpoint、资源释放和临时文件清理，且不再超过 80 行。新增 3 项生命周期契约测试。
2. `707ff357 refactor(practice): 拆分批量提交编排契约` — 新增 `app/services/practice/batch_submission_flow.py`：协议校验/指纹、已提交重放优先、签名批次 revision 完整性、判题与会话一致性、scope 校验、request_id claim、事务内持久化、顺序预约清理和 AI prewarm 容错按原顺序编排；`practice_service.batch_submit_answers` 保留同名薄入口并注入原 replay/事务/outbox/日志依赖。新增 3 项 flow 契约测试，含“已提交重放先于 token 校验”。

- 验证：导入/admission/architecture 62 项通过；批量提交相关 service/session/sequential/claim/commit/persistence/response 119 项通过；架构/依赖/唯一冲突门禁 55 项通过。两次最终均通过改动文件 Ruff、format check、compileall、AST 复测和 `git diff --check`。错误文案、持久化字段、事务 owner 与 monkeypatch 入口逐项对照保持不变。
- 当前后端剩余 >80 行函数：`ai_service.analyze_error` 181、`practice_service.get_smart_scored_questions` 183（受 5 个 AST 架构门禁固定入口）。`batch_submit_answers` 与图片导入入口已清零；`task_queue_service` 保持清零。
- 真实微信开发者工具/模拟器/真机、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker、备份恢复演练仍未验证；本轮没有推送、部署或数据库操作。

## 二百一十四、复习提交结果契约（2026-10-26）

1. `00d28453 refactor(review): 拆分复习提交结果契约` — `review-today/utils/group-submission.js` 将组提交结果统计、会话累计、重试分组、当日进度、准确率与进度条样式拆为小型纯函数；`group-submit-flow-controller.js` 显式转发答案判定、request id、计时快照、结果增强与失败刷新判断端口；`review-today.js` 补齐真实页面接线并修复此前提交请求缺少这些依赖的缺陷。
2. 为满足既有 `review-today.js` 901 行预算，仅移除本批相邻 controller 之间的 5 个非语义空行；最终 900 行，未放宽或修改预算门禁。
3. 验证通过：review group/request/remote/timer `node --test` 21 项；`test-review-submit-completion.js` 1 项；`page-budgets.js` 与 `test-page-budgets.js` 3 项；`group-submission.js` AST 复核无 >50 行函数；`git diff --check` 通过。已仅显式提交 3 个小程序路径。
4. 未验证：微信开发者工具编译、模拟器与真机；生产/外部 OCR/AI/Redis/worker/备份恢复仍保持未验证。旧 practice/review utils 仍有 51-67 行函数，后续继续分批治理。

## 二百一十五—二百一十七、复习旧 utils 契约续作（2026-10-26）

1. `7a0a325f refactor(review): 拆分计时状态契约` — 新增 `review-timer-state.js`：tick/start/pause/resume/reset/clear 与 timing session 构造独立；controller 保留实例与端口注入。5 项计时测试通过。
2. `8c0bd11c refactor(review): 拆分远程批次状态契约` — 新增 `next-remote-batch-state.js`：远端题目归一化、批次进入/草稿恢复提示与空批次刷新/重试/完成判定独立。5 项远程批次测试通过。
3. `c393f6d5 refactor(review): 拆分提交请求状态契约` — 新增 `submit-request-state.js`：复习提交 payload 与组结果投影独立；controller 保留错误提示、请求与页面存活边界。5 项请求测试 + 1 项页面完成回归通过。
4. 三批均通过 `page-budgets.js` 与 `git diff --check`；仅显式提交对应 2 个文件路径。微信开发者工具、模拟器、真机及生产/外部环境仍未验证。

## 二百一十八—二百二十三、刷题旧 utils 契约续作（2026-10-26）

1. `09307d10 refactor(practice): 拆分答题反馈状态契约` — 连击计数与反馈视图 patch 独立；5 项反馈测试通过。
2. `473d9c48 refactor(practice): 拆分退出确认状态契约` — 提交中/待确认/重试阻断状态与确认弹层文案独立；11 项退出测试通过。
3. `3d9e195c refactor(practice): 拆分返回栈状态契约` — 返回目标解析、知识页身份匹配与最近/最旧匹配索引独立；8 项返回栈测试通过。
4. `788acb2d refactor(practice): 拆分题目批次校验契约` — 题目 ID、题型与科目范围错误分层校验；3 项批次测试通过。
5. `3c258997 refactor(practice): 拆分题目加载状态契约` — 批次凭据应用、缺失凭据检测、调试/预热与加载视图进入独立；controller/state/wiring 16 项测试通过。
6. `8a2f4645 refactor(practice): 拆分提交成功状态契约` — 本地结果 payload/cache key 构造与缓存写入降级独立；5 项提交成功测试通过。
7. 六批均通过 `page-budgets.js` 与 `git diff --check`，并仅显式提交对应 2 个文件路径。微信开发者工具、模拟器、真机及生产/外部环境仍未验证。

## 二百二十四、错误分析编排契约（2026-10-26）

1. `3f975b58 refactor(ai): 拆分错误分析编排契约` — 新增 `app/services/ai/analysis_orchestration.py`：本地/跨进程生成锁、锁后缓存复核、输入准备、provider 调用、结果复核与终态选择由一个显式 request 编排；`ai_service.analyze_error` 保留准备阶段和依赖注入，历史 execution/invocation/review 公共导入不删除。
2. 验证通过：AI compatibility/execution/invocation/result-review/prewarm 26 项；架构/依赖/唯一冲突门禁 55 项；合计 81 项通过。改动文件 Ruff、新文件 format check、compileall、AST 复测和 `git diff --check` 通过。
3. 当前 `analyze_error` 94 行，`_execute_with_lease` 103 行；两者仍超过 80 行函数预算，后续继续按阶段拆分，不以本批宣称 AI 分析执行完成。真实外部 AI、生产 Redis 故障恢复、完整 worker 仍未验证。

## 二百二十五、分析调用复核契约（2026-10-26）

1. `60c066a0 refactor(ai): 拆分分析调用复核契约` — 新增 `analysis_review_invocation.py`：provider 调用 request 组装、结果解析/grounding 复核与最终 outcome 选择分为三个显式入口；`analysis_orchestration.py` 只保留锁、锁后缓存、输入准备和阶段组合，`_execute_with_lease` 降至 49 行。
2. 验证通过：AI compatibility/execution/invocation/result-review/prewarm 26 项；架构/依赖/唯一冲突门禁 55 项；合计 81 项通过。改动文件 Ruff、新文件 format、compileall、AST 复测和 `git diff --check` 通过。
3. 当前仅 `ai_service.analyze_error` 94 行超过 80 行；`task_queue_service`、`batch_submit_answers`、图片导入入口和 AI 编排阶段均无 >80 行函数。真实外部 AI、生产 Redis 故障恢复、完整 worker 仍未验证。

## 二百二十六、错误分析入口收敛（2026-10-26）

1. `1cb40a10 refactor(ai): 收敛错误分析入口契约` — `analyze_error` 只保留准备阶段与锁编排入口；原 65 行 request 装配移至 `_analyze_error_with_lease`，超时选择移至 `_analysis_timeout_sec`，依赖与原函数完全一致。
2. 验证通过：AI compatibility/execution/invocation/result-review/prewarm 26 项；架构/依赖/唯一冲突门禁 55 项；合计 81 项通过。Ruff、compileall、AST 复测和 `git diff --check` 通过。
3. 复测确认：`ai_service.analyze_error` 及全部 AI 编排阶段均不再超过 80 行；`task_queue_service` 保持清零。当前唯一已知后端 >80 行函数为 `practice_service.get_smart_scored_questions`（183 行，受 5 个 AST 架构门禁固定入口）。真实外部 AI、生产 Redis 故障恢复、完整 worker 仍未验证。

## 二百二十七、无代码变更基线复核（2026-10-26）

1. `get_smart_scored_questions` 拆分前基线：scored selection/pipeline、practice service 与 5 个 scored AST 架构门禁共 123 项通过；既有 aiosqlite 事件循环关闭警告与 `utcfromtimestamp` 弃用警告未纳入本批处理。
2. 管理端无代码变更基线：`npm run typecheck` 通过；`npm run lint` 退出 0，存在既有 138 个 warning；`npm run test` 141 个文件 / 1755 项通过。
3. 本节仅记录当前验证证据，未修改业务代码、未提交、未推送、未部署。真实微信、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker、备份恢复演练仍未验证。

## 二百二十八、scored 入口拆分尝试结论（2026-10-26）

1. 尝试将 `get_smart_scored_questions` 的 ranking、metadata closure 与 fallback request 装配移入 `practice/scored_entry.py`。行为测试通过，但 3 个 AST 架构门禁失败：它们显式要求真实入口内保留 `score_and_rank_candidates` 调用、`scored_metadata` 投影闭包和 `ScoredFallbackRequest` 装配，防止把 IO/解释权/降级权移出服务入口。
2. 结论：该函数不能通过“搬出三段代码”满足 183 行预算；正确后续方案是先按阶段拆出候选/上下文装载，并同步改写 5 个门禁为新的 ownership 断言，而不是删除门禁。临时新增文件和入口 import 已全部移除。
3. 复核：工作区恢复为无本批业务代码改动；123 项 scored/practice/architecture 基线再次通过。未提交、未推送、未部署。

## 二百二十九、智能打分上下文契约（2026-10-26）

1. `1dc501d3 refactor(practice): 拆分智能打分上下文契约` — 新增 `practice/scored_context.py`：候选池/runtime/subject 条件与知识点、图谱、题目状态、KP 名称、推荐权重装载合并为显式 request 端口；`get_smart_scored_questions` 保留 ranking、metadata closure、fallback request 与终态，符合 5 个 AST ownership 门禁。
2. 验证通过：scored selection/pipeline、practice service 与 5 个 scored 架构门禁 123 项；架构/依赖/唯一冲突门禁 55 项；合计 178 项通过。改动文件 Ruff、新文件 format、compileall、AST 复测和 `git diff --check` 通过。
3. `get_smart_scored_questions` 由 183 行降至 177 行，仍超过 80 行函数预算；继续拆分时必须保持真实入口 ranking/metadata/fallback ownership，不删除或弱化既有 AST 门禁。外部 AI/OCR、Redis 故障恢复、完整 worker、生产 Admin 浏览器仍未验证。

## 二百三十、智能打分后续拆分复核（2026-10-26）

1. 复核 `get_smart_scored_questions` 当前 177 行的构成：入口 import 边界 9 行、候选/学习上下文调用与字段展开约 55 行、ranking/metadata/fallback/终态约 90 行；其中后三段被 AST 门禁固定在真实入口。
2. 上下文装载 port 依赖测试仍通过：scored pipeline/selection 53 项。当前剩余压行空间主要来自上下文字段展开；若继续压缩，应改写 AST 门禁为等价 ownership 断言并保持可读性，不为行数引入隐式 dict/动态包装。
3. 本节未修改业务代码、未提交、未推送、未部署。真实微信、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker、备份恢复演练仍未验证。

## 二百三十一、管理端题目复制按钮组件（2026-10-26）

1. `10659994 refactor(questions): 拆分复制按钮组件` — 新增 `question-copy-button.tsx`，保留原按钮的 aria-label、aria-busy、title、disabled 条件与样式；`questions/page.tsx` 仅注入复制状态和回调，页面从 489 行降至 481 行。
2. 验证通过：`npm run typecheck`；定向 Vitest 2 项（copy button + copy hook）；`npm run lint -- --quiet`；`git diff --check`。仅显式提交 3 个 questions 路径。
3. 管理端浏览器交互、生产 Admin、微信端和外部服务仍未验证；questions 页剩余编辑组合与审核页剩余编排继续待办。

## 二百三十二、智能选题策略编排收敛（2026-10-26）

1. `73a88743 refactor(practice): 收敛智能选题策略编排` — 新增 `practice/scored_policy.py`，通过真实服务端口组合评分、排序、top5 日志、多样性选择与元数据构造；服务保留上下文装载、图谱扩充后且评分前的候选 ID 快照、SQL/fallback 端口和最终日志/切片。`get_smart_scored_questions` 177→80 行，新增 completion 43 行。
2. 更新五个 scored AST 门禁并新增 policy 门禁；两处服务函数均拒绝直接 SQL，各有 mutation 证明。新增排序/选择异常与取消传播、真实端口及 logger identity/日志顺序测试。原入口回放相同 selection/pipeline 58 项通过；最终 selection/pipeline/policy/fallback 67 项通过；此前扩展行为/架构 187 项通过。
3. read-only review 无剩余 P0–P3；最初发现的旧入口直接 SQL 检查遗漏已修复。严格 Ruff（新增模块和改动测试）、全 app correctness、compileall、diff-check 通过；practice_service 的兼容导入导致的 22 项 I001/F401 与原 HEAD 完全一致。
4. 首次按原 CI YAML 重放 static：3124 passed / 3 failed / 8 warnings；两个队列迁移失败因先前拆分丢失 migrated 赋值/异常计数，另一个是预热消费者 AST 仍指向拆分前入口，正在作为独立批次修复。不能将该次运行记为通过。

## 二百三十三、小程序复习组提交回归夹具（2026-10-26）

1. `41a0dc93 test(review): 对齐组提交能力端口契约` — 仅修复现有测试对五个 capability 端口的陈旧预期；验证实际函数引用和 confirm→begin→request→result 顺序，未修改业务行为。
2. Pomodoro/exam/practice/review 前缀 237 个 Node 测试文件合跑：最初 1431 passed / 1 failed，修复后 1432 passed / 0 failed；page-budgets 与 Pomodoro 75 个模块/18 条内部边界通过。review-agent 无发现。
3. 核心 11 页和 Pomodoro controller 已受现有预算治理，但递归补查发现 practice utils 中仍有 51/67/52 行函数，正单独处理；不能从主页面预算通过推导全部客户端完成。真实微信工具、模拟器、真机未验证。

## 二百三十四、历史与图谱评分职责（2026-10-26）

1. `6d83a7a6 refactor(practice): 分离历史与图谱评分职责` — 新增 `smart_score_history.py` / `smart_score_path.py`，分别负责到期/薄弱/历史/覆盖与前置阻塞/奖励/就绪；`calculate_smart_score` 234→30 行。保留签名、原因顺序、浮点相加顺序、权重、配置校验时序和 observed-weak 真实端口。
2. 拆分前 19 项刻画通过；拆分后扩充为 22 项，并与 adaptive/scored/policy/prewarm 架构合跑 135 项通过。5000 组确定性新旧浮点位与 reasons 完全一致；只读 reviewer 独立执行 12000 组正常、4000 组异常/非有限值和 32 组时序探针一致，补充 CI 新路径 156 项通过，无发现。
3. 新模块每个函数 ≤50 行；严格 Ruff/format、全 app correctness、compileall、diff-check 通过。文案解释仍 126 行，顺序选题、知识总结、投影协调等内部函数仍有超预算；后端学习域未整体完成。
4. 已增补 CI 清单中的 17 个 AI/import/queue 契约与两个本批评分测试，清单共 228 个 static 路径，正在进行最终 YAML 三步骤本地重放。该 CI 改动尚未提交。

## 二百三十五、迁移失败进度与客户端反馈导航收敛（2026-10-26）

1. `4bffd15b fix(queue): 保留迁移失败前的确认进度` — `V1ToV2DrainError` 携带已确认迁移数，入口保持原 logger/warning 与吞普通异常语义；取消传播、已获取客户端关闭、普通 close 失败不覆盖结果。第一项成功、第二项失败返回 1，失败项 partial v2 状态回滚且 v1 队头可重试，无成功汇总日志。
2. 修正此前无效的 socket HSET 失败夹具：改为在 fakeredis Lua 的 `redis.call` 内注入 SETEX 失败，实际经过 `pcall` 回滚窗口；未改 Lua 源和协议哈希。定向 43 项通过，独立复审 112 组历史/当前行为对照一致，无发现。真实 Redis 中断恢复未验证。
3. `6cf07c58 refactor(practice): 收敛刷题反馈导航与加载控制器` — feedback 51→13 行、navigateBack 67→19 行、loadQuestions 52→36 行；同文件内按正确反馈、无目标回退/重试/复查、响应准入拆分。保留 44/96/180ms 重试、64ms 成功复查、nextTick+20ms、去重/死亡解锁和加载端口顺序。
4. 三个 controller 47 项在 HEAD 原实现与拆分后均通过；相关 practice/page-budget 401 项通过；独立 261 组轨迹/异常/引用对照一致，无发现。首轮精确 reliability 步骤 1437 TAP 通过，四独立番茄脚本 46/106/12/39、渲染 43、5 fixtures 的 31 项及存储/考试导航通过。
5. 单独体积门禁仍失败：study 1,396,402 字节（本批前保持其他工作树不变回算三个 HEAD 文件为 1,395,945，净增 457），超过 1.2 MiB 整数上限 138,111 字节，未调整阈值。此为源码统计，不是微信工具编译/上传包体积。

## 二百三十六、后端回归清单补全（2026-10-26）

1. `c6d66944 ci(backend): 纳入分析导入与队列兼容回归` — 新增 19 个已存在测试路径，static 209→228；prewarm 架构消费者准确跟随批量提交编排移至 `practice.batch_submission_flow`，AI/OCR 兼容文档同步。
2. 精确重放 YAML 三个步骤：static 3307 passed / 8 warnings、mocked readiness 69 passed、cloud OCR profile 30 passed，全部本地通过。独立复审清单无缺失/重复，原三个失败均已关闭。

## 二百三十七、AI 响应递归解析职责（2026-10-26）

1. `34aed462 refactor(ai): 分离响应内容递归解析职责` — 原 84 行入口拆为 20/14/21/40 行的形状分派、列表择优、内嵌解析和字典编排，均留原模块；helper 不增加深度、递归/校验继续查原模块 monkeypatch 端口、公开函数导入 identity 不变。
2. 新增 53 项刻画与原 43 项在原实现和拆分后均通过；作者 10,500 次输出和 250 组轨迹一致，相关缓存/响应/视觉/SQLite/依赖 186 项通过。独立 reviewer 28,461 次输出、6,746 组轨迹（其中 6,591 次异常注入）一致，无 P0–P3。
3. 新增自动架构检查：全部函数 ≤50、仅标准解析 import、fresh import 无模型/配置/数据库/AI 服务副作用。Python 3.11 语法、严格 Ruff/format、compileall/diff-check 通过。文件仍 411 行，300 行规范仍待治理；未调用真实 AI。

## 二百三十八、推荐理由文案规则（2026-10-26）

1. `d8e4b9c2 refactor(practice): 分离推荐理由文案规则` — 新增 `smart_reason_text.py`，原理由入口 126→50 行；保留归一化顺序、图谱→到期→确认薄弱→观测薄弱→错题→阻塞→就绪→覆盖优先级、中文逐字、名称读取与 observed 动态端口。
2. 19 项刻画先跑原实现通过，扩展后 20 项也在原实现通过；与数值/selection/pipeline/adaptive/架构合跑 151 项通过。独立 reviewer 遍历 256 种 reason 子集，221,184 组普通和 168,960 组非规范输入一致，30,136 组轨迹（其中 27,576 次异常注入）一致。
3. 修复独立审查的两项 P3 门禁缺口：完整 import allowlist/直接 I/O 禁令与 4 个 mutation；全部同步/异步函数预算与 2 个超长 helper mutation。补 observed 无名称 fallback、graph/weak 优先不调用 observed；最终相关门禁及文案 30 项通过，复审无发现。

## 二百三十九、解析与文案回归入口及最终后端重放（2026-10-26）

1. `c9c1e70e ci(backend): 固定解析递归与推荐文案回归入口` — static 再纳入递归刻画、文案刻画、解析架构三条测试路径，228→231，无缺失/重复。
2. 对应业务改动后的精确 YAML 三步骤本地重放：static 3381 passed / 8 warnings（475.08s）、readiness 69 passed、cloud OCR 30 passed。该次 static 已收集后追加的评分门禁 mutation/fallback 强化另由上述最终 30 项覆盖，不把其新用例计入 3381。
3. 七个 Python 文件严格 Ruff、全 app CI 口径 Ruff、compileall 与 diff-check 通过。全部本地提交，未 push、未部署，用户原 docs/删除/未跟踪文件继续保留。

## 二百四十、当前剩余范围复核（2026-10-26）

1. `practice/` 内仍有 >80 行函数：answer projection 140；knowledge issue context 146 / session summary 296；projection reconciliation 111；sequential reserve 132 / questions 97；strategy rerank 108。`services/ai/` 本轮 AST 补查无 >80 行函数，但文件规范、完整执行语义与真实外部验收未整体完成。
2. 小程序 controller 预算不涵盖所有 helper/组件；exam 内 answer/stem-render/code-reconstructor、重复 quiz-runner/mp-html 等仍需分批语义审查。study 体积债仍未解决。
3. 阶段 0 全业务语义审查、管理端剩余 questions/review 编排、全栈兼容清理继续保留。真实微信工具/模拟器/真机、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、跨进程完整 worker、多 dispatcher 和备份恢复演练仍未验证。

## 二百四十一、小程序学习 controller 全量预算门禁（2026-10-26）

1. `6c78bf7b ci(miniprogram): 约束学习控制器预算与语法` — 新增动态递归门禁，扫描七个目录内全部 `*controller.js`：154 个生产 controller、905 个有函数体的 function-like，固定 50 行函数/300 行模块，0 超额。最大模块 master-controller 286 行，最长函数 50 行。
2. 缺目录、路径非目录、无 controller 均失败，自动发现新嵌套文件；AST 覆盖 nested/method/arrow/class/getter。修复独立 reviewer P3：TS parser 的 JS 模式也会接受类型标注；新增 `node:vm.Script` 仅编译校验，拒绝 TS 专属语法且不执行 require/顶层代码。
3. 新门禁 21 项与 page-budget 3 项定向通过，独立复审无发现。最终精确 reliability 步骤本地重放 1458 TAP / 0 fail / 0 skipped；四独立番茄脚本 46/106/12/39、渲染 43、5 fixtures 的 31 项及存储/考试导航继续通过。日志 `/tmp/priority-mini-final.log`。
4. 两个新文件为 scripts/tests，按打包忽略规则不计入 study 分包；体积债仍为 1,396,402 字节。该门禁不覆盖所有 helper/渲染组件，不构成客户端、阶段 0 或整体目标完成。已更新兼容文档，只显式提交四路径；用户原有修改与删除继续保留，未 push、未部署。

## 二百四十二、策略重排装载与评分职责（2026-10-26）

1. `d891f7ed refactor(practice): 分离策略重排装载与评分职责` — 原 108 行入口降至 42 行；知识点与掌握度各至多一次查询，数值分量由 37 行纯模块独立。保留 logger、best-effort、部分元数据写入、取消、权重局部绑定、随机数逐题动态读取及零探索率仍抽样。
2. 原版首次 22 项刻画加既有 metrics 10 项共 32 项通过；扩充后的 24 项契约在原实现内存重放通过，新版与 architecture/metrics/legacy 合跑 43 项通过。5,000 组确定性输出、元数据引用、SQL/random/log 轨迹对照一致；独立 reviewer 无 P0–P3。
3. `d77ae744 test(practice): 独立重排回归的脚本化端口夹具` — 测试文件从 326 降至 281 行，移入 56 行 support。三个移动函数 AST 一致；独立复审确认其余测试 AST 不变，30 项通过。

## 二百四十三、顺序预留查询与补位职责（2026-10-26）

1. `537624a7 refactor(practice): 分离顺序预留查询与补位职责` — service 354→285，reserve 132→37、get 97→49；新增 selection 235 行，通过原服务动态端口组合 SQL、预留循环、重读、计数和结果装载，发题不提交，reset 原提交保留。
2. 原版 36 项刻画通过；核心 56 与调用方/依赖 87 项通过。作者 720 组差分覆盖 2,805 条 SQL/参数；独立 reviewer 1,500 reserve＋500 issuance 场景、5,453 对 SQL/参数一致，原四个保留函数 AST 一致，无发现。
3. 全部业务文件≤300、函数≤50，严格 Ruff/format/app correctness/compile/diff-check 通过；PostgreSQL 仅 SQL 编译与脚本化对照，不是真实并发验收。

## 二百四十四、答案投影与修复轮询（2026-10-26）

1. `1b8ab649 refactor(practice): 分离答案投影阶段与修复轮询` — project 140→45、reconcile 111→33；四业务文件均≤300、最长函数49。阶段只执行证据/可变状态副作用，原入口保留行锁、revision/current guard、终态、一次commit、提交后缓存失效。
2. 保留逐条 savepoint、outbox payload/trace、原任务/修复去重、空扫描 rollback、租约循环与动态 settings/reconcile/sleep/logger。普通错误边界和取消传播不变。
3. 最终 85 项刻画在原实现重放通过，相关 158 项通过；作者 answer/reconcile 各 1,000 差分一致。独立审核 88 项通过，四份行为测试原实现 81 项通过，核对额外动态端口及 8 个保留函数 AST，无发现。真实 PG/Redis/跨进程 worker 仍未验收。

## 二百四十五、考试答案与讲解归一化（2026-10-26）

1. `ea09b008 refactor(exam): 分离答案与讲解结果归一化规则` — normalizeBlankAnswer 93→9、normalizeResult 57→45；canonical/标记/位置解析和练习题建议结构分开，保留优先级、exports 顺序、原引用、getter/类型转换/异常/文案。
2. 独立复审在原模块与当前模块上重放同一 27＋10 项均通过，无发现。当前两个文件230/232行、所有函数≤50；生产源码净增397字节，仅 exam 分包。study仍1,396,402字节，exam源码774,561字节。
3. 新测试纳入待提交的 reliability 清单；最终精确步骤本地重放 1495 TAP passed / 0 fail / 0 skipped，原独立番茄/渲染/fixture/存储/考试导航脚本通过。日志 `/tmp/learning-domain-mini-ci.log`；不等同微信工具或设备验收。

## 二百四十六、知识会话总结与签名基线投影（2026-10-26）

1. `93fa65be refactor(practice): 分离知识会话总结与基线投影` — 原 service575→294，issue146→44、summary296→44；baseline101/points147/projection138行，全部函数≤50。查询与事务所有者保留；signed96上限、summary24上限、持久化scope优先/legacy fallback和processing早返保持原序。
2. 最终原实现33项/当前33项通过，相关69与主流程含架构40项通过。独立审查30项新刻画原版通过、当前66项通过，5000组原/新差分、13700组SQLite/PostgreSQL编译SQL与参数对照一致；7项架构和13个违规样例检测有效，无P0–P3。没有真实PG查询或并发验收。
3. 仅显式提交9个生产/测试路径和对应兼容文档；所有用户docs、执行日志和既有删除均保留，未push、未部署。

## 二百四十七、学习域与考试归一化回归接线（2026-10-26）

1. `031ed3e8 ci(learning): 纳入学习投影与考试归一化回归` — static清单231→248路径，唯一/存在/已跟踪；reliability新增考试答案27项与讲解10项。独立只读审查无P0–P3。
2. 精确当前YAML本地重放3606 static passed（12条既有datetime弃用警告）/69 readiness/30 cloud；日志`/tmp/learning-domain-ci-{static,readiness,cloud}.log`与summary。mini步骤1495 TAP通过/0fail/0skip，独立番茄/渲染/fixture/导航脚本通过。此时还未纳入后续OCR single-pass和AI/题干helper新增测试，不能把后续源码变更冒充已完成这轮全量回放。

## 二百四十八、真实 Redis 队列重放与旧测试导入修复（2026-10-26）

1. `b86359ab test(queue): 修正真实 Redis 回归的版本常量依赖` — 仅将hardening一行私有常量导入改到task_queue_contract实际所有者；生产代码未改，严格Ruff与独立只读审查通过。
2. 本机新建独立Unix-socket Redis7.2.5实例，关闭持久化、DB1，只用合成数据。首轮68pass/1ImportError，修复后同组69pass/0skip，61.41秒；Lua、owner/generation、retry/dead、cancel、reaper与迁移均按现有断言验证。实例已正常停止、日志保留`/tmp/learning-queue-redis-xiqkgkkr/pytest.log`，首轮证据`/tmp/learning-queue-redis-uqam33d0/pytest.log`。
3. 不涉及开发/生产Redis，也不等同进程中断恢复、多dispatcher、跨进程完整worker或备份恢复验收。

## 二百四十九、OCR 单遍编排失败、恢复和取消基线（2026-10-26）

1. `af5121ae test(ocr): 固化单遍编排失败恢复与取消边界` — 新增三测试/夹具文件，生产循环未改。规范27阶段逐一普通失败/取消、初始/后阶段checkpoint错误、工件恢复跳过与真实数据传递、progress异常/取消、chunk不写全局工件、内存字段释放/计数与options引用均刻画。
2. 初版69新＋31相关=100通过；独立审查发现2个P3：恢复只检查跳过未检查数据传入，progress文档忽略早期break例外。已补首个后续/最终questions断言、真实data.copy AST mutation拒绝，3个失败progress序列，文档准确收敛。最终73新＋31相关=104通过，独立5项复跑及复审无余项。日志`/tmp/single-pass-final.log`。
3. OCR基线明确27阶段定义与执行循环，不把替身阶段当作真实算法/外部服务验收；chunked/coordinator/VL rebuild、各阶段实际算法和Redis检查点跨进程仍未完成。对应+2测试路径加入待提交251路径CI回放。

## 二百五十、AI 文本语法与作答核对职责（2026-10-26）

1. `657f8a95 refactor(ai): 分离文本语法与作答核对职责` — analysis_content411→270，新增text_syntax95/answer_check111；最长40/33/42，三个业务模块均满足300/50。保留原函数定义/metadata/globals和动态patch生效时点、结果引用及NameError；无外部AI调用。
2. 生产首次修改前新增37项＋旧契约/门禁135原版通过；补4项端口移除后最终新41项，原专属137通过，新版相关244通过。作者10522结果/异常＋630轨迹一致。独立审查原137、新含gate149，1232组结果/引用/异常/轨迹＋40端口时点＋6循环/深度案例一致，迁移8函数还原AST一致，无P0–P3。
3. 只提交5个代码/测试文件和AI兼容文档。当前AI包无>300行文件，但仍有10个函数>50行；不表示整个AI执行、预算共享或外部模型验收已完成。

## 二百五十一、考试题干渲染与诊断职责（2026-10-26）

1. `4185e7ae refactor(exam): 分离题干渲染与诊断职责` — 原983行单文件拆为入口100、七helper13/107/143/145/158/219/240行；所有92个function-like≤50，最长41。buildRenderModel原137行改入口，核心renderModel29行，保持exports/arity/导入顺序/实例状态/五模式payload/getter/异常/引用语义。
2. 32项原/新契约通过；作者6500差分一致，独立750差分与43函数AST对照一致。独立相邻77、CODE197、invariant43、5fixture31、表格/runner脚本通过。gate改复用admin直接TS依赖+Script，无mini node_modules也可运行。
3. 独立P3：原同源检查替代parity只测空URL/guard返回值，未锁住有效URL和guard状态。main补有效/选项URL、second/third两次不同页告警完整文本、reset后无告警及4个同名同arity行为mutation。最初单次告警会继承末页造成盲区，已在提交前修复；最终59/59、runner-sync与阻断mini依赖复审通过，无余项。
4. 业务源码净增5790字节，仅exam：780351bytes/93files；study1396402/174仍超既有预算，阈值未改。不等同微信编译/模拟器/真机。13路径显式提交，用户脏工作区未纳入。

## 二百五十二、编排恢复与题干回归门禁接线（2026-10-26）

1. `7fc52e9a ci(refactor): 纳入编排恢复与渲染契约门禁` — static248→251，新增OCR执行/状态与AI ports；mini新增题干契约和gate。两位独立review核对清单/路径/隔离环境，无发现。
2. 精确251路径回放3730static passed（12既有datetime警告）/69readiness/30cloud；日志`/tmp/priority-extended-ci-{static,readiness,cloud}.log`与summary。最终精确mini1554TAP/0fail/0skip，四独立番茄/渲染43/5fixture31与存储/导航脚本通过，日志`/tmp/priority-extended-mini-reviewed.log`。
3. 这次full回放早于后续OCR完成阶段清理/观察及normalization批，不把后续未纳入检查冒充已被3730覆盖；后续批按其独立相关回归与门禁记录。

## 二百五十三、完成阶段清理与 split 质量观察（2026-10-26）

1. `e3063d60 refactor(ocr): 分离完成阶段清理与分割质量观察` — new pipeline_stage_completion54行、三函数21/14/7；single-pass382→340，保留metrics后/checkpoint前顺序、输入释放、split quality→routing、动态原logger和取消。失败补偿与终态所有权未迁移。
2. 新4项观察刻画原版通过，连同前批77项；当前108核心，pipeline/chunk/resume/工件等376通过；dependency+门禁32通过。作者2000清理/观察/warning/取消差分一致。独立原77/当前167，重复2000差分match、分支与全orchestrator逆还原AST一致，无P0–P3。
3. 新模块fresh import不初始化观察器/编排器/配置/DB，10项gate含7mutation实际生效。全应用Ruff/compile/diff-check通过；未执行真实OCR/AI/大PDF内存或新增生产验收。

## 二百五十四、会话时间、身份与计数校验（2026-10-26）

1. `264d8b2e refactor(practice): 分离会话时间身份与计数校验` — normalization337→290/session110，入口77→17，函数最长38/33。保留UTC/logger/原函数globals/动态builtin与阈值/错误优先级及返回引用；作者收尾将builtins改私有别名、补计数对象引用刻画，最终均纳入证据哈希。
2. 原版初147/终148；当前相关284，main含token修复185通过；作者4096结果/引用/异常链/日志＋384动态轨迹一致，独立复验原148、185及六类端口探针无代码发现。文档P3将误写的5秒纠正为原session2秒（不能混用batch token答案5秒），复审关闭。20架构gate/Ruff/app correctness/compile/diff-check通过。
3. `142757ef test(practice): 修正批次签名回归的定义模块依赖` — 只将旧token测试所有imports统一到实际batch_token模块，去imports后AST完全一致；原service缺私有符号导致collection失败，未恢复生产转发。17token＋59旧normalization=76通过，合新契约/gate185通过。两批显式提交，CI+7paths仍待最终收尾。

## 二百五十五、提取源与单次 OCR 区间处理（2026-10-26）

1. `834a98b7 refactor(ocr): 分离提取源与单次识别区间处理` — _run_extract222→30，新增stage70/pdf198/diagnostics89，全部业务函数≤50。原同步签名/globals/source两次比较、PDF路径/非PDF内容优先、结构化浅拷贝、一次OCR、region部分状态和四遍诊断顺序保留。
2. main39新＋12旧原51通过；作者扩充getter/callee/异常/partial-region等后改前原69，终原70/new含gate97，相关282通过（7条AsyncMock未await警告未屏蔽）。独立原70/current97，1024结果/类型/状态/引用/遍历差分＋48原入口frame动态端口/异常/取消轨迹一致；18helper＋2入口mutation拒绝，所有范围AST/hash匹配，无P0–P3。
3. 10路径显式提交；未改single_pass等其余方法，原orchestrator除方法体及一条import外AST一致。新helperfresh import不初始化配置/DB/OCR引擎，真实OCR/大PDF/跨进程仍未验收；整体编排器7018行仍欠治理。
4. CI最终+12路径（251→263）经Faraday独立核验唯一存在、旧序保留/隔离env正确，未重跑已在执行的full；最终结果/提交待下一节记录。

## 二百五十六、后端本轮最终 CI 回放与收尾（2026-10-26）

1. `e5d01ce9 ci(backend): 固化会话归一化与提取阶段回归` — static251→263（新增12），全部唯一存在且旧顺序保留；Faraday独立只读review无发现，YAML/bash语法/隔离env正确。
2. 最终263路径精确YAML本地回放4026passed/15既有datetime弃用warnings（441.78秒）；readiness69passed、cloudOCR30passed。日志`/tmp/priority-final-domain-ci-{static,readiness,cloud}.log`与summary。本轮生产源码在开始collection前定稿，作者最终hash与独立review一致，无中途生产/测试修订。小程序未再改生产，最后精确reliability1554TAP/0fail/0skip及独立脚本证据沿用§252，不重复跑未变化的客户端。
3. 最后app Ruff/新Python严格Ruff、Python3.11语法、compileall与diff-check通过；原四份用户docs diff与`/tmp/user-docs.diff`逐字一致。所有本轮代码/测试/CI已显式提交，用户docs/AGENTS/任务日志/context/旧删除与本地脚本未暂存，未push/部署/生产变更。
4. 目标仍active。practice剩1个>300文件（batch_submission_flow368）/10个>50函数，AI包无>300文件但10个>50函数；OCR整体编排器7018、singlepass340/chunked221/split473/ocrrouter395均未完成治理。study源码1396402byte、超1.2MiB门禁138111byte，仍失败；exam780351byte。真实微信/外部OCRAI/生产Admin/Redis中断恢复/完整跨进程worker/多dispatcher/备份恢复仍未验收。

## 二百五十七、考试代码恢复与导入伪影扫描（2026-10-26）

1. `ee154d46 refactor(exam): 分离代码结构恢复与导入伪影清理`：原332行拆为入口51、signals40、structure89、artifacts105、strings81；14函数均≤50，五文件≤300。保留六导出/arity、历史花括号输出、修复选项getter顺序及异常对象、语言保护和日志；依赖均留在exam分包。
2. 改前15项刻画通过；最终24行为＋17架构/16mutation，合相邻59共100通过；CODE197、render invariant43、5fixture31通过。独立原HEAD基线132099差分＋20getter一致，新增9getter异常场景已固化。审查P3指出NewExpression绕过gate，补构造调用/括号解包及4mutation后独立复验关闭，无余项。
3. reliability新增两Node命令。exam源码净增2830字节为783181/97files；study不变1396402/174、超预算138111，源码体积门禁仍失败，未抬阈值。不代表微信编译/模拟器/真机。证据`/tmp/exam-code-final-node.log`与`/tmp/exam-code-{mode,render-invariant,render-fixtures,package-size}.log`。

## 二百五十八、批量提交准备与事务边界（2026-10-26）

1. `7b486d88 refactor(practice): 分离批量提交校验与会话准备`：flow368→297/preparation159，所有函数≤50。六同步函数经live lookup委托，原dataclass定义/模块/slots、函数签名与六异步函数体保留；新模块不导入DB/config/worker，认领/事务/回放/预热留原处。原墙钟2秒和答案独立容差未混用。
2. 原版24项通过；最终practice全目录及相关幂等/token/session/gate共764通过（9既有datetime警告），依赖方向与架构另53通过。独立现165、原60，96协议输入和20成功/回放/认领竞争/异常/取消差分一致，六同步逆还原AST与六异步AST不变，无P0–P3。证据`/tmp/practice-preparation-{original,final,dependencies}.log`。
3. 静态CI新增flow契约/准备契约/门禁，263→266唯一存在路径，未重跑全266；§256旧4026证据不能视为覆盖本批。严格Ruff、app correctness Ruff、compileall、diff-check通过。两批共15显式路径提交，staging空；用户四份docs diff仍与原快照逐字相同，原AGENTS/docs/任务日志/删除/本地脚本未纳入，未push/部署。
4. 目标仍active；practice无>300文件但仍10函数>50，services/ai无>300文件/10函数>50（不包括app/ai/client841、answer_grounding572、prompts874）。下一步OCR split473的布局/跨页/重建/重叠去重语义审查和刻画，再按职责治理；客户端study helper/组件及体积债仍未完成，真实环境验收边界同§256。

## 二百五十九、完整 split 编排与恢复边界（2026-10-26）

1. `6bf651e9 refactor(ocr): 分离分割输入恢复与重叠去重编排`：`_run_split`473→29，原orchestrator7018→6575。新增八文件42/60/67/77/79/90/94/117行，共18显式函数均≤50；输入顺序、原blocks布局过滤覆盖跨页结果、VL发布/冻结映射、prose二次过滤、视觉/人工回退、共享seen逐题部分更新和最后诊断/冻结/日志均保留。
2. 生产修改前新增38契约，与现有chunk/crosspage合96通过；扩展55原版回放通过，现版75（55契约＋20gate）通过。最终全相关613通过49.92秒，含pipeline目录、chunk/resume/e2e、crosspage、实际splitter/quality和实际收集到的split类。53依赖/架构通过；此前113组合和598相关是测试补强前证据，未冒充最终数目。
3. 独立生产审查逆还原全AST、1200差分、原/新96和最终55/55一致，无P0–P3。独立测试审查4P3：同名测试类覆盖导致block-prose诊断未锁住、VL三个位置参数未断言、端口别名/直接resolver逃逸、长lambda预算遗漏。补10prose案例/VL引用断言/5mutation及端口上下文约束后，独立75/55通过，prose noop产生4预期失败、VL错参4预期失败，P3全部关闭。测试/support亦满足300/50。
4. 静态CI新增5paths，266→271唯一存在，未全量回放271；本批源码/测试/CI/docs17路径hash在最终验证至提交保持不变。严格Ruff/app correctness、compileall、Python3.11grammar和diff-check通过。四份用户docs diff不变，17路径显式提交、staging空，未push/部署或真实OCR/AI调用。
5. 证据：`/tmp/pipeline-split-final-related.log`613、`/tmp/pipeline-split-revised-contract.log`75、`/tmp/pipeline-split-original-final-contract.log`55、`/tmp/pipeline-split-final-source-hashes.json`；原实现`/tmp/pipeline-split-before.py`保留。目标仍active；OCR router395/singlepass340/chunked221未完成，下一步先刻画router预算/并发/质量gate/取消/模型失败语义。客户端study超预算、真实微信/外部OCRAI/生产Admin/Redis中断/完整worker/恢复演练边界不变。

## 二百六十、OCR router 预算执行与候选发布（2026-10-26）

1. `ada7ea47 refactor(ocr): 分离纠错路由预算执行与候选发布`：原router395→11，orchestrator6575→6196；九新模块41–102行/全部函数≤50。保留分类后预算导入、semaphore3、估算×3先检查/模型后记账、router_call_stats优先、gather输入顺序、子取消降级/父取消传播、元数据浅拷贝、安全trace、领域质量观察、敏感过滤部分修改和指标flush。
2. 生产改前27契约通过；最终原49/current含gate70通过，完整pipeline/chunk/resume/e2e/adapter/quality相关622通过48.63秒，另53依赖/架构通过。先前618/45为补强前证据，未冒充最终结果。独立生产全AST逆还原、1000差分、原49/新49一致，无P0–P3。
3. 独立测试review3P3：反转fix_results仍能通过、删除record_correction未锁住、质量gate送评文本未断言。补3任务明确2→0→1完成与input/candidate/publishedtext/layout关联、指标参数/日志与flush顺序/异常及取消、shadow文本与decision/context身份；原49/current70复验通过，三mutation分别产生1/3/2预期失败，所有P3关闭。门禁覆盖9非空模块/async/嵌套/lambda/端口别名/resolver/freshimport；测试support亦300/50。
4. CI新增4paths，271→275唯一存在，未全量回放275。17路径hash在最终run/review/commit间一致；严格Ruff/app correctness、compileall、3.11grammar、diff-check通过。原四份用户docs diff不变，17路径显式提交，staging空，未push/部署。外部OCRAI/Redis真实预算争用/生产数据库/完整worker未验收。
5. 证据`/tmp/pipeline-router-{final-related,final-contract-gate,original-final-contract,dependencies}.log`与final-source-hashes.json；原实现`/tmp/pipeline-router-before.py`和runner保留。目标仍active；下一批singlepass340输入/config/resume/终态职责，核对旧docstring“输出不恢复”与当前实际artifact恢复语义。chunked221及完整真实验收、study体积债等继续保留。

## 二百六十一、single-pass 输入、恢复、执行与收尾（2026-10-26）

1. `43b30fba refactor(ocr): 拆分单次导入流水线执行`：`_run_single_pass` 保留完整 async keyword-only 签名、19 参数的名称/顺序/类型/默认值及模块 globals，340→32 行。七模块 state/input/checkpoint/execution/loop/result/stage 为 42–107 行、函数≤50。修正旧说明：checkpoint completed_stages 元数据不提供输出，接受的 artifact 写进后续 stage 使用的同一 live data 并决定跳过阶段。
2. 保留阶段构造/vision/初始 checkpoint/restore 次序；page option 浅拷贝和共享引用；结果 warnings 合并时点、metrics/cleanup/checkpoint/artifact 顺序；普通失败、取消、early break、review隔离、progress callbacks、成功/失败终态 marker、统计诊断和质量投影顺序；原模块 globals/builtin 动态解析时点。外部 OCR/AI、真实 Redis/数据库及完整 worker 未由本组合成契约验证。
3. 六组契约＋两个架构门禁最终152通过；保存原实现重放扩展契约115通过。相关 pipeline/chunk/resume/checkpoint/artifact 与架构回归616通过。按CI YAML精确重放279唯一存在路径：静态/non-GPU 4270通过/15既有 datetime 弃用警告，readiness69、cloud OCR30通过。依赖方向/架构53通过。严格Ruff、app正确性Ruff、compileall、3.11语法、300/50和diff-check通过。
4. 独立审查初始发现1 P2（旧 completion 门禁与委托入口不兼容）及3 P3（签名只锁数量、warnings/结构化事件无刻画），全部修复并复核关闭；completion缺失/重复/内联观察器、签名默认值/名称/顺序、warnings合并、起止事件删除等mutation均被拒绝。独立生产审查无P0–P3，额外核对1000组差分、8取消时点、异常链与阶段回调修改。18个代码/测试/CI/docs路径hash核验；用户原有4份admin/backend docs改动与`/tmp/user-docs.diff`相同，未暂存。
5. 显式16路径本地提交，index提交后为空；main ahead119，未push/部署。完整证据：`/tmp/single-pass-final-domain-ci-static.log`、readiness/cloud日志、`/tmp/single-pass-final-related.log`、`/tmp/single-pass-revised-contract-gate.log`、`/tmp/single-pass-original-revised.log`、`/tmp/single-pass-dependencies.log`、`/tmp/single-pass-final-source-hashes.json`。下一优先建议：刻画并拆分`backend/app/services/ai/analysis_persistence.py`的`persist_repaired_analysis`/`persist_valid_analysis`，保留 parsed 原地修改、两次 commit 与 AiChat snapshot 边界；具体消费者/风险由本批独立审查记录。整体目标仍未完成。


## 二百六十二、AI 分析结果投影与两次持久化边界（2026-10-26）

1. `a01e8a25 refactor(ai): 分离分析结果投影与持久化边界`：`persist_repaired_analysis`68→37、`persist_valid_analysis`59→36，原模块223→176，新增projection79行。原async签名/默认值/类型及其他三个helper AST不变；原入口仍持有WrongQuestion赋值与commit①，原append仍add AiChat/commit②。投影负责safe/parsed元数据及snapshot，动态原globals/builtin与repair函数内import时点保留。
2. 改前18契约通过，最终原版37（含4真实隔离SQLite）通过，当前37＋21gate=58通过；AI分析/缓存/预热相关294通过，依赖/架构53通过。冻结9路径后精确CI YAML静态283路径4328通过/15既有datetime警告，readiness69、cloud30通过；先前4327是末项mutation补充前收集，不冒充最终版本。严格Ruff/app正确性、compileall、3.11语法、300/50、diff-check通过。
3. 独立生产审查完整AST逆还原一致，800差分与两commit实际task取消一致，无P0–P3。测试审查P2业务字段共同丢失未锁、P3投影ORM add/namespace绕过已修复；补执行前独立deepcopy/嵌套identity和SQLite独立expected、实际helper与resolver mutation，首条docstring逃逸补强后独立58通过、无未关闭项。业务字段删除mutation触发4契约＋4SQLite失败。snapshot仍dict(context)浅复制，不主动过滤任意base64上下文，文档明确未新增安全过滤策略。
4. 九显式路径本地提交、未push/部署，main ahead120；用户四份docs与`/tmp/user-docs.diff`一致，原AGENTS/任务日志/删除项/未跟踪文件未纳入。证据`/tmp/analysis-persistence-{closed-contract-gate,original-revised,frozen-related,dependencies}.log`、`/tmp/analysis-persistence-frozen-domain-ci-{static,readiness,cloud}.log`、`/tmp/analysis-persistence-frozen-source-hashes.json`；原快照`/tmp/analysis-persistence-before.py`保留。
5. 整体目标仍active。services/ai超50函数由10降8；practice仍10。下一建议analysis_outcomes的持久化后日志＋响应发布，保留persist默认回调定义时绑定、await成功后实时读取原引用、日志参数求值与response动态patch。不要机械拆result_review参数转发。真实微信/外部OCRAI/生产Admin/Redis故障/完整worker/恢复演练及study体积债仍未完成。


## 二百六十三、AI 分析持久化后发布边界（2026-10-27）

1. `c0b41b76 refactor(ai): 分离持久化后的分析结果发布`：outcomes224→180，新publication67。repair58→40/valid72→42；原async签名、定义时persist默认对象、await参数和其余定义AST不变。保存成功后才同步记录日志、构造响应；原对象引用及globals/builtins读取时点保留，不新增事务、回滚或重试。
2. 最终原实现重放35通过（含真实默认persist函数＋替身Session/append）；当前AI分析相关302通过，专属35＋19gate=54通过，依赖/架构53通过。冻结8路径精确CI YAML静态286路径4378通过、15既有datetime警告，readiness69/cloud30通过。旧4376是补默认回调前，先前同4378测试期间有测试调整，均不代替最终closed日志；closed冻结哈希全程不变。
3. 独立生产审查完整AST逆还原一致、原新各39项通过，无生产P0–P3。测试审查P2默认回调未实际执行/valid持久化关键参数未锁、日志级别遗漏及P3 mapping identity漏锁全部修复。最终Descartes只读复核50项通过，默认回调2项通过；dict(context)、dict(answer_grounding)、user_id=0、info→warning内存mutation均触发相应失败，无未关闭项。原审查者Mencius后续额度403，改由新审查者复核并未切模型。
4. 新测试支持模块122行/最长50，其余新测试≤300/50。严格Ruff/app正确性、compileall、3.11语法、diff-check通过。显式8路径本地提交，main ahead121，未push或部署。四份用户docs diff与`/tmp/user-docs.diff`字节一致，AGENTS/日志/删除项/未跟踪数据未纳入。
5. 证据`/tmp/analysis-publication-closed-{original,related,ci-summary}.log`、`/tmp/analysis-publication-closed-domain-ci-{static,readiness,cloud}.log`、`/tmp/analysis-publication-closed-source-hashes.json`；原快照`/tmp/analysis-publication-before.py`保留。AI service下超50函数由8降6；practice仍10；整个AI域、全栈门禁与真实环境验收仍未完成。下一批按用户优先级推进study代码题修复职责：原源码与考试拆分前字节一致，固定两包47契约已在study改前通过。


## 二百六十四、学习分包代码题恢复职责（2026-10-27）

1. `fe11a15b refactor(study): 分离代码题恢复与伪影清理职责`：study的`utils/code-reconstructor.js`原332行/9145字节，与考试拆分前版本字节一致。沿用已验证的包内职责划分为入口51、signals40、structure89、artifacts105、strings81，六导出/arity与选项读取次序保持。没有引入跨分包require，也不以这次拆分声称消除study/exam实现副本。
2. 先将固定契约参数化到两个分包，study生产改动前47通过，再拆study实现；最终47契约+19门禁=66通过。原快照独立结果/异常差分25971组、getter轨迹12组、日志280条一致；CODE197/render43/fixture31通过。按当前reliability YAML精确执行Node步骤终态0，1620TAP/0fail/0skip，154controllers/905functions预算通过，未修改CI清单。
3. 八路径冻结哈希`/tmp/study-code-final-source-hashes.json`保持不变。Descartes只读审查最终版No findings，另独立528组原新对照（476输出/异常/日志、16选项getter、12转换/属性访问、24console情形）与66项测试通过，独立AST核对14函数全≤50；没有声称完整AST逆还原。显式提交范围5个study业务文件+2现有测试+render-invariant文档，main ahead122未push/部署，索引为空；严格保留其他dirty文件。JavaScript语法与300/50由架构门禁复核，diff-check通过。
4. 体积门禁仍失败且未放宽：study1399232字节/178文件，比本批前1396402增加2830；exam783181/97，主包497503/168。不能称全部门禁通过，也不等同微信编译体积。真实编译、模拟器、真机与完整学习页面验收未完成。
5. 证据`/tmp/study-code-{original-contract,final-contract-gate,differential,mode,render,fixtures,package-size,final-reliability}.log`；原快照`/tmp/study-code-reconstructor-baseline/code-reconstructor.js`，差分runner`/tmp/compare_study_code.js`，精确Node步骤`/tmp/study-code-reliability-node-step.sh`。整体目标仍active，后续需继续study其他helpers/重复组件/体积、学习域/队列/OCR剩余编排及真实环境验收。

6. 独立审查证据`/tmp/study-final-review-YbWmYA/{review-output.log,independent-observations.json,focused-tests.log,final-freeze-and-baseline-check.json}`；其528组独立执行与作者25971组结果分别记录，不相互冒充。提交前后8冻结路径哈希一致、四份用户docs diff不变。下一候选OCR `_run_chunked`（221行）：先刻画独立session初始化/每chunk/final状态、共享hash载入降级/去重/清理、按chunk失败继续及异常/取消传播边界，再拆初始化、循环与终态聚合；原docstring的never raise不能替代实际异常范围核对。


## 二百六十五、OCR 分块导入编排边界（2026-10-27）

1. `2a36a0b2 refactor(ocr): 分离分块导入会话与终态编排`：`_run_chunked`221→36、orchestrator5889→5718；新增state41/input70/execution50/result95，所有新函数≤50。原签名/默认值与函数内checkpoint模块、GlobalHashIndex捕获不变。每初始化/索引加载/chunk/final独立session，循环finally范围、普通load异常降级与取消传播保留。完整helper逆还原AST、签名和其余定义AST一致。
2. 原89契约在改生产前通过，补强后原95通过；最终当前95+26gate纳入最终相关823通过，依赖/架构53通过。冻结13路径后精确CI YAML静态295路径4560通过/15既有datetime警告，readiness69、cloud30通过。旧817/20gate及191小范围均是补强前证据，最终以frozen日志为准。严格Ruff/app正确性、compileall、3.11语法、300/50、diff-check通过。
3. 独立生产审查Cicero No findings：完整AST逆还原、47运行差分（含12真实task.cancel）及另2个outcome抑制专项一致；证据仅在该审查聊天工具记录，没有/tmp脚本，不编造落盘路径。测试审查3P2/2P3已全部补：shared独立expected＋原ref、诊断内容deepcopy＋identity、session退出/fallback及hash/后chunk抑制、checkpoint逐调用替换、完整start日志。五类原存活mutation现在分别触发1/2/2/2/1/4/1失败，负对照原95通过。
4. 两项gate P2也关闭：逐helper端口允许集拒绝project派生session，禁止state alias/dunder访问拒绝从__dict__绕过namespace/db；26独立门禁通过，原3个绕过与另6种注入均被拒绝。CI新增4contracts+gate+既有chunk runner/resume/status/synthetic E2E共9路径（286→295），第13节文档同步实际失败范围、代表batch及历史抑制行为。首次Ruff误删locals间接导入的失败已用captured-port noqa修复；实际取消测试新增wait_for超时cancel/gather，不再挂起。
5. 13显式路径本地提交，main ahead123，索引为空，未push/部署。四份用户docs diff与`/tmp/user-docs.diff`一致，原AGENTS/任务日志/删除项/未跟踪文件未纳入；日志和context保持未提交。
6. 证据`/tmp/pipeline-chunked-frozen-{ci-summary,related}.log`、`/tmp/pipeline-chunked-frozen-domain-ci-{static,readiness,cloud}.log`、`/tmp/pipeline-chunked-frozen-source-hashes.json`、`/tmp/pipeline-chunked-original-revised.log`、`/tmp/pipeline-chunked-dependencies.log`。原快照/tmp/pipeline-chunked-before.py；逆还原/tmp/verify_pipeline_chunked_ast.py；原重放/tmp/run_original_pipeline_chunked.py；最终CI runner/tmp/replay_pipeline_chunked_frozen_ci.py。独立测试mutation`/tmp/chunked-contract-review-nmjxx4hr/fixed-mutation-summary.json`、门禁`/tmp/chunked-gate-final-verification-zmb0crcx/verification-summary.json`。
7. 整体目标仍未完成。orchestrator剩余VL rebuild291、resume246、structure freeze222、scanned OCR220、visual crop204、run185、background180、execute_chunk180等；当前不声称整个OCR域完成。下一优先拟做本地独立Redis故障恢复：本机有redis-server、无docker；既有69Redis集成不等于停机恢复，worker_kill仅模拟心跳消失不等于真实子进程崩溃。仅用自建Unix socket实例/合成任务，保留证据，先刻画fail-closed/重连/NOSCRIPT/持有任务恢复，再考虑隔离worker子进程；生产操作仍需独立授权。study体积1399232仍超限，微信/外部OCRAI/生产Admin/完整worker/备份恢复等真实验收仍未完成。


## 二百六十六、自有 Redis 真实崩溃与队列恢复（2026-10-27）

1. `97d59f8b test(queue): 验证自有 Redis 崩溃与持久化恢复`：新增 owned_redis126行、recovery257行，最长函数37/30；生产代码、Lua及协议未改。harness仅使用新建私有目录/Unix socket，TCP port0、AOF always，实际SIGKILL并wait(-9)，同目录重启并核对PID/run ID/版本。退出仅停止自有子进程，保留AOF/日志/evidence.json，不删除证据或访问外部Redis。
2. 有效production/cloud显式及推断配置下三场景共6项：中断拒绝v1/v2入队且无local fallback、v2 dequeue/health抛错；同queue/pool/persistent client重连，真实NOSCRIPT触发全部21脚本重载；ready载荷和幂等保留，重启后新任务可完成；processing未过期owner可实际续租，真实停机使短租约到期，reaper恰好回收一次，新generation/token拒绝旧owner每次heartbeat/complete/fail，终态ready/processing均空。
3. 保留首次stale socket请求可能失败的现有语义：测试侧最多3次get_task/dequeue调用并记录错误，不给生产方法新增自动重试，不证明响应丢失窗口的exactly-once。续租120→300直接核对RedisTIME、score/hashlease/TTL增长；每次旧owner操作后立即比对raw hash/processing/hb owner/fencing/TTL，PTTL前后采样区间和实际耗时防止调度延迟误报。
4. 独立审查发现2P2测试缺口（stale拒绝可破坏processing后被新hb修复、有效hb假成功未续租）及2P2延迟误报（PTTL响应延迟250ms、续租后2.15s）；全部修复关闭。最终Descarte独立6pass，原两mutation分别2fail/4pass与4fail/2pass，另3个TTL变异被拒，21自有Redis均退出；此前24组/23mutation全部被拒及39实例退出为中间版本证据。Cicero最终两延迟正例通过，独立双实例隔离/AOF加载/generation mismatch另有证据。最终均No findings。
5. 冻结4路径后最终队列相关契约/核心/架构/真实恢复233通过（含6真实Redis恢复），0skip；严格Ruff/format/app正确性、compileall、3.11语法、300/50、YAML命令/隔离配置、diff-check通过。无--run-integration时6skip是安全默认行为，不计通过。未重跑全仓静态CI4560；无生产代码改动。CI增加二进制安装、显式集成命令及always evidence artifact，远端CI未验证。
6. 证据：`/tmp/queue-recovery-final-related.log`、`/tmp/queue-recovery-final-source-hashes.json`、`/tmp/queue-recovery-default-skip.log`；最终变异`/tmp/rr-review-f9g7xk9h/verification-summary.json`，先前完整变异`/tmp/rr-review-4o5x_1d0/run-summary.json`；延迟复验`/tmp/redis-recovery-review-rTId8x/incremental_flake_recheck.{json,log}`，初始隔离/AOF探针同目录probe/review-evidence。初始缺口证据`/tmp/rr-review-cbnnkclr/`仍保留。
7. 四显式路径本地提交，main ahead124，未push/部署；用户四份docs与`/tmp/user-docs.diff`相同，原AGENTS/任务日志/删除项/未跟踪文件未纳入，日志和context未提交。整体仍ACTIVE：本证据仅私有单节点AOF always，不覆盖生产everysec丢写窗口/网络分区/完整worker/外部OCRAI/备份恢复。下一优先可开展自有Redis+实际worker子进程的SIGTERM/SIGKILL恢复；必须区分真实worker_main完整bootstrap和仅dispatcher+合成handler子进程，旧test_worker_kill手工删heartbeat不算实际进程崩溃。


## 二百六十七、真实 worker 进程退出与学习投影恢复（2026-10-27）

1. `a6b083e7 test(worker): 验证真实进程退出与学习任务恢复`：九显式路径本地提交，六新增helper/测试＋既有owned_redis增强＋CI/docs；未改生产业务代码/Lua/协议。main ahead125，未push/部署，index提交后为空。七份代码102/131/193/200/207/113/138行，最长函数44，满足300/50。
2. 启动未修改的`python -m app.worker_main`，真实executors/dispatcher/reaper/prewarm生命周期；自建PG15.8集群/Redis7.2.5，私有Unix socket无TCP，真实Alembic upgrade head，白名单环境与私有cwd/HOME/TMPDIR。实际子孙进程按/proc birth tick登记并使用pidfd安全清理，覆盖PG backend自行新建sid；不继承父凭据，不删除数据库/AOF/日志/证据。
3. SIGTERM用实际PG行锁挂起真实学习投影，drain后释放锁，当前任务完成/后续任务保持pending/进程exit0，替换worker执行遗留任务；新task_id重投同practice event无重复副作用。SIGKILL实际exit-9，真实默认600s lease与heartbeat自然到期，期间不改键/时钟/handler；replacement真实reaper/dispatcher领取gen1→2，新token拒绝旧owner，随后实际学习投影完成且重复投递不增加数据。
4. 独立SQL expected覆盖projection、behavior/version/time/answer、Leitner counts/box1、mastery counts/score56及adaptive counts/score43。fixture currentanswerB/immutableA且revisionID=questionID+10000，避免共同expected/可变源误读。六项唯一P2全部修复并独立关闭：旧claim提前采样、漏adaptive、immutable答案源未区分、PG后代清理不全、首child强制等待错误跳过后续child、父凭据继承。原claim/adaptive/mutable源mutation均被拒，短lease1秒探针只算诊断，不算真实600s验收。
5. 最终冻结七代码路径实际完整两模块5 passed/0skip/664.55s：真实SIGTERM/SIGKILL＋三项永久安全回归（真实SIGSTOP backend使pg_ctl fast stop失败后的后代清理、首child force-wait错误继续其他child、合成凭据标记隔离/unowned拒绝）。相关生命周期/投影/架构/真实Redis320 passed。严格Ruff/format/app正确性、compileall、3.11语法、300/50、YAML独立命令/隔离env/always artifact、diff-check通过。未重跑全仓4560或远端CI；CI单独step允许20min，安装PGbinary并留证。
6. 首轮完整634.20s真实运行1pass/1fail（采样读到旧gen1，实际replacement已gen2）保留`/tmp/worker-process-real-suite.log`，不计最终通过。曾用session/PGID清理方案被真实安全测试否定（PGbackend ownsid），最终改实际子孙树＋birth/pidfd；私有HOME导致user-site依赖缺失及顺序冲突，已按父sys.path已安装包原顺序显式传递解决，未改依赖或透传环境。
7. 最终`/tmp/worker-process-final-suite.log`、`/tmp/worker-process-final-related.log`、`/tmp/worker-process-final-code-hashes.json`及`/tmp/worker-process-final-source-hashes.json`；正例native证据`/tmp/worker-runtime-gg2rvjjz/`、`/tmp/worker-runtime-fow2aja3/`，后者记录exit-9、自然expiry及gen1→2/exit0。安全审查`/tmp/worker-process-review-6xZCWP/final-tree-review-manifest.json`和cleanup_tree_recheck/permanent_safety_tree_recheck；测试审查`/tmp/wp-review-4_80fhc5/final-review-evidence.json`。初版缺口证据仍保留，不覆盖。
8. 用户四份docs diff仍与`/tmp/user-docs.diff`一致，原AGENTS/删除项/未跟踪文件及日志/context未纳入。整体目标ACTIVE：仅本地test/local_import、合成数据和学习投影分支，不证明production/cloud配置/allhandler/externalOCRAI/multidispatcher/backuprestore/真实微信完成。下一优先返回OCR编排，刻画`backend/app/features/pipeline_orchestrator.py::resume_pipeline_background`的watermark snapshot、已完成chunk/hash/独立session与paused/completed边界，再分拆；小程序source预算仍未达标。


## 二百六十八、OCR 暂停流水线恢复编排（2026-10-27）

1. `2894dae9 refactor(ocr): 分离暂停流水线恢复编排职责`，仅14个显式路径：原编排器、5个resume业务模块、6个测试/门禁与支持模块、CI及兼容文档§14。恢复入口246→35行，编排器5718→5520；state43/input91/context69/execution60/result24，全部新业务函数≤44行，11个新增Python文件全部满足300/50与Python3.11语法。完整签名、入口导入捕获、原模块/builtin动态端口和其余定义保持，作者逆还原AST一致。
2. 保留caller查询、subject_id为None才恢复科目、水印快照优先及实时/默认回退、completed batch索引、已见hash重建、逐chunk独立session与pending原顺序。source属性仍逐块读取；索引load普通失败降级、取消传播、loop-only finally、非标准session抑制后的seen_hashes/outcome局部作用域、uncached最终failed判定和退出session后缓存失效保持。当前checkpoint缺少可选get_stage_checkpoint属性的best-effort降级也未改变。
3. 先在原实现新增80项通过后才移生产逻辑；最终原函数重放89通过，当前89契约+26门禁=115通过，最终相关853通过，依赖方向22通过。严格Ruff/format、新模块3.11语法及300/50、app正确性、compileall、diff-check通过。没有改小程序/Admin，本批无微信或浏览器验收。
4. 精确当前CI YAML三步骤：静态299路径4674通过/15条既有datetime弃用warning，readiness69/cloud30通过。该完整CI在最后新增1项final-session动态端口测试前完成；此后只改ports测试文件，业务6路径未变，最终89/115/853均重新执行通过。不能把4674表述为新增该1项后的完整CI，也不把本地YAML重放视为远程CI。
5. Cicero生产独立No findings：完整逆还原AST、71组原新差分一致，其中每版13次真实Task.cancel；签名及其余模块语句/定义未变。另独立docs/CI审查No findings。Descartes最初7P2已全部关闭：逐块完整kwargs、final progress被session抑制、水印独立运行前快照、progress/两次invalidate调用时点、派生session别名、首条必须docstring、两条SQL模型/等值条件/参数/排序。原7mutation最终分别被拒；第3项残余提前缓存final invalidate也被exit:5新增断言检出。Cicero补充P3非ValueError模式异常传播已补3种身份/无后续初始化断言并关闭；其扩大捕获RuntimeError变体1失败。最终两位审查在各自限定范围No findings，无遗留P0–P3。
6. 证据：最终`/tmp/pipeline-resume-{original-closed.log,closed-contract-gate.log,closed-related.log,closed-source-hashes.json}`；全CI`/tmp/pipeline-resume-final-{ci-summary.log,domain-ci-static.log,domain-ci-readiness.log,domain-ci-cloud.log,source-hashes.json}`，后者14path与closed仅ports测试1文件不同。旧冻结/失败/中间日志均保留。作者AST`/tmp/verify_pipeline_resume_ast.py`；独立业务`/tmp/ocr-resume-original-review/{verification.json,inverse-report.json,original-results.json,current-results.json}`；最初7P2`/tmp/resume-contract-review-6iguh864/`、复验`/tmp/resume-revised-review-1q953nax/`、最终闭合`/tmp/resume-closed-manifest-review-mte_uk5a/{results.json,verification.json}`；P3`/tmp/ocr-resume-extra-test-review/closure-{original,current,mutant}.log`。
7. 显式本地提交，无push/部署/生产变更，无AI trailer。14最终路径哈希提交前冻结，四份用户docs diff仍与`/tmp/user-docs.diff`一致。日志/context不暂存；其他用户dirty文件/删除严格保留。整体目标仍active，OCR编排器其他大职责、AI/学习域剩余职责、小程序体积与真实环境验收继续推进；不能把本批表述为整个OCR域或全部优先任务完成。


## 二百六十九、AI 模型故障与题目版本守卫（2026-10-27）

1. `7747c547 refactor(ai): 分离模型故障与题目版本守卫判定`，显式9路径：provider_exception/revision_guard、3组新契约和支持模块、架构门禁、CI与AI兼容文档。同模块提取3个故障谓词、历史语义比较和守卫响应；分类入口64→24、版本守卫68→41；文件101→107与93→101。所有7个本批Python文件≤300/函数≤50，services/ai超50函数由6降4；不代表整个AI域完成。
2. 保留文本/metadata/status读取先后、auth→rate→transient→model→request→vision→generic优先级、完整error/retry/model三元组、短路及实时_contains_any。谓词显式if返回True/False，避免自定义str.__eq__早命中时重复真假判断。版本守卫先current grounding/ID转换，再按wrong_version_id与wrong_question.question_id双条件唯一查询；保留await后历史输入、两个signature分别查找、None身份判定、warning→文案→UTC时间、对象引用、错误/取消传播，不增事务或模型调用。
3. 生产改前109项通过，最终原版重放117通过（98新契约+旧15provider+4SQLite），当前含20gate共137通过；最新全部AI服务/相关架构758通过。严格Ruff/format/app正确性、compileall、3.11语法、300/50、diff-check通过。两个模块完整逆还原AST含签名/imports/旧helper/其余语句一致。CI精确305路径4814通过/15既有datetime warnings，readiness69/cloud30通过；冻结9路径一直不变，本地YAML重放不是远程CI。
4. 独立业务Cicero No findings：8448故障组合差分、3个str子类一次性truth轨迹、20个revision异常/取消以及原18定向轨迹一致，含真实Task.cancel。docs/CI独立No findings。Descartes4P2全部补齐并关闭：options运行前deepcopy+原ref防共同污染；response builder返回后才读clock；真实cancel测试进入/完成/收尾有界且finally cancel/gather；gate拒绝ast.Delete及真实current/historical删除注入。独立当前137/原117通过，2个clear、提前clock、查询前返回、2个delete变异全被拒；取消变异2.49s内由测试自身超时终止，未到外层10s。最终限定范围No findings。
5. 扩展回归发现既有`test_ai_advice_snapshot.py`错误固定集合顺序：首次最终related757通过1失败（实际weak_points为[队列,栈]）。6个PYTHONHASHSEED中0/3通过，1/2/4/5失败，advice_snapshot业务明确list(set)。仅把测试改成list类型+sorted完整内容断言，保数量/去重；6seed各3项全部通过，全部相关758通过，ruff仅另压平一个既有数组fallback断言，除预期替换外AST一致，格式后seed1三项再通过。单独1路径提交`7d6918e5 test(ai): 修正学习建议弱项集合的顺序断言`，无业务修改，独立Cicero No findings。该旧测试不在305-path静态清单中，直接多seed与全AI回归分别记录，不冒充完整CI覆盖了它。
6. 证据：`/tmp/ai-failure-{original-final.log,original-expanded.log,current-expanded.log,original-closed.log,closed-contract.log,final-related.log,accepted-related.log,final-ci-summary.log,final-source-hashes.json}`；`final-related`为757+1的旧顺序失败，最终验收用`accepted-related`758，不覆盖失败证据。CI`/tmp/ai-failure-final-domain-ci-{static,readiness,cloud}.log`。早期regex fixture误判status冒号，按原版修正测试后通过；初次related含猜错的缺失测试路径未收集，不作通过证据。AST`/tmp/verify_ai_failure_guard_ast.py`；独立`/tmp/ai-guards-{before,final}-review/`、`/tmp/ai-failure-gate-review-lgocxuu6/`与`/tmp/ai-failure-closed-review-ruuro9i7/{results.json,source-check.json}`。排序复现`/tmp/ai-advice-order-{before,after}-results.json`及每seed日志、最终`/tmp/ai-advice-order-formatted.log`，业务hash`/tmp/ai-advice-business-before-sha.json`。
7. 两提交均显式路径、人类author、无AI trailer、无push/部署/生产变更。9主批路径冻结hash提交后不变，索引为空；四份用户docs diff仍等于`/tmp/user-docs.diff`，其他用户改动和删除保留。日志/context不暂存。整体仍active：AI剩余preparation58/orchestration59/result_review59/75、OCR大职责、学习域/客户端体积及真实模型/微信/生产验收继续推进。

## 二百七十、番茄钟服务启动与会话终态编排（2026-10-29）

1. `623d2444 refactor(pomodoro): 收敛番茄钟服务启动与终态编排`：`pomodoro_service.py` 1036+/561-，新增 `pomodoro_start_request.py`（12 行 frozen dataclass）。启动链路拆出 `_create_start_session`、`_prepare_new_start`、`_require_matching_start_payload`、`_normalize_start_preset`、`_initial_expected_end`、`_resolve_start_subjects`、`_equal_408_subjects`、`_single_start_subjects`、`_new_pomodoro_session`、`_handle_start_integrity_race`；暂停/恢复拆出 `_repair_delayed_pause`、`_open_new_pause_interval`、`_rollback_concurrent_pause`、`_prior_event_time`、`_repair_delayed_resume`、`_shorten_latest_closed_pause`、`_resume_open_pause`、`_recompute_running_state`、`_extend_expected_end`；统计快照拆出 `_build_snapshot_state`、`_prepare_snapshot_state`、`_snapshot_period`、`_initial_snapshot_state`、`_accumulate_snapshot_sessions`、`_snapshot_response`、`_statistics_response`、`_requested_snapshot_period`、`_statistics_week_dates`、`_initial_trends`、`_initial_accumulation_state`；会话加载拆出 `_load_sessions_with_subject`、`_subject_lite_session`、`_load_chunked_pauses`、`_merged_practice_review_subquery`、`_load_practice_lite_sessions`、`_load_practice_subject_sessions`、`_practice_subject_lite_session`；历史与终身统计拆出 `_history_where_clauses`、`_merged_history_subquery`、`_load_history_page`、`_history_subject_map`、`_history_allocation_map`、`_first_lifetime_study_day`、`_min_session_start`。
2. 保留语义：幂等键先于活跃会话守卫、`PomodoroStartIdempotencyConflictError` 与 409 映射、free 模式时长/通知归一化位置、IntegrityError 竞争时先查幂等键再查活跃会话并 `raise ... from exc`；pause/resume 的 floor/reject_stale_before、`_prior_event_time`、`_effective_paused_sec` 与 `expected_end_time` 扩展顺序；统计窗口 `requested_statistics_period` 入参、trends/日/范围累加顺序；history 过滤/分页与科目分配映射；未新增 commit/rollback/flush。唯一删除为 `_snapshot_needs` 内联化（上一轮 P3）。
3. 定向回归 278 passed（2 条既有 datetime 弃用 warning），`ruff check`、`compileall`、`git diff --check` 通过；本批三提交后再按当前 CI YAML 精确重放静态步骤（435 路径）7495 passed / 64 warnings / exit=0。未运行远程 CI、PostgreSQL/Redis 集成、真实 AI/OCR。
4. 证据 `/tmp/pomodoro-service-final-related.log`、`/tmp/batch270-272-ruff.log`、`/tmp/batch270-272-static-ci.log`、`/tmp/batch270-272-source-hashes.json`。显式 6 路径本地提交，未推送、未部署、未操作数据库。

## 二百七十一、OCR 分块执行与 router 配置编排（2026-10-29）

1. `871d8705 refactor(ocr): 分离分块执行与路由配置编排`：`_execute_chunk` 180→9 行委托 `pipeline_chunk_execution`（263 行/8 函数，最长 50 行）；`_build_router_config` 117→7 行委托 `pipeline_ocr_router_config`（144 行/7 函数，最长 26 行）；`pipeline_ocr_router_state.resolve_router_port` 增加缺失 `__builtins__` 时的降级读取。
2. 保留语义：chunk 的 `PDF_RENDER_PAGE_WINDOW` 流式渲染与逐页 `aclose`、`mark_chunk_running`→chunk.start→overlap 计算→single pass→update_status→invalidate→chunk.finish 顺序、hash_index 推送、diagnostics 投影、异常与取消边界（CancelledError 不写终态）；router 配置的 opts 基础值、PaddleOCR-VL/OpenAI 兼容分支、AI_REPAIR fallback、admin_ai_configs 过滤与 rolling-upgrade 别名顺序，以及对 `pipeline_orchestrator` globals/builtins 的实时端口解析。
3. 新增 `test_chunk_execution_contract.py` 10 项（渲染、失败隔离、取消、端口实时解析）、`test_ocr_router_config_contract.py` 8 项、两条架构门禁 6 项；连同 router/端口契约 66 passed。CI 清单新增两条契约路径与一条架构门禁。
4. `ruff check`、`compileall`、Python 3.11 AST 语法、300/50 预算、`git diff --check` 通过；本批三提交后本地精确 CI YAML 静态重放列入两条契约与一条门禁，重放 7495 passed / exit=0。未运行远程 CI、真实 OCR/AI、Redis/worker。
5. 证据 `/tmp/ocr-chunk-router-final-related.log`、`/tmp/batch270-272-{ruff,source-hashes,static-ci}`。显式 10 路径本地提交，未推送、未部署、未操作数据库。

## 二百七十二、小程序刷题与统计页面 controller 收敛（2026-10-29）

1. `3bca9350 refactor(miniprogram): 收敛刷题与统计页面 controller`：26 路径。刷题页新增 `practice-lifecycle-controller/-page-adapter`、`practice-session-timer-controller/-page-adapter`、`practice-subject-load-controller/-page-adapter`，`onShow/onHide/_startTimer/_clearTimer/loadPracticeSubjects` 改为懒加载委托；统计页把 `_loadRequestControllerCapabilities` 与 6 组页面级 controller 组装（load commit/failure、date request/commit/failure、canvas init）拆为 7 个 page-adapter，页面 1264→1165 行；番茄钟页 `_loadSubjects` 委托 `createSubjectLoadController`；预算 ceiling 同步（practice 1240→1212、stats 1291→1165），`pomodoro-boundaries.js` 新增惰性 controller/委托门禁。
2. 保留语义：1 秒计时循环、后台时间扣除、`_pageAlive`/`activeStartedMonoMs` 守卫与 `_timer` 页面属性；请求序号、选中科目保留、默认科目初始化；launch preset 自动开始（本次修正为 preset 应用失败不自动开始并补回归用例）；统计页首屏/日期请求形状、stale 判定、pie/trend canvas 回调与 toast guard。
3. 新增/更新 7 个 Node 测试文件；`node --test tests/*.js` 2079 passed；render regression 5 fixtures/31 passed；`page-budgets.js`、`learning-controller-budgets.js`、`pomodoro-boundaries.js` 三门禁通过。
4. 未执行微信开发者工具编译、模拟器/真机、真实网络与 canvas 交互；未修改主包/分包依赖与渲染路径。
5. 证据 `/tmp/miniprogram-controller-final-node.log`、`/tmp/miniprogram-controller-render-regression.log`、`/tmp/miniprogram-controller-final-gates.log`。显式 26 路径本地提交，未推送、未部署。

> 2026-10-29 状态：上述三批本地提交后 `main` ahead 33，提交后暂存区为空；用户四份 docs、`AGENTS.md`/`CLAUDE.md`、`docs/development/`、`prompts/*` 删除与新增、`backend/service_compatibility.py` 诊断文件继续保留为工作区未提交改动。整体目标仍 active：下一步继续管理端 questions/review 剩余编排、后端学习域其余入口、OCR 视觉裁剪/结构冻结剩余编排、AI 剩余执行职责与真实环境验收。

## 二百七十三、学习计划规则/完成度装载/视图装配分离（2026-10-29）

1. `81864c03 refactor(study): 分离学习计划规则、完成度装载与视图装配`，显式 8 路径：`study_plan_rules.py`（250 行）、`study_plan_completion.py`（280 行）、`study_plan_views.py`（218 行）、`study_plan_service.py`（1134→816 行）、两条新测试、`ci.yml` 静态清单与 `STUDY_PLAN_COMPATIBILITY.md`。纯规则（阶段/整数分配/权重/可用性/动态剩余/ceil/study_day_seconds/科目权重拆分/补充分钟封顶/完成度分桶）与日快照、分配视图全部迁出；service 以 12 个下划线别名保持历史私有名可导入，`_today_completion` 保留为瘦包装，`get_study_plan_overview` 拆为 `_OverviewInputs/_OverviewFacts/_OverviewTotals` 与 8 个编排助手，入口按 `_load_day_start_minute → _load_active_plan → _load_overview_inputs → _materialize_overview_day → _load_overview_facts → _overview_totals → _overview_response` 委托。
2. 保留语义：今日完成度的 review 2 题/分钟、smart→new、exam 计分、非 smart 按 weak/new 计划分配、pomodoro 原始/补充分钟与封顶、study-day 窗口、`_ensure_day_snapshot` savepoint claim 与先锁定 plan 再物化日快照的提交时点均未变；本次审计补充把上一轮遗漏的 `_study_day_seconds`、`_task_by_type` 两个历史私有名恢复为别名。
3. 行为等价证据：以 `HEAD` 版实现与拆分后函数做约 2000 组随机输入对拍（阶段、整数分配、权重、可用性、动态剩余、补充分钟、科目权重拆分、快照 payload、分配视图）差异为 0；`load_today_completion` 与原 `_today_completion` 查询顺序、`activity_spans` 装配与 commit 时点一致；DB 级 overview 对照仅 `created_at/updated_at` 与每次新签发 `plan_token` 不同。
4. 新增 `test_study_plan_completion_contract.py` 5 项（真实 SQLite：review 取整、exam/smart 计分、非 smart 10:20 四分支、pomodoro 30/20 与封顶、overview 配置/未配置形状）与 `test_study_plan_boundaries.py` 5 项（模块 260/300/230、函数≤50、service 820、legacy ceiling 150/80/65、依赖方向、零写操作、委托顺序、别名身份、负向变异）；两条路径已进 CI 静态清单并核对存在。
5. `ruff check`、`compileall`、`git diff --check`、定向 34 passed 通过；本批提交前按当前 CI YAML 精确重放静态步骤 437 路径 7505 passed / 64 warnings / exit=0（新增 10 项即来自本批两条测试）。`ruff format --check` 仍为提示性（既有 104 文件未格式化，含 HEAD 版 service）。
6. 证据 `/tmp/study-plan-batch-static-ci.log`（7505 passed, ELAPSED 591.48s, EXIT=0）、`/tmp/replay-study-plan-ci-static.sh`、`/tmp/study-plan-batch-source-hashes.json`（8 路径，提交后哈希不变）；首次重放脚本末行续行缺陷导致 tee 未落盘，该次输出不作证据，已重跑。文档同步：`STUDY_PLAN_COMPATIBILITY.md` 增补第 8 节模块契约/差分结论并更新第 6/7 节。
7. 显式路径本地提交，无 push/部署/生产变更、无 AI trailer；`AGENTS.md`/`CLAUDE.md`/`docs/*`/`prompts/*` 等用户未提交改动与 `backend/service_compatibility.py` 诊断文件继续保留。整体目标仍 active：学习域 `knowledge_map_service`（7 个 >50 行函数，最长 172 行）、小程序复习/结果页与体积债务、任务队列、OCR 编排其余大函数、AI 分析执行及真实环境验收继续推进。

## 二百七十四、小程序考试页 controller 装配收敛（2026-10-29）

1. `02f4d5f3 refactor(miniprogram): 收敛考试页 controller 装配`，显式 13 路径：`exam-runner/index.js` 761→550 行，新增 6 个 page-adapter（pending-cache 52、timer 40、answer 89、navigation 43、submit 113、reconnect 19 行），新增 `exam-runner-boundaries.js` 门禁（209 行）与两条测试，`page-budgets.js` ceiling 762→550，`test-exam-terminal-navigation.js` 源断言改指适配器，`reliability.yml` 新增门禁与两条测试。
2. 保留语义：13 组 controller 端口对象与迁移前**逐字节一致**（仅 `this.`→`page.` 重命名，脚本逐组比对 13/13 命中）；页面 45 个方法数量不变，惰性记忆化字段（`_examTimer`/`_examSubmitOutcome` 等）与 `build*(this)` 委托形态保留；`wx`/`setInterval` 仍由运行时全局解析。
3. 门禁：页面 550 行上限、适配器行数预算与函数≤50、依赖白名单（逐模块 require 仅允许 `./exam-runner-view`、`./submit-helpers`、`./exam-attempt-cache`、`../../../utils/api`）、13 条惰性委托精确文本、禁止页面内联 `create*Controller({`、禁止页面 require 自身目录、禁止非字面量 require 与动态 import；负向变异（丢委托/换 builder 参数/内联装配/越预算/越权依赖/动态 require/未登记模块）均被拒。
4. 验证：`node --test tests/*.js` 2094 passed（含本批考试页适配器契约 8 项与边界 8 项）、`render_regression` 5 fixtures/31 passed、页面预算与三条既有门禁 + 考试门禁共 90 passed、`node --check` 6 个适配器与页面、`git diff --check`。未执行微信开发者工具编译、模拟器/真机、真实网络与 canvas 交互。
5. 证据 `/tmp/exam-runner-final-node.log`、`/tmp/exam-runner-render-regression.log`、`/tmp/exam-runner-gates.log`、`/tmp/exam-runner-batch-source-hashes.json`（13 路径，提交后哈希不变）。
6. 显式路径本地提交，无 push/部署/生产变更、无 AI trailer。提交后 `main` ahead 35，暂存区为空。
7. 继续：`review-today.js`（900 行）与 `practice-result/index.js`（896 行）同构收敛、`wrong-book`/`wrong-detail`（1547/1653 行）体积债务、后端学习域 `knowledge_map_service`、任务队列、OCR 视觉裁剪/结构冻结剩余编排、AI 剩余执行职责与真实环境验收，整体目标仍 active。

## 二百七十五、小程序番茄钟页面 controller 装配收敛（2026-10-29）

1. 范围：`miniprogram/pages/pomodoro/pomodoro.js` 2184→1596 行。新增 `utils/pomodoro-page-support.js`（46 行：`PHASE`/`PRESETS`/`MOTTOES`/`FREE_TIMER_MAX_MS`/`POMODORO_UNKNOWN_START_KEY`/`POMODORO_TERMINAL_CONFLICT_KEY`/`POMODORO_PAUSE_TOGGLE_COOLDOWN_MS` 与 `parseServerTime`，页面改为 import）与 7 个页面适配模块（合计 1066 行）：session 162、session-control 225、confirm 183、celebration 89、recovery 222、view 138、restore 47。52 组 controller 端口对象（46 个 `_get*Controller`、`_pauseSyncController`/`_activeSessionReconciler`/`_runningStateMigrator`/`_getPendingSyncStore`、`_restoreSession`/`_restoreFreeSession`）整对象迁入适配器 `build*PageCapabilities(page, deps)`；页面只保留 `if (!this._x) { this._x = create…(build…(this, deps)) }` 懒创建与单次委托，`api` 由页面经 deps 注入，适配器不得直接 require。
2. 保真证据：以 HEAD 版页面为基准逐站点比对，迁移前后对象字面量（仅 `this.`→`page.` 与 4 处 `page: page`→`page` 简写）52/52 逐字一致、顶层端口键 52/52 一致、页面委托 52/52 且每处恰好一次、页面无内联端口对象、页面无未解析自由标识符、页面与全部适配器函数 ≤50 行；脚本 `/tmp/audit-pomodoro-committed.js`，输出 `/tmp/pomodoro-adapter-audit.log`。
3. 门禁：`pomodoro-boundaries.js` 新增 `PAGE_ADAPTER_MODULES`（依赖白名单 + 禁止 `../../utils/api`）/`ADAPTER_BUDGETS`/`PAGE_CONTROLLERS`(50)/`RESTORE_CONTROLLERS`(2)/`adapterViolations`；页面上限 2185→1596；受治理模块 75→76（新增 support），依赖边 18→48；“page no longer imports governed module” 改为从页面沿 require 图判定可达性，据此移除页面两条死导入（`createCountdownController`、`buildCancelEndConfirmPlan`，对应模块仍由 `start-timer/start-break` 与 `cancel-end-confirm-controller` 消费）。`page-budgets.js` ceiling 2186→1596。
4. 测试：`test-pomodoro-module-boundaries.js` 57 项（新增可达性、适配器依赖面/api 注入、内联端口、委托模板、预算增长用例），新增 `test-pomodoro-page-adapter-contracts.js` 6 项；`node --test tests/*.js` 2113 passed；render regression 5 fixtures/31 passed；5 条架构门禁 + `node --check` 全通过。
5. CI 脚本同步（保持原语义，改指新归属）：`test-pomodoro-free-timer-limit.js`（常量解析改指 support，`maxMs: FREE_TIMER_MAX_MS` 改指 recovery adapter，`shouldFinalize` 改指 session-control adapter）、`test-pomodoro-resilience.js`（网络 controller 断言改指 recovery adapter builder；HEAD 既有 1 项 `client_start_id` 失败保持不变）、`test-pomodoro-stability-runtime.js`（VM 沙箱增加 realm 内 CommonJS 加载器与新模块映射，46/46 通过）；`reliability.yml` 增加 `test-pomodoro-page-adapter-contracts.js`。HEAD 即失败的 `test-v5-ui-fixes.js`/`test-v8-fixes.js`/`test-408-feature-integration.js` 未变（已用 `/tmp/pa-head` worktree 对照）。
6. 文档：`docs/architecture/REFACTOR_INVENTORY.md`（页面行 2180→1596 并补装配说明）、`docs/architecture/SYSTEM_ARCHITECTURE.md`（模块清单与说明）。证据 `/tmp/pomodoro-adapter-{final-node,render-regression,gates,legacy-scripts,audit}.log`、`/tmp/pomodoro-adapter-source-hashes.json`（19 路径）。
7. 保留语义：端口对象逐字不变，懒创建字段与顺序、`wx`/`setTimeout` 运行时全局解析、`_restoreSession` 的 free 分流与 shell 顺序、`api.now()` 注入点均不变；未验证：微信开发者工具编译、模拟器/真机、真实 canvas 交互与网络故障注入。显式路径本地提交，无 push/部署/生产变更、无 AI trailer。
8. 继续：`practice-result/index.js`（896 行）同构收敛、`wrong-book`/`wrong-detail` 体积债务、后端学习域 `knowledge_map_service`、任务队列、OCR 视觉裁剪/结构冻结与 AI 剩余执行职责、真实环境验收；整体目标仍 active。

## 二百七十六、刷题结果页 controller 装配收敛（2026-10-29，`7c3952d2`）

1. 范围：`miniprogram/subpackages/study/practice-result/index.js` 896→823 行。6 组能力对象迁入同目录 `utils/practice-result-*-page-adapter.js`（5 个模块共 161 行）：payload state（6 键）、payload ports（17 键，`knowledgePracticeSync` 与页内 `buildErrorDonutSvg` 经 deps 注入）、batch diagnosis（13 键，`api` 注入）、trend load（5 键）、408 teacher（17 键，`api` 注入）、back navigation（12 键）。
2. 保真证据：以迁移前页面快照 `/tmp/pr-adapter/practice-result-before-page.js` 为基准，`/tmp/pr-adapter/audit.js` 输出 `/tmp/pr-adapter/audit-final.log`：6/6 对象字面量（仅 `this.`→`page.`）与端口键集合逐项一致，6/6 页面恰好一次委托 builder，`_practicePayloadController` 内 `_practicePayloadPorts`/`_practicePageState`/`applyPracticePayloadOrchestration` 各恰好一次；页面无新增未解析自由标识符，`setTimeout` 随导航适配器迁出；页面与 5 个适配器函数均 ≤50 行。
3. 门禁：新增 `scripts/architecture/practice-result-boundaries.js`（22 个受治理模块、依赖白名单、每模块行数预算、函数 ≤50、页面 823 行上限、4 个 controller 委托模板、payload 三段委托模板、页面 require 唯一性、13 个能力键不得回流页面）；`page-budgets.js` ceiling 897→823；`learning-controller-budgets` 既有目录门禁继续覆盖该 utils 目录。输出 `Practice-result boundaries passed: page 823 lines, 4 controllers, 161 adapter lines, 22 governed modules`。
4. 测试：新增 `tests/test-practice-result-module-boundaries.js` 9 项（扫描、委托缺失/漂移、内联端口、页面上限、adapter require 唯一性、能力键回流、依赖/动态 import/预算负例、超长函数负例）；另补 `test-practice-result-page-adapter-contracts.js` 6 项运行时接线契约，覆盖实例缓存隔离、动态字段/方法、注入 API、全局 wx 替换、迟响应拒绝和 inflight 身份。最终冻结源码后 `node --test tests/*.js` 2128 passed（`/tmp/pr-adapter/frozen-node.log`），渲染回归 5 fixtures/31 passed（`/tmp/pr-adapter/accepted-render.log`），定向 `test-practice-result-diagnosis.js`、`test-study-ui-refinements.js`、`test-practice-reference-ui.js`、`test-page-budgets.js`、`test-learning-controller-budgets.js` 全部通过；6 条架构门禁 exit=0。
5. CI：`reliability.yml` 增加 `practice-result-boundaries.js`、`test-practice-result-module-boundaries.js` 与 `test-practice-result-page-adapter-contracts.js`，YAML 解析通过。独立只读审查无可操作发现，并验证 18 项定向测试与 27 项 HEAD/当前页面差分断言。
6. 文档：`docs/architecture/REFACTOR_INVENTORY.md` 学习闭环行同步 896→823 与装配说明；本轮未改 `SYSTEM_ARCHITECTURE.md`（该文件无刷题结果页专行，保持原有粒度不夸大）。
7. 保留语义：`api` 与存储 facade 仅经 deps 注入；懒创建字段/顺序、`onLoad`→`recoverSubmittedResult`→`applyPracticePayload` 链路、diagnosis 刷新序列守卫、缓存恢复与待提交恢复键均不变。未验证：微信开发者工具编译、模拟器/真机、真实 AI 408 teacher 与网络故障注入。
8. 继续：`wrong-book`(1547)/`wrong-detail`(1653) 体积债务；后端 `knowledge_map_service`(942)、`task_queue_service`(2345)、OCR `pipeline_orchestrator`(4441) 与 `ai_service`(702) 剩余职责；真实环境验收；整体目标仍 active。本批显式 12 路径已本地提交为 `7c3952d2`，暂存区为空；规则、记忆系统和交接文档更新保持未提交，既有受保护脏路径与未跟踪上下文继续保留。

验收限制与完整范围：阶段 0 全量逐业务域语义审查、管理端 questions/review 剩余编辑组合与页面编排、全栈预算门禁、客户端边界和兼容清理继续未完成。真实微信、外部 OCR/AI、生产 Admin 浏览器、多 dispatcher、全部 worker handler 与备份恢复演练仍未完成；§266/§267 的隔离真实 Redis 恢复及学习投影 worker 进程验收属于已记录的局部证据，不能扩大为生产故障恢复或完整 worker 验收。重审/回滚与 Leitner 到期过滤已有实现，勿按旧“设计预留”描述重复立项。

## 二百七十七、后端知识地图只读投影拆分（2026-10-29，`8a57a68d`）

1. 按交接首项推进 `knowledge_map_service.py`：942→633 行，科目汇总/状态、子树元数据、节点响应迁入 `knowledge_map_summary.py`（124 行）、`knowledge_map_hierarchy.py`（175 行）、`knowledge_map_nodes.py`（128 行）；新增模块函数均 ≤50 行，不增加数据库访问、事务或可变共享状态。
2. 拆分前真实 SQLite 原基线 5 passed，新增投影刻画 11 passed。保留科目/子树缺失掌握分数差异、可靠度阈值、可练覆盖门槛、题数×置信度加权、节点 snapshot 优先级、默认值和字段顺序；未统一既有不同口径。
3. 新增架构门禁 10 项（300/50 预算、service 633 行冻结上限、4 个既有长函数各自冻结预算、禁止投影反向依赖/SQL/动态执行，含负向用例）；CI 显式加入新测试。相关图谱/自适应/掌握度/知识点测试共 149 passed；严格 Ruff、compileall、CI YAML 解析和 diff check 通过。
4. 差分证据 `/tmp/knowledge-map-batch/audit.log`：11,250 次确定性投影比较一致、剩余 12 个函数完整 AST 未变、5 组真实 SQLite 响应/SQL/参数顺序一致。独立只读 review 无 actionable findings（含 P3），26 项定向测试及独立 2,000 组随机树共 19,153 次差分通过。
5. 显式 9 路径本地提交 `8a57a68d`，无 push/部署/生产或用户数据变更；原有保护路径和日志改动未暂存。文档同步兼容基线与盘点。真实 PostgreSQL、大数据性能、Admin 浏览器、微信工具/真机和外部 OCR/AI 未验证。
6. 继续：知识地图查询/树/关系/详情编排仍有 4 个既有 >50 行函数；按兼容基线继续收敛后进入 wrong-book/wrong-detail，再按交接清单处理队列、OCR、AI 和完整范围未完成项。整体目标保持 active。

## 二百七十八、后端知识地图查询与详情编排收敛（2026-10-29，`f0103ae7`）

1. `knowledge_map_service.py` 633→195 行，保留三个业务入口与顺序编排；新增 queries（221 行）、topology（104 行）、relations（82 行）、detail（143 行），nodes 128→149 行补详情节点装配。知识地图 8 模块均 ≤300 行，所有函数（含嵌套）≤50 行，最大 50；无 schema/API/事务/写入变化。
2. 查询条件、subject map 排序/detail 无 ORDER BY、父边优先级/环拒绝、snapshot 顺序、树深度截断、详情祖先完整深度、关系 round 后排序/每组8条、recent_answers 不可变版本映射与 await 前后字段求值位置保持。
3. 新增 topology 3 项、detail 3 项，均在旧实现上通过。架构门禁 10→14 项，所有 map 模块须登记/300/50/只读、service 禁止 SQL、投影依赖保持中立；CI 新增两条测试路径。相关回归 159 passed；全局架构/依赖方向 53 passed；严格 Ruff、compileall、CI YAML 与 diff check 通过。
4. 旧完整实现（`/tmp/knowledge-map-batch/before.py`）对照：11,250 次投影比较、5 组真实 SQLite 响应/SQL参数顺序一致；独立只读审查无 actionable findings（含 P3），36 项定向测试与 200 组×3入口=600 次响应/递归字段顺序/SQL调用类型、顺序、条件、排序差分全部通过。
5. 显式12路径本地提交 `f0103ae7`，不 push/部署，不访问生产/用户数据；保护路径与原有任务记录继续未提交。日志 `/tmp/knowledge-map-batch/{orchestration-final-pytest,direction-pytest,orchestration-audit,original-detail-tests}.log`。
6. 下一项：小程序 wrong-book(1547)/wrong-detail(1653)体积债务；随后 practice.js剩余职责、pomodoro-stats视图回写、队列/OCR/AI与全栈未完成范围。真实 PostgreSQL/微信/外部AI/OCR等验收限制不变；整体目标 active。

## 二百七十九、小程序错题本列表与统计视图投影（2026-10-29，`65642c81`）

1. `wrong-book/wrong-book.js` 1547→1306 行；27 个页面方法迁入同页 `utils/wrong-book-value-view.js`（82 行）、item-view（130 行）、analysis-view（143 行），另有 view-page-adapter（37 行）。静态 helper 仍按原页面 import 顺序注入；adapter getter 读取当前页面方法并 bind 页面，保留动态替换、回调绑定与实例隔离。
2. 保留默认参数、题目装饰/统计 fallback、零掌握进度既有 truthy 口径、任务分组占用/排序/预览与未分组数量、Date运行时。27 个迁移方法体归一化后相同、其余107个页面属性不变；9,944次确定性投影差分一致；独立审查另3,007次比较一致且输入不变。
3. 新增view契约7项、模块门禁6项，既有日期筛选保持；最终定向共14 passed。全量 `node --test tests/*.js` 2141 passed；render regression 5 fixtures/31 passed；既有6门禁+新增wrong-book门禁、node --check、CI YAML解析、diff check通过。新目录由独立wrong-book门禁覆盖，不混称属于七个既有controller目录。
4. 独立只读review发现1项P3：new Function绕过动态执行门禁；已覆盖NewExpression、补两负例并复核，无剩余 actionable findings。文档新增 `WRONG_BOOK_COMPATIBILITY.md`，盘点与reliability CI同步。
5. 显式12路径本地提交 `65642c81`，暂存区空；不push/部署，无生产或用户数据变更；原保护路径保持。证据 `/tmp/wrong-book-view-batch/{baseline,full-node,render,audit,final-targeted}.log`。未执行微信工具/模拟器/真机/真实AI或弱网及批量撤销交互。
6. 继续wrong-detail体积债务与wrong-book剩余请求/批量/AI编排，再按交接清单推进。整体全栈目标仍active，不能据这三批标记计划完成。


## 二百八十、小程序错题详情状态规则与专项老师端口（2026-10-29，`2f3c870b`）

1. 页面1653→1533行；八个AI状态helper、题目投影与专项老师22端口装配迁至同页ai-state（88行）、question-view（28行）、teacher-page-adapter（37行）。原teacher controller未改；页面保留私有包装/静态import顺序、动态API/配置/global wx、实例惰性缓存。
2. 原八状态方法/题目投影体保持，其余118页面属性保持；22端口仅this→page。9,000次确定性差分一致。八项行为契约在原实现重放全部通过；当前8契约+7门禁=15通过，全量Node2156通过，render5fixtures/31通过，八条架构门禁/语法/YAML/diff通过。
3. 两轮独立只读审查（实现及最终CI/源断言/文档增量）无P0–P3可操作发现。视觉/KaTeX脚本通过。408-teacher错题详情源断言改指adapter/controller，仍停在practice-result既有API断言；error-diagnosis未改，仍有practice-result occurrence diagnosis_id既有失败；原实现重放均复现，不混称全过。
4. 显式13路径本地提交2f3c870b，暂存区空；原11个受保护tracked差分逐字节保持，无push/部署/生产或数据变更。兼容文档WRONG_DETAIL_COMPATIBILITY.md与inventory/CI同步。日志/tmp/wrong-detail-state-batch/。
5. 继续wrong-detail导航/AI生成恢复/重新生成与错因编排、wrong-book请求/批量/AI编排，然后practice/pomodoro-stats/后端队列OCRAI及全栈剩余范围。真实微信工具/模拟器/真机/外部AI与完整学习闭环验收未完成，整体目标active。


## 二百八十一、小程序错题切题动画与看门狗（2026-10-29，`88830317`）

1. 页面1533→1454；10个滑动/出入场动画/看门狗方法迁入wrong-detail-content-transition.js（132行/函数≤50），显式page与原常量/_sleep注入。不新增controller实例、共享状态或依赖；原page方法名/参数/async标记保留。10体仅this→page，其他109个Page属性不变（其中94方法），动态Date/timers/方法及onUnload保持。
2. 改前9契约通过，最终11项在原页面重放通过，当前状态/边界/切题共26通过。6000次确定性状态/计时器/patch差分一致。全量Node2167通过，render5fixtures/31通过，八门禁/语法/视觉/KaTeX/YAML/diff通过。页面预算1454、5模块/15委托；CI增加切题契约。
3. 两轮独立只读审查覆盖代码/测试/门禁及最终docs，无P0–P3可操作发现；独立核对10方法及94其余方法、运行26项；最终九路径哈希与冻结记录一致。兼容文档新增§4与inventory同步。日志/tmp/wrong-detail-transition-batch/{baseline,original-final,targeted-final,full-node,render,gates,audit}.log，禁止重跑一次性extract.js。
4. 显式九路径本地提交88830317；main相对origin/main `65642c81` ahead2（已按2026-10-29 15:33:36外部push更新的引用更正，用户已确认继续；本轮未push），索引空，无push/部署/生产或用户数据操作。原11保护tracked差分保持，原日志/rules/未跟踪上下文继续未暂存。
5. 下一项仍为wrong-detail导航数据/AI生成恢复/重新生成/错因编排及wrong-book请求/批量/AI，再按交接practice/pomodoro-stats/后端队列OCRAI/Phase0/Admin/全栈与真实验收继续。两条legacy源断言既有失败和真实微信/网络/AI验收限制保持；整体目标active。


## 二百八十二、小程序错题详情导航编排（2026-10-29，`d84d514c`）

1. 页面1454→1355行；6个导航数据准备/VM构建/切换提交/列表删除/失败路径方法迁至navigation-data（51行）、navigation-flow（76行），原Page方法名/参数/async保留，均为精确单次委托。API读取、wx存储/toast通过调用时箭头注入；页面渲染/helper由await后调用箭头读取，保留动态替换时点。
2. 保留无效索引锁行为、缓存命中身份/time、响应存活/序号先于缓存与render、AI/题库分析优先级、错误诊断重复normalize、patch字段顺序及对象引用、commit动画后守卫/副作用/setData回调顺序、404/410旧drop(0)、storage错误吞掉。没有修复/改写既有业务行为。
3. 11个契约在拆分前源码全过；最终13项原页replay全过。当前状态+边界+转场+导航39通过；全量Node2180、渲染5fixtures/31、八架构门禁/JS语法/AI视觉与KaTeX/CI YAML/diff check通过。独立800组response/state/字段顺序对照一致。门禁7模块/21精确委托/1355行。
4. 独立生产与文档/CI只读复核无P0–P3；校验原变更6/6方法体（接收者及API/storage/toast seam调整）、参数/async与113其他Page properties；独立39定向通过。11路径冻结哈希未变，原用户tracked差分保持。兼容文档§5与REFACTOR_INVENTORY、CI同步。证据`/tmp/wrong-detail-navigation-batch/`。
5. 显式11路径本地提交`d84d514c`，main相对origin/main `65642c81` ahead3（远端引用本轮未更新，用户已确认基于当前状态继续）；索引空，无push/部署/生产或数据操作。受保护日志等继续未暂存。NEXT错题详情AI生成/恢复/重新生成与错因编排，然后wrong-book请求/批量/AI，再按全栈计划。真实微信/外部AI和完整学习闭环未验收，整体目标ACTIVE。


## 二百八十三、小程序错题详情 AI 轮询与恢复应用（2026-10-29，`74a35fa8`）

1. 页面1355→1302行；请求身份/持久化轮询/恢复应用三个方法迁至wrong-detail-ai-recovery.js（64行/函数≤50），保留原方法名/参数/async和单次委托。不新增共享状态，生成/重新生成/后台恢复任务其他编排仍待治理。
2. 保留44次请求/43等待、2000/3000/5000ms阈值、请求前/等待后/响应后守卫、falsey marker/新一代过滤/空结果跳过、catch边界与catch外sleep；API每轮调用时解析且receiver保持，normalizer在await后读取。恢复顺序reset→私有结果/marker→cache→cards/setData与对象身份/来源标志保持。三方法体接收者及fetch端口以外相同，116其他Page属性原文不变。
3. 12项恢复契约原页面replay全过；当前五组51通过，全量Node2192通过、render5fixtures/31通过、八架构门禁/语法/视觉/KaTeX/CI YAML/diff check通过；800组确定性轮询/恢复状态/轨迹差分一致。门禁8模块/24委托/1302页面预算，CI新增恢复契约。
4. 独立实现及最终文档/CI两轮只读review无P0–P3；冻结10路径哈希一致。两个legacy脚本在before与current均复现practice-result既有断言失败，不混称全过。文档兼容§6与inventory同步。证据/tmp/wrong-detail-ai-recovery-batch/；禁止重跑extract-recovery.js。
5. 显式10路径本地提交74a35fa8，author lmh，无AI trailer；相对origin/main 65642c81 ahead4，索引空。保护tracked/untracked哈希提交前后保持；仅本节和context继续追加，日志/rules不暂存。无push/部署/生产/数据操作。
6. NEXT：wrong-detail AI生成/重新生成/后台恢复与错因剩余编排，wrong-book请求/批量/AI，然后按交接practice/pomodoro-stats/队列OCRAI/Phase0/Admin/全栈门禁与验收推进。真实微信/外部AI与完整学习闭环未验收，整体目标ACTIVE。


## 二百八十四、小程序错题详情普通 AI 生成编排（2026-10-29，`b004ea82`）

1. 页面1302→1245行；普通生成入口/结果分流/成功写回/错误恢复四方法迁至wrong-detail-ai-generation.js（75行/函数≤50），原参数/async/单次委托保持。四方法体仅this→page，115其他Page属性原文不变；生成请求协议/重新生成/后台恢复任务与错因剩余编排仍待治理。
2. 保留guard/baseline/序号/loading/request顺序及迟响应reset；generating→fallback→空内容→success优先级、动态页面方法与helper receiver、marker回退、cache/cards/setData顺序不变。错误处理console→notice→非等待enqueue→await poll→恢复应用→最终身份与错误状态不变；request/application异常await当前error handler、handler失败传播不变。
3. 12新契约在原页重放全过，当前六组63通过；全量Node2204、render5fixtures/31、八架构门禁/语法/视觉/KaTeX/CI YAML/diff通过。800组四入口状态/调用轨迹/字段顺序差分一致。页面预算1245、9模块/28委托；CI新增生成契约。
4. 独立实现及最终docs/CI两轮只读review无P0–P3；9路径冻结哈希提交前后保持。文档兼容§7及inventory同步；证据/tmp/wrong-detail-ai-generation-batch/，禁止重跑extract-generation.js。两条既有legacy源断言失败及微信/真实AI/完整闭环未验收限制不变。
5. 显式9路径本地提交b004ea82，author lmh，无AI trailer，相对origin/main 65642c81 ahead5，索引空；保护路径提交前后hash保持，仅本节/context追加且不暂存。无push/部署/生产/数据操作。NEXT重新生成/后台恢复/请求协议/错因编排，随后wrong-book与全栈其余清单；整体ACTIVE。


## 二百八十五、小程序错题详情 AI 重新生成编排（2026-10-29，`33ee6b53`）

1. 页面1245→1143行；重新生成入口/分流/生成中恢复/cache-preserved/fallback/empty/success/error分派/recovery/timeout十方法迁至ai-regeneration（144行/函数≤50），保留原方法名/参数/async。方法体仅this→page及toast端口，109其他Page属性原文不变。
2. 保留oldCards/oldResult/baseline捕获、序号/patch/request顺序、generating→有效cache-preserved→fallback→empty→success优先级、历史结果/marker回退/cache/setData/toast次序。错误catch不await分派，分派不return recovery Promise，enqueue不await/后续poll与身份守卫保持。wx动态解析及receiver保持。
3. 15契约原页replay全过；当前七组78通过，全量Node2219/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过；1200组十入口状态/轨迹/字段顺序差分一致。10模块/38委托/1143预算，CI增加重新生成契约。
4. 实现及最终docs/CI独立只读review无P0–P3；9冻结路径hash提交前后匹配。compatibility§8/inventory同步；证据/tmp/wrong-detail-ai-regeneration-batch/，禁止重跑extract-regeneration.js。保护路径提交前后保持，仅tasklog/context追加未暂存。
5. 显式9路径本地提交33ee6b53，author lmh/noAI trailer，相对origin/main65642c81 ahead6，索引空，无push/deploy/生产/数据操作。NEXT AI请求/后台恢复入队/cache/错因，随后wrong-book及全栈剩余。legacy断言失败与真实微信/外部AI/full-flow验收限制保持，整体ACTIVE。


## 二百八十六、小程序错题详情 AI 请求与缓存支持（2026-10-29，`966e9697`）

1. 页面1143→1101行；loading复位/cache写回/request/recovery enqueue/failure state/tap六方法迁至ai-request（68行/函数≤50）。三无页面依赖函数仅接收实际入参/依赖，其他显式page；原页面参数/async/单次委托保持，113其他Page属性原文不变。
2. 保留live api.post receiver、payload/字段序、force布尔、强制入队才baseline、55000/10000ms与suppress。request sync/async错误传播；enqueue的baseline/request/response异常仍catch→动态console.warn→false。cache仅entry.data替换，cache/entry/normalized身份和timestamp/status保持，undefined marker不写与falsey写空字符串区分。tap忙碌守卫/私有ID优先/current loader/不返回Promise/live wx保持。
3. 13契约原页replay全过，当前八组91通过、全量Node2232/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过；900组六入口结果/状态/轨迹/字段序一致。11模块44委托/1101预算，CI增加请求支持契约，fixture增加definition确保reset/cache测真实方法。
4. 实现及最终docs/CI两轮独立只读review无P0–P3；10冻结路径hash提交前后匹配。compatibility§9/inventory同步；证据/tmp/wrong-detail-ai-request-batch/，禁止重跑extract-request.js。
5. 显式10路径本地提交966e9697，author lmh/noAI trailer，origin/main65642c81 ahead7，索引空；保护路径提交前后保持，仅tasklog/context追加未暂存。无push/deploy/生产/数据操作。NEXT错因诊断/详情加载/掌握撤销等剩余职责，然后wrong-book和全栈其余范围；legacy源断言与真实微信/外部AI/full-flow限制保持，整体ACTIVE。


## 二百八十七、小程序错题详情诊断编排（2026-10-29，`92c619f6`）

1. 页面1101→963行；诊断sheet/选择/保存/next action/refresh七方法迁至diagnosis-flow（168行/函数≤50），原签名/async/单次委托保持，112其他Page属性原文不变。注入API/diagnosis对象和平台getter，保留getter求值顺序/API及wx receiver/await后helper/当前ID/Date读取。
2. 保留主次选择上限与副本、query编码/0false参数、occurrence ID/本地raw用户确认/server ID/cache entry替换/视图身份；refresh fallback→request→守卫/confirmed保护/分别合并cache和view/finally独立规则。
3. 新发现且保留的原基线限制：save响应若data envelope，外层raw覆盖确认/选择后normalizer仍优先内层data，normalized可能旧primary或未确认；直接/diagnosis wrapper无该差异。不夹带业务修复。
4. 15契约原页replay全过，当前九组106/全量Node2247/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过；1120组七入口结果/状态/轨迹/字段序一致。12模块51委托/963预算，CI增加diagnosis契约；legacy wrongdetail断言归属迁移并单独全过，完整脚本原版/当前practice-result diagnosis_id失败保持。
5. 实现及最终docs/CI两轮独立只读review无P0–P3；11冻结路径hash提交前后匹配，compatibility§10/inventory同步。证据/tmp/wrong-detail-diagnosis-batch/，禁止重跑extract-diagnosis.js。
6. 显式11路径本地提交92c619f6，author lmh/noAI trailer，origin/main65642c81 ahead8，索引空；保护路径保持，仅tasklog/context追加未暂存；无push/deploy/生产/数据操作。NEXT详情加载/生命周期/掌握撤销，再wrong-book和全栈其余清单；真实环境等限制保持，整体ACTIVE。


## 二百八十八、小程序错题详情加载与预取编排（2026-10-29，`f3c690c8`）

1. 页面963→867行；加载入口/初始patch/响应投影及字段/优先解析/渲染检查/错误/预取八方法迁至load-flow（130行/函数≤50）。原签名/async/单次委托保持，111其他Page属性原文不变；纯初始patch不接收page。
2. 保留序号/reset/patch/诊断与teacher序号/请求顺序、响应守卫后先cache再projection、null projection仍保留cache、私有字段在最终guard前副作用、重复diagnosis归一化、调用时renderer/analysis/helper、非等待诊断刷新及invariant先于trace读取。预取300000ms边界/请求起点时间戳保护/undefined返回/拒绝吞掉而同步异常传播保持。
3. 15契约原页重放通过，当前十组121/全量Node2262/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过；1000组八入口结果/状态/轨迹/字段序一致。13模块59委托/867预算；CI与compatibility§11/inventory同步。
4. 实现及最终docs/CI两轮独立只读review无P0–P3；10冻结路径及15保护路径hash提交前后匹配。证据/tmp/wrong-detail-load-batch/，禁止重跑extract-load.js。
5. 显式10路径本地提交f3c690c8，author lmh/noAI trailer，相对origin/main65642c81 ahead9，索引空；保护路径保持，仅tasklog/context追加未暂存。无push/deploy/生产/数据操作。NEXT生命周期/掌握撤销/删除剩余职责，再wrong-book及全栈清单；legacy失败、data envelope限制、真实环境验收缺口不变，整体ACTIVE。


## 二百八十九、小程序错题详情生命周期与底部操作栏（2026-10-29，`23b98e33`）

1. 页面867→771行；加载/初始化/导航来源/show-hide/滚动交互/底部timer/卸载十二方法迁至lifecycle（146行/函数≤50），无page依赖的来源解析不传page。原签名/async/单次委托保持，107其他Page属性原文不变。
2. 保留render guard先于初始化赋值/null原型缓存及新实例/data与controller身份；ID/source/30分钟严格TTL/重复及非正有限ID/异常回退；动态wx receiver与hooks/load不await。操作栏3000ms空闲续等和存活守卫、卸载序号→timers→hooks→cache→guard及异常部分清理保持。
3. 14契约原页重放通过，当前十一组135/全量Node2276/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过；1000组生命周期/来源/timer/卸载状态轨迹一致。14模块71委托/771预算；CI与compatibility§12/inventory同步。
4. 实现及最终docs/CI两轮独立只读review无P0–P3；10冻结路径和15保护路径hash提交前后匹配。证据/tmp/wrong-detail-lifecycle-batch/，禁止重跑extract-lifecycle.js。
5. 显式10路径本地提交23b98e33，author lmh/noAI trailer，相对origin/main65642c81 ahead10，索引空；保护路径保持，仅tasklog/context追加未暂存。无push/deploy/生产/数据操作。NEXT掌握/撤销/删除/渲染安全职责，再wrong-book及全栈清单；既有失败和真实验收缺口不变，整体ACTIVE。


## 二百九十、小程序错题详情掌握与撤销编排（2026-10-29，`86f09f01`）

1. 页面771→620行；掌握弹层/请求/结果/写回与重新加入复习九方法迁至master-flow130行，撤销入口/请求/错误/提交/窗口/timer八方法迁至master-undo93行，函数≤50。原签名/async/单次委托保持，102其他Page属性原文未变。
2. 保留私有ID优先/busy/patch-before-request/await后guard和live handler、skip/count同步、cache元数据与view副本/undo snapshot、5000ms窗口/120ms当前index前进、API/wx receiver和错误/finally边界。新刻画并保留404/410后仍commit+success toast，timer清理try外失败保留inflight两处原限制，不夹带修复。
3. 原页15契约与当前通过，十二组150/全量Node2291/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过；1360组十七入口返回/状态/轨迹/字段序一致。16模块88委托/620预算；CI及compatibility§13/inventory同步。
4. 实现及最终docs/CI两轮独立只读review无P0–P3；10冻结与15保护路径hash提交前后匹配。证据/tmp/wrong-detail-master-batch/，禁止重跑extract-master.js。
5. 显式10路径本地提交86f09f01，author lmh/noAI trailer，origin/main65642c81 ahead11，索引空；保护路径保持，tasklog/context追加未暂存。无push/deploy/生产/数据操作。NEXT移出错题本/渲染安全/老师剩余职责，再wrong-book及全栈清单；真实环境与既有失败限制保持，整体ACTIVE。


## 二百九十一、小程序错题详情移出与返回编排（2026-10-29，`7d5fc800`）

1. 页面620→579行；更多菜单/确认开关/移出请求五方法迁至remove-flow63行/函数≤50，原签名/async/单次委托保持，114其他Page属性原文不变。
2. 保留ID/busy/try外clearUndo与patch、响应后当前列表与index、String过滤全部同ID/cache删除/原ids-ts存储shape、异常吞掉、空列表toast→clear→220ms返回、非空await load后无第二alive guard与原catch/部分写回。
3. 原页9契约与当前通过，十三组159/全量Node2300/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过；1000组五入口结果/状态/轨迹/字段序一致。17模块93委托/579预算，CI/compatibility§14/inventory同步；实现及最终docs独立review无P0–P3。
4. 显式9路径本地提交7d5fc800，author lmh/noAI trailer，索引空，无push/部署/生产/数据操作。证据/tmp/wrong-detail-remove-batch/；禁止重跑extract-remove.js。提交前AGENTS外部变化导致保护hash失败，但shell未中止而继续提交；已只读确认提交恰为9个冻结路径，未包含AGENTS。后续校验与commit改为同一Python进程，失败立即中止。
5. 用户明确确认并重新提供AGENTS，按当前规则继续。恢复时CLAUDE已改为引用AGENTS并保留Claude专属流程；两文件均作为恢复前现有改动保护、不暂存，其他旧保护路径匹配。本节与context补记未暂存。NEXT渲染安全/专项老师交互，再wrong-book及全栈清单；真实环境验收缺口保持，整体ACTIVE。


## 二百九十二、小程序错题详情渲染安全与专项老师交互收敛（2026-10-29，`a66f1b55`）

1. 页面579→502行；渲染检查/trace/安全模式三方法迁至render-safety63行，专项老师动作开合/缓存键/反馈四方法迁至teacher-interaction46行；函数≤50，原签名/async/单次委托保持，112其他Page属性原文不变。原run408TeacherAction直接controller委托与另7薄入口保留，104Page方法+4页外helper均登记108精确模板，19模块预算300/50。门禁新增未知callable/spread负例。
2. 保留CODE/MIXED边界/日志自愈顺序/live config/20trace引用/动态renderer与字段顺序；teacher六字段key/try外验证/提交时payload/await后live cachekey及wx/helper和API receiver/toast先于formatter/原并发和无alive guard行为。
3. 原页11契约与当前通过，十四组171/全量Node2312/render5fixtures31/八门禁/JS语法/visual/math/CI YAML/diff通过；1400组七入口返回/状态/轨迹/字段序一致。reliability注册新契约；ci.yml仅backend/docker/migration四job，无本批需改的mini固定清单。compatibility§15/inventory同步。
4. 实现及最终文档/CI两轮独立review无P0–P3；11冻结路径和新版19保护路径提交前后hash一致，用户确认的AGENTS/恢复前CLAUDE变动均保留不暂存。代码检索通过codebase-memory-mcp CLI工具，index_status ready并核对五路径coverage；graphify query已执行但repo graph缺失，未虚称图覆盖。
5. 显式11路径本地提交a66f1b55，author lmh/noAI trailer，校验与commit同Python进程、失败即止；索引空，无push/deploy/生产/用户数据操作。证据/tmp/wrong-detail-remaining-batch/，禁止重跑extract-remaining.js。本节/context追加不暂存；NEXT错题本请求/批量/AI编排，再practice/pomodoro-stats/队列OCRAI/Phase0/Admin/全栈及真实验收。整体ACTIVE。


## 二百九十三、小程序错题本加载请求编排（2026-10-29，`76e42e53`）

1. 页面1306→1141行；筛选重载/页面加载/统计/列表/任务流/科目六方法迁至request-flow191行，函数≤50。原参数/default/async/单次委托保持，六方法仅替换receiver/API端口，其余128个Page属性原文不变。
2. 保留日期同步与任务参数try外位置、各请求不同destroyed/alive/seq守卫、列表两次guard、await后当前helper/状态、Promise.all启动顺序、列表分页/字段序/高频全局优先口径、reset任务流非等待、错误日志与格式化边界。筛选patch可覆盖默认字段，统计/科目未新增alive守卫。
3. 原页14契约与当前通过，四组定向28/全量Node2326/render5fixtures31/八门禁/JS语法/visual/math/CI YAML/diff通过；1200组六入口返回/状态/轨迹/字段序差分一致。页面预算1141，5模块/33委托；reliability注册请求契约，compatibility§4/inventory同步。
4. 独立实现及最终docs/CI两轮只读review无P0–P3；10冻结路径与19保护路径hash提交前后匹配。证据/tmp/wrong-book-request-batch/，禁止重跑extract-request.js。代码图index ready、outline157结果全部取完；graphify图缺失的限制保持，不虚称完整覆盖。
5. 显式10路径本地提交76e42e53，author lmh/noAI trailer，相对本地origin/main65642c81 ahead14；校验与commit同Python进程失败即止，索引空。保留用户现有改动，仅tasklog/context追加且不暂存；无push/deploy/生产/用户数据操作。NEXT错题本生命周期/选择/批量/撤销/AI，随后practice/pomodoro-stats/队列OCRAI/Phase0/Admin/全栈及真实验收。整体ACTIVE。


## 二百九十四、小程序错题本选择与工具条交互（2026-10-29，`dc432aca`）

1. 页面1141→1028行；视图切换/批量模式/交互滚动/工具条计时/点击长按/选择切换与全选/有效键同步/徽标反馈十六方法迁至selection-flow179行，函数≤50。仅this接收者/idle常量/平台getter替换，其余118个Page属性原文不变。
2. 保留map复制与truthy判定/有效键忽略原值/屏外键与全选不额外sync；列表重复ID和任务ID去重口径。保留工具条5000ms、徽标未跟踪首段16ms与260ms、执行时alive/mode/visible；700ms长按抑制、try内平台动态读取与receiver/异常吞掉/当前hook与部分写入边界。
3. 新15契约原页/当前通过，五组43/全量Node2341/render5fixtures31/八门禁/JS语法/visual/math/CI YAML/diff通过；1600组入口/状态/timer/轨迹/字段序差分一致。门禁1028预算/6模块49委托；reliability新增选择契约；compatibility§5/inventory同步。
4. 独立实现与最终docs/CI两轮只读review无P0–P3，10冻结与19保护hash提交前后匹配；暂存blob逐文件匹配hash。代码图Verify选择相关16结果完整、coverage四路径metadata_match/no_recorded_issue/best effort，generation2026-10-29T11:31:10Z；graphify仍无repo图，回读已定位文档。证据/tmp/wrong-book-selection-batch/，禁止重跑extract-selection.js。
5. 显式10路径本地提交dc432aca，author lmh/noAI trailer，origin/main65642c81 ahead15；校验与commit同Python进程失败即止，索引空，保护路径保持，tasklog/context追加未暂存。无push/deploy/生产/数据操作。NEXT错题本生命周期/批量请求与撤销/AI，再全栈剩余清单；真实微信/外部AI/完整闭环未验收，整体ACTIVE。


## 二百九十五、小程序错题本批量请求与撤销（2026-10-29，`d614adf0`）

1. 页面1028→894行；批量菜单/确认/请求/ID与动作规则/成功错误/缺失接口/重载十二方法迁至batch-flow131行，掌握结果/撤销/清理三方法迁至batch-undo67行，函数≤50。原参数/async/单次委托保持，三个纯规则不传page；其余119个Page属性原文不变。
2. 保留确认前捕获ids/labels、数字字符串严格往返转换、确认/loading异常try外、hideLoading→销毁判断→当前handler顺序、非等待菜单/缺失接口；skipped/count/undo副本与5000ms窗口、undo undefined返回/then.catch/非等待reload/动态API及platform receiver和部分inFlight状态保持。
3. 新刻画保留既有缺陷：普通成功响应无updated_count时_handleBatchSuccess引用未定义ids，ReferenceError由动作入口catch处理；请求前timer/loading异常可保留inFlight，成功处理异常进原重试catch。未夹带业务修复。
4. 新18契约原页/当前通过，六组61/全量Node2359/render5fixtures31/八门禁/JS语法/visual/math/CI YAML/diff通过；1500组入口/返回/状态/timer/轨迹/字段序差分一致。门禁894预算/8模块64委托；reliability新增批量契约，compatibility§6/inventory同步。独立实现及最终docs/CI两轮review无P0–P3。
5. 11冻结路径与19保护路径hash提交前后匹配、暂存blob逐文件匹配；同Python进程失败即止校验+commit。显式11路径本地提交d614adf0，author lmh/noAI trailer，origin/main65642c81 ahead16，索引空。用户改动保持，日志/context追加不暂存，无push/deploy/生产/用户数据操作。
6. 证据/tmp/wrong-book-batch-actions/，禁止重跑extract-batch.js。Verify图generation2026-10-29T11:44:40Z，相关5结果完整/四路径coverage metadata_match/no_recorded_issue/best effort。NEXT错题本生命周期/导航导出/AI，然后practice/pomodoro-stats/队列OCRAI/Phase0/Admin/全栈及真实验收。既有legacy/data envelope/真实客户端与外部AI等限制保持，整体ACTIVE。


## 二百九十六、小程序错题本生命周期与导航导出（2026-10-29，`5748c0b9`）

1. 页面894→783行；load/ready/show/hide/unload五方法迁至lifecycle67行，能力检查/返回/详情导航/导出入口与记录/详情事件六方法迁至navigation-flow92行，函数≤50。原签名/async/单次委托保持，两个无page导航入口不传page；其余123个Page属性原文不变。
2. 保留load部分seq/state重置/配置/query/helper顺序、ready非等待subjects、show存活/日期/工具条/ready guard/非等待Promise.all后当前diagnosis无新增销毁guard；卸载六序号→工具条→两timer→撤销与异常部分清理保持。能力flag严格true/requestId守卫/try边界/当前formatter保持；导航ids引用和原始ID/ts/索引/存储失败fallback、导出有限非零ID含负数小数/100上限/全局写入顺序与路由、平台/app动态getter保持。
3. 新17契约原页/当前/replay通过，七组78/全量Node2376/render5fixtures31/八门禁/JS语法/visual/math/CI YAML/diff通过；11方法AST token归一化等价，1100组入口/返回/状态/导航/轨迹/字段序差分一致。初始提取误改export-config路由被契约捕获并恢复，最终token检查包含字符串原值；禁止重跑extract-lifecycle.js。
4. 门禁783预算/10模块75委托，reliability新增生命周期契约，compatibility§7/inventory同步。独立实现及最终docs/CI两轮review无P0–P3；11冻结及19保护hash提交前后匹配，staged blob逐文件匹配。证据/tmp/wrong-book-lifecycle-batch/；Verify图generation2026-10-29T11:58:48Z，相关4+测试19结果完整，四路径coverage metadata_match/no_recorded_issue/best effort。
5. 同Python进程失败即止校验与显式11路径本地提交5748c0b9，author lmh/noAI trailer，origin/main65642c81 ahead17，索引空；保护用户改动保持，tasklog/context追加未暂存，无push/deploy/生产/数据操作。NEXT错题本筛选/AI剩余编排，然后practice/pomodoro-stats/队列OCRAI/Phase0/Admin/全栈及真实验收。所有既有baseline/legacy和真实客户端/外部AI/full-flow限制保持，整体ACTIVE。


## 二百九十七、小程序错题本 AI 状态与缓存设置（2026-10-29，`108f83c7`）

1. 页面783→652行；文案/归一化/内容与pending判定/详情投影五方法迁至ai-state80行，用户/设置键/设置恢复/开关/缓存恢复/签名/缓存提交八方法迁至ai-persistence107行，函数≤50。原签名/单次委托保持，纯规则不传page；13方法AST token仅receiver及storage/cache/platform/prefix注入替换，其余121个Page属性原文不变。
2. 保留JSON深拷贝/混合accuracy与详情口径/内容动态normalizer/签名firstItem读取；用户truthy优先/原设置prefix与严格true/storage异常null；缓存对象身份/原始summary/时间先于save/save后当前detail helper/字段顺序与失败部分状态。开关保持存储→timer清理→patch→420ms→toast→启动；活动请求失效seq、已有promise.finally后当前alive/setting/helper及非等待语义保持。
3. 新15契约原页/当前/replay通过，八组93/全量Node2391/render5fixtures31/八门禁/JS语法/visual/math/CI YAML/diff通过；1300组入口/返回/状态/缓存/timer/轨迹/字段序差分一致。门禁652预算/12模块88委托；reliability新增AI状态契约，compatibility§8/inventory同步。独立实现与最终docs/CI两轮review无P0–P3。
4. 11冻结与19保护hash提交前后匹配、staged blob逐文件匹配；同Python进程失败即止校验+显式11路径本地提交108f83c7，author lmh/noAI trailer，origin/main65642c81 ahead18，索引空。用户改动保持，tasklog/context追加不暂存，无push/deploy/生产/用户数据操作。
5. 证据/tmp/wrong-book-ai-state-batch/，禁止重跑extract-ai-state.js。Verify图generation2026-10-29T12:17:10Z，相关10结果完整，四路径coverage metadata_match/no_recorded_issue/best effort；不宣称新文件索引完整性。NEXT错题本筛选/AI请求轮询与结果交互，再全栈其余清单。既有缺陷及真实客户端/外部AI/full-flow限制保持，整体ACTIVE。


## 二百九十八、小程序错题本 AI 请求与交互编排（2026-10-29，`00d2bb18`）

1. 页面652→504行；诊断检查/延迟/轮询/ensure/请求装配与执行/fetch/结果分流/错误九方法迁至ai-request-flow147行，洞察展开/刷新/反馈三方法迁至ai-interaction53行，函数≤50。原参数/async/单次委托保持，delay不传page；12方法AST token仅receiver及API/cache/platform/timeout注入替换，其余122个Page属性原文不变。
2. 保留严格零与去重/force/前台已有数据/缓存过期和签名冷却优先级，55000ms与refresh字段、4次延迟1200/1550/1900/2250ms/延迟后seq+alive/当前API及helper、result不await和catch/finally边界；展开loading try外/finally hide/无额外aliveguard、刷新非等待、反馈成功toast原catch范围保持。
3. 新刻画保留原并发限制：executor finally无条件清当前Promise字段，可清掉较新字段；第四轮响应后直接返回无新增guard。本批不夹带身份保护或业务修复。
4. 新20契约原页/当前/replay通过，九组113/全量Node2411/render5fixtures31/八门禁/JS语法/visual/math/CI YAML/diff通过；1200组入口/返回/状态/请求轮询/轨迹/字段序差分一致。门禁504预算/14模块100委托；reliability新增AI请求契约，compatibility§9/inventory同步。独立实现与最终docs/CI两轮review无P0–P3。
5. 11冻结及19保护hash提交前后匹配、staged blob逐文件匹配；同Python进程失败即止校验与显式11路径本地提交00d2bb18，author lmh/noAI trailer，origin/main65642c81 ahead19，索引空。用户改动保持，tasklog/context追加未暂存，无push/deploy/生产/数据操作。
6. 证据/tmp/wrong-book-ai-request-batch/，禁止重跑extract-ai-request.js；Verify图generation2026-10-29T12:33:17Z，相关11结果完整，四路径coverage metadata_match/no_recorded_issue/best effort。NEXT错题本筛选剩余编排和完整入口门禁，然后全栈其余清单。既有缺陷和真实客户端/外部AI/full-flow等限制保持，整体ACTIVE。


## 二百九十九、小程序错题本筛选与完整入口门禁（2026-10-29，`4593692e`）

1. 页面504→478行，12筛选/日期/参数/重试/加载更多方法迁至filter-flow76行/函数≤50；AST token仅receiver及API/date helper替换，122其他唯一属性/123声明和完整顺序不变。保留custom也先now/空patch、truthy/日期计数/参数字段序、Number不校验finite、retry返回与loadMore非等待。
2. 15模块112委托，114唯一Page方法/115声明（原noop两处）及19私有默认字段纳入门禁；data要求object literal但不宣称校验其内部值。独立review发现首noop漂移被Map覆盖的P3，已逐occurrence校验并补首noop负例，复核关闭。
3. 原页/当前/replay各10契约通过，定向126/全量Node2424/render5fixtures31/八门禁/JS语法/visual/math/YAML/diff通过，1200组差分一致。compatibility§10/inventory/CI同步；实现与最终docs两轮review无剩余P0–P3。
4. 9冻结路径、19保护hash及staged blob提交前后匹配；同Python进程失败即止校验和显式本地提交4593692e，author lmh/noAI trailer，origin/main65642c81 ahead20，索引空。保留现有用户改动，tasklog/context追加未暂存，无push/deploy/生产/数据操作。
5. 证据/tmp/wrong-book-filter-batch/，禁止重跑extract-filter.js；图generation2026-10-29T12:49:19Z相关查询全部分页完成，6路径coverage metadata_match/no_recorded_issue仅best effort。NEXT practice剩余页面职责、pomodoro-stats视图写回，再队列/OCR/AI/Phase0/Admin/全栈及真实验收；既有缺陷和真实客户端/外部AI/full-flow限制不变，整体ACTIVE。


## 三百、重构工作流调整（2026-10-29，用户确认Q1–Q5）

按页面/完整链路合并批次，批内定向验证，批末全量验收和一次独立审查；保留兼容、300/50预算及原有Git/数据边界。执行规则见 `prompts/tasks/refactor_workflow.md`。context已压缩，原文快照在 `prompts/tasks/archive/context-2026-10-29-before-workflow.md`；本文件历史保留。下一批为practice整个剩余页面职责，退出流程不单独提交，其后pomodoro-stats。命令/数字/hash集中批次结果清单；不机械复制多份日志或重复独立审查。


## 三百零一、Practice整页剩余职责收敛（2026-10-29，`b2617894`）

按新工作流一次整页批次完成controller装配、生命周期与启动预设收敛，保留行为/接口与既有controller；兼容边界见 `docs/architecture/PRACTICE_SUBMISSION_COMPATIBILITY.md` §23，验收数字/命令/源码哈希见 `docs/architecture/refactor-results/practice-page-2026-10-29.json`。一次独立审查的两项P3门禁缺口已修复并增量复核关闭。显式18路径本地提交，保护/冻结/blob校验与commit同进程失败即止，提交后索引空；无push/生产/数据操作。用户明确其他任务已提交的cfd191a8/a61c2146不属本任务，已按HEAD核对并保留。NEXT pomodoro-stats整页视图写回/装配；整体ACTIVE，真实客户端及全栈验收未完成。


## 三百零二、Pomodoro统计整页装配与视图写回（2026-10-29，`f786b057`）

一个整页批次完成47方法/六职责模块收敛，原controller/投影与语义保持；边界见 `docs/architecture/LEARNING_DATA_COMPATIBILITY.md` §17，验收数字/命令/hash见 `docs/architecture/refactor-results/pomodoro-stats-page-2026-10-29.json`。独立review一项P3（禁用注册条件仍过门禁）已修复并增量复核关闭；显式17路径同进程失败即止校验+本地提交，保护21/冻结/blob提交前后匹配，索引空，无push/生产/数据操作。NEXT后端OCR冻结/跨页编排及AI剩余长函数；当前AST实测task_queue_service2345行但无>50函数，不重复按旧记录拆分。整体ACTIVE，真实客户端/外部服务/完整闭环仍未验收。


## 三百零三、OCR 冻结投影与跨页合并完整链路（2026-10-29，`99a09fcd`）

按新工作流一次批次迁移冻结应用/双轨对比/VL 重绑定/跨页检测合并，五历史入口和动态端口语义保持；兼容边界见 `docs/architecture/PIPELINE_ORCHESTRATOR_COMPATIBILITY.md` §16，命令/数字/hash集中于 `docs/architecture/refactor-results/ocr-freeze-cross-page-2026-10-29.json`。一次独立review无P0–P3，11路径显式本地提交，21保护/冻结/staged blob同进程失败即止校验并提交后复核，索引空，无push/生产/数据操作。额外全目录architecture扫描的两项既有legacy-name白名单失败已复现并记录，本批未扩大白名单；固定CI静态清单通过。NEXT剩余OCR诊断/工件/后台编排完整链路、AI及Phase0/Admin/全栈验收；整体ACTIVE，外部服务与真实客户端未验收。


## 三百零四、接口改动优先级调整（2026-10-29，用户确认）

当前顺序改为“小程序接口 > 后台管理系统接口 > OCR 接口”，已同步 `context.md`、`refactor_workflow.md` 和 `docs/architecture/REFACTOR_INVENTORY.md`。本轮OCR后续仅只读盘点无实现改动，转向小程序实际消费的Public API及其业务链路；保留既有完整链路批次、兼容和Git/生产边界。
