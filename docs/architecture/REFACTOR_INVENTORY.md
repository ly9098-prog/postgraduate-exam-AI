# 全栈重构源码盘点

> 核对日期：2026-10-20；对应 `prompts/tasks/current_task.md` 阶段 0/4。
> 本清单登记真实入口、结构证据、回归入口和后续决策，不代表所有业务语义已审查完毕。

## 1. 范围与证据

- 后端直接解析 `backend/app/**/*.py`：525 个模块、2,098 条模块导入边。覆盖函数内和 TYPE_CHECKING 内的导入、相对导入及字面量动态导入（相对动态导入需同时给出字面量 package）；不执行应用代码，不读取数据库或真实配置。
- 路由以 `backend/app/api/v1/router.py`、`backend/app/api/admin/router.py` 和 `backend/app/api/router.py` 的实际注册为准。Public/Admin 使用同一个后端，另有内部 OCR worker 路由；本清单不按文件名推断是否对外启用。
- 管理端通过 TypeScript AST 检查 `admin-frontend/src/app/**/page.tsx`：32 个页面入口，含登录和重定向页；枚举导入及函数长度，不把外层 React 函数的 JSX 行数等同于业务复杂度。
- 小程序从 `miniprogram/app.json` 的 pages/subPackages 解析 25 个注册页面，再用 TypeScript AST 读取实际 JS、require 和方法长度；不根据目录位置推断主包归属，例如番茄钟位于 pages 下但实际注册为分包。
- Codebase Memory 索引时间为 2026-10-15T16:20:28Z，scope 覆盖返回 known_gaps 和截断。仅用于确认索引状态，本清单的模块/入口与依赖数据来自当前文件扫描；未据索引缺失认定死代码。

## 2. 按业务域登记

后端路径相对 `backend/`，管理端页面相对 `admin-frontend/src/app/`，小程序路径相对 `miniprogram/`；测试是已存在的核查入口，除执行记录明确列出的命令外，不代表本批已运行。

| 业务域 | 后端入口与实现 | 管理端消费者 | 小程序消费者 | 决策与后续验证 |
| --- | --- | --- | --- | --- |
| 身份与权限 | `app/api/v1/auth.py`、`admin_auth.py`、`admin_rbac.py`；`services/admin_auth_service.py` | `(auth)/login`、`admin-users`、`roles`、`app-users`、`audit-logs`；`lib/auth`、`lib/api/client.ts` | `pages/login/login.js`、`utils/auth.js`、`utils/api.js` | 保留两类 JWT/RBAC 边界，认证协议不重做。管理员/角色页面仍为长入口，状态与请求职责待逐段核查。验证入口：后端 `test_admin_auth.py`、`test_admin_rbac.py`，前端 `auth-store.test.ts`、`client.test.ts`；真实 401 刷新/403 与会话恢复待验证。 |
| 题库治理 | `questions.py`、`admin_questions.py`、`admin_subjects.py`、`admin_knowledge.py`、`admin_syllabus.py`；`services/admin_question_service.py`、`question_revision_service.py`、`question_snapshot_service.py` | `questions`、`subjects`、`syllabus`、`knowledge-graph`、`coverage`、`review` | 刷题与错题页、`subpackages/knowledge` | 题库页已拆查询、保存和部分编辑职责，不能据此标记知识图谱等页面完成。保留版本/知识点权威实现，后续核对各页面请求、转换及草稿生命周期。现有 `question-*.test.ts`、题库 API 与版本测试继续作基线。 |
| 导入与 AI/OCR | `imports.py`、`ai_import.py`、`admin_imports.py`、`admin_ai_config.py`、`admin_ai_settings.py`；`features/pipeline_orchestrator.py`、`question_pipeline.py`、`services/import_pipeline_service.py` | `imports/*`、`ai-settings`、`system/tasks` | 当前 25 个注册页没有独立 AI/OCR 导入页面，不新增小程序导题入口 | 审核页已拆纯规则、mutation、编辑和详情展示，仍需收敛状态与页面组合。OCR 编排/worker 相互导入与 question_pipeline 兼容入口见静态循环登记；迁移必须补恢复、任务与人工审核证据。现有 `tests/architecture`、`tests/pipeline`、`tests/ocr_pipeline` 为验证入口。 |
| 学习闭环 | `practice.py`、`wrong_questions.py`、`review.py`、`exams.py`、`study_plan.py`、`study_hub.py`、`adaptive_learning.py`；`services/practice_service.py`、`wrong_question_service.py`、`review_scheduler.py`、`exam_service.py`、`study_plan_service.py` | `exams`、`exams/[id]`、`recommendation/*`、题库配置 | `subpackages/study` 的刷题/结果/错题/今日复习/学习计划，`subpackages/exam` | GET 发题编排已治理；提交、错题/复习、考试、计划/推荐仍待迁移。刷题 `_loadQuestions` 342 行、今日复习 `submitGroup` 207 行，先刻画会话/答案/完成口径，不搬进万能 runner。回归入口：后端 `tests/practice`、`test_practice_chain_regressions.py`、`test_review_api.py`；小程序 `test-review-submit-completion.js`、`test-practice-result-diagnosis.js`。 |
| 学习数据 | `pomodoro.py`、`stats.py`、`study_report.py`、`sync.py`；`services/pomodoro_service.py`、`pomodoro_normalization.py`、`pomodoro_attribution.py`、`stats_service.py`、`study_report_service.py` | `dashboard`、`app-users` 中已有展示 | `pages/home`、`pages/dashboard`、番茄钟和 `productivity/pomodoro-stats` | 番茄钟纯计算/持久化/待同步队列已接入，Page controller 与统计响应转换待治理。后端统计快照函数 338 行；必须保留多学科归因、暂停、跨日和幂等口径。现有番茄钟独立 Node 脚本及 `test_pomodoro_study_day_stats.py`、PostgreSQL 并发测试为入口。 |
| 公式与导出 | `formulas.py`、`admin_formulas.py`、`exports.py`；`services/formula_*`、`services/export/*` | `formulas`、`formulas/[id]`、`formulas/new`、`formulas/categories` | `subpackages/formulas`、`subpackages/export` | 保留已有公式编辑 workbench/图谱辅助模块；列表页与导出记录页转换/查询职责待核查。DOCX/OMML 与 export service/processor 既有局部互引按具体边登记，不新增第二套导出器。回归入口：后端 `tests/export`、`test_admin_formulas.py`；小程序公式脚本、`test-export-capability-error.js`。 |
| 公共运行时 | `main.py`、`worker_main.py`、`scheduler_main.py`；`services/task_queue_service.py`、`task_queue_worker.py`、缓存/存储/健康服务 | `lib/api/client.ts`、`lib/api/sse.ts`、`system/tasks`、`imports/tasks` | `app.js`、`utils/api.js`、`utils/storage.js`、现有内容渲染器 | 主入口 lifespan 870 行、任务消费 `_process_task_v2` 307 行，按角色/状态机拆分。HTTP、worker、scheduler 的退出与失败路径分别验证；新门禁不证明运行时安全。回归入口：`test_worker_sigterm.py`、`test_worker_kill.py`、任务队列测试及客户端 API/SSE 测试。 |

## 3. 当前热点的具体处理依据

长度是物理行数；函数长度含嵌套块。这里只列优先热点，未列出的文件没有被认定为“无需处理”。

| 路径 | 文件行数 | 候选函数/方法及行数 | 已确认职责或待分离边界 |
| --- | ---: | --- | --- |
| `backend/app/features/pipeline_orchestrator.py` | 7151 | `_run_split` 473 | 阶段输入/输出、检查点、恢复与异常传播；复用已有 stages，待故障注入。 |
| `backend/app/services/practice_service.py` | 4103 | `get_smart_scored_questions` 540 | 选题/评分/查询组合，保留 provider 与批次签名边界。 |
| `backend/app/services/task_queue_service.py` | 3535 | `fail_v2` 187 | 状态迁移/租约/重试/存储耦合，须数据库与队列集成。 |
| `backend/app/services/ai_service.py` | 2301 | `analyze_error` 790 | 错题分析与预热生命周期相互导入，保持凭据和画像边界。 |
| `backend/app/main.py` | 2156 | `lifespan` 870 | 资源初始化、任务启停与 app 装配混合，按角色生命周期迁移。 |
| `backend/app/services/pomodoro_service.py` | 1825 | `build_pomodoro_statistics_snapshot` 338 | 统计与归因响应组合，需同口径快照/跨日回归。 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 2496 | `ImportReviewPage` 2256 | 请求/展示已部分抽出，草稿、预览、筛选和弹层编排仍集中。 |
| `admin-frontend/src/app/(admin)/questions/page.tsx` | 2397 | `QuestionsPage` 2044 | 查询/保存/草稿与部分编辑已抽出，其余页面组合待迁移。 |
| `admin-frontend/src/app/(admin)/knowledge-graph/page.tsx` | 1809 | `KnowledgeGraphPage` 613 | 图谱转换和交互已有页面外函数；继续核查请求/布局/选择状态。 |
| `admin-frontend/src/app/(admin)/system/tasks/page.tsx` | 1599 | `SystemTasksPage` 1121 | 任务列表/详情/事件消费与 UI 编排边界待核查。 |
| `miniprogram/pages/pomodoro/pomodoro.js` | 3866 | `onShow` 283 | 恢复、状态修正与生命周期耦合，页面实例 controller 尚未收敛。 |
| `miniprogram/subpackages/study/practice/practice.js` | 2633 | `_loadQuestions` 342 | 会话加载、响应转换与页面写回待分离，保留分包与渲染契约。 |
| `miniprogram/subpackages/productivity/pomodoro-stats/index.js` | 2570 | `_renderTrendBars` 182 | 统计映射/图形派生与视图写回待分离。 |

## 4. 依赖门禁与既有循环

`backend/tests/architecture/test_dependency_direction.py` 扫描全应用，service/feature 到 API 的静态导入必须为零。相对导入、局部导入和可静态解析的字面量动态导入也参与检查；源码语法错误、空目录或目录缺失不会静默跳过。

`dependency_scan.cyclic_edges` 计算强连通分量内部的全部边。基线 `import_cycle_baseline.json` 逐边记录现存 6 组/120 条静态循环边及迁移前需补的回归；新增边（包括同一既有循环组内的新边）与新增模块都不能借组级白名单通过。已解除的循环边必须从基线移除，不允许留下无限期许可。基线只登记当前事实，不将这些循环标记为已修复：

| 静态循环组 | 模块数/内部边 | 已核对原因与迁移条件 |
| --- | --- | --- |
| database / models 注册 | 47 / 95 | models 引用 Base，database 的局部初始化导入模型注册；先分离注册所有权并验证迁移/启动。 |
| ocr_fix 包与适配器/router | 4 / 6 | 包导出与适配器/路由内导入；先补 gateway 与失败路径验证。 |
| question pipeline / writer / AI complete/enrich / draft | 5 / 9 | 历史兼容入口与抽出的实现回调原管线；迁移调用方后才能收尾旧转发。 |
| import pipeline / worker / formula graph / batch image | 4 / 6 | worker 调业务执行器，生产者通过 worker 模块入队；拆生产者协议时验证队列/恢复。 |
| DOCX / OMML | 2 / 2 | 导出器调用 OMML，OMML 局部引用导出器布局；用既有文档输出回归验证。 |
| AI service / prewarm worker | 2 / 2 | AI 分析引用预热 revision，worker 调 AI service；角色启停与预热协议保持不变。 |

第三十八批已解除 embedding / vector config 的 2 模块循环：`services/embedding_endpoints.py` 统一 URL 构造，运行请求与管理端连通测试直接依赖该纯规则，后者不再导入 embedding 执行服务；原配置读取方式不变。26 项端点/调用方回归及 302 组新旧规则对照验证行为一致，对应两条循环边已从基线移除。

第三十九批已解除 export service / processor 的 2 模块循环：`services/export/state_machine.py` 持有原转换表与校验函数，两类消费者直接依赖该规则。55 项状态规则测试、900 组新旧返回值/异常对照与现有导出/并发回归验证等价；不改变任务领取、事务或失败恢复。两条循环边已移除。导出 phase3 的 12 项旧验收仍依赖缺失的本机 DOCX 产物，重构前后均失败，尚需将其改为可重复生成的测试夹具。

该图包含 TYPE_CHECKING、函数内及延迟导入；静态循环不等同于运行时循环导入错误。扫描器不解析计算生成的模块名、动态插件/monkeypatch、隐式包初始化带来的依赖或第三方内部关系，因而“无新增静态循环”不能证明运行时没有循环、死锁或资源泄漏。

运行入口：

```bash
cd backend
.venv/bin/python -m pytest tests/architecture/ -q
ruff check tests/architecture/dependency_scan.py tests/architecture/test_dependency_direction.py
```

CI 已将新测试加入原有 Static architecture & non-GPU regression tests 步骤；不新增生产运行入口。

## 5. 未完成的验收

- 本清单完成注册入口枚举和后端静态依赖基线，仍需逐用例核对全部消费者、事务/状态机和异常行为。阶段 0 的全量语义审查保持未完成。
- 上表的“待核查/待迁移”必须有代码与回归证据后才能改为完成；行数下降、文件移动、AST 解析成功均不能单独满足治理验收。
- PostgreSQL/Redis、OCR/AI 外部服务、真实后台浏览器与微信编译/模拟器/真机没有在本批运行。高风险迁移须另补相应测试环境与故障证据。
