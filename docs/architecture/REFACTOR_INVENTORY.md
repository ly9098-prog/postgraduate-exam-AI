# 全栈重构源码盘点

> 核对日期：2026-10-23（§1 计数为当日复跑；各批次叙事截止 2026-10-22）；对应 `prompts/tasks/current_task.md` 阶段 0/4。
> 本清单登记真实入口、结构证据、回归入口和后续决策，不代表所有业务语义已审查完毕。

## 1. 范围与证据

- 后端直接解析 `backend/app/**/*.py`：591 个模块、2,282 条模块导入边（2026-10-23 用 `backend/tests/architecture/dependency_scan.py` 复跑；0 静态循环）。覆盖函数内和 TYPE_CHECKING 内的导入、相对导入及字面量动态导入（相对动态导入需同时给出字面量 package）；不执行应用代码，不读取数据库或真实配置。
- 路由以 `backend/app/api/v1/router.py`、`backend/app/api/admin/router.py` 和 `backend/app/api/router.py` 的实际注册为准。Public/Admin 使用同一个后端，另有内部 OCR worker 路由；本清单不按文件名推断是否对外启用。
- 管理端通过 TypeScript AST 检查 `admin-frontend/src/app/**/page.tsx`：32 个页面入口，含登录和重定向页；枚举导入及函数长度，不把外层 React 函数的 JSX 行数等同于业务复杂度。
- 小程序从 `miniprogram/app.json` 的 pages/subPackages 解析 25 个注册页面，再用 TypeScript AST 读取实际 JS、require 和方法长度；不根据目录位置推断主包归属，例如番茄钟位于 pages 下但实际注册为分包。
- Codebase Memory 索引时间为 2026-10-15T16:20:28Z，scope 覆盖返回 known_gaps 和截断。仅用于确认索引状态，本清单的模块/入口与依赖数据来自当前文件扫描；未据索引缺失认定死代码。
- 编号批记（§4/§6）截止「第一百一十二阶段」（2026-10-22，5c62d707）；2026-10-22 当天的前端/统计/复习重构批次（2753ccf9…84e8dc66 等 9 个提交）以 §2/§3 表格行登记，不占编号批记。

## 2. 按业务域登记

后端路径相对 `backend/`，管理端页面相对 `admin-frontend/src/app/`，小程序路径相对 `miniprogram/`；测试是已存在的核查入口，除执行记录明确列出的命令外，不代表本批已运行。

| 业务域 | 后端入口与实现 | 管理端消费者 | 小程序消费者 | 决策与后续验证 |
| --- | --- | --- | --- | --- |
| 身份与权限 | `app/api/v1/auth.py`、`admin_auth.py`、`admin_rbac.py`；`services/admin_auth_service.py` | `(auth)/login`、`admin-users`、`roles`、`app-users`、`audit-logs`；`lib/auth`、`lib/api/client.ts` | `pages/login/login.js`、`utils/auth.js`、`utils/api.js` | 保留两类 JWT/RBAC 边界，认证协议不重做。管理员/角色页面仍为长入口，状态与请求职责待逐段核查。验证入口：后端 `test_admin_auth.py`、`test_admin_rbac.py`，前端 `auth-store.test.ts`、`client.test.ts`；真实 401 刷新/403 与会话恢复待验证。 |
| 题库治理 | `questions.py`、`admin_questions.py`、`admin_subjects.py`、`admin_knowledge.py`、`admin_syllabus.py`；`services/admin_question_service.py`、`question_revision_service.py`、`question_snapshot_service.py` | `questions`、`subjects`、`syllabus`、`knowledge-graph`、`coverage`、`review` | 刷题与错题页、`subpackages/knowledge` | 题库页已拆查询、保存和部分编辑职责，不能据此标记知识图谱等页面完成。草稿保存与图片/选项即时写入的 owner/generation、缓存合并和权限边界见 `ADMIN_QUESTION_COMPATIBILITY.md`；页面剩余筛选、列表/表格、抽屉展示和版本比较组合仍待治理。保留版本/知识点权威实现。现有 `question-*.test.ts`、题库 API 与版本测试继续作基线。 |
| 导入与 AI/OCR | `imports.py`、`ai_import.py`、`admin_imports.py`、`admin_ai_config.py`、`admin_ai_settings.py`；`features/pipeline_orchestrator.py`、`question_pipeline.py`、`services/import_pipeline_service.py` | `imports/*`、`ai-settings`、`system/tasks` | 当前 25 个注册页没有独立 AI/OCR 导入页面，不新增小程序导题入口 | 审核页已拆纯规则、mutation、编辑、详情展示、动作反馈与确认/选择状态；已选批量全部失败现在保留选择与确认供重试，部分/成功仍清理。仍需收敛权限、跨刷新选择、异步刷新及剩余弹层组合；排序/过滤/分页、选择集、动作返回与已知边界见 `REVIEW_QUEUE_COMPATIBILITY.md`。OCR 编排/worker 相互导入与 question_pipeline 兼容入口见静态循环登记；迁移必须补恢复、任务与人工审核证据。现有 `tests/architecture`、`tests/pipeline`、`tests/ocr_pipeline` 为验证入口。 |
| 学习闭环 | `practice.py`、`wrong_questions.py`、`review.py`、`exams.py`、`study_plan.py`、`study_hub.py`、`adaptive_learning.py`；`services/practice_service.py`、`wrong_question_service.py`、`review_scheduler.py`、`exam_service.py`、`study_plan_service.py` | `exams`、`exams/[id]`、`recommendation/*`、题库配置 | `subpackages/study` 的刷题/结果/错题/今日复习/学习计划，`subpackages/exam` | GET 发题编排已治理；刷题科目树/最近科目、启动预设、发题批次校验与最近科目选择/持久化、选项交互、题目展示/渲染缓存/答案状态/计算字段/答题反馈/渲染不变式检查/题目计时/安全模式自愈纯规则已抽出；提交、错题/复习、考试、计划/推荐仍待迁移。今日复习 `submitGroup` 剩余 73 行，题目提交 payload 构建/不可变校验、批改请求/结果缺失处理、结果匹配/投影、失败提示、历史合并、重试组、今日进度/视图字段、提交入口/重校验/日同步、提交确认、请求与结果写回 controller 已收敛；`nextGroup` 入口忙碌拦截、flow 序号、日同步回滚、本地/远端优先级、请求异常、完成态和 dock 写回 controller 已收敛，本地重试组答案过滤/会话/视图切换/计时重启与远端批次、题目规范化、草稿恢复、静默刷新、空批次重试/完成判定、迟响应守卫由子 controller 承接；完成 dock 展示、旧 fade 清理、5 秒隐藏及页面/phase/剩余任务守卫已收敛；计时启动/恢复/暂停/重置/停止、tick 十秒截断、elapsed 视图和幂等时长快照由 timer controller 承接；标记掌握/撤销掌握、5 秒 undo 窗口、inactive 任务与失败路径由 master controller 承接；首次启动批次的忙碌/flow/空批次/错误守卫、题目规范化、草稿恢复、当前题装配、任务计数与渲染接线由 start controller 承接；草稿键构建、读写、持久化、恢复与已提交清理由 draft controller 承接；单选/多选/多空选项切换、答案持久化触发与视图写回由 answer interaction controller 承接；题目展示/当前题装配/已答计数/runner 字段/已答标记同步由 question display controller 承接；概览 VM 构建/建议文案/批次大小归一化由 overview VM controller 承接；渲染不变式检查/渲染轨迹记录/setData 体积检查由 render safety controller 承接；批次大小选择器展示/关闭/选择/确认由 batch size sheet controller 承接；题目分组/富化/结果富化由 question enrichment controller 承接；复习会话创建/日期串/请求 ID/科目标签由 review session controller 承接；返回拦截/退出确认/导航回退由 nav back controller 承接；安全模式激活与当前题重渲染由 self heal controller 承接；概览同步到会话/跨天重置/活动会话 VM 调整由 overview sync controller 承接，不搬进万能 runner。回归入口：后端 `tests/practice`、`test_practice_chain_regressions.py`、`test_review_api.py`；小程序 `test-practice-subject-tree.js`、`test-practice-launch-preset.js`、`test-practice-question-batch.js`、`test-practice-recent-subjects.js`、`test-review-group-submission.js`、`test-review-submit-confirm-controller.js`、`test-review-submit-request-controller.js`、`test-review-submit-result-controller.js`、`test-review-submit-entry-controller.js`、`test-review-next-retry-group-controller.js`、`test-review-next-remote-batch-controller.js`、`test-review-next-group-controller.js`、`test-review-result-dock-controller.js`、`test-review-timer-controller.js`、`test-review-master-controller.js`、`test-review-start-batch-controller.js`、`test-review-draft-controller.js`、`test-review-answer-interaction-controller.js`、`test-review-question-display-controller.js`、`test-review-overview-vm-controller.js`、`test-review-render-safety-controller.js`、`test-review-batch-size-sheet-controller.js`、`test-review-question-enrichment-controller.js`、`test-review-session-controller.js`、`test-review-nav-back-controller.js`、`test-review-self-heal-controller.js`、`test-review-overview-sync-controller.js`、`test-review-submit-completion.js`、`test-practice-result-diagnosis.js`。 |
| 学习数据 | `pomodoro.py`、`stats.py`、`study_report.py`；`services/pomodoro_service.py`、`pomodoro_subject_projection.py`、`pomodoro_statistics_window.py`、`pomodoro_statistics_accumulation.py`、`pomodoro_statistics_response.py`、`learning_time_projection.py`、`pomodoro_normalization.py`、`pomodoro_attribution.py`、`stats_service.py`、`study_report_service.py`、`recommendation_experiment_service.py`、`recommendation_metrics_service.py`、`study_plan_service.py` | `dashboard` 使用独立 Admin 统计；推荐实验页和 `app-users` 的展示仍待细查 | `pages/home`、`pages/dashboard`、番茄钟、学习计划和 `productivity/pomodoro-stats` | 有界语义与迁移决定见 `LEARNING_DATA_COMPATIBILITY.md` 和 `LEARNING_DECISION_COMPATIBILITY.md`：事务/统计日/科目快照、报告口径与学习计划分配不能直接合并。推荐首次分组、学习计划/日快照已使用 savepoint claim；推荐日指标聚合增加 PG advisory lock/SQLite write lock，覆盖 variant 为空的并发重复风险。stats/report 趋势查询已收紧半开上界，但保留各自 accuracy 与复习口径。snapshot 窗口、响应、两来源累计与科目投影已分离，Page controller 与剩余装配仍待治理。`sync.py` 实际为 Admin 权限题库导入，归导入/题库域；旧统计测试缺口已修复并接入 CI，仍不称全域完成。 |
| 公式与导出 | `formulas.py`、`admin_formulas.py`、`exports.py`；`services/formula_*`、`services/export/*` | `formulas`、`formulas/[id]`、`formulas/new`、`formulas/categories` | `subpackages/formulas`、`subpackages/export` | 保留已有公式编辑 workbench/图谱辅助模块；列表页与导出记录页转换/查询职责待核查。DOCX/OMML 与 export service/processor 既有局部互引按具体边登记，不新增第二套导出器。回归入口：后端 `tests/export`、`test_admin_formulas.py`；小程序公式脚本、`test-export-capability-error.js`。 |
| 公共运行时 | `main.py`、`worker_main.py`、`scheduler_main.py`；`services/task_queue_service.py`、`task_queue_worker.py`、`task_queue_script_bindings.py`、缓存/存储/健康服务 | `lib/api/client.ts`、`lib/api/sse.ts`、`system/tasks`、`imports/tasks` | `app.js`、`utils/api.js`、`utils/storage.js`、现有内容渲染器 | 主入口 lifespan 136 行、任务消费 `_process_task_v2` 307 行，按角色/状态机拆分。v1/v2 入队、fencing、死信、取消、reaper 和 v1→v2 迁移边界见 `TASK_QUEUE_COMPATIBILITY.md`。HTTP、worker、scheduler 的退出与失败路径分别验证；新门禁不证明运行时安全。回归入口：`test_worker_sigterm.py`、`test_worker_kill.py`、任务队列测试及客户端 API/SSE 测试。 |

## 3. 当前热点的具体处理依据

长度是物理行数；函数长度含嵌套块。这里只列优先热点，未列出的文件没有被认定为“无需处理”。

| 路径 | 文件行数 | 候选函数/方法及行数 | 已确认职责或待分离边界 |
| --- | ---: | --- | --- |
| `backend/app/features/pipeline_orchestrator.py` | 7151 | `_run_split` 473 | 阶段输入/输出、检查点、恢复与异常传播；复用已有 stages，待故障注入。 |
| `backend/app/services/practice_service.py` | 4132 | `get_smart_practice_questions` 446 / `get_smart_scored_questions` 144 | smart 策略编排仍由入口持有；scored 满额/缺口补充已迁至 `practice.smart_scored_supplement`，查询、评分、最终日志与事务仍由调用方负责，后续继续收口其余分支。 |
| `backend/app/services/task_queue_service.py` | 2690 | `fail_v2` 187 | 21 个 Lua 脚本与键空间构造已迁至独立协议模块，脚本源/实例绑定顺序集中于 `task_queue_script_bindings.py`；v1→v2 已改为单任务原子迁移，脚本字节、既有 key 命名和 v2 状态返回保持不变。`DurableTaskQueue` 仍持有入队、认领、租约、重试、死信和管理编排，须继续结合真实队列集成拆分。 |
| `backend/app/services/ai_service.py` | 2301 | `analyze_error` 790 | revision 协议已移至中立模块，解除预热循环；分析执行编排仍待治理，保持凭据和画像边界。 |
| `backend/app/main.py` | 461 | `lifespan` 174 | HTTP/观测/关闭、schema/seed/自检及HTTP角色/隔离/失败策略已独立；执行器/孤儿协调器/OCR资源装配与归属已独立；其他角色启动与完整失败清理仍待治理。 |
| `backend/app/core/bootstrap.py` | 282 | `_run_role_async` 50 | 独立worker/scheduler入口；审计/推荐启动与HTTP共用，原TaskRegistry/失败策略保留。完整worker/scheduler runner初始化/等待/关闭受控契约已建立；失败清理存在既有缺口；隔离子进程SIGTERM/SIGINT和CLI正常退出已测，真实外部依赖全链未验收。 |
| `backend/app/services/pomodoro_service.py` | 1756 | `build_pomodoro_statistics_snapshot` 338 | 科目快照与整数秒分配已迁至75行纯模块，事务、查询、窗口和累计仍由原服务持有；继续补组合/失败契约后治理。 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 2351 | `ImportReviewPage` 2148 | 来源定位、AI 建议/答案等价、列表/表格徽章、筛选默认/重置、预览抽屉快照、批量补全草稿/结果、确认弹层、审核结果反馈、确认/选择状态、快速补答案视图及图片答案完整流程规则已抽出；徽章保留两视图的未知风险回退和显式来源差异，抽屉规则保留 JSON 快照、未保存确认及空段落语义，草稿规则保留 storage 失败静默、损坏数据回退和策略归一化，结果规则保留摘要顺序、非成功明细排序及失败/跳过样式，确认规则保留动作文案、选择数说明、危险态与驳回输入条件，反馈规则保留四类返回文案和单题成功后关闭抽屉，确认状态保留取消不清选择/原因及 mutation reset 顺序，快速补答案规则保留结果优先级、页签/步骤可见性和加载文案，图片流程保留文件顺序、模式持久、预览/写入清理和错误回退。页面仍集中筛选 interactions、编辑确认、异步刷新和剩余弹层编排；文本批量请求、执行锁与结果展示仍在页面。选择集跨队列刷新当前保留失效 ID 是既有行为，尚未改变。 |
| `admin-frontend/src/app/(admin)/questions/page.tsx` | 2397 | `QuestionsPage` 2044 | 查询/保存/草稿与部分编辑已抽出，其余页面组合待迁移。 |
| `admin-frontend/src/app/(admin)/knowledge-graph/page.tsx` | 1809 | `KnowledgeGraphPage` 613 | 图谱转换和交互已有页面外函数；继续核查请求/布局/选择状态。 |
| `admin-frontend/src/app/(admin)/system/tasks/page.tsx` | 1599 | `SystemTasksPage` 1121 | 任务列表/详情/事件消费与 UI 编排边界待核查。 |
| `miniprogram/pages/pomodoro/pomodoro.js` | 2180 | `onShow` 18 / `onHide` 30 | 展示恢复、离页持久化、倒计时/自由计时冷恢复、启动仪式、未知启动恢复、待同步动作、终态冲突、今日统计、主题、活动会话轻同步、暂停切换、恢复错误、庆祝消除、休息恢复、完成庆祝、工作完成、自由计时启动、取消结束确认、自由结束确认、倒计时暂停确认、倒计时中断确认、idle 重置及自由计时展示更新 controller 已独立；确认窗口快照纯规则已抽出，计时启动、自由计时已用时长及画布初始化/绘制已完成 controller 化；结束确认编排和其他页面职责仍待治理。 |
| `miniprogram/subpackages/study/practice/practice.js` | 2262 | `_loadQuestions` 191 | 科目树规范化、可选择科目扁平化、图标/标记、最近科目装饰、父科目/子科目关系和范围解析已迁至 `practice/utils/subject-tree.js`；启动参数解析、定向题约束覆盖、fast/完整启动视图和启动 override 写入已迁至 `practice/utils/launch-preset.js`；发题请求参数构建、章节后代范围契约与题目 ID/题型/科目范围校验已迁至 `practice/utils/question-batch.js`；默认科目选择和最近科目去重/截断/持久化值构建已迁至 `practice/utils/recent-subjects.js`；失败/成功/顺序重置视图、批次凭据写回和顺序计时重置已迁至 `practice/utils/question-load-state.js`；顺序完成确认、reset 请求、迟响应/卸载守卫、失败提示和重载分发已迁至 `sequential-restart-controller.js`。存储读写、请求发送和其余迟响应守卫仍在页面。 |
| `miniprogram/subpackages/productivity/pomodoro-stats/index.js` | 1627 | `onDayStartChange` 141 | 日期解析/格式化/周月边界/分布区间纯规则已迁至 `date-utils.js`；缓动、日期标签、学习标签、分布数据判定与颜色加深纯规则已迁至 `view-helpers.js`；时长格式化与数字/单位分段文本纯规则已迁至 `duration-formatter.js`；科目树构建、聚合值分配与分布归一化纯规则已迁至 `subject-distribution.js`；历史记录视图模型纯规则已迁至 `session-view-model.js`；饼图标签布局/碰撞解析纯规则已迁至 `pie-label-layout.js`；趋势柱网格/柱体/日期渲染已迁至 `trend-chart.js`；选中时长数值动画 token/计时器/展示写回已迁至 `duration-animation-controller.js`；饼图点按坐标换算、扇区选择与详情收起已迁至 `pie-tap-controller.js`；首屏数字/饼图动画与标签渐进显示编排已迁至 `start-animations-controller.js`；饼图几何参数、椭圆扇区与圆角矩形路径纯规则已迁至 `pie-geometry.js`；颜色加深缓存已迁至 `shade-color-cache.js`；画布亮/暗主题色板已迁至 `canvas-palette.js`；分布科目视图模型与主题色选择已迁至 `subject-items.js`；饼图标签绘制/DPR 对齐已迁至 `pie-label-renderer.js`；统计映射与视图写回待分离。 |

## 4. 依赖门禁与既有循环

`backend/tests/architecture/test_dependency_direction.py` 扫描全应用，service/feature 到 API 的静态导入必须为零。相对导入、局部导入和可静态解析的字面量动态导入也参与检查；源码语法错误、空目录或目录缺失不会静默跳过。

`dependency_scan.cyclic_edges` 计算强连通分量内部的全部边。第五十八批后全应用静态循环为零，`import_cycle_baseline.json` 已缩减为空数组；既有门禁继续拒绝任意新增循环边，不设组级白名单。扫描仍包含局部和 TYPE_CHECKING 导入；零静态循环不等于运行时资源、完整角色或业务端到端验收完成。

2026-10-23 队列协议边界批次将 `task_queue_service.py` 从 3,535 行降至 2,763 行：20 个 Lua 脚本文本按 v1 生命周期、v1 恢复、v2 入队/认领/回收、v2 终态转换拆入四个纯数据模块，Redis key 构造迁入 `task_queue_keys.py`；原服务继续重导出既有私有 key helper 和 prefix，任务 API、脚本参数、key 命名空间和状态返回均未改变。脚本 SHA-256 20/20 与原实现一致，新增脚本/key/尺寸门禁。后续脚本绑定批次将条目集中到 `task_queue_script_bindings.py`，服务降至 2,676 行；加载顺序、非幂等加载和 NOSCRIPT 全量重载接入 2 项直接回归。该证据仍不替代生产 Redis 中断、完整 worker、多 dispatcher、lease 回收或备份恢复演练。

第三十八批已解除 embedding / vector config 的 2 模块循环：`services/embedding_endpoints.py` 统一 URL 构造，运行请求与管理端连通测试直接依赖该纯规则，后者不再导入 embedding 执行服务；原配置读取方式不变。26 项端点/调用方回归及 302 组新旧规则对照验证行为一致，对应两条循环边已从基线移除。

第三十九批已解除 export service / processor 的 2 模块循环：`services/export/state_machine.py` 持有原转换表与校验函数，两类消费者直接依赖该规则。55 项状态规则测试、900 组新旧返回值/异常对照与现有导出/并发回归验证等价；不改变任务领取、事务或失败恢复。两条循环边已移除。当时导出 phase3 的 12 项旧验收因本机 DOCX 产物缺失而失败；第四十批已改为由真实导出器在 pytest 临时目录生成合成样本，恢复可重复验收。

第四十九批已解除 AI service / prewarm worker 的 2 模块循环：`ai/prewarm_revision.py` 持有原 revision 哈希规则，6 个消费模块直接引用，worker 不再提供旧实现/重导出。保持 prompt version、计数转换、答案原值、SHA-256 截取、任务 id/payload 和用户过滤不变。18 项规则、9 项协议/入口启停及 3 项架构测试通过；新进程导入规则不加载 worker、AI service 或 database。队列交接使用 mock 存储/入队端口，生命周期验证使用受控协程，不代表真实 Redis 租约、模型服务或部署角色验收。

第五十批已解除 DOCX / OMML 的 2 模块循环：`services/export/docx_fonts.py` 持有原字体策略和 East-Asian run 字体设置，两个渲染器直接调用；OMML 仅在纯文本兜底时惰性导入该规则，不再加载完整导出器。11 项字体/兜底测试及 3 项边界测试通过，108 组 run XML、原始兜底段落和 6 份完整文档的全部 ZIP 部件字节对照一致；完整架构与相关导出回归 391 项通过。没有修复既有 OOXML 元素顺序、矩阵包装或片段 LaTeX 问题，不据输出一致宣称 Word/WPS/LibreOffice 视觉验收通过。

第五十一批已解除 database / models 注册的 47 模块/95 边循环组：唯一声明基类迁至 `core/orm_base.py`，45 个模型/契约模块和 Alembic 直接引用，`database.Base` 仍是同一对象供现有运行时调用方使用。完整 79 表/79 mapper/1,076 列/246 索引的属性、默认值和 PostgreSQL/SQLite DDL 与迁移前一致；新进程模型注册和 Alembic metadata 装配均不加载配置或运行时数据库引擎。临时 SQLite 完整迁移、重复 init、用户持久化、失败清理及 cloud profile 禁止 runtime DDL 通过。真实 PostgreSQL/生产启动尚未验证，不能据静态循环消除标记高风险运行时整体完成。

第五十三批已解除 ocr_fix 包/适配器/router 的 4 模块/6 边循环组：包初始化只保留说明，两个业务入口直接导入 router，适配器直接导入 interfaces 模块，四处测试 patch 跟随真实定义迁移。3 个业务模块除 import 外完整 AST 不变，保留原错误/降级、安全门、模型配置和人工审核链路；不删除 DeepSeek 适配类或旧 OCR 兼容用例。15 项真实适配器/路由契约在修改前后通过；7 项边界测试确认新进程导入包、协议、canonical_output 或 router 不加载 AI client、配置、数据库及适配器。扩大架构/OCR/协调器/API 回归 314 通过、2 既有失败、1 既有 xfail；两项旧失败均是现有 router 测试仍注入 `deepseek` 键、而自动链使用 `openai-compatible`。未改生产路由或跳过失败，真实 OCR/模型、数据库/队列和客户端未验证。

第五十四批将上述自动链测试的七处注入键改为真实 canonical 名称，原结果/异常/安全拒绝与规则回退断言保留，不改生产行为。服务文件 24 项通过；扩大 OCR/导入边界/配置与故障回归共 136 通过、1 既有 xfail，关闭上述 2 项旧失败。外部 OCR/LLM 仍使用替身，不据此宣称生产链验收完成。

第五十五批去掉 question_pipeline 对 AI complete/enrich/draft 的旧转发，Admin service 直接依赖补全模块，App AI 路由直接依赖草稿生成模块并继续从 core 读取日志。旧代码新进程先导入 complete/enrich 均因部分初始化 ImportError 失败，新进程回归恢复通过；3 个生产文件完整 AST 归一化 import/调用所有者后相同，运行时 328 条路径 OpenAPI 完全一致。新增 5 项边界与 2 项降级/非法科目测试，结合原 App 权限用例 10 项通过；扩大架构/审核/题目回归 294 通过、19 项相同既有失败、8 项既有 xfail。该批只精确移除已解除的 7 条循环边，未治理 writer 兼容导出、旧解析副本、全部 AI 成功写入或真实模型/事务环境。

第五十六批迁移 writer 调用方并移除 core 的 writer 转发、Excel/PDF 副本和行解析转发；core 从 1,811 行减至 1,400 行，不新增业务模块。原转发函数与 writer 函数对象相同，writer 源码未改；4 个旧解析 helper 去掉 docstring 后 AST 相同，旧科目猜测副本虽不同但早已被 writer 导出覆盖，保留实际 writer 的 canonical 规则。剩余生产 AST 和运行时 328 路径 OpenAPI 与变更前一致。新增 4 项边界/首导入、3 项严格解析契约通过；扩大架构/解析/导入/Admin 回归 248 通过、3 项相同既有失败、2 项既有 xfail、12 项 xpass。12 项因 patch 修正到真实 writer 而转为 xpass，旧数学脚本的 check 只打印失败仍是测试缺口，不能视为每个内容断言都有效。题目静态循环全部解除，完整成功持久化、真实 OCR/数据库/队列与客户端仍待验证。

该图包含 TYPE_CHECKING、函数内及延迟导入；静态循环不等同于运行时循环导入错误。扫描器不解析计算生成的模块名、动态插件/monkeypatch、隐式包初始化带来的依赖或第三方内部关系，因而“无新增静态循环”不能证明运行时没有循环、死锁或资源泄漏。

运行入口：

```bash
cd backend
.venv/bin/python -m pytest tests/architecture/ -q
ruff check tests/architecture/dependency_scan.py tests/architecture/test_dependency_direction.py
```

CI 已将新依赖测试、预热协议/架构、DOCX 字体/边界、ORM 注册/边界、OCR 适配器/导入边界、题目 AI 边界/降级及 writer 边界/解析契约测试加入原有 Static architecture & non-GPU regression tests 步骤；不新增生产运行入口。

## 5. 番茄钟模块边界与尺寸门禁

`miniprogram/scripts/architecture/pomodoro-boundaries.js` 是独立 Node AST 检查入口，复用 `admin-frontend/package.json` 已声明的 TypeScript 开发依赖。先安装管理端依赖；解析器不进入小程序运行包，不修改小程序依赖清单，也不执行应用模块。

- 当前覆盖 65 个已治理模块，路径均位于 `miniprogram/pages/pomodoro/utils/`；其中包括倒计时冷恢复 `countdown-session-restore-controller.js`、自由计时冷恢复 `free-session-restore-controller.js`、启动仪式 `start-session-controller.js`、未知启动恢复 `unknown-start-controller.js`、待同步动作 `pending-sync-controller.js`、终态冲突 `terminal-conflict-controller.js`、今日统计 `stats-controller.js`、主题 `theme-controller.js`、活动会话轻同步 `active-sync-controller.js`、暂停切换 `pause-toggle-controller.js`、恢复错误 `resume-error-controller.js`、庆祝消除 `celebration-dismiss-controller.js`、休息恢复 `break-restore-controller.js`、完成庆祝 `completion-celebration-controller.js`、工作完成 `work-complete-controller.js`、自由计时启动 `free-timer-begin-controller.js`、取消结束确认 `cancel-end-confirm-controller.js`、自由结束确认 `show-end-free-confirm-controller.js`、倒计时暂停确认 `pause-countdown-end-confirm-controller.js`、倒计时中断确认 `confirm-interrupt-countdown-controller.js`、idle 重置 `reset-to-idle-controller.js`、自由计时展示更新 `update-free-elapsed-controller.js`、倒计时启动 `begin-countdown-controller.js`、暂停会话 `pause-session-controller.js`、恢复会话 `resume-session-controller.js`、倒计时中断确认展示 `show-countdown-interrupt-confirm-controller.js`、结束确认分发 `confirm-end-timer-controller.js`、结束会话 `end-session-controller.js`、暂停自由计时 `pause-free-timer-controller.js`、恢复自由计时 `resume-free-timer-controller.js`、中断会话 `interrupt-session-controller.js`、自由结束确认分发 `confirm-end-free-timer-controller.js`、自由计时上限 `free-timer-limit-controller.js`、自由计时已用时长 `free-elapsed-controller.js`、休息启动 `start-break-controller.js`、计时启动 `start-timer-controller.js`、画布初始化 `canvas-init-controller.js`、画布绘制 `draw-ring-controller.js` 和纯规则 `end-confirm-snapshot.js`。恢复壳只创建对应 controller 并委托 `restore(session)`；启动壳懒创建单一 controller，并分别委托 `start()` / `startFree(startSeq)`；未知启动壳懒创建单一 controller，并委托 `reconcile(explicitAttempt)` / `postStart(payload, startSeq)`；待同步壳懒创建单一 controller，并分别委托 `reconcileFailure(pending, error)` / `drain()` / `complete(sessionId, clientActionAt)` / `interrupt(sessionId, clientActionAt)`；终态冲突壳懒创建单一 controller，并分别委托 `record(sessionId, requestedAction, serverStatus)` / `read()` / `consume(sessionId, requestedAction)` / `consumeAny()` / `ack(conflict)` / `handle(sessionId, conflict)`；统计壳懒创建单一 controller，并委托 `load()`，同时以 `invalidate()` 使在途请求失效；主题壳懒创建单一 controller，并委托 `viewModel(mode)` / `sync()` / `apply(mode, persist, animate)` / `toggle()` 以及 `clearSwitchTimer()`；活动会话轻同步壳懒创建单一 controller，并委托 `canLightSync(active)` / `syncLight(active, failClosed)`；暂停切换壳懒创建单一 controller，并委托 `acquire()` / `release()` / `toggle()`；恢复错误壳懒创建单一 controller，并委托 `reconcile(error, sessionId)`；庆祝消除壳懒创建单一 controller，并委托 `dismiss()`；休息恢复壳懒创建单一 controller，并委托 `restore()`；完成庆祝壳懒创建单一 controller，并委托 `show(sessionId, options)`；工作完成壳懒创建单一 controller，并委托 `complete()`；自由计时启动壳懒创建单一 controller，并委托 `begin(session)`；取消结束确认壳懒创建单一 controller，并委托 `cancel()`；自由结束确认壳懒创建单一 controller，并委托 `show()`；倒计时暂停确认壳懒创建单一 controller，并委托 `pause()`；倒计时中断确认壳懒创建单一 controller，并委托 `confirm()`；idle 重置壳懒创建单一 controller，并委托 `reset()`；自由计时展示更新壳懒创建单一 controller，并委托 `update()`；倒计时启动壳懒创建单一 controller，并委托 `begin(session)`；暂停会话壳懒创建单一 controller，并委托 `pause()`；恢复会话壳懒创建单一 controller，并委托 `resume()`；倒计时中断确认展示壳懒创建单一 controller，并委托 `show()`；结束确认分发壳懒创建单一 controller，并委托 `confirm()`；结束会话壳懒创建单一 controller，并委托 `end()`；暂停自由计时壳懒创建单一 controller，并委托 `pause()`；恢复自由计时壳懒创建单一 controller，并委托 `resume()`；中断会话壳懒创建单一 controller，并委托 `interrupt()`；自由结束确认分发壳懒创建单一 controller，并委托 `confirm()`；自由计时上限壳懒创建单一 controller，并分别委托 `check()` / `autoFinish()` / `complete()`；自由计时已用时长壳懒创建单一 controller，并分别委托 `getElapsedMs(now)` / `getEffectiveElapsedMs(now)`；休息启动壳懒创建单一 controller，并委托 `start(totalSec, options)`；计时启动壳懒创建单一 controller，并委托 `start(totalSec, options)`；画布初始化壳懒创建单一 controller，并分别委托 `init(force)` / `schedule(retryCount, initSeq, previousRect)`；画布绘制壳懒创建单一 controller，并委托 `draw(totalSec, isBreak)`；`end-confirm-snapshot.js` 是无副作用纯模块，页面以 `isValidConfirmSnapshot(snapshot, api.now())` 校验快照并按 `buildFreeConfirmSnapshot` / `buildCountdownInterruptSnapshot` 组装持久化字段，副作用仍在页面。
- 当前登记 16 个含依赖模块、共 17 条内部依赖：`confirm-recovery → timer-math`；`cancel-end-confirm-controller → cancel-confirm-state`；`show-end-free-confirm-controller → end-confirm-snapshot/end-confirm-view-model`；`pause-countdown-end-confirm-controller → end-confirm-snapshot`；`update-free-elapsed-controller → timer-math`；`show-countdown-interrupt-confirm-controller → end-confirm-view-model`；`pause-free-timer-controller → timer-math`；`free-timer-limit-controller → timer-math`；`free-elapsed-controller → timer-math`；`start-break-controller → countdown-controller`；`start-timer-controller → countdown-controller`；`canvas-init-controller → canvas-layout`；`draw-ring-controller → ring-geometry`；`cancel-confirm-state → cancel-confirm-format`；`completion-celebration → ../../../utils/storage`；`end-confirm-view-model → timer-math`。除此之外不导入页面、API、第三方或其他分包；require 必须直接接收单个字符串字面量，别名、计算参数、动态/ES 导入会失败。
- 已治理模块不直接访问 wx/Page、隐式 this、全局时钟/定时器/网络或全局宿主；通过 options/storage 等显式能力回调访问外部副作用。静态检查允许属性名、注释与字符串出现同名词，不用文本搜索将它们判为越界。
- 每个覆盖模块不超过 300 行，所有有函数体的函数、箭头、表达式、方法和访问器不超过 50 行。真实 `Page({...})` 中已治理的生命周期和适配方法也保持 50 行；页面总行数设为现存 2,180 行上限，因剩余未治理职责记录为技术债，后续抽取时应同步缩减上限，不扩增白名单掩盖增长。
- 语法错误、空/仅注释文件、缺失源码、缺失治理方法/页面导入或异常 Page 定义会失败。52 项独立门禁回归覆盖违规注入、嵌套函数、虚假同名对象方法、两个恢复 controller 的精确委托壳、启动仪式/未知启动恢复/待同步动作/终态冲突/今日统计/主题/活动会话轻同步/暂停切换/恢复错误/庆祝消除/休息恢复/完成庆祝/工作完成/自由计时启动/取消结束确认/自由结束确认/倒计时暂停确认/倒计时中断确认/idle 重置/自由计时展示更新/倒计时启动/暂停会话/恢复会话/倒计时中断确认展示/结束确认分发/结束会话/暂停自由计时/恢复自由计时/中断会话/自由结束确认分发/自由计时上限/自由计时已用时长/休息启动/计时启动/画布初始化/画布绘制的懒创建与精确委托接线、确认窗口快照模块的页面接线和完整扫描失败路径。

管理端依赖安装后，从仓库根目录运行：

```bash
node miniprogram/scripts/architecture/pomodoro-boundaries.js
node miniprogram/tests/test-pomodoro-module-boundaries.js
```

`.github/workflows/reliability.yml` 在既有 `admin-build` 的依赖安装后、构建前运行门禁、52 个 `node --test` 文件及页面韧性/恢复/渲染脚本。启动仪式 controller 的独立 14 项、未知启动恢复 controller 的独立 16 项、待同步动作 controller 的独立 17 项、终态冲突 controller 的独立 16 项、今日统计 controller 的独立 5 项、主题 controller 的独立 7 项、确认窗口快照纯规则的独立 4 项、活动会话轻同步 controller 的独立 9 项、暂停切换 controller 的独立 6 项、恢复错误 controller 的独立 8 项、庆祝消除 controller 的独立 3 项、休息恢复 controller 的独立 5 项、完成庆祝 controller 的独立 3 项和工作完成 controller 的独立 4 项和自由计时启动 controller 的独立 3 项和取消结束确认 controller 的独立 5 项和自由结束确认 controller 的独立 6 项和倒计时暂停确认 controller 的独立 6 项和倒计时中断确认 controller 的独立 5 项和 idle 重置 controller 的独立 4 项和自由计时展示更新 controller 的独立 4 项和倒计时启动 controller 的独立 4 项、暂停会话 controller 的独立 3 项和恢复会话 controller 的独立 4 项和倒计时中断确认展示 controller 的独立 3 项和结束确认分发 controller 的独立 4 项和结束会话 controller 的独立 4 项、暂停自由计时 controller 的独立 3 项和恢复自由计时 controller 的独立 3 项和中断会话 controller 的独立 3 项和自由结束确认分发 controller 的独立 3 项和自由计时上限 controller 的独立 7 项和休息启动 controller 的独立 4 项和计时启动 controller 的独立 4 项和画布绘制 controller 的独立 4 项，以及刷题科目树纯规则 5 项、启动预设纯规则 3 项、发题批次校验纯规则 3 项、最近科目纯规则 3 项、加载状态纯规则 3 项和顺序重置 controller 3 项回归已接入；远端 GitHub CI 尚未运行。没有新增小程序 `npm test`。

范围限制：该策略只覆盖番茄钟明确登记的 65 个模块与页面方法，不证明其他小程序业务、所有分包边界或运行时能力隔离已完成；不是安全沙箱。主题/科目缓存等既有 wx 适配、其他页面、双份代码一致性和全仓尺寸基线仍需后续核查。行为正确性继续由独立回归和真实微信环境验收，不能由 AST 门禁替代。

## 6. 未完成的验收

- 第五十一批发现并用 HEAD 原 database/45 模型源码在新进程复现 3 项既有失败：`test_p5_0_schema_baseline_migration` 要求当前不存在的 PracticeRecord.answers；`test_pomodoro_v2_migration` 两项 runtime 测试以当前不可用的“数学二”夹具启动会话。第五十二批已按当前 per-answer/PracticeSession 契约、canonical 科目和受控时钟修复断言/夹具，并显式清理共享 SQLite 中未级联移除的 allocation 子表；三份交接测试共 42 项通过，不修改生产行为、不增加 skip/xfail。该批扩大回归额外出现的 study_day_stats/scheduler 13 项旧失败已由第六十一批恢复，见后文；PostgreSQL 条件测试本地跳过，不宣称迁移/并发验收完成。

- 第四十一/四十二批已新增并接入 `pages/pomodoro/utils/sync-retry-controller.js`，重试状态仅由 controller 持有，页面提供显式能力回调。独立 9 项测试及 Page VM 29 项运行回归覆盖退避、隐藏/卸载清理、监听身份、终态冲突与真实队列单次并发 drain；不代表 `onShow` 恢复、整个页面或微信真实网络行为已经完成验收。
- 第四十三批活动会话恢复下沉到 `pages/pomodoro/utils/active-session-recovery.js`，模块组合本地恢复、待同步动作处理和服务端状态应用；页面保留能力接线与完成/确认前置分支。10 项独立测试、Page VM 33 项运行回归及 6,144 组旧/新轨迹与状态对照验证本地证据，微信首帧、后台切换和真实网络行为仍未验证。
- 第四十四批完成标记的视图转换下沉到纯函数 `pages/pomodoro/utils/completion-recovery.js`；6 项独立测试、Page VM 35 项运行回归和 1,920 组旧/新结果对照通过。完成标记校验、振动、同步和延迟统计仍由原页面执行，结束确认及剩余生命周期编排未完成。
- 第四十五批 `pages/pomodoro/utils/confirm-recovery.js` 组合确认快照恢复，复用 timer-math，合并自由/倒计时暂停补偿回执逻辑；7 项模块测试、Page VM 39 项回归及 864 组旧/新状态和回调轨迹对照通过。有效性、导航保护和失效清理留在页面；确认取消/提交及剩余页面职责未完成治理，真实微信运行尚未验证。
- 第四十六批 `pages/pomodoro/utils/show-recovery.js` 收敛 onShow 优先级，完成与确认分支独立，页面仅持有生命周期状态和能力接线。11 项入口测试、Page VM 42 项运行回归及 12,288 组完整旧/新 onShow 轨迹和状态对照通过；恢复入口治理有本地证据，整个页面、其他生命周期和真实微信行为仍未完成验收。
- 第四十七批 `pages/pomodoro/utils/hide-storage.js` 集中离页取消意图、确认持久化及运行快照构建，保留存储上下文、时钟取值和清理顺序。8 项模块测试、Page VM 46 项运行回归及 13,824 组完整旧/新 onHide 对照通过；生命周期局部有本地证据，确认操作、计时/画布和整个页面仍未治理完毕。

- 本清单完成注册入口枚举和后端静态依赖基线，仍需逐用例核对全部消费者、事务/状态机和异常行为。阶段 0 的全量语义审查保持未完成。
- 第六十三批登记 readiness 的 Alembic stale 缺口，第一百一十二阶段已按独立行为批次修复：`stale` 现纳入关键失败，依赖检查命中时返回 HTTP 503；生产模式仍隐藏 checks 明细。
- 第六十五批核实旧 SSE `active` 计数仅在连接开启时刷新，关闭时只更新 per-user 连接表；`sse_active_connections` 则每次采样重新求和。迁移保留这两个现有口径，未把共享计数所有权收敛当作活动快照刷新缺口已修复。
- 上表的“待核查/待迁移”必须有代码与回归证据后才能改为完成；行数下降、文件移动、AST 解析成功均不能单独满足治理验收。
- PostgreSQL/Redis、OCR/AI 外部服务、真实后台浏览器与微信编译/模拟器/真机没有在本批运行。高风险迁移须另补相应测试环境与故障证据。
- DOCX 验收已检查 ZIP 完整性、XML 可解析、python-docx 重开、原生表格/合并单元格、PAGE 页脚、中文/化学字符和 OMML 矩阵节点/元素值。当前输出有两个页脚且仅使用 PAGE，旧 NUMPAGES 断言已按实现更新。
- 第四十批额外使用 docx 技能附带的严格 OOXML 校验器检查合成输出，校验未通过：`header2.xml` 的 pBdr、`document.xml` 的 shd/tblBorders/keepWithNext 元素顺序及 `settings.xml` 的 zoom 缺少 percent 属性。源码与样本还显示 OMML 矩阵缺少行列包装，`segments.text` 中的 LaTeX 走纯文本路径；本批未修改生产渲染器，单独登记为既有格式/渲染问题。当前测试通过不证明完整 OOXML 合规、矩阵布局正确或 Word/LibreOffice 显示一致。

第五十七批分离公式批次的创建、执行和单一进程内状态所有者：Admin API 直接依赖 batch_service/state，两个 worker 分发分支直接依赖 batch_runner，preview/confirm service 不再依赖 worker。保持原队列 payload、任务 id、重试次数、逐卡事务、失败继续、取消传播与跳过计数口径。新增 17 项契约/交接测试和 2 项架构/预算测试；完整架构、公式 API、上传及队列指标共 288 项通过。111 组旧/新状态与事务/重试/取消轨迹相同，328 路径 OpenAPI 相同。进程内状态不跨进程共享是原有限制，本批没有声称独立生产 worker 批次状态已验收；真实 Redis/PostgreSQL、渲染进程及生产仍未运行。剩余 import/batch image/worker 的 4 条循环边待继续治理。

第五十八批拆出 Public/Admin 唯一上传入口、不可变输入快照及图片/Excel/文档 admission 模块，后台执行服务不再导入 worker；移除最后 4 条循环基线边。输入只保留原 12 个参数，不新增业务状态。原后台服务剩余非导入/说明 AST 不变，完整 328 路径 OpenAPI 一致；160 组响应/异常及校验、资源预留、暂存、状态、队列、释放调用对照一致。新增 29 项 admission 和 4 项架构/新进程回归通过；扩大架构、上传/API、故障注入与公式队列交接为 226 通过、8 项相同既有失败。新增第 4 项首导入测试后定向 33 项通过。8 项失败涉及旧权限夹具、错误脱敏预期及直接调用路由缺少用户参数，未通过修改生产行为或 skip/xfail 掩盖。保留原队列取消不释放预留的行为；真实 Redis/PostgreSQL、OCR/模型、完整角色生命周期与客户端仍未验证，零静态循环不关闭阶段 0/1/3/4 的其他待办。

第五十九批恢复上述 8 项上传/状态 API 测试失败：权限缓存 miss 下执行真实权限判断，HTTP 400 按当前脱敏 envelope 检查；状态路由使用真实 SQLite 所有权查询与显式用户。新增 4 项权限/他人记录/缺失状态回归，两文件 22 项通过；完整架构/admission/上传/API/故障与公式交接共 239 项通过。两文件已接入现有 CI，不修改生产权限、错误或业务语义；本地 SQLite/替身端口证据不证明真实 PostgreSQL/Redis/部署角色和客户端完成。

第六十批从 main 抽取 `core/http_error_contract.py` 和 `core/http_error_handlers.py`，分别拥有公开策略和异常适配；装配保留原位置与注册顺序，不反向引用 main、不保留转发。10 个迁移函数 AST 与其余 main AST 对照一致，792 组旧/新响应、头、日志和 context 轨迹一致，运行时 OpenAPI 328 路径一致。69 项 HTTP 契约/边界测试接入既有 CI；本轮完整架构及上传/状态/公式批次/隐私/AI 能力回归 322 项通过。静态图 538 模块、2,145 条边且无循环；新模块满足 300/50 预算。main 仍有 1,843 行，lifespan、中间件、健康/指标及完整角色退出待治理；真实 PostgreSQL/Redis、外部服务、客户端和远端 CI 未验证。

第六十一批恢复 study_day_stats/scheduler 的 13 项旧失败：canonical 科目及 ID 断言、受控学习日/服务时钟、SQLite allocation 清理；原时间/归因/异常规则不变。两文件 48 项通过，真实 pause/resume 精确验证 90 秒，完成先验证未到时拒绝再验证 25 分钟完成。停用的 canonical 408 科目继续与无科目合并，异常暂停不补造区间。扩大完整架构/HTTP/ORM/分配/归因/迁移回归 293 通过、9 项条件跳过；未运行真实 PostgreSQL 并发。两文件接入现有 CI，静态回归显式使用隔离测试配置；本地完整执行该 CI 步骤 577 项通过。不修改生产代码/配置、不增加 skip/xfail；远端 CI 未运行。

第六十二批将安全头、CORS/Host 装配和追踪日志迁至 `core/http_middleware.py`；main 显式提供配置，原注册位置、选项和四层顺序一致。每个 app 的安全模式由闭包隔离，新模块导入不加载 settings、数据库或 main。18 项原实现刻画先通过；增加 app 隔离及日志失败测试后契约/边界共 24 项通过。160 组安全头、108 组日志/响应/异常/context 轨迹相同，展开日志 helper 后 AST 和其余 main AST 相同，328 路径 OpenAPI 相同。本地完整 CI 静态步骤 599 项通过，随后追加的两项日志错误测试已包含在 24 项定向复验；远端 CI 未运行。新模块 126 行、函数最长 42 行，main 1,729 行；静态图 539 模块/2,147 边/零循环。健康/指标、生命周期和完整角色验证仍待继续，不以文件缩短代替治理验收。

第六十三批恢复健康/readiness 基线：原公开 health 1 项失败及 readiness 显式运行后的 9 项失败均由测试夹具修复，生产实现不变。OCR profile patch 指向真实导入位置；队列使用 v2 端口；调度器开关明确；空间断言不再条件放行；恢复 OCR hysteresis 并移除全局 lifespan 污染。新增调度器/队列临界与云/本地状态和详情脱敏矩阵后，三文件 69 项通过。独立 CI 步骤只对指定 mocked readiness 文件打开目录门禁，并使用隔离配置；不运行真实 DB/Redis 集成，不将 39 项此前条件跳过当作验证。Alembic stale 仍返回 200 的既有缺口单列，不因本批绿色而视为已修复。

第六十四批分离指标访问策略、队列深度/计数与 OCR/AI 采样到三个职责模块。队列计数/网关/AI guard/budget 继续由原实现持有，不新增副本；访问判断保持先于实际采样。36 项原实现刻画先通过，迁移后增补取消和部分字段读取失败；结合 3 项依赖/新进程/尺寸门禁，完整 CI 静态步骤本地 644 项通过，独立 readiness 69 项通过。79 组完整响应/头/异常/采样轨迹与旧实现一致，展开 helper 后端点 AST 和其余 main AST 相同，328 路径 OpenAPI 一致。main 1,607 行，新模块 30/58/66 行、函数最长 39；静态图 542 模块/2,154 边/零循环。系统/DB/SSE/调度器指标和健康/生命周期仍待治理，真实外部服务/部署/客户端与远端 CI 未验证。

第六十五批把剩余系统/storage/DB/进程/worker/scheduler 输出与 SSE 采样按职责分离，main 指标端点组合 36 行。原 Admin SSE 六个计数迁到唯一中立模块，路由直接写入、sampler 直接读取，去掉旧路由变量及服务读取 API 的依赖；连接表和限额/超时/清理语义保持原状。迁移前 52 项指标与真实 SSE 刻画通过；迁移后完整本地静态 CI 665 项、readiness 69 项通过，测试按职责分文件后定向 75 项通过。80 组完整正文/头/错误/采样轨迹、展开端点 AST、Admin route 归一化 AST 和 328 路径 OpenAPI 一致。新模块 13/28/102 行，函数最长 27 行，main 1,521 行；静态图 545 模块/2,162 边/零循环。真实 Redis/PostgreSQL/SSE、角色启动/退出、客户端和远端 CI 未验收；旧 active 快照刷新问题单独登记。

第六十六批将 readiness 响应映射迁至纯 `core/readiness_response.py`，不可变 snapshot 仅记录现有探针结果；main 原探针顺序和 draining 回退仍在。15 项原调用/失败顺序刻画先通过，加入纯矩阵、引用不变性和 2 项新进程/依赖/尺寸门禁后，定向 125 项通过；完整静态 CI 本地 731 项、readiness 69 项通过。4,096 组旧/新状态/JSON字节/头一致，探针前半段及其余 main AST、328 路径 OpenAPI 一致。新模块 75 行/最长函数 31 行；main 1,491 行，图 546 模块/2,163 边/零循环。Alembic stale 原缺口未修，真实探针与角色生命周期/客户端/远端 CI 未验收。

第六十七批将七个基础探针迁至 `readiness_dependency_probes.py`，main 直接消费真实定义，显式传入会话工厂、Redis/production 参数和原 Alembic 路径；保留惰性端口和所有错误/取消规则。33 项原实现契约先通过，迁移后相关定向 208 项通过，7 个函数及剩余 main AST 归一化一致；76 组旧/新数据库/Redis/队列结果与 328 路径 OpenAPI 一致。完整本地静态 CI 771 项、readiness 69 项通过，3 项新进程/单向依赖/预算/调用门禁接入现有 CI。新模块 156 行、最长函数 29 行，main 1,358 行；图 547 模块/2,168 边/零循环。无真实服务/部署/客户端/远端 CI 验收，OCR readiness、角色和生命周期仍待继续。

第六十八批将 OCR 配置/远端 health 检查和显式失败状态迁至 `ocr_readiness.py`，main 拥有一个状态实例，Doctor 直接导入探针而不再导入 HTTP app。26 项原实现刻画先过，迁移后加入 state 隔离及 3 项依赖/新进程/尺寸门禁，完整静态 CI 本地 801 项、readiness 69 项通过。3,072 组配置/状态/调用/异常/取消对照、展开 helper AST 和 328 路径 OpenAPI 一致；传输替身覆盖 URL/timeout/auth/trace/HTTP边界。模块 105 行/最长函数44，main 1,275 行；图548模块/2,172边/零循环。真实 OCR/Doctor全链与角色/生命周期/客户端未验证，lag仍为main原状态。

第六十九批将角色检查迁至 `role_readiness.py`，显式传入 settings，scheduler 审计/推荐检查独立函数；原 logger、优先级、错误/日志和取消规则保留。22 项原实现刻画先过，迁移后定向 148 项通过；2,560 组角色/云/draining/backend/开关/运行组合结果和日志顺序一致，展开 AST 与 328 路径 OpenAPI 一致。3 项新进程/依赖/预算/实际调用门禁接入 CI，完整静态步骤本地 826 项、readiness 69 项通过。模块97行、函数41/43行，main1,184行；图549模块/2,178边/零循环。真实运行角色启动/失败清理/退出尚未验收，lag和lifespan继续待治理。

第七十批将 lag 样本和监测迁入中立 `core/event_loop_health.py`，main/readiness/metrics/ResourceGuard 共享同一对象，去掉从 sys.modules 查 main 的读取。原监测任务启动/取消顺序不变，无新角色任务。8 项原实现刻画先过，迁移后定向164项、完整静态CI839项/readiness69项通过；36组多tick/取消轨迹、AST和328路径OpenAPI一致。真实任务取消不遗留子任务，独立进程无main读取默认0。模块22行/监测7行，main1,166行；图550模块/2,180边/零循环。真实lifespan完整启停、外部依赖、客户端和远端CI仍未验收。

第七十一批将原九类后台任务顺序取消/一次30秒共享等待迁至`core/runtime_task_shutdown.py`；main保留任务引用及export stop→取消等待→scheduler stop的位置。7项原片段刻画先过，加入真实task/共享wait取消与3项架构门禁后定向25项通过；343组done/cancel/wait/log轨迹、展开lifespan AST及328路径OpenAPI一致。完整静态CI本地851项/readiness69项通过。模块40行/函数31行，main1,126行、lifespan829行；图551模块/2,181边/零循环。pending采用替身wait，未等待真实30秒；不代表真实角色/外部服务优雅退出验收。


第七十二批按渲染资源、队列/AI/数据库连接和孤儿协调器停止拆出`core/runtime_resource_shutdown.py`，main保留OCR关闭后的原顺序与最终诊断。16项原刻画先过，迁移后取消/任务/lag/架构42项通过；264组错误/取消/调用/日志、完整块及展开lifespan AST和328路径OpenAPI一致。完整静态CI871项（2条既有弃用警告）/readiness69项通过。新模块69行、函数22/29/7行，main1,073行/lifespan771行；图552模块/2,187边/零循环/反向API。导入不加载运行时资源；替身清理不证明真实依赖/角色优雅退出，启动失败边界与完整治理继续待办。


第七十三批`core/runtime_role_shutdown.py`拥有role显式分流的drain/reaper及scheduler/prewarm停止；formula pool关闭复用已有资源关闭模块，main原相对顺序不变。72项原刻画先过，迁移后定向120项；3,645组角色/错误/取消轨迹与48组公式超时/force轨迹、完整块/展开main AST及328路径OpenAPI一致。既有公式池真实生命周期9项通过，完整静态CI946项（2条既有弃用警告）/readiness69项通过。角色模块63行/函数23和31行，资源模块97行/formula25行；main999行/lifespan695行，553模块/2,192边/零循环。HTTP原本拒绝worker/scheduler，片段测试不证明独立角色完整启停；真实依赖/失败恢复/客户端验收仍待完成。


第七十四批原OCR执行器云判断/惰性导入/30秒关闭迁至已有资源模块；main原web/all分流和formula→executor→gateway→shared client顺序保持，gateway/client原错误传播不变。35项原片段刻画先过，迁移后相关132项通过，3,000组角色/画像/导入/错误/取消/日志、完整块/展开main AST及328路径OpenAPI一致。完整静态CI983项（2条既有弃用警告）/readiness69项通过。模块120行、OCR helper21行；main981行/lifespan676行，553模块/2,193边/零循环。替身执行器/HTTP不证明真实OCR或完整角色退出；启动及yield前失败清理继续待办。


第七十五批补33项直接进入完整真实HTTP lifespan的隔离契约，保留真实asyncio任务/取消/共享等待与线程调用，25个资源端口替身和临时目录/连接拒绝避免外部副作用；同33项对`92a81296`旧完整lifespan也通过。覆盖正常/请求异常/真实task.cancel、角色与OCR分流、yield前后错误和清理顺序；定向184项、完整静态CI1,016项（2条既有弃用警告）/readiness69项通过。单进程确认所有25模块、settings/env/cwd/lifespan/engine/task/socket/httpx/logger恢复，fixture收尾自身全部任务。无生产代码变更，结构计数不变。

新确认的既有失败清理缺口：startup发生在yield/try-finally之前，配置/DB/致命执行器/OCR初始化错误或取消不会执行关闭序列；OCR gateway失败时已创建的lag task与shared HTTP client不会由该路径清理。相同旧实现契约证实不是本轮抽取新增；先登记为单独行为修复待办，不用本批修复/skip/xfail掩盖。shared client关闭错误仍按原逻辑阻断后续共享资源关闭。上述模拟端口测试不证明真实服务/独立角色的完整退出安全。


第七十六批`services/runtime_startup_checks.py`接管原三段独立session：管理员初始化/策略seed各一次commit，AI自检只读；main保留原session factory/管理员函数/Settings对象与顺序，APP_ENV仍在session enter后读取，原服务导入时机保持。46项原刻画先过，迁移后含完整lifespan/配置读取/架构83项通过；931组会话/提交/退出/异常/取消/导入/日志轨迹、完整块/展开main AST及328路径OpenAPI一致。3项临时SQLite验证真实落库、重复执行和commit错误/取消回滚。完整静态CI1,069项（2既有弃用警告）/readiness69项通过，完整lifespan状态恢复再通过。模块84行/函数11、18、31行，main930行/lifespan620行，554模块/2,195边/零循环。yield前失败清理既有缺口保持单独待办，schema/资源/角色启动及全栈完整验收未完成。


第七十七批将既有导出幂等键schema兼容与只读schema差异诊断分至两个具体服务，main保持init_db→兼容修复→差异诊断→seed/自检的位置与原session factory。原44项刻画先过；补SQLite batch规划错误/取消及重试后，46项对旧`05b094a6`完整AST也通过，最终schema/架构49项、相关完整lifespan/启动133项通过。11项临时SQLite验证各类约束/索引、原数据、重复执行与规划失败恢复；208组PostgreSQL SQL/参数/提交/退出/错误/取消轨迹、反射与batch完整块/展开main AST及328路径OpenAPI一致。完整静态CI1,118项（2既有弃用警告）/readiness69项通过，lifespan全局状态恢复再通过。模块141/67行、函数最长31行，main769行/lifespan458行，556模块/2,199边/零循环。保留SQLite run_sync/原inspect导入顺序、PG提交位置及差异查询best-effort语义；不新增运行DDL规则。规划故障测试不代表全部DDL执行中断恢复，真实PostgreSQL/独立角色/外部服务验收及已知yield前失败清理仍待完成。


第七十八批`core/http_runtime_policy.py`拥有HTTP角色归一化与配置/env写回、云OCR模块隔离及组件启动失败报告，main仍传原Settings/解析器/探针/production mode，原8组件标签和顺序不变；旧私有report入口移除。132项原刻画先过，相关168项通过；258组状态/env/probe/error/cancel/cause/log、完整函数/展开main AST和328路径OpenAPI一致。完整静态CI1,253项（2既有弃用警告）/readiness69项通过，完整lifespan33项状态恢复再通过。模块90行/函数23、26、22行，main708行/lifespan412行，557模块/2,202边/零循环。额外旧云隔离测试4失败/3通过：test env与cloud profile不兼容，相关文件与旧提交相同且复现未加载main/新policy，确认既有fixture缺口；新进程cloud配置/无Paddle导入检查通过，下一批修复测试而不放宽生产guard。完整独立角色/启动失败清理仍未完成。


第七十九批独立恢复旧云OCR测试基线（原8失败/15通过），不修改app生产源码：一致的安全画像、隔离并恢复runtime singleton/SDK对象、清空profile cache，移除pipeline/staging强制重导入。真实legacy wrapper/诊断/远端执行编排/gateway过滤由替身端口验证，云成功/失败/异常/取消均校验识别与shutdown；混合画像必须拒绝。四类新解释器探针在临时cwd使用合成Fernet key、拒绝socket连接，包含真实HTTP装配/OpenAPI无Paddle；不等同于实际lifespan启动。云30项、与完整lifespan/策略混合195项、额外全局状态恢复通过；原YAML静态1,253项（2既有弃用警告）/readiness69项/新增独立云步骤30项通过。严格Ruff/compileall/diff/保护哈希与只读审查通过，No findings。生产图保持557模块/2,202边/零循环，main708行/lifespan412行；启动资源/角色治理及既有清理缺口、真实依赖/客户端验收仍待完成。


第八十批`core/runtime_resource_startup.py`拥有原角色执行器与孤儿协调器启动，main保留原位置及Executors失败报告边界。原24项刻画先过，扩充后26项对旧`8be9e754`完整AST通过；相关实际lifespan/执行器/guard/架构114项、旧位置门禁迁移后9项通过。完整块/展开main AST、288组角色/画像/注册/故障/取消/日志轨迹、328路径OpenAPI一致。10组真实执行器注册/线程工作/关闭、真实协调器task幂等启停和registry恢复、无socket连接通过；真实Redis协调与独立角色仍未验收。新增3项架构/惰性导入/真实消费门禁，原YAML完整静态1,282项（2既有弃用警告）/readiness69项/云30项通过，33项lifespan状态恢复再过；严格Ruff/compileall/diff/33项保护哈希及review-agent只读No findings。模块35行/函数19与7行，main690行/lifespan390行，558模块/2,205边/零循环/反向API。其他角色启动/既有清理缺口及全栈验收继续待办。


第八十一批`services/runtime_ocr_startup.py`接管HTTP OCR配置/共享client/worker/gateway装配，lifespan每实例资源对象立即保留构建成功的client/gateway；main仍拥有原角色/失败报告/关闭顺序，禁用依赖导入与部分失败/取消状态保留。32项原块刻画和16项完整lifespan失败边界均对旧`716d90a5`通过；相关149项通过。资源字段映射后完整块/展开main AST、192组配置/导入/构建/资源/发布/错误/取消/日志轨迹和328路径OpenAPI一致，client默认None对应旧未赋值保护且原close日志与错误传播保留。真实httpx/PaddleX worker/cloud gateway装配/共享client非ownership/关闭及singleton恢复通过，无socket/Paddle；未调用外部OCR。原YAML静态1,333项（2既有弃用警告）/readiness69项/云30项通过，49项lifespan状态恢复再过；严格Ruff/compileall/diff/保护哈希、review-agent只读No findings。模块63行/函数41行，main646行/lifespan342行，559模块/2,208边/零循环/反向API。yield前失败清理/client关闭阻断等既有缺口不变，其他角色启动与全栈验收继续待办。


第八十二批`services/runtime_scheduler_startup.py`将HTTP all与独立bootstrap scheduler共有的审计/推荐启动收敛为两个具体函数，显式接收各调用方logger，原main报告和bootstrap_report各自保留。原20项启动/完整独立scheduler刻画先过，新增HTTP失败8项后共28项对旧`3a39d843`完整两个入口通过；相关80项通过。原两块/展开完整main/bootstrap AST、48组导入/await/日志/错误/取消轨迹及328路径OpenAPI一致。独立scheduler使用真实9类TaskRegistry任务、替身外部端口，outbox回调/失败/取消/清理有证据；不代表真实进程退出。真实APScheduler新实例各1job、幂等start/注册/stop及原状态恢复通过，无网络/job执行。原YAML静态1,364项（2既有弃用警告）/readiness69/云30通过；77项HTTP/独立scheduler混合全局状态恢复通过，严格检查/33保护哈希/review-agent只读No findings。模块19行/函数5与7，main642/lifespan334、bootstrap719/调度初始化93；560模块/2,210边/零循环/反向API。余下启动/失败清理/独立角色及外部依赖/客户端完整验收仍待完成。


第八十三批两入口周期cleanup/导出循环收敛至`services/runtime_periodic_tasks.py`，直接消费唯一真实定义并移除旧私有forwarder。三类原task_id/label/惰性system-task调用和UTC调度/锁/注册所有者保持，export显式原caller logger；asyncio/TaskRegistry/任务名/local fallback与关闭归属不变。原34项刻画先过，相同34项对旧`f078b239`完整函数通过；相关77项、原函数体/展开main和bootstrap完整AST、32组ID/label/await/log/error/cancel及328路径OpenAPI一致。真实system-task三种循环由两入口注册/等待/实际cancel/finally注销通过，无业务执行/网络。原YAML静态1,401项（2既有弃用警告）/readiness69/云30通过，混合111项全局状态恢复通过；严格检查/保护哈希/review-agent只读No findings。模块32行/最长函数7行，main614/lifespan334、bootstrap688/调度初始化93，561模块/2,214边/零循环/反向API。真实分布式任务业务/独立进程/其他生命周期与全栈验收仍待完成。


第八十四批仅测试/CI/文档：32项直接运行完整独立_run_role_async/worker与scheduler初始化/shutdown_role，真实TaskRegistry/ManagedTask/asyncio任务/取消/共享wait/to_thread，外部端口替身/临时目录/拒绝socket。覆盖两角色/画像/OCR正常顺序、startup/配置/signal安装错误和取消、真实等待任务cancel、关闭普通错误继续/取消阻断、未知角色；与HTTP混合99项通过。同32项在旧3a39d843完整bootstrap通过（旧周期端口作名称绑定），runner/shutdown/worker init/signal安装AST一致。确认独立runner初始化失败和等待信号cancel不进入shutdown，任务可能遗留；fixture只收尾自身task，不修生产行为。需单独处理，与HTTP yield前失败/client关闭阻断同为既有待办。原YAML静态1,433项（2既有弃用警告）/readiness69/云30通过，99项同进程Settings/env/cwd/TaskRegistry/signal/task/socket/lifespan/周期端口/30模块与父别名恢复，逐fixture sys.path稳定（pytest首次setup路径预置单独排除）。严格检查/33保护哈希/review-agent只读No findings。端口192/测试124行，生产结构和561模块/2,214边/零循环保持。真实OS信号/CLI进程退出/外部依赖及全栈其他域仍未验收。


第八十五批bootstrap通用ManagedTask/TaskRegistry完整迁至`core/runtime_task_registry.py`，装配入口直接消费真实类，原实例/role/信号/关闭顺序、postgraduate-ai.bootstrap logger、共享wait/超时/pending二次cancel与wait吞取消保持。原13项刻画先过，追加真实等待者cancel后14项对旧edfdb4f8完整类通过；相关完整角色/独立scheduler55项通过。原两个类与展开整个bootstrap AST一致、340组callback/register/done/cancel/wait/pending/log/错误/取消轨迹一致（仅pending set二次cancel无序段归一化）。新增3项依赖/预算/唯一类与真实消费/无资源导入门禁，原YAML静态1,450项（2既有弃用警告）/readiness69/云30通过；113项混合单进程新logger/全局与模块状态恢复通过。严格检查/33保护哈希/review-agent只读No findings。模块114行/最长方法22，bootstrap580，main614/lifespan334保持，562模块/2,215边/零循环/反向API。原wait吞取消/pending不再等待及runner清理缺口未修，真实进程/信号/外部依赖/全栈验收仍待完成。


第八十六批独立worker OCR块迁至已有runtime_ocr_startup的具体函数，原已解析profile和bootstrap logger显式传入，scratch/executor→OCR→orphan/任务/prewarm顺序保持。HTTP数据类/装配AST不变；worker factory仍无共享client参数，保留其连接所有权。原20项块刻画先过，新增部分OCR失败6项后完整角色38项；同20+38项对旧3fe28948完整bootstrap/原块通过。原块/展开整个bootstrap AST、120组画像/配置/import/构建/发布/log/错误/取消轨迹一致，相关127项、混合139项全局状态恢复通过。真实PaddleX/gateway构建并验证worker拥有client、gateway关闭client、singleton恢复、无网络/Paddle且无OCR请求。原YAML静态1,477项（2既有弃用警告）/readiness69/云30通过，扩展原消费/位置/预算/惰性门禁，严格检查/33保护哈希/review-agent只读No findings。OCR模块89行/HTTP41与worker23，bootstrap560/worker init49，main614/lifespan334保持；562模块/2,213边/零循环/反向API。未发布worker资源/runner清理缺口保持独立待办，OS信号/CLI/真实服务及全栈验收仍未完成。


第八十七批HTTP/独立scheduler相同outbox闭包收敛至outbox_queue_adapter的具体工厂，捕获queue对象并于每次await时解析当前enqueue_v2；原ID/type/payload/schema映射和返回/异常/取消保持，入口仍拥有原导入/任务创建/日志/部分失败与关闭。原52项刻画先过且对旧138414df完整闭包52通过，相关133项通过；原闭包/展开两个完整模块AST与50组轨迹一致。真实临时Redis7 Unix socket（port0/无持久化/独立测试实例）验证v2 Lua接受数据/schema落库、幂等、容量拒绝、校验错误和实例停止后的不可用结果；无现有/外部Redis连接，测试进程已退出，不代表outbox DB发布/租约/重试或生产验收。原YAML静态1,532项（2既有弃用警告）/readiness69/云30通过，混合191项状态恢复、严格检查/33保护哈希/review-agent只读No findings。模块28/工厂17，main604/lifespan323、bootstrap550/scheduler init82，563模块/2,216边/零循环/反向API。其余生命周期/失败清理/真实角色与全栈验收仍待完成。


第八十八批独立scheduler三个可选组件原try块迁至已有runtime_scheduler_startup同步装配函数，原registry/logger显式传入；outbox双任务/投影/健康的导入/任务创建/部分失败/非致命warning/取消及独立性保持，bootstrap仍拥有任务registry/完整runner/关闭。18项云画像工厂/实际import失败基线先过，连同完整角色/独立scheduler共66项对旧f2c440a5完整bootstrap通过；相关125项、三完整块/展开整个bootstrap AST与135组轨迹一致。门禁迁至实际outbox consumer并补原registry/logger/顺序/Exception/≤50行检查；原YAML静态1,551项（2既有弃用警告）/readiness69/云30通过，混合209项状态恢复、严格检查/33保护哈希/review-agent只读No findings。真实新helper构建dispatcher/reconciler coroutine并在DB执行前关闭，捕获真实enqueue callback在临时Redis Unix socket通过v2 Lua接受/幂等/容量/schema/停机验证，实例已退出，不等同于DB发布/租约/重试验收。scheduler模块71行/新增17、13、8，bootstrap520/scheduler init50，main604/lifespan323保持，563模块/2,218边/零循环/反向API。其余shutdown/runner清理/信号/CLI/真实服务/客户端与全栈验收继续待办。


第八十九批（2026-10-21）原bootstrap信号安装迁至中立runtime_signals，caller显式传stop Event/logger，runner原init→安装→等待→shutdown归属保持。原10端口+4真实子进程基线先过，扩充13单元+38完整角色共51项对旧5f31342a通过；installer正文/展开整个bootstrap AST、96组注册/重复callback/日志/event/error/cancel轨迹一致。真实4个POSIX child harness通过runpy执行worker/scheduler实际__main__/run_role/runner，干净合成env/临时cwd/替身外部端口且拒绝socket；父进程仅向确认ready的本测试child发SIGTERM或SIGINT，实际handler唤醒等待、2或9真实task完成、原资源顺序和role写回/exit0通过，子进程均退出。非POSIX明确条件不运行，本地无skip；不是实际DB/Redis/OCR全链或失败清理修复证明。原YAML静态1,571项（2既有弃用警告）/readiness69/云30通过，混合226项全局/模块/新信号端口/sys.path恢复通过，严格检查/33保护哈希/review-agent只读No findings。模块24/installer17行，bootstrap498，main604/lifespan323保持，564模块/2,219边/零循环/反向API。其他shutdown/runner职责、既有清理缺口和全栈其他域仍待治理。


第九十批（2026-10-21）独立shutdown六具体职责迁至standalone_runtime_shutdown，原role/logger显式输入，bootstrap保留原开始/完成日志/顺序和一次registry等待/实时Settings grace读取。原44刻画先过，扩充49项direct+38完整角色共87项对旧4f914e3e六段原块与完整bootstrap通过；六完整块/展开整个bootstrap AST、2,592组角色/画像/资源顺序/deadline/线程参数/错误/取消/日志轨迹一致。保留独立公式timeout不force、OCR profile导入try外、gateway和非worker draining普通错误静默等原策略。原YAML静态1,623项（2既有弃用警告）/readiness69/云30通过，含真实POSIX4child信号/退出；混合275项新shutdown.asyncio及全局/模块/sys.path状态恢复通过。独立真实资源脚本验证worker/PDF线程工作后池关闭/registry恢复、内存SQLite SELECT1后dispose连接close事件、真实orphan task停止和queue close，无网络；不代表生产全链。严格检查/33保护哈希/review-agent只读No findings。新模块155/最长30，bootstrap379/shutdown30（runner61），main604/lifespan323保持，565模块/2,226边/零循环/反向API。既有失败清理缺口/其他runtime职责及外部服务、客户端与全栈计划仍待继续。


第九十一批（2026-10-21）bootstrap原HTTP启动拒绝/scratch/失败reporter迁至standalone_runtime_policy；三个真实消费者直接使用原Settings/logger/profile及唯一角色集合，原校验/写回/画像/资源顺序保持，无旧私有壳。原116刻画先过，补2真实临时目录幂等/数据保留后118项，相同118+38完整角色+10scheduler共166项对旧275771c2完整实现通过；当前163项direct/架构/完整角色/真实OS信号通过。三原正文/展开bootstrap AST在显式绑定后相同，仅顶层docstring纠正HTTP共享生命周期失实描述，763组argv/env/path/profile/mkdir/frozen report/log/error/cause/cancel轨迹一致。保留只看argv[0]、角色和路径不归一化、尾斜杠显式路径允许、工厂时冻结production判定等原行为。原YAML静态1,744项（2既有弃用警告）/readiness69/云30通过，混合393项policy.os/sys及全局/模块/sys.path状态恢复通过；严格检查/33保护哈希/主agent按review-agent只读No findings，无子agent。模块91/最长26，bootstrap292并加入≤300门禁，runner61，main604/lifespan323保持；566模块/2,229边/零循环/反向API。runner/失败清理独立待办、真实外部服务/客户端与全栈其他域继续。


第九十二批（2026-10-21）HTTP/独立runner重复staging启动扫描归services/runtime_staging_startup唯一实现，原logger显式输入、懒import/普通错误warning/cancel传播及原profile之后/资源之前位置保持。原117契约先过，补2真实线程/临时目录保留数据后同组129项对旧755fbcfe完整main/bootstrap及原块通过；当前含架构和4真实信号child126项通过，混合441项全局/模块/父别名/sys.path恢复通过。两原完整try块/展开main与bootstrap AST及328路径OpenAPI一致，48组import/count/await/日志/错误/context/cancel轨迹一致。实际磁盘验证仅扫描测试临时目录中的新根文件和嵌套文件，未清理现有资源；不代表完整生产staging保留策略或失败恢复验收。原YAML静态1,793项（2既有弃用警告）/readiness69/云30通过；collection后追加2项真实扫描已纳入最终定向126/旧版129/混合441，未计入1,793。严格Ruff/全应用Ruff/compileall/diff/33保护哈希及主agent按review-agent只读No findings，无子agent。新模块16/函数11，main597/lifespan315，bootstrap282/runner50，567模块/2,229边/零循环/反向API；既有失败清理/外部服务/客户端及其他全栈阶段继续。


第九十三批（2026-10-21）HTTP启动画像/角色与导出诊断归runtime_http_startup_diagnostics两个具体函数，四目录准备归已有core.runtime_resource_startup；显式原Settings/role/profile/logger，main保留sweep→诊断→导出诊断→目录→init_db位置。原87直接+43完整HTTP共130先过；增加2完整导出配置失败后同组132对旧6b3f93da完整main与原三个块通过；当前相关213项通过，混合538项resource.os及全局/模块/父别名/sys.path恢复通过。三个原块/展开完整main/原资源函数AST、328路径OpenAPI和73组config/profile/log/import/capability/目录/error/context/cancel轨迹一致。原capability后读取REDIS_URL、三静态目录后读取EXPORT_DIR、部分目录创建及异常传播不变，实际临时目录幂等/保留数据通过；模块导入三次mkdir和local web原false日志/实际processor fallback均未改变。新3架构门禁和main545/lifespan258预算接入CI，原资源/扫描门禁跟随真实owner。原YAML静态1,895项（2既有弃用警告）/readiness69/云30通过，已含本批全部新增用例；严格Ruff/全应用Ruff/compileall/diff/CI路径/33保护哈希与主agent按review-agent只读No findings，无子agent。新诊断模块74/函数36、24，资源48/目录6，main545/lifespan258，bootstrap282/runner50；568模块/2,233边/零循环/反向API。既有启动/等待失败清理、真实外部服务/完整持久化/客户端及全栈其他阶段仍待完成。


第九十四批（2026-10-21）HTTP worker dispatcher/reaper/AI prewarm 三段迁至services/runtime_http_worker_startup.start_http_worker_tasks，新增HttpWorkerTasks持有两引用，main直接消费原production/logger/report_failure，保留local→worker→scheduler顺序和shutdown标签归属。原114先过，迁移后137通过，旧版122对原完整main通过；两原块/展开main AST和328路径OpenAPI一致。新3架构门禁接入CI，HTTP policy门禁更新。原YAML静态1,967/readiness69/云30通过，混合607全局/模块/父别名/sys.path恢复通过；严格检查/33保护哈希/主agent按review-agent只读No findings。main523/lifespan232/worker47/函数31，bootstrap282/runner50；569模块/2,235边/零循环/反向API。既有清理缺口/外部服务/客户端及全栈阶段继续。


第九十五批（2026-10-21）HTTP scheduler heartbeat/audit/metrics/4周期/outbox共7段迁至services/runtime_http_scheduler_startup.start_http_scheduler_tasks，HttpSchedulerTasks持7引用，main直接消费原production/logger/report_failure，保留worker→scheduler→reconciler顺序和shutdown标签归属。三种失败策略保留：heartbeat/audit/metrics用report_http_startup_failure；4周期bare create；outbox logger.warning。原26直接先过，迁移后118通过，旧版79对原完整main通过。原YAML静态1,996/readiness69/云30通过，混合607全局/模块/父别名/sys.path恢复通过；严格检查/33保护哈希/主agent按review-agent只读No findings。main461/lifespan174/scheduler模块90/函数≤50，bootstrap282/runner50；570模块/2,238边/零循环/反向API。既有清理缺口/外部服务/客户端及全栈阶段继续。


第九十六批（2026-10-21）HTTP lifespan 的 OCR gateway/client 关闭与子进程诊断两段迁至已有 core/runtime_resource_shutdown.py 的 shutdown_http_ocr_gateway(resources) 与 log_active_children()，main 直接消费原模块函数并传原 _ocr_resources；原 shutdown_ocr_executor→gateway→client→render→connections→reconciler→completed→children 顺序和 lazy import 边界保持。TYPE_CHECKING HttpOcrResources 注解仅静态分析，不新增运行时 core→services 导入。原 40 项 OCR shutdown 契约先在旧实现通过；恢复 strict positions==sorted(positions) 关闭顺序门禁并扩充依赖图/probe 禁导入后 155 项受影响测试全过。原 YAML 完整静态 229 项 architecture + 644 项 lifespan/startup + 451 项 runtime/standalone = 1,324 项通过（含既有 2 弃用警告之外无新增）；33 保护哈希/review-agent 只读 No findings。module 159/函数≤22 行，main 436/lifespan 147；571 模块/2,242 边/零循环/反向 API。既有 yield 前失败不清理、shared client 关闭阻断后续清理、真实外部服务/完整持久化/客户端及全栈其他阶段继续。


第九十七批（2026-10-21）HTTP lifespan 的 lag 监控停止与导出处理器停止两段迁至 core/runtime_http_shutdown.py 的 stop_lag_monitor(task) 与 stop_export_processor(role)，main 直接消费模块函数；原 drain→lag→export→cancel 顺序和异常/取消边界保持。保留 lag 监控 CancelledError 静默通过、export 处理器普通错误 warning 和 import 边界；caller 仍持有 _lag_monitor_task 和 _scheduler_tasks.export_processor_task 的 None/done 守卫。原 51 项受影响测试先过；新增 6 项单元契约覆盖 None/done/pending task 和 success/import/runtime/cancel 边界后全过。更新 2 项架构门禁跟随新调用位置；完整静态 232 项 architecture + 389 项 lifespan/startup + 133 项 resource/task + 223 项 standalone + 408 项 runtime = 1,385 项通过，无新增失败。33 保护哈希/review-agent 只读 No findings。module 27 行/函数 8、9 行，main 436→429/lifespan 147→136 行；571 模块/2,240 边/零循环/反向 API。既有 yield 前失败清理、shared client 关闭阻断等行为缺口不夹带修复；真实外部服务/完整 outbox 持久化/客户端及全栈其余阶段继续。


第九十八批（2026-10-21）practice_service.py 的 get_smart_scored_questions 内 4 处重复元数据构建（2 处 smart_scored + random_fallback + repeat_window_fallback）提取为模块级 _build_scored_metadata 和 _build_fallback_metadata 两个私有函数；保留原字段集、round 精度、reason 构建调用和所有 kwargs。函数从 540 行降至 516 行；新增两个 helper 各 28/8 行。原 208 项 practice 测试 + 621 项 architecture/lifecycle + 232 项 architecture = 1,061 项通过，4 项既有 MagicMock 失败经 stash 验证为基线。0 循环/0 反向 API/33 保护哈希通过/review-agent 只读 No findings。practice_service.py 4117 行，函数仍超 50 行预算——后续继续按阶段提取候选构建/评分/降级编排。


第一百零二批（2026-10-21）scored状态/近期KP/QKP、KP名称及用户权重加载分离为具体helper，原session/查询顺序与权重await保留。直接入口测试发现第一百零一批图谱抽取的请求题量上限和provider对象归属回归，恢复原 `max(count * 3, 30)` 与赋值语义；此前外围208项通过及“No findings”不能证明该路径等价，旧记录须结合本条更正阅读。新增16项完整scored入口/状态契约并接入CI，15组对抽取前e8a045c0完整函数的结果、元数据、SQL轨迹、图谱参数与错误/取消一致；练习域混合224项通过（10条既有弃用/线程收尾警告）。SQL与SAVEPOINT均为端口替身，未验证真实PG/Redis/OCR。practice_service仍有4千余行，评分/多样性/补齐编排及全栈其余阶段继续，不以行数或零静态循环认定完成。
最终按原YAML本地重放静态2,015（2条既有警告）/readiness69/云OCR30均通过；严格Ruff/compileall/diff与33保护哈希通过。四个新增helper47/17/7/33行，practice_service4,254/入口239行。下一步先刻画评分、多样性、补齐的真实分支，再调整业务职责；不继续以外围测试通过数替代直接行为证据。


第一百零三批（2026-10-21）原scored两轮多样性选择归中立practice/scored_selection，已有分数/QKP/题量和解释工厂显式输入；元数据在原选中位置生成，入口继续拥有评分与随机/最终补齐DB查询。模块47/函数36行，practice_service4224/入口208行；图572模块/2242边/零循环/反向API。18项完整入口真实评分/解释/多样性/补齐契约和3项架构门禁入CI；18组与旧82fb84eb完整函数的结果、元数据、SQL/参数、随机偏移、日志及错误/取消一致。定向37、混合242通过（11条弃用/aiosqlite线程收尾警告）。保留多KP计数min策略、补齐2000边界和原超量元数据口径；SQL/上游加载仍替身，不代表真实PG/完整生产验收。其余评分/补齐编排与全栈阶段继续。
最终原YAML静态2036（2既有警告）/readiness69/云OCR30通过；61个其他service函数AST未变、两轮选择循环按变量/元数据端口归一化后相同。原分支日志、参数与异常对照和33保护哈希均通过；只验证本批范围，后续评分/随机补齐及全栈其他阶段继续。


第一百零四批（2026-10-21）scored随机/最终补齐查询归practice/scored_fallback，显式conditions/session/remaining与原sampler；caller继续拥有过滤、放宽顺序、fallback级别、metadata与合并loop。保留首次<=remaining不limit/ID排序、<=2000随机、>2000offset及最终原sampler不同口径。模块95/函数34、14、27，practice_service4191/入口171；图573模块/2244边/零循环/反向API。新增11项完整入口故障/空计数/sampler契约（总29项迁移前先过），新增3架构门禁入CI。定向51、混合253通过（12条既有弃用/线程收尾警告）；29组原完整函数参数/SQL/结果/metadata/日志/随机/错误对照一致；61其他service函数AST、两caller条件与合并loop AST不变。仅隔离SQL端口，不证明真实PG/生产事务；评分与其他全栈领域继续治理。
最终原YAML静态2050（2既有警告）/readiness69/云OCR30通过；严格Ruff/compileall/diff与33保护路径哈希通过。下一步继续评分编排及加载边界，所有既有其他领域/客户端/失败清理待办保持，不用结构计数代替全栈验收。


第一百零五批（2026-10-21）scored逐题评分与稳定降序排序归practice/scored_ranking，入口显式传入原scorer/state/KP/mastery/recent/now及全部图与权重端口；日志、解释元数据、多样性和补齐仍由调用方拥有。模块49/函数36，practice_service4180/入口159；图574模块/2246边/零循环/反向API。新增3项直接契约（精确原实参/候选不可变/同分稳定，普通错误与取消止于失败候选）计入总32项，3项架构门禁入CI；32组旧入口比较覆盖结果/metadata/SQL/随机/日志/错误取消，两个scorer monkeypatch场景由直接契约单独覆盖，不宣称未归一化整套AST等价。混合256通过、原YAML静态2056/readiness69/云OCR30通过；严格检查与33保护哈希通过。隔离端口不证明真实PG/外部服务；其他长函数和全栈领域继续。


第一百零六批（2026-10-21）scored两处补齐结果合并迁至practice/scored_fallback_merge.merge_fill_questions：显式接收selected/ids/rows/metadata/reason/strategy/原metadata工厂，保留首次补齐不去重与最终放宽重复限制去重的不同口径，metadata仍在原行追加时点生成；入口继续拥有过滤、查询、fallback级别、日志和最终slice。模块33/函数19，practice_service4181/入口159；图575模块/2248边/零循环/反向API。新增2项完整入口契约验证行序/重复规则/元数据调用点及普通错误/取消后的短结果，3项新架构门禁入CI；第105批评分helper调用表达式保持不变，未归一化AST限制不因此消除。定向47、练习/API混合201通过；原YAML静态2,062（2既有警告）/readiness69/云OCR30通过；严格Ruff/全应用Ruff/compileall/diff/CI路径/33保护哈希通过。未做真实PG/外部服务验收。


第一百零七批（2026-10-21）scored两级补齐编排迁至practice/scored_fallback_flow.run_scored_fallback，caller通过ScoredFallbackRequest显式传原query/merge/metadata/revision/sampler端口与基础subject条件；module保留level 3/4、每级重新计算remaining、首次随机补齐含excluded_sub、最终放宽历史条件及两条去重策略。模块98/函数8、22、22，practice_service4170/入口144；图576模块/2250边/零循环/反向API。新增2项flow直接契约覆盖base→subject→revision→排除→可选excluded顺序、remaining及两次merge口径，3项flow架构门禁入CI，精确检查17个入口端口与条件AST并递归拒绝DB持久化调用；旧scored架构门禁跟随真实flow消费者。首次审查指出的base_conditions与request.db.execute守卫缺口已修正。定向68、练习/API混合206通过；最终原YAML静态2,067（2既有警告）/readiness69/云OCR30通过；严格Ruff/全应用Ruff/compileall/diff/CI路径/33保护哈希通过。真实PG/外部服务未验收。

第一百零八批（2026-10-21）smart scored满额/缺口补充编排迁至practice/smart_scored_supplement.run_scored_supplement，ScoredSupplementRequest显式携带17个参数/端口，模块保留原scored优先、remaining计算、exclude_ids、合并后截断、普通异常返回None继续内联weakness路径及取消传播；查询、推荐提供者、合并、最终日志和事务仍由practice_service拥有，模块无I/O依赖。模块100/函数49、16，practice_service4132/入口446；图577模块/2251边/零循环/反向API。新增4项完整入口契约与3项架构/新进程门禁入CI，修复旧smart/path异步scalar、真实patch目标与sequential替身；知识路径在练习过滤前写日志/提交请求会话的既有缺陷仍单列。定向11、修复旧子集8、练习/API混合270通过；最终原YAML静态2,075（2既有警告）/readiness69/云OCR30通过；严格Ruff/全应用Ruff/compileall/diff/CI路径/33保护哈希通过。真实PG/外部推荐服务未验收。

第一百一十二阶段（2026-10-22）运行时启动/关闭失败边界：HTTP lifespan 以同一 try/finally 覆盖 startup 与 yield，yield 前 db/executor/OCR 失败也走有序清理，已有启动异常不被清理错误或清理取消覆盖；standalone 资源拆为 `StandaloneRuntimeResources(role, registry, ocr)`，worker OCR client 在 gateway 构造窗口保留并按自身 shutdown 关闭，gateway 普通失败或取消不跳过暂存 worker/shared client，显式 resources 不回落全局 singleton；新增 `runtime_startup_cleanup` 统一保留原失败及 SystemError 身份。readiness 将 Alembic stale 作为关键失败返回 503，生产 checks 继续脱敏。OCR shutdown 定向 47 项、全量 architecture 255 项通过；tests/core 为 1,620 passed、4 skipped、3 failed，后者为交接既有 safe_remote_fetch/staging orphan 用例失败。Ruff、compileall、diff 通过；已本地提交 `5c62d707`，本轮未重新执行 33 路径哈希核对；未运行真实 PostgreSQL/Redis/OCR/AI、生产退出或客户端验收。
