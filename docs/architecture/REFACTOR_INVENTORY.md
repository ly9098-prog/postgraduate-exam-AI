# 全栈重构源码盘点

> 核对日期：2026-10-20；对应 `prompts/tasks/current_task.md` 阶段 0/4。
> 本清单登记真实入口、结构证据、回归入口和后续决策，不代表所有业务语义已审查完毕。

## 1. 范围与证据

- 后端直接解析 `backend/app/**/*.py`：536 个模块、2,139 条模块导入边。覆盖函数内和 TYPE_CHECKING 内的导入、相对导入及字面量动态导入（相对动态导入需同时给出字面量 package）；不执行应用代码，不读取数据库或真实配置。
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
| `backend/app/services/practice_service.py` | 4101 | `get_smart_scored_questions` 540 | 选题/评分/查询组合，保留 provider 与批次签名边界。 |
| `backend/app/services/task_queue_service.py` | 3535 | `fail_v2` 187 | 状态迁移/租约/重试/存储耦合，须数据库与队列集成。 |
| `backend/app/services/ai_service.py` | 2301 | `analyze_error` 790 | revision 协议已移至中立模块，解除预热循环；分析执行编排仍待治理，保持凭据和画像边界。 |
| `backend/app/main.py` | 2156 | `lifespan` 870 | 资源初始化、任务启停与 app 装配混合，按角色生命周期迁移。 |
| `backend/app/services/pomodoro_service.py` | 1825 | `build_pomodoro_statistics_snapshot` 338 | 统计与归因响应组合，需同口径快照/跨日回归。 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 2496 | `ImportReviewPage` 2256 | 请求/展示已部分抽出，草稿、预览、筛选和弹层编排仍集中。 |
| `admin-frontend/src/app/(admin)/questions/page.tsx` | 2397 | `QuestionsPage` 2044 | 查询/保存/草稿与部分编辑已抽出，其余页面组合待迁移。 |
| `admin-frontend/src/app/(admin)/knowledge-graph/page.tsx` | 1809 | `KnowledgeGraphPage` 613 | 图谱转换和交互已有页面外函数；继续核查请求/布局/选择状态。 |
| `admin-frontend/src/app/(admin)/system/tasks/page.tsx` | 1599 | `SystemTasksPage` 1121 | 任务列表/详情/事件消费与 UI 编排边界待核查。 |
| `miniprogram/pages/pomodoro/pomodoro.js` | 3631 | `onShow` 18 / `onHide` 30 | 展示恢复与离页持久化已独立；确认操作、计时/画布、统计及其他职责仍待治理。 |
| `miniprogram/subpackages/study/practice/practice.js` | 2633 | `_loadQuestions` 342 | 会话加载、响应转换与页面写回待分离，保留分包与渲染契约。 |
| `miniprogram/subpackages/productivity/pomodoro-stats/index.js` | 2570 | `_renderTrendBars` 182 | 统计映射/图形派生与视图写回待分离。 |

## 4. 依赖门禁与既有循环

`backend/tests/architecture/test_dependency_direction.py` 扫描全应用，service/feature 到 API 的静态导入必须为零。相对导入、局部导入和可静态解析的字面量动态导入也参与检查；源码语法错误、空目录或目录缺失不会静默跳过。

`dependency_scan.cyclic_edges` 计算强连通分量内部的全部边。第五十八批后全应用静态循环为零，`import_cycle_baseline.json` 已缩减为空数组；既有门禁继续拒绝任意新增循环边，不设组级白名单。扫描仍包含局部和 TYPE_CHECKING 导入；零静态循环不等于运行时资源、完整角色或业务端到端验收完成。

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

- 当前覆盖 9 个已治理模块：`timer-math.js`、`session-storage.js`、`pending-sync-queue.js`、`active-session-recovery.js`、`completion-recovery.js`、`confirm-recovery.js`、`hide-storage.js`、`show-recovery.js`、`sync-retry-controller.js`，路径均位于 `miniprogram/pages/pomodoro/utils/`。
- 唯一许可的模块依赖是 `confirm-recovery → timer-math`；其他模块不导入页面、API、全局存储、第三方或其他分包。require 必须直接接收单个字符串字面量；别名、计算参数、动态/ES 导入会失败。
- 已治理模块不直接访问 wx/Page、隐式 this、全局时钟/定时器/网络或全局宿主；通过 options/storage 等显式能力回调访问外部副作用。静态检查允许属性名、注释与字符串出现同名词，不用文本搜索将它们判为越界。
- 每个覆盖模块不超过 300 行，所有有函数体的函数、箭头、表达式、方法和访问器不超过 50 行。真实 `Page({...})` 中已治理的生命周期和适配方法也保持 50 行；页面总行数设为现存 3,631 行上限，因剩余未治理职责记录为技术债，后续抽取时应同步缩减上限，不扩增白名单掩盖增长。
- 语法错误、空/仅注释文件、缺失源码、缺失治理方法/页面导入或异常 Page 定义会失败。13 项独立反例测试覆盖违规注入、嵌套函数、虚假同名对象方法和完整扫描失败路径。

管理端依赖安装后，从仓库根目录运行：

```bash
node miniprogram/scripts/architecture/pomodoro-boundaries.js
node miniprogram/tests/test-pomodoro-module-boundaries.js
```

`.github/workflows/reliability.yml` 在既有 `admin-build` 的依赖安装后、构建前运行门禁、9 个独立 Node 测试文件及页面韧性/恢复/渲染脚本。本地执行新增步骤的原始命令通过，独立 Node 测试共 85 项；远端 GitHub CI 尚未运行。没有新增小程序 `npm test`。

范围限制：该策略只覆盖明确列出的 9 个模块与页面方法，不证明其他小程序业务、所有分包边界或运行时能力隔离已完成；不是安全沙箱。主题/科目缓存等既有 wx 适配、其他页面、双份代码一致性和全仓尺寸基线仍需后续核查。行为正确性继续由独立回归和真实微信环境验收，不能由 AST 门禁替代。

## 6. 未完成的验收

- 第五十一批发现并用 HEAD 原 database/45 模型源码在新进程复现 3 项既有失败：`test_p5_0_schema_baseline_migration` 要求当前不存在的 PracticeRecord.answers；`test_pomodoro_v2_migration` 两项 runtime 测试以当前不可用的“数学二”夹具启动会话。第五十二批已按当前 per-answer/PracticeSession 契约、canonical 科目和受控时钟修复断言/夹具，并显式清理共享 SQLite 中未级联移除的 allocation 子表；三份交接测试共 42 项通过，不修改生产行为、不增加 skip/xfail。扩大回归为 216 通过、13 失败、16 条件跳过；额外 study_day_stats/scheduler 两文件单独运行仍为相同 13 失败/35 通过，涉及旧科目、统计分类和当前日期相关断言，尚待处理。PostgreSQL 条件测试本地跳过，不宣称迁移/并发验收完成。

- 第四十一/四十二批已新增并接入 `pages/pomodoro/utils/sync-retry-controller.js`，重试状态仅由 controller 持有，页面提供显式能力回调。独立 9 项测试及 Page VM 29 项运行回归覆盖退避、隐藏/卸载清理、监听身份、终态冲突与真实队列单次并发 drain；不代表 `onShow` 恢复、整个页面或微信真实网络行为已经完成验收。
- 第四十三批活动会话恢复下沉到 `pages/pomodoro/utils/active-session-recovery.js`，模块组合本地恢复、待同步动作处理和服务端状态应用；页面保留能力接线与完成/确认前置分支。10 项独立测试、Page VM 33 项运行回归及 6,144 组旧/新轨迹与状态对照验证本地证据，微信首帧、后台切换和真实网络行为仍未验证。
- 第四十四批完成标记的视图转换下沉到纯函数 `pages/pomodoro/utils/completion-recovery.js`；6 项独立测试、Page VM 35 项运行回归和 1,920 组旧/新结果对照通过。完成标记校验、振动、同步和延迟统计仍由原页面执行，结束确认及剩余生命周期编排未完成。
- 第四十五批 `pages/pomodoro/utils/confirm-recovery.js` 组合确认快照恢复，复用 timer-math，合并自由/倒计时暂停补偿回执逻辑；7 项模块测试、Page VM 39 项回归及 864 组旧/新状态和回调轨迹对照通过。有效性、导航保护和失效清理留在页面；确认取消/提交及剩余页面职责未完成治理，真实微信运行尚未验证。
- 第四十六批 `pages/pomodoro/utils/show-recovery.js` 收敛 onShow 优先级，完成与确认分支独立，页面仅持有生命周期状态和能力接线。11 项入口测试、Page VM 42 项运行回归及 12,288 组完整旧/新 onShow 轨迹和状态对照通过；恢复入口治理有本地证据，整个页面、其他生命周期和真实微信行为仍未完成验收。
- 第四十七批 `pages/pomodoro/utils/hide-storage.js` 集中离页取消意图、确认持久化及运行快照构建，保留存储上下文、时钟取值和清理顺序。8 项模块测试、Page VM 46 项运行回归及 13,824 组完整旧/新 onHide 对照通过；生命周期局部有本地证据，确认操作、计时/画布和整个页面仍未治理完毕。

- 本清单完成注册入口枚举和后端静态依赖基线，仍需逐用例核对全部消费者、事务/状态机和异常行为。阶段 0 的全量语义审查保持未完成。
- 上表的“待核查/待迁移”必须有代码与回归证据后才能改为完成；行数下降、文件移动、AST 解析成功均不能单独满足治理验收。
- PostgreSQL/Redis、OCR/AI 外部服务、真实后台浏览器与微信编译/模拟器/真机没有在本批运行。高风险迁移须另补相应测试环境与故障证据。
- DOCX 验收已检查 ZIP 完整性、XML 可解析、python-docx 重开、原生表格/合并单元格、PAGE 页脚、中文/化学字符和 OMML 矩阵节点/元素值。当前输出有两个页脚且仅使用 PAGE，旧 NUMPAGES 断言已按实现更新。
- 第四十批额外使用 docx 技能附带的严格 OOXML 校验器检查合成输出，校验未通过：`header2.xml` 的 pBdr、`document.xml` 的 shd/tblBorders/keepWithNext 元素顺序及 `settings.xml` 的 zoom 缺少 percent 属性。源码与样本还显示 OMML 矩阵缺少行列包装，`segments.text` 中的 LaTeX 走纯文本路径；本批未修改生产渲染器，单独登记为既有格式/渲染问题。当前测试通过不证明完整 OOXML 合规、矩阵布局正确或 Word/LibreOffice 显示一致。

第五十七批分离公式批次的创建、执行和单一进程内状态所有者：Admin API 直接依赖 batch_service/state，两个 worker 分发分支直接依赖 batch_runner，preview/confirm service 不再依赖 worker。保持原队列 payload、任务 id、重试次数、逐卡事务、失败继续、取消传播与跳过计数口径。新增 17 项契约/交接测试和 2 项架构/预算测试；完整架构、公式 API、上传及队列指标共 288 项通过。111 组旧/新状态与事务/重试/取消轨迹相同，328 路径 OpenAPI 相同。进程内状态不跨进程共享是原有限制，本批没有声称独立生产 worker 批次状态已验收；真实 Redis/PostgreSQL、渲染进程及生产仍未运行。剩余 import/batch image/worker 的 4 条循环边待继续治理。

第五十八批拆出 Public/Admin 唯一上传入口、不可变输入快照及图片/Excel/文档 admission 模块，后台执行服务不再导入 worker；移除最后 4 条循环基线边。输入只保留原 12 个参数，不新增业务状态。原后台服务剩余非导入/说明 AST 不变，完整 328 路径 OpenAPI 一致；160 组响应/异常及校验、资源预留、暂存、状态、队列、释放调用对照一致。新增 29 项 admission 和 4 项架构/新进程回归通过；扩大架构、上传/API、故障注入与公式队列交接为 226 通过、8 项相同既有失败。新增第 4 项首导入测试后定向 33 项通过。8 项失败涉及旧权限夹具、错误脱敏预期及直接调用路由缺少用户参数，未通过修改生产行为或 skip/xfail 掩盖。保留原队列取消不释放预留的行为；真实 Redis/PostgreSQL、OCR/模型、完整角色生命周期与客户端仍未验证，零静态循环不关闭阶段 0/1/3/4 的其他待办。
