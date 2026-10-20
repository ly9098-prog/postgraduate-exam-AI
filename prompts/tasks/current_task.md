# 全栈高内聚、低耦合重构实施计划

> 编制日期：2026-10-19；更新日期：2026-10-20。状态：前三十九批已提交；阶段 0/1/4 部分完成，完整治理尚未完成。
> 已确认方向：全量盘点、分批治理；保持现有行为、界面与外部接口兼容。
> 已获“开始执行”、继续批次及“先提交”授权，实施等价重构并分批本地提交；不推送，不执行生产操作，不清理既有资源。

## 一、目标与实施边界

将“消除屎山”落实为可验证的工程目标：职责按业务聚合、依赖单向、业务规则有唯一权威实现、关键规则可以脱离页面和网络独立测试、修改一个领域不要求无关领域同步修改。文件变短只是结果，不能作为唯一验收依据。

- 后台前端为 `admin-frontend/`，小程序前端为 `miniprogram/`；两者共用 `backend/` 的 FastAPI 单体后端，不建设两套后端，也不把客户端身份边界合并。
- 保留 `/api/v1` 与 `/api/admin/v1` 路径、HTTP 方法、字段、分页、状态码、错误和鉴权语义；保留 Admin RBAC、审计、用户隔离及人工审核链路。
- 保留数据库结构、事务边界、持久化键、任务协议、幂等、统计口径和运行角色。确需改变业务行为、数据库或外部契约的问题，单独记录，不夹带在等价重构中实现。
- 保留现有 UI、交互、导航、主包/分包边界与渲染结果；不做视觉改版，不借重构增加产品功能。
- 遵守根目录及就近 `AGENTS.md`、`docs/project/PROJECT_RULES.md`；不引入微服务、Kubernetes、LangChain/LlamaIndex、通用 service 抽象类或新的全局状态框架。
- 不预先引入 repository 层、依赖注入容器、事件总线或万能工具包；优先复用现有模块，只有明确职责边界和真实调用需求才新增模块。

## 二、当前证据与盘点范围

### 2.1 已核实的候选热点

以下为 2026-10-19 初始盘点物理行数；当前拆分结果见执行记录。行数只用于定位候选，不意味着这些文件的每个部分都需要重写。

| 区域 | 候选文件 | 行数 | 已知依据/后续核查重点 |
| --- | --- | ---: | --- |
| 共享后端 | `backend/app/main.py` | 2156 | 同时注册生命周期、HTTP 中间件、异常处理、健康与指标接口；lifespan 约 870 行 |
| 用户后端 | `backend/app/api/v1/practice.py` | 1307 | 发题函数约 639 行；路由存在内容处理、选题编排及版本装配 |
| 用户后端 | `backend/app/services/practice_service.py` | 4103 | 已有 `services/practice/` 子模块，仍有选题、签名、提交等大函数；用户业务依赖 Admin 学科服务需核查 |
| 共享运行时 | `backend/app/services/task_queue_service.py` | 3535 | 多种入队、失败处理和重试入口；须保留并发/状态机语义 |
| 导入后端 | `backend/app/features/pipeline_orchestrator.py` | 7151 | 多个长阶段函数；优先复用既有 pipeline stages 和 OCR 边界测试 |
| 管理端 | `admin-frontend/src/app/(admin)/questions/page.tsx` | 3855 | 页面内包含筛选、请求、编辑状态及展示组合 |
| 管理端 | `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 3664 | 页面包含编辑数据转换、请求和审核交互，已有多空题辅助模块须保留复用 |
| 小程序 | `miniprogram/pages/pomodoro/pomodoro.js` | 3984 | 需逐段核实计时、恢复、同步、视图状态职责 |
| 小程序 | `miniprogram/subpackages/study/practice/practice.js` | 2633 | 需核实页面编排与题目会话/渲染边界 |
| 小程序 | `miniprogram/subpackages/productivity/pomodoro-stats/index.js` | 2570 | 需核实统计响应转换、筛选和展示派生逻辑 |

证据限制：Codebase Memory 索引生成于 2026-10-15，属于 best-effort，不能证明完整调用覆盖；review 页面局部解析不完整，番茄钟及统计页显示索引后变更。优先使用当前源码复核。计划期部分小程序只读检查曾被 Hook 拦截；用户确认关闭后已完成本批番茄钟相关读取和运行回归，但不代表全部小程序业务域已核查。

### 2.2 全量覆盖清单

阶段 0 对下列业务域逐一登记“入口、实现、调用方、测试、问题证据、处理批次”；没有明确耦合问题的模块标记“保留现状”，而非强制拆分。

| 业务域 | 后端盘点 | 管理端盘点 | 小程序盘点 |
| --- | --- | --- | --- |
| 身份与权限 | 微信认证、Admin JWT/RBAC、审计 | 登录、权限展示、管理员/角色 | 登录、会话恢复、请求认证 |
| 题库治理 | 题目、版本、学科、知识点、大纲 | 题库、版本编辑、学科/知识点/图谱 | 题目消费、筛选、知识地图 |
| 导入与 AI/OCR | 提取、结构化、暂存、审核、发布、恢复 | 导入工作区、审核、任务、AI 配置 | 实际存在的相关入口；没有则不新增 |
| 学习闭环 | 发题、作答、错题、复习、考试、计划、推荐 | 对应题库/考试/配置管理 | 刷题、考试、错题、复习、学习计划 |
| 学习数据 | 番茄钟、统计、学习报告、同步 | 已有统计消费与运维展示 | 首页、dashboard、番茄钟、历史/统计 |
| 公式与导出 | 公式库、资源、导出任务与文件 | 公式编辑/分类、导出相关管理 | 公式阅读、导出与记录 |
| 公共运行时 | 启动、队列、worker/scheduler、缓存、存储、健康 | API/SSE、错误、追踪、任务查询 | API、存储、主题、生命周期、渲染工具 |

部署脚本、迁移历史、生成合约、第三方 KaTeX/mp-html/Lottie、图片资源不做顺手清理。仅当它们直接影响边界或验收时读取和验证，不修改生产设置。

## 三、目标依赖与模块职责

### 3.1 后端

- 路由只负责参数、认证/权限依赖、调用业务入口、响应映射；领域规则、查询编排和状态变化进入现有 service/feature 模块。
- 领域 service 可调用领域规则与数据模型，不得反向导入路由；跨 Admin/Public 共用的学科或题目规则沉到中立模块，权限判断仍留在各自身份边界。
- 每个用例保留唯一事务所有者。拆分函数不能顺手增加 `commit`、改变 rollback/flush 顺序或破坏同事务的 outbox/审计写入。
- `main.py` 保留装配职责；生命周期、HTTP 配置和健康观测按明确职责抽取。抽取模块不导入全局 app，不在导入阶段启动任务或创建连接。
- OCR 提取、规则处理、AI 增强、质量门禁和发布保持既有边界。复用现有 gateway、stage 和恢复机制，不新增第二套编排器。
- 使用具体函数/数据结构表达最小输入输出；不通过 `__init__.py` 重导出，不把所有参数塞进无边界 dict，不用运行时动态导入掩盖循环依赖。

### 3.2 管理端

- 页面负责路由参数、权限和布局组合；同页 feature hooks 管理服务端状态与 mutation；纯函数/reducer 管理编辑规则；展示组件通过有类型的 props 交互。
- 同一业务的 API 方法与 query keys 就近聚合，通过既有 `apiRequest` 发请求；保留 token single-flight refresh、trace、超时、FormData 和错误展示行为。
- TanStack Query 继续拥有服务端状态；编辑草稿局部保存，跨页状态才考虑既有 Zustand。禁止把整页 state 搬进一个超大 hook 或全局 store。
- 题目转换、选项、多空题、结构化表格和版本模型优先复用现有公共实现；领域差异用明确参数/适配器表达，不强行统一审核草稿和已发布题目语义。
- feature 默认放在对应路由的 `hooks/`、`components/` 和纯逻辑模块，至少两个真实调用方且语义相同才提升为共享模块；不整体搬迁所有页面目录。

### 3.3 小程序

- Page/Component 保留生命周期、事件、导航与视图映射；响应转换、计时计算、答案投影等可测规则放入业务就近模块。
- 复用已有 API 边界，区分普通请求、上传、认证和真实存在的离线同步职责；不把页面交互或业务重试全部塞入万能 `api.js`。
- 页面各自拥有 controller 实例与清理逻辑；禁止新建共享可变单例造成跨页面污染，保持计时器、订阅和前后台切换行为。
- study/exam 共用逻辑的提取以实际依赖和分包规则为前提；保留现有分包可独立加载的约束，不让主包或兄弟分包直接引用另一分包代码。
- 若为分包可用性需要保留两份渲染代码，先使用已有一致性检查守护；只在收益和打包方式已验证时抽取，不为消重引入运行时依赖风险。

## 四、分阶段实施清单

每批固定流程：核查工作区和调用点 → 补充行为刻画测试 → 抽取纯规则 → 迁移调用方 → 校验边界和回归 → 更新本文件。无关改动不纳入批次；出现现有未记录变更时暂停确认，不覆盖它们。

### 阶段 0：完成基线与可执行治理清单

- [ ] 补齐上述全量业务域的源码检查，记录问题实例及受影响消费者，不以行数或未被图索引引用判定死代码。
- [ ] 为每个候选记录文件/函数长度、依赖方向、循环依赖、重复职责、外部入口、调用方和回归脚本；按风险与收益确定逐批迁移清单。
  - 第三十七批新增 `docs/architecture/REFACTOR_INVENTORY.md`，登记 523 个后端模块的静态依赖基线、32 个管理端页面和 25 个小程序注册入口，并按七个业务域列实现/消费者/回归入口与待验证项。逐用例语义审查尚未完成，该项仍未勾选。
- [ ] 固定四类兼容基线：API/OpenAPI、数据库与事务、客户端状态/存储、UI 与渲染。记录已有失败和未验证环境，不把历史问题算作本轮新增。
- [x] 核实并修复 `backend/tests/architecture/test_architecture_boundaries.py` 的扫描路径：首批记录扫描 512 个 Python 文件；第二批为 514 个，第三批为 516 个，第四批为 519 个。增加缺失/空目录失败和注入违规检出测试，消除“零文件通过”。
- [x] 选定并完成首批纯规则抽取：刷题内容转换、管理端题库 URL 筛选、小程序番茄钟时间计算；未触碰队列/OCR 并发核心。后端与小程序先跑基线；管理端另与 Git 原版进行 96 组规则对照。
- [x] 第二批完成刷题请求筛选与学科/知识点范围解析；保留路由 HTTP 映射和既有 `practice_service` 查询，修复旧 API 测试夹具以恢复有效契约回归。
- [x] 第三批完成刷题候选策略和 Leitner 到期筛选；保留最终版本范围校验、签名及顺序预约事务位置，对照重构前真实调用轨迹和 OpenAPI。
- [x] 第四批完成最终候选守卫、签名上下文与不可变响应构建；补充顺序预约提交/异常顺序和知识范围快照测试，保留路由事务所有者。

阶段出口：每个业务域都有“处理/保留/待验证”结论；首批目标、调用方和验证命令明确；高风险行为已有可重复的基线。

### 阶段 1：完成低风险纵向样板

- [x] 后端已从刷题路由提取题干/选项清洗与响应投影，并拆出请求筛选及范围解析，继续复用 `services/practice/`。
- [x] 候选选题策略与 Leitner 到期筛选已拆出；路由不再直接组织定向、随机、相似、智能和顺序选题策略，HTTP 错误仍由路由映射。
- [x] 已拆出最终候选守卫、签名上下文与响应构建，刻画不可变版本范围、曝光清理、知识范围与顺序预约提交/异常路径；路由保留 HTTP 映射及事务所有权。
- [x] 第九批收敛发题请求装配和观测编排；GET 入口 48 行，HTTP 映射与最终事务提交由同路由模块 21 行适配函数持有。该项仅覆盖发题入口，不代表提交等完整刷题链路已治理。
- [x] 发题回归保持不可变版本、签名批次、顺序预约、答案投影和冲突行为；第八批将跨 Admin 科目解析依赖迁至中立模块，Admin 权限/写入/审计仍留在原边界。
- [ ] 管理端先重构 questions，再重构 imports/review：先提取纯转换/筛选，再迁移请求与 mutation hooks，最后按可独立描述的界面职责拆组件。
  - 第十批已迁移 questions 列表、详情和历史版本查询 hooks，集中 query keys 与预取配置；第十一批迁移最小 PATCH 和手动保存/删除 mutation；第十二批迁移进入编辑/保存后草稿转换及即时操作前保存编排；第十三/十四批拆分代码块、表格编辑与版本对比展示。第十五批聚合编辑草稿生命周期与关闭保护；其余组件组合和 imports/review 仍待治理。
  - 第十七至二十九批已迁移 imports/review 的编辑初始化、筛选参数、科目投影、审核/保存/答案/AI 补全/文本和图片批量答案 mutation，以及文本/图片结果展示与答案解析编辑区。题干/选项编辑、详情展示和页面状态组合仍待治理，该项保持未完成。
- [ ] 小程序番茄钟先提取无副作用计算，再隔离会话持久化/同步适配，最后收敛页面 controller；保留当前已实现的计时模式、恢复和统计口径，不新增旧方案中的未核实行为。
- [ ] 样板入口完成后检查依赖变化、独立测试和调用复杂度；禁止把旧大文件内容原封不动搬进另一个大文件。

阶段出口：三个运行部分各有一条真实功能链迁移且回归等价；新依赖方向可由自动检查验证，才将模式扩展至其他域。

### 阶段 2：扩展到学习域与管理域

- [ ] 后端按“刷题提交 → 错题/复习 → 考试 → 计划/推荐 → 统计/番茄钟”推进；保留 ReviewSchedule 权威性、题目版本约束、时间/学科口径和任务投影一致性。
- [ ] 管理端继续处理 AI 配置、任务页、公式编辑、知识图谱、考试和权限管理；使用领域 hooks/client，保留缓存失效、URL 筛选、草稿和权限行为。
- [ ] 小程序按“刷题/考试会话 → 错题/今日复习 → 结果页 → dashboard/计划 → 公式/导出”推进；优先复用现有 runner、内容规范化与渲染辅助模块。
- [ ] 共用规则和协议集中到最小领域模块；跨端只共享契约与测试样例，不强行让 Python、React 和小程序使用同一运行时代码。
- [ ] 每个域完成时补充空数据、异常、取消/离页、重复触发、旧数据兼容测试；未发现问题的模块保留结构，不为覆盖率制造修改。

阶段出口：全量业务域的迁移/保留决策有证据，客户端不拥有后端权威业务规则，页面与路由不再集中承载已治理域的核心业务。

### 阶段 3：共享运行时与导入高风险治理

- [ ] 把启动、HTTP 异常/中间件、健康/指标从 app 装配中拆出；覆盖 HTTP/worker/scheduler 各自启动、失败清理和退出，不改变生产画像及角色隔离。
- [ ] 按生产者、状态迁移、存储操作、重试与消费者职责拆分任务队列；保留现有任务版本、锁、租约、去重、ack、重试及死信行为，不合并不同协议的语义。
- [ ] 使用既有 OCR pipeline stages 拆编排器；先确定阶段输入/输出与上下文所有权，再迁移实现。保留恢复检查点、失败传播、人工审核和 OCR/AI 配置边界。
- [ ] 对 service/feature 中的公式、导出、存储、AI 等剩余热点按已盘点问题治理；不重做已经稳定的基础设施，也不因当前代码少被调用就删掉运行入口。
- [ ] 高风险批次必须通过对应数据库/队列/故障注入测试后才标记完成；外部服务不可用时如实记为未验证，不以 mock 单测替代集成验收。

阶段出口：角色生命周期、任务与导入状态机回归等价；没有新增第二套队列、OCR 或网关；人工审核及安全门禁保持有效。

### 阶段 4：长期门禁、收尾与交接

- [x] 后端增加 AST 依赖规则和新循环依赖检查；禁止业务层反向依赖 API、越界访问私有 OCR/AI 实现，并对错误示例验证检查确实会失败。
  - 第三十七批全应用静态扫描确认 service/feature → API 为零；新门禁逐边限制循环，初始登记 8 组/124 条既有静态循环边；第三十八批解除 embedding/config、第三十九批解除 export service/processor 循环后缩减为 6 组/120 条。新增边/模块不能通过，已解决边必须缩减基线。既有 OCR/AI 私有边界与注入反例测试继续通过；运行时循环和高风险迁移仍待专项验证。
- [ ] 管理端在现有 ESLint/测试体系中限制已治理 feature 越界和绕过请求 client；小程序用独立 Node 检查模块引用、分包边界与需要保持的双份代码一致性。
- [ ] 对现有超标记录有路径和原因的基线：未治理文件不得继续增长，新增/拆出业务文件遵守单文件不超过 300 行、函数不超过 50 行；非业务生成资源排除，已治理目标清零而非反复扩大白名单。
- [ ] 仅在静态调用、动态注册、字符串入口、分包配置和回归测试都确认后，清理旧转发和重复实现。删除文件/资源须单独盘点并遵守确认保护，不与普通抽取混在一起。
- [ ] 按实际改动同步架构、API/Admin/前端文档和本任务勾选状态；CI 接入准确命令，不引入不存在的仓库根级 `npm test`。

阶段出口：所有处理项有测试证据，所有保留项有理由，未验证项明确列出；门禁能拦截新增的同类问题，临时兼容层没有无期限残留。

## 五、测试与验收方法

### 5.1 命令与环境

- 后端在 `backend/` 执行 `python -m compileall -q app`、`ruff check <本批修改的 Python 文件>`、`python -m pytest <受影响测试路径> -v --tb=short`。兼容现有 CI 全量 lint 时使用其既有参数，不以忽略新增错误通过验收。
- 管理端在 `admin-frontend/` 执行 `npm run typecheck`、`npm run lint`、`npm run test`；移动路由/组件边界或改变构建依赖时执行 `npm run build`。新测试须被当前 Vitest 配置实际收集。
- 小程序在 `miniprogram/` 使用现有独立 Node 脚本：按改动选择 `tests/test-code-mode.js`、`tests/test-config-resolution.js`、`tests/test-export-capability-error.js`、`tests/test-latex-symbols.js`、`tests/test-multi-blank-answer.js`、`tests/test-render-invariant.js` 和 `tests/render_regression/run.js`。runner 一致性检查运行前先确认脚本及所需环境。
- 页面/渲染/分包调整补微信开发者工具编译、模拟器与真机检查，三者分别记录。生产 PostgreSQL/Redis、OCR/AI 和微信环境均不默认可用，使用测试配置而非生产凭据。
- 首批已执行本地测试，具体命令、结果和环境限制见第七节；未运行的集成、构建和微信验收不得视为通过。

### 5.2 行为场景

- 题库/审核：多空题、代码、LaTeX、图片、表格、版本、知识点；保存、批量审核、冲突、取消及失败后重试。暂存内容不得绕过人工审核发布。
- 刷题/复习/考试：合法/非法范围、旧题版本、幂等键复用冲突、并发提交、顺序进度、答案不泄露、复习调度和结果统计。
- 番茄钟/学习数据：当前计时模式、暂停恢复、后台切换、进程重启、断网重连、重复结束、跨日统计；不得多算/少算时长或会话次数。
- 认证/API/SSE：用户与 Admin token 隔离、401 单次刷新、403 权限拒绝、超时/取消、上传、任务事件重连、trace/错误脱敏及审计。
- 队列/OCR/运行角色：重复任务、worker 中断/恢复、失败重试、检查点恢复、外部服务不可用、正常退出；不得吞异常、伪造成功或启动重复周期任务。

### 5.3 完成标准

1. 外部 API、界面交互、数据库语义与部署入口无非预期变化；OpenAPI 差异如存在必须解释且不能破坏兼容。
2. 新拆领域规则不依赖 Page/React/FastAPI 路由即可测试；关键状态变化只有一个事实来源，不靠全局变量或互相回调维持一致。
3. 已治理范围没有新循环依赖、跨域私有调用、重复权威实现或仅改文件位置的假拆分；入口与领域边界可由测试约束。
4. 全量业务域都已审查，实际问题逐批处理、无问题保留；不以“所有文件都改过”或“零长文件”冒充架构完成。
5. 每批记录改动范围、测试命令、通过/失败/未执行原因、剩余项和兼容入口去向；不把计划、静态推断或模拟器结果写成生产/真机已验证。

## 六、安全、回退与执行记录

- 开始实施前重读 `git status`；保留现有文档、资源删除和配置改动，不恢复、不清理、不夹带提交。`current-task.md` 与本文件不是同一文件，不恢复已删除的旧任务。
- 批次必须可独立验证；失败时修复或只回退该批自有修改，不用 `git reset --hard`、`git checkout --` 覆盖工作区；已获分批本地提交授权，不推送或重写历史。
- 适配入口只用于内部调用迁移，调用方全部切换并验证后收尾；不承诺未经确认的外部 Python 导入兼容，不用兼容壳永久保留双套实现。
- 生产迁移、部署、服务重启和数据库/volume/资源删除均不属于本任务。若后续确有需要，另行给出影响范围、备份和授权流程。

| 阶段 | 状态 | 验证/证据 |
| --- | --- | --- |
| 计划编制 | 已完成 | 本地热点扫描、关键后端/管理端源码、项目规则与索引覆盖检查；不代表已全量审计 |
| 0：基线与清单 | 部分完成 | 首批调用点/行为基线与架构扫描已核查；全量业务域盘点仍待继续 |
| 1：纵向样板 | 部分完成 | 三处纯规则、刷题请求/范围、候选策略/到期筛选、最终守卫/签名响应、GET 请求装配与观测、管理端请求协议/查询/保存/删除/即时写入 hooks 与最小 PATCH/草稿转换、小程序番茄钟持久化/同步适配已接入并回归；管理端其余组件与审核页、小程序 controller 仍待收敛 |
| 2：学习与管理域 | 待实施 | 按域小批迁移与回归 |
| 3：运行时与导入 | 待实施 | 角色、队列、OCR 集成/故障验证 |
| 4：长期门禁与收尾 | 部分完成 | 已接入后端全应用反向依赖/新增静态循环门禁与反例测试；全栈预算、分包边界、兼容收尾和最终验收仍待完成 |

## 七、首批执行记录（2026-10-19）

### 7.1 已落地范围

- 后端：`services/practice/response_content.py` 接管代码检测、题干/选项清洗、判断题默认选项；路由调用新模块，测试直接依赖规则，不再为了测纯函数加载路由。保留正文以 `text` 为准的既有规则、代码缩进、罗马枚举和非字典历史值兼容，不改变发题、提交与事务。
- 管理端：`questions/question-list-state.ts` 集中筛选默认值、URL 读写、分页与正整数规则；保留空 `is_active` 与省略参数的不同含义、URL 编码/顺序和既有数值转换，未改请求、mutation、JSX 或交互。
- 小程序：`pages/pomodoro/utils/timer-math.js` 接管累计/倒计时展示与时长减暂停计算；Page 方法作为原入口委托，继续负责 `api.now()`、本地暂停修正和生命周期。保留小数秒及非法暂停值产生 NaN 的原行为，不夹带修正业务口径。
- 测试护栏：修正 OCR AST/编译检查的根路径，扫描不允许为空；增加虚构违规导入检出和刷题投影依赖边界测试。五小时测试不再用正则提取页面函数后 `new Function` 执行，改为直接调用真实规则；Page 沙箱测试加载真实模块并补时钟/暂停接线场景。
- 新业务模块分别为 206/70/33 行，各函数不超过 50 行；旧入口净减少 197/59/23 行，但仍是待持续拆分的长文件，不以行数下降宣称整体完成。

### 7.2 验证证据

- 后端初始刻画：56 项中 48 通过、7 xfailed、1 失败。失败为 `test_deduplication.py` 仍断言 `stem` 优先，与既有 `reconcile_student_stem_fields` 的 `text` 优先实现相悖；仅修正过时断言并迁移导入，未修改正文规则。
- 后端定向回归（`backend/`）：`.venv/bin/python -m pytest tests/practice/ tests/test_services/test_deduplication.py tests/test_api/test_practice_chain_regressions.py tests/architecture/test_architecture_boundaries.py -q`，82 项中 75 通过、7 xfailed，0 失败。
- 扩大回归加入 `tests/test_api/test_practice.py`：79 通过、7 xfailed、7 失败；通过在独立进程内加载 `git show HEAD:backend/app/api/v1/practice.py` 原版路由并复跑，确认相同 7 项失败（另 4 项通过），未覆盖工作区文件。失败涉及旧 sequential 预期、缺少不可变版本范围夹具及 `_MockDB.scalar`；不为重构通过而改生产逻辑、跳过或 xfail 这些测试，后续需更新该测试文件的夹具/契约。
- 后端 `.venv/bin/python -m compileall -q app` 和本批 5 个 Python 文件的严格 `ruff check` 通过。AST 对照确认 10 个异步路由函数签名、装饰器和返回注解与 Git 原版一致；不是运行时 OpenAPI/数据库集成验收。
- 管理端（`admin-frontend/`）：`npm run typecheck`、`npm run lint`、`npm run test` 全部退出 0；Vitest 17 文件、448 测试通过（新增 URL 状态测试 28 项）。ESLint 为 0 错误、137 警告；本批页面与 Git 原版的 5 条诊断按规则、级别和标题一致，新模块/测试为 0 警告，未扩大修复全库警告；另与 Git 原版 URL/数值规则做 96 组等价对照，全部通过。
- 小程序（`miniprogram/`）：`node tests/test-pomodoro-timer-math.js` 20 项；`node scripts/test-pomodoro-free-timer-limit.js` 39 项；`node scripts/test-pomodoro-resilience.js` 106 项；`node scripts/test-pomodoro-resume-latency.js` 12 项；`node scripts/test-pomodoro-stability-runtime.js` 22 项；`node tests/test-pomodoro-subject-cache.js` 16 项；以上全部通过。
- 小程序展示保护：`node tests/test-pomodoro-timer-shimmer.js`、`node tests/test-render-invariant.js`（43 项）、`node tests/render_regression/run.js`（5 fixture / 31 项）通过。
- 未执行：管理端生产构建/浏览器交互、微信开发者工具编译/模拟器/真机、生产 PostgreSQL/Redis、外部 OCR/AI 和生产部署。当前只有本地单测/静态/沙箱证据，不代表端到端或生产验证完成。

### 7.3 后续优先项

1. 继续阶段 0 全量清单；阶段 1 按既定顺序拆刷题候选选题/发题用例、题库编辑/请求状态、番茄钟持久化/同步适配。
2. 后续批次再扩展学习域、导入与运行时；本批未删除资源、改库、提交、推送或部署，保留原有未提交改动与删除状态。

## 八、第二批执行记录：刷题请求范围（2026-10-19）

- 生产代码新增 `backend/app/services/practice/request_filters.py`（63 行）与 `request_scope.py`（88 行）。前者集中知识点筛选、名称 CSV 与定向题目 ID 的解析及错误优先级；后者协调既有学科/知识点解析服务，返回稳定的数据结构。两者不依赖 FastAPI 路由；依赖方向为范围模块调用 `practice_service`，后者不反向导入范围模块，也不新增事务所有者。
- `backend/app/api/v1/practice.py` 仅迁移解析和范围编排，保留认证、HTTP 错误映射、候选策略、不可变版本范围、签名批次、顺序预约、答案投影和会话行为。运行时 `app.openapi()` 与重构前快照的 328 条路径完全一致。
- 旧 `backend/tests/test_api/test_practice.py` 的过时知识点 patch、版本夹具和顺序模式预期已按当前契约修复；新增 8 个 HTTP 参数校验用例，验证安全错误 envelope 且不触发候选查询。原有 11 个用例恢复通过，未通过生产逻辑换取测试通过。
- 定向回归命令（在 `backend/`）：`.venv/bin/python -m pytest tests/practice/ tests/test_services/test_deduplication.py tests/test_api/test_practice.py tests/test_api/test_practice_chain_regressions.py tests/architecture/test_architecture_boundaries.py tests/test_services/test_practice_service.py tests/test_services/test_sequential_reservation.py -q`；结果 200 项收集，193 通过、7 项既有 xfail、13 条警告，退出码 0。本次观察到 10 条 `datetime.utcfromtimestamp` 弃用提示及 3 条 SQLite 异步线程回调在事件循环关闭后的 `PytestUnhandledThreadExceptionWarning`；未逐项复现其重构前基线，未在本批扩大处理连接清理问题。
- 兼容性对照共 1,258 组：定向题目筛选解析与 Git 原始实现的 1,188 组组合、知识点校验 64 组及名称兼容 6 例均一致；未进行生产 PostgreSQL/Redis/OCR/AI/微信环境验收。新增业务模块函数均不超过 50 行，严格 Ruff、`compileall` 与 `git diff --check` 已通过。
- 管理端和小程序本批未修改、未重跑其完整测试；本批未提交、推送、部署或修改数据库。阶段 1 仍为部分完成，候选选题/发题用例、全量盘点及后续管理端和小程序职责拆分继续待实施。

## 九、第三批执行记录（2026-10-20）

### 9.1 已落地范围

- `backend/app/services/practice/candidate_selection.py` 以显式请求/结果数据结构承接定向、随机、章节、相似、智能与顺序候选分流；复用既有 provider，不引入新查询或通用抽象。保留随机超采样、父/叶学科分流、定向结果顺序校验、缺少来源题时的相似模式回退、推荐日志失败容错与顺序预约 ID 规则。
- `backend/app/services/practice/candidate_schedule.py` 承接智能/相似模式的 Leitner 到期复核与随机补题；保留候选排序、补题再复核、补题去重与数量截断。初始候选的既有重复行为仍由后续发题去重处理，不提前改变行为。
- `backend/app/api/v1/practice.py` 从第二批的 1,078 行减至 881 行，仅接入上述入口并映射领域错误；最终不可变版本/学科范围守卫、定向 409、曝光清理、签名批次、响应组装和顺序预约提交/清理仍在原位置。未新增事务所有者，未改鉴权、参数契约、数据库结构与部署入口。
- 两个业务模块分别 228/66 行，最长函数分别 29/50 行；新增 31 个策略测试和 10 个到期筛选测试。架构依赖测试扩展至请求范围、候选策略和到期筛选三个编排模块，禁止它们直接依赖路由、FastAPI 或数据库会话工厂。

### 9.2 验证证据与限制

- 改动前先跑原有刷题 API/链路回归，22 项通过；抽取后再次运行，22 项通过。候选策略、到期筛选、API/链路与架构定向回归共 84 项通过。
- 扩大回归在 `backend/` 执行：`.venv/bin/python -m pytest tests/practice/ tests/test_services/test_deduplication.py tests/test_api/test_practice.py tests/test_api/test_practice_chain_regressions.py tests/architecture/test_architecture_boundaries.py tests/test_services/test_practice_service.py tests/test_services/test_sequential_reservation.py -q`；收集 243 项，236 通过、7 项既有 xfail、12 条警告，退出码 0。
- 警告包含 10 条 `datetime.utcfromtimestamp` 弃用提示及 2 条 aiosqlite 在线程回调时遇到已关闭事件循环的 `PytestUnhandledThreadExceptionWarning`；未逐项复现其重构前基线，未将本批扩大为连接生命周期修复，也不宣称零警告。
- 临时差分脚本直接加载第二批路由源码的原候选/到期筛选代码，比较四种模式、两种学科范围、三档数量、Leitner 开关与八种正常/异常场景，共 384 组结果与 provider/日志/到期查询调用轨迹一致；使用确定性 UUID 和替身 provider，不替代真实服务集成验证。重构前后路由使用相同 prefix 生成端点 schema，并确认完整运行时 OpenAPI 的 328 条路径与第二批快照完全一致。
- 严格 Ruff、`compileall`、`git diff --check` 与新增业务模块 AST 行数检查通过；当前架构扫描为 516 个 Python 源文件。索引仍为旧 best-effort 数据，已以当前源码和测试复核本批边界，未重建索引或据此声称全量治理完成。
- 本批未改管理端和小程序，未重跑其完整测试；未进行 PostgreSQL/Redis、OCR/AI、微信模拟器或真机验收。未暂存、提交、推送、部署或修改数据库；保留全部既有工作区改动及资源删除状态。
- 下一批优先刻画并拆出最终发题编排，再推进管理端请求/mutation 与小程序持久化/同步边界；全量业务域盘点、跨 Admin 学科依赖治理与高风险运行时治理仍未完成。

## 十、第四批执行记录（2026-10-20）

### 10.1 已落地范围

- `backend/app/services/practice/final_candidates.py` 负责最终不可变版本范围、学科范围、候选去重、定向集合冲突及推荐曝光对齐；领域异常由路由映射为原有 409，保留排序、数量截断和曝光日志失败容错。
- `backend/app/services/practice/batch_issuance.py` 负责知识范围基线、今日计划归因校验、按范围生成顺序提交 ID、签名及调用不可变响应构建；保留原有 ID 算法与调用顺序，不提交/回滚事务。
- `backend/app/services/practice/issued_response.py` 只从签发的版本 ID 读取题干、选项和知识点，不回读可变题目内容；保留字段、内容清洗和调试摘要，版本缺失/错配由路由映射为原有 500。
- 路由由 881 行减至 675 行，顺序预约清理 SQL、调试输出及“完整响应构建后才提交”的位置与事务所有者保持不变。发题函数仍为 208 行，请求装配和观测编排还需收敛，未宣称薄路由目标全部完成。
- 三个新增业务文件分别 104/139/133 行，最长函数分别 31/44/31 行；架构 AST 依赖检查扩展至这三个模块，并禁止受检编排模块调用 `commit`/`rollback`。源码扫描当前为 519 个 Python 文件。
- 旧 API 测试仅将版本读取 patch 改到实际依赖的响应模块；不在路由保留重导出兼容壳。新增 27 项测试覆盖顺序/非顺序提交、各阶段异常、版本缺失/错配、响应 schema 失败、定向冲突、最终集合清理、曝光容错、计划归因及知识范围/基线与签名一致性。

### 10.2 验证证据与限制

- 改动前与抽取后原有 API/链路回归均 22 项通过。临时差分脚本加载本批修改前完整路由，对四种模式与十二类正常/异常场景进行 48 组对照：响应或异常、签名参数、清理 SQL/参数、提交次数及调用顺序一致。替身 provider 与签名器用于隔离编排，不代表生产集成通过。
- 以相同装配信息替换本地临时进程中的旧/新路由，端点 schema 与完整运行时 OpenAPI 的 328 条路径一致；不依赖前批次临时快照是否仍存在，不修改服务运行配置。
- 最终扩大回归（`backend/`）：`.venv/bin/python -m pytest tests/practice/ tests/test_services/test_deduplication.py tests/test_api/test_practice.py tests/test_api/test_practice_chain_regressions.py tests/architecture/test_architecture_boundaries.py tests/test_services/test_practice_service.py tests/test_services/test_sequential_reservation.py -q`；收集 273 项，266 通过、7 项既有 xfail、13 条警告，退出码 0。警告包括 10 条 `datetime.utcfromtimestamp` 弃用提示及 3 条 aiosqlite 线程遇到已关闭事件循环的提示；未逐项复现重构前警告基线，也未扩大修改连接生命周期。
- 严格 Ruff、`compileall`、新增业务模块 AST 行数及 `git diff --check` 通过。一次误用系统 `pytest` 因缺少 `pwdlib` 在收集时失败，改用项目 `.venv/bin/python -m pytest` 后完成上述验证，未为此安装依赖或修改环境。
- Codebase Memory 仍为 2026-10-15 的 best-effort 索引，路由已变化，使用当前源码核查调用边界；未重建索引。管理端/小程序本批未修改、未重跑其测试；未进行 PostgreSQL/Redis、OCR/AI 或微信模拟器/真机验收。
- 未暂存、提交、推送、部署或修改数据库；保留全部既有改动及删除状态。后续推进管理端题库请求/mutation 与小程序持久化/同步职责，同时继续收敛刷题路由；全量盘点与高风险治理仍待实施。

## 十一、第五批执行记录（2026-10-20）

### 11.1 已落地范围

- 管理端题库页新增 `admin-frontend/src/app/(admin)/questions/question-api.ts`，集中列表、详情、版本历史、版本详情、编辑、单题删除、批量删除及导出请求协议。
- 页面继续持有 React Query 的 query key、缓存失效、权限判断、确认框、编辑草稿和导出后的浏览器下载；没有把整页状态搬入万能 hook 或全局 store。
- 批量删除保留后端单次 50 条限制、顺序分块、幂等键按原分块复用、失败项继续执行和 snake/camel 响应字段兼容。
- 版本历史仍先请求第一页，再并行补齐后续页并按页序合并；导出仍使用 120 秒超时；API 路径、方法、请求体和 query key 未改变。
- 页面从 3796 行降至 3700 行；新增 API 模块 137 行，函数最长 45 行，未引入新依赖或状态管理框架。
- 新增 API 协议和边界测试，覆盖参数编码、版本分页、主题树扁平化、编辑/删除、批量删除分块与失败、幂等键、导出、错误透传和禁止原生 fetch。

### 11.2 验证证据与限制

- 管理端 `npm run test`：19 个测试文件、487 项通过。
- 管理端 `npm run typecheck`：通过。
- 管理端全库 lint：0 错误、137 条既有警告；页面诊断与抽取前保持一致，新 API 模块和测试无诊断。
- AST/结构对照确认页面 JSX、React Query 配置、mutation 回调、query 参数和幂等键生命周期保持一致；`git diff --check` 通过。
- Codebase Memory 索引仍为 2026-10-15 的 best-effort 版本；本批按当前源码和测试核查，未重建索引。
- 未执行管理端生产构建、浏览器交互、后端生产服务、微信开发者工具或真机验收；未提交、推送、部署或修改数据库，保留其他既有工作区改动。

### 11.3 后续范围

下一批优先处理小程序番茄钟持久化/同步与页面 controller 边界；管理端题库页仍有大量展示与编辑组合代码，后续只在有明确职责和行为护栏时继续拆分。

## 十二、第六批执行记录（2026-10-20）

### 12.1 已落地范围

- 小程序新增 `pages/pomodoro/utils/session-storage.js`，通过注入的存储对象适配同步读写/移除及异常日志；保留原返回值、日志级别和上下文，不依赖全局 `wx`。
- 新增 `pages/pomodoro/utils/pending-sync-queue.js`，集中旧单槽 `completeAfter` 迁移、非法条目修复、按序入队、相邻/终态去重、nonce 更新/确认及 196/200 容量阀值；保留 `pomodoro_pending_sync` 键、时钟调用顺序、终态预留容量和不截断旧动作规则。
- 队列通过每个 Page 实例的惰性适配器接线，存储为唯一队列事实来源，不缓存队列、不共享可变实例；读取或修复落盘失败返回未知状态，不能把失败当作空队列继续执行。
- Page 保留原方法签名并委托；真实 `api.now()` 和安全存储方法仍由 Page 注入。网络 drain、重试、冲突处理、快照清理、恢复和 UI 保留原归属，本批未整体搬移 controller。
- Page 从 3961 行减至 3866 行，两个新增业务模块分别 30/107 行，各函数不超过 50 行；无新增依赖。静态韧性检查转向抽出的真实函数，运行时沙箱加载真实模块，新增独立行为测试与两项 Page 接线检查。

### 12.2 验证证据与限制

- 修改前 106 项韧性、22 项运行时和 12 项恢复延迟回归通过。修改后 `node scripts/test-pomodoro-resilience.js` 106 项、`node scripts/test-pomodoro-stability-runtime.js` 24 项、`node scripts/test-pomodoro-resume-latency.js` 12 项通过。
- 新增 `node tests/test-pomodoro-pending-sync.js` 通过：覆盖存储适配成功/异常日志、旧数据迁移、无效数据修复失败、保守读取、事件时间戳/nonce、去重、容量与终态预留、更新/确认失败、实例隔离及实时读取。该脚本为独立 Node 回归，未虚构统一小程序 `npm test`。
- 其余小程序回归：`node tests/test-pomodoro-timer-math.js` 20 项、`node scripts/test-pomodoro-free-timer-limit.js` 39 项、`node tests/test-pomodoro-subject-cache.js` 16 项、`node tests/test-pomodoro-timer-shimmer.js`、`node tests/test-render-invariant.js` 43 项、`node tests/render_regression/run.js` 5 fixture / 31 项均通过。
- 临时差分脚本加载本批修改前真实 Page 与当前 Page，在 9 种初始数据及正常/读失败/写失败/移除失败下执行 10 种队列操作，共 360 次对照，返回值、存储内容及调用轨迹一致。使用确定性时钟/随机数及存储替身，不代表微信存储或网络集成通过。
- AST 对照确认其余 142 个 Page 成员源码不变；新增业务模块文件/函数预算、改动 JS 的 `node --check` 和 `git diff --check` 通过。
- 结构检索沿用 2026-10-15 的 best-effort 索引并以当前源码核对；未重建索引。本批未改后端/管理端，未重跑其完整检查；未执行微信开发者工具编译、模拟器/真机、生产存储或网络验收。
- 未暂存、提交、推送、部署或修改数据库，保留其他既有工作区改动和删除状态。

### 12.3 后续范围

继续收敛番茄钟 Page 的恢复/同步 controller、管理端题库 query/mutation 与编辑组合，以及刷题路由请求装配；需先刻画对应生命周期和故障语义。全量业务盘点、跨 Admin 学科依赖与运行时/导入治理仍待实施，不能以本批等价抽取宣称整体重构完成。

## 十三、第七批执行记录（2026-10-20）

### 13.1 已落地范围

- 管理端新增题库就近模块 `admin-frontend/src/app/(admin)/questions/question-content-editing.ts`，承接题干读取、结构化文本/换行投影、旧字段回退、OCR 数学换行整理、题干写回及代码块修改后的重复题干同步。
- 模块仅依赖现有 `math-text` 的编程代码识别规则，不依赖页面、React、Query、网络或存储。保留非题干段落和选项段落的顺序与对象引用；代码块插删优先按对象身份匹配，同长度编辑才回退到原下标。
- 页面从 3700 行减至 3472 行；新增业务模块 222 行，各函数不超过 50 行。最小 PATCH、选项规则、图片 URL 解析、React 状态、缓存与 UI 继续保留原职责，未整体搬迁到大型 hook。
- 新增 20 项行为和边界测试，覆盖旧字段优先级、结构化/编程文本选择、数学换行、空内容、显式空题干、选项隔离、代码块插删/替换、非题干引用及模块依赖/尺寸约束。

### 13.2 验证证据与限制

- 抽取前管理端 `npm run test`：19 个文件、487 项通过；抽取后最终 20 个文件、507 项通过。`npm run typecheck` 通过；全库 `npm run lint` 为 0 错误、137 条警告，页面 5 条诊断忽略行号后与本批前一致，新增模块与测试无 lint 诊断。`git diff --check` 通过。
- 临时差分脚本直接加载本批修改前真实页面函数与新模块，复用真实编程代码检测器；582 组内容读取、题干写回、换行及代码块同步对照通过。AST 对照确认页面剩余 23 个顶层函数（含完整页面组件、JSX 与回调）源码不变；不以该证据代替浏览器交互验收。
- 结构检查使用 2026-10-15 的 best-effort 索引，题库页面标记 `metadata_changed`，已直接读取当前源码核实；未重建索引，也未据索引宣称全量调用覆盖。
- 未修改后端/小程序业务，未重跑其完整检查；未执行管理端生产构建、浏览器、微信开发者工具或真机验收。未暂存、提交、推送、部署或修改数据库，保留其余既有改动和删除状态。

### 13.3 后续范围

管理端题库仍有最小 PATCH、query/mutation 与编辑组合待收敛；小程序恢复/同步 controller、刷题路由装配、全量业务盘点及高风险治理继续按行为护栏逐批实施，整体重构尚未完成。

## 十四、第八批执行记录：中立科目解析（2026-10-20）

### 14.1 已落地范围

- 新增 `backend/app/services/subject_resolution.py`，集中已有的严格科目 ID/code 解析与后代范围查询。保留整数 ID 存在性校验、code 去空白/小写匹配、不回退名称/别名/数字字符串，以及包含停用后代的既有语义。
- 19 个公共、共享和导入消费者迁移至中立模块；`admin_subject_service.py` 不再提供或重导出解析函数，继续负责 Admin 写入、RBAC 相关调用与审计。没有新增数据库模型、迁移、写操作或事务所有者。
- 新模块 59 行，最长函数 35 行；新增 22 项真实 SQLite 查询/事务边界测试，以及 6 项全源码导入扫描、违规注入和模块依赖/尺寸检查。已有调用方测试仅调整 import/patch 位置。
- 前七批已在本地提交 `d02c0c1c`；本批按用户“先提交”要求单独收口，保留无关文档、日志、小程序配置与资源删除状态。

### 14.2 验证证据与限制

- 修改前科目管理、科目 ID 和刷题服务回归为 84 通过、3 失败；失败为发布测试缺少真实题目/不可变版本锁夹具，以及两项删除测试的替身缺少 `get_bind`。
- 扩展回归另发现相似题缓存、推荐调度和推荐实验共 8 项失败；通过在临时目录还原 HEAD 的后端源码并加载相同测试复现，结果为 45 通过、相同 8 失败。它们不作为本批新增缺陷，也未通过跳过、xfail 或修改生产规则掩盖。
- 最终扩展回归覆盖科目解析/管理/ID、刷题服务与 `tests/practice/`、全部 `tests/architecture/`、Admin 科目 API、AI 学习、相似题、全局哈希、推荐指标/实验及导出一致性：439 通过、上述相同 11 失败、11 条警告（48.76 秒），退出码 1；新增解析与边界测试共 28 项通过。警告包括已有 datetime 弃用及 aiosqlite 线程回调遇到关闭事件循环，未扩大修改连接生命周期。
- 本批所有改动 Python 文件的严格 Ruff、全应用 `compileall` 和 `git diff --check` 通过。按 `review-agent` 对完整本批 diff、新模块、调用方及测试进行只读审查：No findings；该结论不表示全库或真实服务集成已通过。
- 未执行 PostgreSQL/Redis、外部 OCR/AI、管理端构建/浏览器及微信工具/真机验收；本批未修改前端，不复用前批检查作为当前全栈通过证明。完整任务仍有发题路由装配、页面 controller、全量盘点与高风险治理待完成。

## 十五、第九批执行记录：发题薄路由（2026-10-20）

### 15.1 已落地范围

- `practice/request_assembly.py` 使用显式请求/准备结果数据结构协调科目、trace、知识点校验/查询及定向题目解析，保留原错误优先级和定向集合覆盖 count 的行为；不引入 dict 参数包或 HTTP 对象。
- `practice/question_issuance.py` 协调既有候选、到期筛选、最终守卫和签名响应；在原位置执行最终 ID 转换及观测。预约清理以同用户/科目/预约 ID 和最终集合为条件；服务不提交/回滚，最终提交仍由路由适配函数拥有。
- `practice/request_observability.py` 集中范围日志、响应诊断与快照，保留日志分类、字段、分布、调用顺序及异常传播。三个模块分别 119/79/64 行，最长函数 42/28/25 行。
- 路由文件 675 → 519 行，GET 发题函数 208 → 48 行；另有 21 行 HTTP/事务适配函数。其他端点参数、鉴权、业务及执行顺序未改；没有新增依赖、数据库结构或前端改动。
- 新增 6 项装配/观测测试、3 项空批次/日志异常/模式回退回归，以及新模块依赖、尺寸和薄路由边界约束；原顺序预约各阶段失败与不可变响应测试继续覆盖实际入口。

### 15.2 验证证据与限制

- 修改前刷题目录与两个 API 测试文件 148 项通过；最终在 `backend/` 执行 `.venv/bin/python -m pytest tests/practice/ tests/test_services/test_deduplication.py tests/test_api/test_practice.py tests/test_api/test_practice_chain_regressions.py tests/architecture/test_architecture_boundaries.py tests/test_services/test_practice_service.py tests/test_services/test_sequential_reservation.py -q`：282 通过、7 项既有 xfail、11 条警告，退出码 0（26.94 秒）。警告含既有 datetime 弃用及 aiosqlite 线程回调遇到关闭事件循环。
- 完整运行时 OpenAPI 与修改前保存的基线完全一致（328 条路径）。临时脚本加载修改前真实路由，在 random、sequential、similar 缺少来源题的回退场景与 10 类失败注入中比较响应/异常、调用轨迹、清理 SQL/参数和提交次数，33 组一致；替身 provider 不代替生产集成验证。
- 全部本批 Python 文件严格 Ruff、全应用 `compileall`、模块文件/函数预算及 `git diff --check` 通过。按 `review-agent` 对完整本批 diff、新模块、相邻服务和测试进行只读审查：No findings。
- 一次从仓库根目录执行的测试在收集时因默认暂存目录父级不存在而失败；改在 `backend/` 使用现有开发配置后完成验证，未安装依赖或更改运行配置。
- 未执行 PostgreSQL/Redis、外部 OCR/AI、管理端构建/浏览器或微信工具/真机验证；未推送、部署或清理资源。全量业务盘点、管理端 hooks/组件、小程序 controller、学习域及运行时/导入治理仍待继续，整体目标尚未完成。

## 十六、第十批执行记录：管理端题库查询边界（2026-10-20）

- 新增 `questions/question-queries.ts`，就近集中列表、详情、版本列表、历史版本的 key 与请求配置；详情观察和悬停预取复用同一请求定义，预取仍为 30 秒 staleTime，页面观察仍用默认新鲜度及 `retry: false`。未将科目加载改成缓存查询。
- 新增 `questions/hooks/use-question-queries.ts`，实际页面通过四个有类型 hooks 消费五组查询；当前题目下的两组版本比较保留独立观察者。空选择及 current/null 版本的禁用条件、同题版本占位数据和列表分页占位数据均保持原语义。
- 页面所有题库缓存失效、详情缓存合并与预取改用集中 key；保留原缓存前缀、失效调用顺序和详情专属字段的合并逻辑。页面 JSX 的 19 个顶层子树与 Git 基线逐字一致；未更改权限、mutation、最小 PATCH、草稿或导出协议。
- 增加 13 项真实 QueryClient/QueryObserver 与 React 服务端 hooks 测试，覆盖缓存共用/重新验证、失效范围、占位数据隔离、禁用条件、provider 参数和错误无自动重试；新增 5 项 AST 边界测试，包含反向依赖、原生 fetch 和鉴权 store 越界的负例，以及文件/函数预算。
- 修改前管理端 507 项测试通过；修改后 `npm run typecheck`、`npm run lint`、`npm run test` 和 `npm run build` 成功，22 个测试文件共 525 项通过。ESLint 退出码 0、有 137 条警告；新增模块另行执行严格 ESLint，页面警告与原版按规则/级别/消息比较。构建成功不等同于浏览器人工交互验收。
- 按 `review-agent` 对完整页面 diff、新模块/测试及相邻 API、缓存写回、失效和预取调用点进行独立只读审查：No findings。未运行真实后台浏览器、后端集成或小程序验收；本批无 Python 改动，不把前批 Ruff 作为本批 TypeScript 检查。
- 整体计划仍未完成：接下来继续题库最小 PATCH 与 mutation 职责、编辑状态/展示组合，再处理审核页和小程序 controller；全量盘点及高风险治理仍按原计划推进。

## 十七、第十一批执行记录：题库最小 PATCH 与 mutation（2026-10-20）

- 新增 `questions/question-edit-patch.ts`，唯一实现可见编辑差异判断：标量、题干、非题干结构、多空选项组、规范化选项与知识点。页面 dirty 判定、手动保存 hook 和即时操作前保存均引用同一纯函数；保留隐藏 OCR 题干、数学换行、旧数据和最小写入语义。
- 新增 `hooks/use-question-update.ts`，集中手动保存的选中题目/详情/空 PATCH 错误顺序、请求和缓存失效。成功 UI 反馈先执行，再依原顺序失效全题库与当前题目；保存失败仍由页面展示原消息，不关闭编辑器。
- 新增 `hooks/use-question-delete.ts`，集中单题/批次请求及每个页面实例自己的 chunk 幂等键 Map；拒绝路径保留键，任何正常返回（包括部分失败结果）的成功回调先清键再通知 UI，最后失效缓存。未修改既有 `deleteQuestionBatch` 捕获分块错误并聚合结果的协议，不把该协议的正常返回误记为 hook 拒绝。
- 页面仍持有权限、选择/抽屉、删除结果消息、编辑生命周期和即时操作前保存；未移植为万能 hook。新增三个业务模块均满足文件 300 行、函数 50 行预算，页面现为 3345 行，仍是待继续治理的大页面。
- 增加 20 项纯 PATCH、11 项真实 React Query mutation 执行测试，并扩展 6 项边界/预算检查；mutation 测试通过 React 服务端渲染取得实际 hook，再调用真实 mutateAsync，API 使用替身。覆盖错误优先级、反馈/失效顺序、失败不失效、单题目标、键复用/成功清理及页面实例隔离；不等同于浏览器渲染或实际 DELETE/PATCH 验收。
- 临时对照脚本从 Git 基线读取原始函数，分别运行新旧规则；10 类内容、5 类选项、13 类编辑和4类题干输入共 2600 组结果逐字一致、输入未变化。页面 19 个 JSX 子树与基线逐字一致。
- 在 `admin-frontend/` 运行 `npm run typecheck`、`npm run lint`、`npm run test` 和 `npm run build` 全部成功，24 个测试文件共 562 项通过。全量 ESLint 为 0 错误/137 警告，页面 5 项既有警告按规则/级别/首行消息与基线相同；新增及扩展模块另以 `eslint --max-warnings 0` 通过。
- 按 `review-agent` 对完整本批 diff、新模块、测试、调用点和即时保存相邻代码进行独立只读审查：No findings。`git diff --check` 通过；本批无 Python 改动，Ruff 不适用于这些 TypeScript 文件。
- 未运行真实后台浏览器/服务器、微信工具/真机和生产集成。完整目标仍未达成：题库编辑与组件、导入审核、小程序 controller、全量盘点及后端学习/运行时治理继续待实施。

## 十八、第十二批执行记录：题库编辑草稿与即时写入（2026-10-20）

- 新增 `questions/question-edit-draft.ts`，聚合进入编辑及保存响应的字段映射；进入编辑深拷贝内容、适配旧字符串及选项形态，保存响应直接采用后端选项，两种语义保持明确。展示用题干规范化不反写持久化内容。
- 新增 `hooks/use-question-immediate-mutations.ts`，持有图片/选项操作前的最小 PATCH 保存、实例级并发 Promise、详情缓存合并和即时操作响应接纳。保留 clean → ID → 表格 → 空代码 → 并发复用 → 详情 → PATCH 的原检查顺序；失败后清除并发引用并允许重试。
- 保存前写回依次合并详情、恢复草稿和 textarea、失效全题库及题目 scope、展示消息；即时写入回调只接纳内容与选项，保留其他本地字段，保留详情 `import_record`，按原 scope → 全题库顺序失效。页面不再直接调用 `updateQuestion`。
- 新业务模块分别为 54/106 行，文件和函数预算检查通过；页面从 3345 行降至 3214 行，仍保留权限、编辑状态与关闭/取消/离页保护、渲染组合，不能视为整页治理完成。
- 新增 11 项草稿转换与 13 项即时写入测试，另增加 4 项依赖/预算检查。使用真实 hook 与 QueryClient、替身 API 覆盖检查优先级、并发合并、失败重试、实例隔离、缓存元数据和保留本地标量编辑；服务端渲染测试不覆盖浏览器重渲染或真实上传。
- 临时对照脚本从 Git 基线提取 `startEditing`，120 组旧/新进入编辑结果一致；另 120 组保存响应转换结果一致，输入均未变化。19 个 JSX 子树逐字不变。
- 管理端 `npm run typecheck`、`npm run lint`、`npm run test`、`npm run build` 成功，26 个测试文件共 590 项通过。ESLint 为 0 错误/137 警告；新增模块及扩展边界测试以 `eslint --max-warnings 0` 通过。
- 后端在 `backend/` 执行 `ruff check app/ --ignore I001,F401,N818` 和 `python3 -m compileall -q app` 成功；本批无 Python 改动，未重复执行后端 pytest。该 Ruff 命令使用既有 CI 豁免参数，不代表全库严格零告警。
- 按 `review-agent` 对完整本批 diff、新模块/测试和图片/快捷选项调用点进行独立只读审查：No findings。未运行真实后台交互、微信工具/真机和生产集成；剩余范围仍按完整计划继续。

## 十九、第十三批执行记录：题库结构化编辑拆分（2026-10-20）

- 新增 `question-segment-editing.ts`，集中段落替换、代码插入位置和代码字段更新规则；继续复用既有题干同步规则，保留普通题干与旧版重复代码题干的不同处理方式。
- 新增 `components/question-code-editor.tsx` 与 `components/question-table-editors.tsx`，承接原页面的代码块与表格编辑组合。页面继续拥有草稿状态和保存门禁；回调按完整段落数组索引替换/删除，保留旧代码 `text` 读取、规范 `code` 写入、可选字段清空及辅助元数据。
- 三个新业务文件分别为 51/154/32 行；题库页面从 3214 行降至 3018 行。本批按“先提交”收口，未继续扩大 controller 或其他业务模块的改造。
- 新增 13 项纯规则测试。首次运行有两项测试误把普通题干当成随段落自动重建；核对原实现后修正预期，并补充旧版重复代码题干的同步/清空用例，未改变生产规则。
- 管理端 `npm run typecheck`、`npm run lint`、`npm run test`、`npm run build` 成功，27 个测试文件共 603 项通过；全量 ESLint 为 0 错误/137 警告，四个新增源码/测试文件的 `eslint --max-warnings 0` 通过。
- 后端 `ruff check app/ --ignore I001,F401,N818` 通过；本批没有 Python 改动，未重复后端 pytest。按 `review-agent` 对页面 diff、新模块、测试及相邻题干规则进行只读审查：No findings。
- 未执行真实浏览器交互、组件事件回归、微信工具/真机或生产集成；本批未新增组件依赖门禁或 DOM 等价自动对照，相关验证仍待补充。全栈完整治理计划尚未完成，其他已有文档、日志、小程序配置和资源删除不纳入本次提交。

## 二十、第十四批执行记录：版本对比展示与组件回归（2026-10-20）

- 新增 `question-version-comparison.ts`，集中六类字段的展示投影及原有字符串/JSON 比较语义。两侧选项仍依据当前题型投影，保留多空题历史别名、空值占位、对象键顺序和数值/字符串比较规则，不增加后端业务判断。
- 新增版本字段、差异区域与比较结果组件，继续复用现有题干、选项、公式、解析和知识点渲染器；难度 badge 在当前题目与历史比较间复用。页面继续拥有历史查询、版本选择/交换、折叠状态及占位数据标签，未把页面状态整体搬到万能 hook。
- 题库页面从 3018 行降至 2800 行；五个新增业务模块为 40/28/85/37/76 行。AST 门禁覆盖本批及前批八个模块，验证单文件 300 行/函数 50 行预算、依赖白名单和直接请求限制；新增 JSX 事件内 fetch 负例，解析器按 TSX 扫描。
- 新增 10 项结构化编辑组件回归，实际展开无 hook 的包装组件并调用事件回调，验证完整段落索引、旧代码文本、可选字段清空、输入不可变及表格适配；表格叶组件使用真实 SSR，事件测试仅验证包装层，不冒充浏览器或叶组件交互验收。
- 新增 23 项版本投影及真实 SSR 渲染测试，覆盖六类字段、普通/多空选项、空数据、初次加载、保留旧快照的刷新展示和差异列。另增加 16 项模块依赖/预算检查。
- 临时对照脚本加载修改前真实 JSX/辅助函数，与新组件使用同一实际渲染器进行 HTML 比较：134 组字段对比、48 组选择/加载状态、9 组代码编辑区域及 9 组表格区域一致；仅归一化 class 空白。该对照不证明浏览器重渲染、焦点或滚动行为。
- 管理端 `npm run typecheck`、`npm run lint`、`npm run test`、`npm run build` 成功；29 个测试文件、652 项通过。全量 ESLint 为 0 错误/137 警告，新增模块/测试与扩展门禁严格 ESLint 通过；追加 JSX 负例后定向门禁 31 项通过。
- 后端 `ruff check app/ --ignore I001,F401,N818` 和全应用 `python3 -m compileall -q app` 通过；本批未修改 Python，未重复后端 pytest。按 `review-agent` 对完整 diff、新模块、测试及查询/标签调用点只读审查：No findings。
- 未运行真实浏览器、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。完整阶段清单仍未完成，后续继续题库编辑生命周期、导入审核、小程序 controller、全量业务盘点及后端高风险治理。

## 二十一、第十五批执行记录：题库编辑生命周期（2026-10-20）

- 新增 `hooks/use-question-editor.ts`，持有页面实例自己的编辑状态、草稿、题干文本、dirty 判定及未保存意图；进入编辑仍调用既有草稿转换，dirty 仍由同一最小 PATCH 规则判断。保存/即时写入和列表选择仍接回这些 setter，不新增全局状态或第二份草稿。
- 进入、取消、确认放弃、关闭抽屉的操作就近聚合；关闭复用清空草稿动作，保留 setter 顺序。取消以 dirty 为条件，关闭以 editing 且 dirty 为条件；非编辑模式即使空草稿被判 dirty，仍直接关闭，未顺手改变旧行为。
- 新增 `question-editor-events.ts`，集中抽屉滚动锁、beforeunload 和 Escape 订阅/清理。保留已阻止事件、展开的下拉 portal、确认框及未保存意图的拦截优先级；清理恢复既有 overflow 并移除同一监听函数。页面继续拥有权限、列表/抽屉选择、确认框展示和布局。
- 两个新增业务模块为 119/45 行，文件/函数预算及依赖门禁通过；页面从 2800 行降至 2703 行，仍有选项编辑等待拆职责，不以行数下降视作整页完成。抽取后为页面四处 callback/effect 显式补齐稳定 setter 依赖，未增加最终 lint 警告。
- 新增 21 项回归：通过真实 React 服务端重渲染验证草稿、dirty、取消/关闭、确认后清空和实例隔离；使用原生 EventTarget 与 DOM 字段替身验证事件分支和监听清理。Node 普通 Event 的 returnValue 为布尔类型，首次定向运行 1 项失败；测试替身明确模拟 BeforeUnloadEvent 的字符串字段后通过，未修改生产规则。
- 临时对照加载修改前真实动作与 effect 源码，160 组操作/异步滚动调用轨迹、160 组事件订阅/拦截/清理轨迹与新实现一致；页面 7 个 JSX 子树逐字不变。该对照及服务端重渲染均不代替浏览器 effect 调度、焦点或真实离页验收。
- 管理端 `npm run typecheck`、`npm run lint`、`npm run test`、`npm run build` 成功；30 个测试文件共 677 项通过。全量 ESLint 为 0 错误/137 条既有警告，新增模块/测试和扩展边界测试的严格 ESLint 通过。
- 后端 `ruff check app/ --ignore I001,F401,N818`、`python3 -m compileall -q app` 通过；无 Python 改动，未重复后端 pytest。按 `review-agent` 对完整本批 diff、新模块、测试和保存/选择/确认框调用点进行只读审查：No findings。
- 未运行真实浏览器、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。其余题库组件、imports/review、小程序 controller、全量盘点与后端高风险治理仍待继续；完整目标尚未完成。未改动或纳入提交已有无关文档、日志、小程序配置与资源删除。

## 二十二、第十六批执行记录：题库选项编辑职责（2026-10-20）

- 新增 `question-option-editing.ts`，聚合普通选项投影、原始 storage key/image 解析、普通文本草稿更新，以及多空题组的字段别名选择和增改/复用规则。仍由页面持有草稿实例；多空变更继续用函数式 setter，普通选项编辑继续用当前渲染快照，保持原有更新时序。
- 新增 `components/question-option-editor.tsx`，拆出多空分组标题/行/操作区与普通选项图片区/快速添加。保留 `blank_option_groups` 优先、旧 `blank_groups` 写回、空组选项创建限制、选项 key 与对象附加字段、图片/批量添加的即时 mutation 协议和现有 class/文案。
- 题库页面从 2703 行降至 2397 行；新增组件 193 行、纯规则模块 98 行。边界测试覆盖模块依赖与 300 行文件/50 行函数预算。
- 新增 4 组规则/渲染回归，覆盖 legacy alias、canonical precedence、组选项新增/复用、原始选项键和图片/扩展字段保留，并用真实 React SSR 检查普通/多空分支内容。定向 feature/boundary 测试 43 项通过；类型检查和 Next build 通过。
- 全量管理端 31 个测试文件、685 项通过；ESLint 0 错误/137 警告（与前批全量基线相同）；后端 Ruff 全应用检查通过。按 `review-agent` 对完整差异、新模块、状态更新与组件调用点进行只读审查：No findings。未运行真实浏览器、微信开发者工具/真机或生产集成。完整目标尚未完成，其他业务域和阶段出口仍待继续；已有无关工作区变更不纳入本批。

## 二十三、第十七批执行记录：导入审核编辑状态转换（2026-10-20）

- 新增 `imports/review/review-edit-state.ts`，集中审核条目的编辑状态类型、题型规范化、多空题分支、题干/选项旧字段优先级与状态初始化；页面继续持有审核草稿及交互状态。
- 审核页面移除对应内联转换逻辑，改为调用纯适配模块。适配器仅依赖 API 类型、题型规范化及既有多空题规则，不依赖页面、网络或浏览器；逐项保留空字符串阻断 `??` 回退、选项对象映射的 `text: null` 历史回退结果及无效多空分组错误。
- 新增 5 项针对性测试覆盖字段优先级、富文本选项、空值兼容、多空答案映射、异常分组、依赖边界和文件/函数预算。首次测试中的一处 stem 断言与旧 `??` 行为不符，已修正为兼容性预期；复核时发现对象映射的空 text 旧回退行为，并补充断言保留。
- `npm run typecheck` 通过；全量 `npm run test` 为 32 个测试文件、690 项通过；定向测试 5 项通过；全量 `npm run lint` 为 0 错误/137 警告，两个新增文件以严格 ESLint 通过；`npm run build` 成功。构建在补充 `text: null` 回归断言之前执行，之后该改动由定向测试、严格 ESLint 和类型检查覆盖。
- 按只读审查方式检查完整页面差异、字段解析实现、边界测试及页面调用点，未发现额外行为偏差。未运行真实后台浏览器/服务器、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批单独本地提交，仅包含任务记录、架构记录和三个导入审核相关文件；不推送，不包含现存用户文档、日志、小程序配置修改和资源删除。完整治理目标仍未完成。

## 二十四、第十八批执行记录：导入审核队列参数投影（2026-10-20）

- 新增 `imports/review/review-query-state.ts`，纯函数负责将当前筛选、页码、URL batch id 和 debounce 后关键词投影为既有 review-queue 请求参数；页面仍持有筛选、分页、debounce、query key 与请求状态。
- 查询参数的 batch id 仍优先采用筛选值，否则回退 URL 参数；保留固定 `page_size: 50`、`subject_id` 数值转换（包括非数字输入产生 `NaN`）、空 risk/answer status 转 `undefined`，未改 query key、参数序列化及请求地址。
- 新增 2 项纯规则回归覆盖 URL batch 回退、显式筛选优先级、空值和既有数值转换；定向导入审核测试 7 项通过，新增模块与测试严格 ESLint 通过。
- 管理端全量 `npm run typecheck`、`npm run test`、`npm run lint`、`npm run build` 均通过；33 个测试文件共 692 项通过；ESLint 0 错误/137 警告，与此前基线一致。首次全量 lint 曾因传入整个 filters 对象新增 1 条依赖警告，调用改为显式传入被使用字段后复验回到基线。
- 未运行真实后台浏览器/服务器、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。导入审核请求/mutation hooks、审核界面其余职责以及完整全栈盘点继续待治理。
- 本批独立本地提交仅包含任务记录、架构记录、审核页面和新增查询参数模块/测试；不推送，不纳入既有文档、日志、小程序配置修改与资源删除。完整治理目标仍未完成。

## 二十五、第十九批执行记录：导入审核科目叶节点解析（2026-10-20）

- 新增 `imports/review/review-subject-state.ts`，将科目候选过滤从页面移至纯函数模块；规则优先级保持为显式 `is_leaf`、`parent_id` 派生、路径祖先推断、无元数据返回全部。
- 页面仍持有科目查询、缓存和 `useMemo` 生命周期，只消费纯转换结果；没有改变请求字段、下拉选择或编辑科目行为。
- 新增 2 项测试覆盖四种 metadata 形态。首次 parent_id 用例误将根节点视为叶节点，核对旧算法后修正预期为无子节点的 id `3`；生产实现未因此改变。
- 管理端全量 typecheck、33 个测试文件/694 项测试、全量 lint 和 Next build 均通过；lint 为 0 错误/137 条既有警告，新增模块和测试严格 ESLint 通过。
- 未运行真实后台浏览器/服务器、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。审核页的 query hooks、mutation、状态域和组件职责继续待治理。
- 本批独立本地提交仅包含任务记录、架构记录、审核页面和科目解析模块/测试；不推送，不纳入既有文档、日志、小程序配置修改与资源删除。完整治理目标仍未完成。

## 二十六、第二十批执行记录：导入审核请求执行边界（2026-10-20）

- 新增 `imports/review/review-action-requests.ts`，集中单题通过/驳回、选中题批量操作、整批幂等请求及低风险批次操作的 endpoint/body/header 组装；页面继续持有 TanStack mutation 生命周期、确认状态、驳回原因、成功提示、缓存失效和抽屉控制。
- 批量逐题请求仍按 6 项分块串行推进，保留每个分块内 `Promise.allSettled`、输入顺序映射部分失败题号及非 Error 拒绝值转字符串；整批审核的幂等键仍在失败/不确定响应时留存，在成功回调时清空。低风险批次仍可回退到 URL batch id，普通整批操作仍只使用筛选中的 batch id。
- 新增 4 项请求边界测试，覆盖单题错误包装、批量并发上限与部分失败顺序、整批路径/幂等键和低风险批次 ID 回退。管理端 `npm run typecheck` 通过；全量 `npm run test` 为 35 个文件、698 项通过；全量 `npm run lint` 为 0 错误/137 警告，与既有基线一致；新增模块/测试严格 ESLint 通过；`npm run build` 成功。
- 未运行后台浏览器人工交互、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成；本批无 Python 改动，不代表本轮目标要求的后端 Ruff 验收已完成。导入审核其余 mutation、编辑规则与展示组件、全量业务域和高风险运行时治理仍待继续。
- 本批仅涉及管理端审核页面、新请求模块/测试以及架构/任务记录；独立本地提交，不推送、不夹带工作区原有文档/日志/小程序配置和资源删除。全栈治理目标仍未完成。

## 二十七、第二十一批执行记录：导入审核 mutation hook（2026-10-20）

- 新增 `imports/review/hooks/use-review-action-mutation.ts`，承接审核请求执行器与 TanStack Query mutation 的接线；实例级幂等键 Map、成功后键清理、批次/题库/审核队列缓存失效及拒绝路径保持在 feature hook 内，页面继续拥有反馈文案、抽屉关闭、确认状态和选中题重置。
- 页面不再直接持有审核 mutation 与幂等键生命周期，仍通过 `apiRequest` 和已有 `review-action-requests.ts` 执行单题、选中题、整批和低风险动作；请求参数、失败重试键、缓存失效顺序和拒绝时不重置行为未改变。
- 新增真实 QueryClient/Mutation 回归 3 项与依赖/预算边界测试 2 项；定向审核测试 9 项通过，全量管理端为 37 个测试文件、703 项通过；`npm run typecheck`、`npm run lint`、`npm run build` 均通过。全量 ESLint 仍为 0 错误/137 条既有警告；新 hook、测试和边界文件以严格 ESLint 通过。
- 按 `review-agent` 对本批完整 diff、调用点、请求执行器、hook 和新增测试做只读审查：No findings。后端 `python3 -m compileall -q app` 与 `ruff check app/ --ignore I001,F401,N818` 通过；未运行后台浏览器人工交互、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批待独立本地提交，不推送、不夹带工作区原有文档、日志、小程序配置与资源删除。导入审核编辑/展示职责、小程序 controller、全量业务盘点及后端学习/运行时/OCR 高风险治理仍待继续。

## 二十八、第二十二批执行记录：导入审核保存请求与 mutation hook（2026-10-20）

- 新增 `imports/review/review-save-request.ts`，集中普通题、多空题保存 payload、选项段落元数据、题干段落编辑写回、视觉/结构化表格阻断和多空答案校验；生产规则继续复用已有 `buildMultiBlankSavePayload`，不改变字段优先级、答案序列化或 PUT 路径。
- 新增 `imports/review/hooks/use-review-update-mutation.ts`，承接保存请求、审核队列/详情缓存失效及 mutation 错误边界；页面继续计算视觉模型、未核验表格和运行时问题，保留编辑草稿、成功提示、详情状态接纳与保存后关闭时序。
- 页面移除保存 payload 与视觉阻断请求实现，仅保留 `visualBlockReasons` 投影和 UI 编排。新增普通/段落/视觉阻断/多空 payload 回归 3 项、真实 QueryClient mutation 回归 2 项及依赖/预算门禁；全量管理端 39 个测试文件、710 项通过，typecheck/build 通过，lint 0 错误/132 警告。
- 后端 `python3 -m compileall -q app` 与 `ruff check app/ --ignore I001,F401,N818` 通过。按 `review-agent` 对本批完整 diff、保存请求、mutation hook、页面调用点和测试做只读审查：No findings。未运行真实后台浏览器、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批待独立本地提交，不推送、不夹带工作区原有文档、日志、小程序配置与资源删除。导入审核补全/答案/图片操作、展示组件、小程序 controller、全量业务盘点及后端学习/运行时/OCR 高风险治理仍待继续。

## 二十九、第二十三批执行记录：导入审核答案 mutation（2026-10-20）

- 新增 `imports/review/hooks/use-review-answer-mutations.ts`，承接快速答案保存与人工确认的 PUT 请求、成功/失败反馈回调及队列/详情缓存失效；页面继续管理提示文案与快速答案草稿清理。
- 保留 `/imports/questions/{id}`、PUT 方法、`{ answer }` 与 `{ answer_status: "manual_verified" }` 请求体，以及成功回调先于队列、详情失效的顺序。失败只调用对应错误反馈，不清理草稿或失效缓存。
- 新增真实 QueryClient mutation 测试覆盖请求体、回调/失效顺序、失败路径及 hook 实例隔离；同步增加 feature 依赖/函数长度边界与架构映射。
- 管理端 `npm run typecheck`、`npm run test`（40 个文件/714 项）、`npm run lint`（0 错误/132 警告）及 `npm run build` 通过；定向 2 个测试文件/8 项通过。对本批改动文件执行 ESLint 为 0 错误，新增 hook 与测试无警告；页面文件报告 18 条原有警告。后端 `python3 -m compileall -q app` 与 `ruff check app/ --ignore I001,F401,N818` 通过，`git diff --check` 通过。
- 对完整差异、两个请求体、成功/失败回调、缓存失效顺序、页面调用点和测试进行只读缺陷审查：No findings。未运行真实后台浏览器人工交互、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立提交仅包含相关管理端页面/hook/测试、架构与任务记录，不推送，不夹带工作区既有文档、日志、小程序配置与资源删除。其余审核补全/图片/批量答案操作、导入审核展示、小程序 controller、全量业务盘点及后端学习/运行时/OCR 高风险治理仍待继续；全栈治理目标未完成。

## 三十、第二十四批执行记录：导入审核 AI 补全 mutation（2026-10-20）

- 新增 `imports/review/hooks/use-review-complete-mutation.ts`，承接单题 AI 补全 POST、失败错误包装、队列缓存失效和详情缓存写回；页面仍负责成功文案、活动抽屉状态与本地详情接纳。
- 保留原请求路径与方法、错误包装、成功文案分支、队列失效、详情缓存优先更新及 `syncedDetailRef`/编辑状态更新顺序。新测试覆盖请求、成功副作用顺序和拒绝路径；依赖边界测试与架构映射同步更新。
- 管理端 `npm run typecheck`、`npm run test`（41 个文件/717 项）、`npm run lint`（0 错误/132 警告）及 `npm run build` 通过；定向 2 个测试文件/8 项通过。严格 ESLint 对新增 hook、测试与边界文件为 0 警告，页面现有 18 条警告与此前该文件基线一致。后端 `python3 -m compileall -q app`、`ruff check app/ --ignore I001,F401,N818` 和 `git diff --check` 通过。
- 按 review-agent 的只读缺陷审查流程核对完整 diff、请求错误包装、回调与缓存写入顺序、页面调用点及 QueryClient 测试：No findings。未运行真实后台浏览器人工交互、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含管理端页面/hook/测试与架构/任务记录；不推送、不夹带工作区既有文档、日志、小程序配置和资源删除。批量答案、图片导入、页面展示职责与全栈其余阶段仍待继续。

## 三十一、第二十五批执行记录：导入审核文本批量答案 mutation

- 新增 `imports/review/hooks/use-review-batch-answer-mutations.ts`，承接文本批量答案预览/应用请求、加载/错误生命周期与审核队列缓存失效；页面继续拥有原始文本草稿、预览/结果状态和展示。图片答案导入仍是独立工作流，本批不合并两个协议。
- 保留预览路径、POST 方法、trim 后的 `raw_text` 与 `allow_partial_prefix: true`；应用继续发送预览 token 与空字符串回退的 operation id。应用成功先接纳结果，再失效 `import-review-queue`；失败保留预览并展示原错误，不触发缓存失效。pending 状态从 mutation 派生，事件处理使用不向 React 事件回调泄漏 rejection 的 `mutate`。
- 新增 4 项真实 QueryClient mutation 回归，覆盖预览请求/生命周期、预览失败、应用请求及结果/失效顺序、应用失败不失效；扩展审核页边界测试，禁止页面重新内联文本批量答案接口。
- 验证：管理端 `npm run check` 通过，含 typecheck、全量 test（42 个文件/722 项）、lint（0 错误/132 警告）和 production build；后端全应用 Ruff 与 compileall 通过；`git diff --cached --check` 通过。新增 hook、测试与边界测试严格 ESLint 检查通过。
- 按 review-agent 只读缺陷审查流程核对完整暂存 diff、请求协议、hook 回调/缓存时序、页面调用点和新增 QueryClient 测试：No findings。该结论不代表真实后台浏览器、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成已验证。
- 本批不改后端 API、图片导入、小程序、数据库或生产配置。独立本地提交，不推送；完整目标仍未完成：全量业务盘点、审核图片/展示职责、小程序 controller、后端学习域/队列/OCR 与阶段 4 长期门禁继续待实施。

## 三十二、第二十六批执行记录：导入审核图片答案 mutation

- 新增 `imports/review/hooks/use-review-image-answer-mutations.ts`，承接图片预览 FormData、preview token 应用请求、加载/错误生命周期及审核队列缓存失效；页面继续持有文件列表、导入模式、预览/结果展示和文件选择/移除状态。
- 保留 `/answers/image/preview` 与 `/answers/image/apply` 路径、POST、重复 `files` 表单字段、`mode` 字段、token/operation id 请求体、错误文案和成功后队列失效顺序；文本批量答案协议保持独立。
- 新增 4 项 QueryClient mutation 回归，覆盖 FormData 内容、预览失败、应用副作用顺序与应用失败；边界测试限制页面内联接口并纳入 hook 的依赖/尺寸预算。
- 管理端 `npm run check` 通过，含 typecheck、全量 test（43 个文件/727 项）、lint（0 错误/132 警告）及 production build；新增 hook、测试和边界测试严格 ESLint 通过。后端全应用 `ruff check app/ --ignore I001,F401,N818` 与 `python3 -m compileall -q app` 通过。
- 按 review-agent 只读缺陷审查流程核对完整差异、multipart 请求、回调/缓存顺序、页面调用点和 QueryClient 测试：No findings。审查未发现阻断本批提交的问题；该结论不代表真实后台浏览器、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成已验证。
- 本批不改 API、数据库、生产配置、小程序和 OCR pipeline。完整目标仍未完成：全量业务盘点、审核展示职责、小程序 controller、后端学习域/队列/OCR 与阶段 4 长期门禁继续待实施。

## 三十三、第二十七批执行记录：文本批量答案结果展示

- 新增 `imports/review/components/batch-answer-results.tsx`，集中预览统计、逐题表格、警告、写入按钮与完成结果展示；内部按统计、行和表格划分组件，所有函数不超过 50 行，文件不超过 300 行。组件只依赖既有 API 类型、图标和 Button，无请求、缓存、页面或可变状态依赖。
- 页面继续拥有预览/结果的显示条件、草稿、mutation、弹窗和关闭状态，使用明确的 `onApply` / `onClose` 回调连接。逐项保留原 class、状态优先级、空答案、题号 `??` 回退、未知状态、警告顺序和按钮禁用条件。
- 新增 4 项回归，验证逐行状态颜色/文案、空字符串和零值题号、转义、空表格/空警告、零值统计、写入禁用和关闭回调；将组件纳入依赖和尺寸边界门禁。临时从 HEAD 提取旧 JSX，与新组件进行 256 组 SSR HTML 对照，输出逐字一致；该证据不代替真实浏览器交互验证。
- 管理端 `npm run check` 通过：typecheck、44 个文件/732 项测试、lint（0 错误/132 条既有警告）和 production build；新组件、测试及边界测试的严格 ESLint 通过。定向 2 个文件/13 项测试通过，后端全应用 Ruff 与 compileall 通过。
- 按 review-agent 的只读缺陷审查流程检查完整差异、原 JSX、组件参数、回调接线、渲染条件与测试：No findings。未运行真实后台浏览器、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含审核展示组件/测试、页面/边界测试及架构/任务记录；不推送，不夹带现存文档、日志、小程序配置与资源删除。图片预览展示、审核编辑区、小程序 controller、全量业务盘点、后端学习域/运行时/OCR 及长期门禁仍未完成，整体目标保持进行中。

## 三十四、第二十八批执行记录：图片答案结果展示

- 新增 `imports/review/components/image-answer-results.tsx`，集中图片预览统计、逐题匹配表格、来源与置信度、警告、确认写入和完成结果；按统计、行、表格与来源信息划分内部组件。文件 191 行，函数均不超过 50 行；仅依赖既有 API 类型、图标与 Button，不持有请求、缓存或可变状态。
- 页面仍拥有文件选择、导入模式、预览/结果显示条件、mutation 和弹窗状态；通过 `onApply` / `onClose` 接线。保留未知匹配状态的“未匹配”回退、题号 `??`、空题干/答案、来源文件筛选、零置信度展示/取整和非 rule 提取方式的历史文案，不合并文本与图片协议。
- 新增 5 项回归覆盖状态颜色/文案、空字符串/零值编号、内容转义、来源筛选/置信度/提取方式、空表格/警告/零值统计、答案或解析单独可写时启用、pending 禁用及结果/关闭回调；组件纳入依赖和尺寸门禁。临时提取 HEAD 的原 JSX 进行 256 组 SSR HTML 对照，输出逐字一致；脚本首次因提取边界缩进匹配不准失败，修正临时脚本后通过，生产实现未受影响。
- 管理端 `npm run check` 通过：typecheck、45 个测试文件/738 项测试、lint（0 错误/132 条既有警告）及 production build；定向 2 个文件/15 项测试与新增模块/测试/边界文件严格 ESLint 通过。后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、原 JSX、来源规则、按钮条件、显示条件、回调调用点及测试：No findings。未运行真实后台浏览器交互、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含审核图片展示组件/测试、页面/边界测试及架构/任务记录；不推送，不夹带既有文档、日志、小程序配置和资源删除。审核编辑区、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 与长期门禁仍待完成，整体目标保持进行中。

## 三十五、第二十九批执行记录：审核答案与解析编辑职责

- 新增 `review-answer-selection.ts`，聚合单选/多选选中判定与切换纯规则；新增 89 行 `components/review-answer-editor.tsx`，仅接收题型、选项 key、答案、解析及两个字段回调。页面保留完整草稿及原渲染快照的 `setEditState({ ...editState, field })` 更新时序，不将编辑状态搬入组件。
- 保留多选逗号/中文逗号/空白分隔、选项 key 大小写敏感、追加时的原顺序和重复项、移除时删除全部匹配项及未知题型的单选回退。多空题不显示快速按钮，继续使用既有 `isMultiBlankChoice`，保留原手动槽位答案输入和提示；不改多空题权威解析、保存或派生逻辑。
- 新增 3 项纯规则回归和 4 项组件回归，覆盖选中/切换、旧字符串兼容、空选项提示、多空分支、真实原生控件回调与两个字段隔离；两个模块加入依赖/尺寸门禁。临时从 HEAD 提取旧 JSX，对 96 组题型/答案/空选项组合同时比较 SSR HTML 与控件回调产生的完整草稿更新，均一致。
- 管理端 `npm run check` 通过：typecheck、47 个测试文件/747 项测试、lint（0 错误/132 条既有警告）及 production build；定向 3 个文件/19 项测试、新增模块/测试/边界文件严格 ESLint、后端全应用 Ruff 与 compileall、Git diff 检查通过。
- 按 review-agent 只读流程检查完整差异、新模块与测试、原选择逻辑、页面草稿回调和多空题调用边界：No findings。未运行真实后台浏览器输入/焦点交互、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含审核答案编辑组件/规则/测试、页面/边界测试及架构/任务记录；不推送，保留现有无关文档、日志、小程序配置和资源删除。题干/选项编辑、详情展示、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 及长期门禁仍待完成，整体目标保持进行中。

## 三十六、第三十批执行记录：审核视觉片段编辑与拖拽职责

- 新增 174 行 `components/review-visual-segment-editor.tsx`，按片段卡片、排序、归属和图片展示划分内部组件；复用既有 `segment-utils` 的不可变排序/移动/删除/归属操作，继续使用完整片段数组的索引与长度，不按可见片段重编号。
- 新增 37 行 `hooks/use-review-segment-drag.ts`，聚合实例级源索引引用、拖拽/悬停状态和原生 DnD 事件；由页面无条件调用以保留原生命周期。保留原 dataTransfer、preventDefault、结束/离开/放置的重置时序及源 ref 语义；未新增全局状态或网络依赖。
- 页面继续持有上传请求、替换索引、文件输入引用及异步函数式写回，组件通过明确回调触发文件选择与片段更新。首次全量 lint 检出将含 ref 的整个 props 传向卡片引起的 refs 规则错误，已将输入 ref/文件事件隔离在编辑器根组件并清理迁移后闲置导入，复验通过；没有禁用规则。原生图片预览的 1 条既有 no-img-element 警告随源码迁移保留，全量警告基线不变。
- 新增 2 项 hook 测试，覆盖 React 服务端重渲染中的拖拽/悬停/重置、源 ref 跨渲染保持及实例隔离；3 项组件测试覆盖隐藏规则、完整数组索引、排序/归属/删除、空图片、上传态和文件/拖拽回调；两个模块纳入依赖/尺寸门禁。临时提取 HEAD 原 JSX，64 组视觉类型/URL/上传/拖拽状态组合的 SSR HTML 和操作回调对照均一致。
- 管理端 `npm run check` 通过：typecheck、49 个测试文件/754 项测试、lint（0 错误/132 条既有警告）及 production build；定向 3 个文件/19 项测试通过。新 hook、两个测试及边界文件严格 ESLint 通过，展示组件 ESLint 为 0 错误/1 条上述既有图片警告；后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、原生拖放处理、可见性/索引规则、上传调用点与引用生命周期、组件及 hook 测试：No findings。SSR 与事件替身不代表真实浏览器拖放、焦点或文件选择已验证；未运行后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含审核视觉组件/hook/测试、页面/边界测试及架构/任务记录；不推送，保留既有无关文档、日志、小程序配置与资源删除。题干表格/普通文本与选项编辑、详情展示、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 及长期门禁仍待完成，整体目标保持进行中。

## 三十七、第三十一批执行记录：审核选项编辑职责

- 新增 `components/review-option-editor.tsx`，按多空题、图片选项和普通文本的既有优先级组合展示；页面继续持有编辑草稿、多空 reducer、图片模式确认与回调。多空题仍复用 `MultiBlankChoiceEditor`，图片题仍复用 `OptionVisualEditor`，未复制其状态或规则。
- 新增 `review-option-editing.ts`，集中普通选项文本更新和选项视觉片段移除；保持选项扩展字段、片段对象引用、原数组索引、移除最后片段时写入 `undefined` 及隐藏 text 片段不展示的行为。
- 新增 2 项纯规则测试、4 项组件/分支测试和依赖/尺寸门禁，覆盖普通选项空态、文本与片段回调、片段索引、有效多空优先、图片模式回退、确认回调及多空多选标记。临时从 HEAD 提取旧 JSX，对 60 组题型/分组数量/图片模式组合比较 SSR HTML 与原生控件回调，均一致。
- 管理端 `npm run check` 通过：typecheck、51 个测试文件/762 项测试、lint（0 错误/132 条既有警告）及 production build；定向测试通过，新规则/测试/边界文件严格 ESLint 通过；选项组件保留 1 条既有原生图片预览警告。后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、分支优先级、普通选项不可变更新、多空/图片子组件接线与页面回调：No findings。SSR/事件替身不代表真实浏览器输入、图片模式交互或多空高级面板已验证；未运行后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含审核选项组件/纯规则/测试、页面/边界测试及架构/任务记录；不推送，保留现有无关文档、日志、小程序配置与资源删除。题干/表格编辑、详情展示、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 与长期门禁仍待完成，整体目标保持进行中。

## 三十八、第三十二批执行记录：审核 JSON 详情展示

- 新增 `components/review-json-view.tsx`，负责四组数据的字段投影、固定顺序、颜色、默认展开的 details 与 JSON 展示；仅依赖 API 类型，页面继续持有详情/编辑模式和当前导入条目。所有分组都是对象，直接复用原生 `JSON.stringify(data, null, 2)`，不复制页面为其他展示保留的通用格式化函数。
- 保留基础信息、解析数据、重复检测、OCR/AI 原始数据的字段及键顺序、undefined 省略、null/空字符串/布尔/零值、内容转义、class 与样式。组件纳入依赖和尺寸门禁，不新增请求、全局状态或业务规则。
- 新增 3 项 SSR 回归验证四组结构/展开、嵌套空值及完整字段边界与原始文本转义。首轮测试误按未转义引号断言，并将嵌套空值误解为标量格式化，核对旧实现后修正预期；类型检查发现夹具缺少必需风险字段，补齐后通过。临时从 HEAD 提取旧 JSX，对 64 组值组合进行 HTML 对照，输出逐字一致。
- 管理端 `npm run check` 通过：typecheck、52 个测试文件/766 项测试、lint（0 错误/132 条既有警告）、production build；新增组件/测试及边界测试严格 ESLint 通过，后端全应用 Ruff、compileall 与 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、旧字段投影、序列化语义、详情模式条件和新增测试：No findings。未运行真实浏览器折叠/模式切换、后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含审核 JSON 组件/测试、页面/边界测试及架构/任务记录，不推送、不夹带现有无关文档/日志/小程序改动及删除。文本详情、题干/表格编辑、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 和长期门禁仍待完成，整体目标保持进行中。

## 三十九、第三十三批执行记录：审核来源证据展示

- 新增 `components/review-source-evidence.tsx`，按原始文本/JSON、OCR 空态、原题快照、原图区域/整页回退划分内部组件，页面仅传入 `raw_data` / `parsed_content`。不持有请求、编辑状态或发布行为；所有函数符合 50 行预算，文件符合 300 行预算。
- 保留原始数据的 `raw_text || ocr_text || text || stem` 真值优先级及前置真值非字符串时整体 JSON 回退，空对象仍展示 JSON；快照仅在 literal true 显示整页徽标/审核用途提示，点击仍执行 `window.open(url, "_blank")`；原区域图优先于整页图，bbox、页码零值和旧字段行为不变。
- 新增 3 项回归验证原始文本选择与转义、非字符串阻断、快照严格布尔值/延迟点击、原图优先级与缺图/bbox；组件纳入依赖和尺寸门禁。临时从 HEAD 提取旧 JSX，63 组原始数据/来源组合的 SSR HTML 对照逐字一致。
- 管理端 `npm run check` 通过：typecheck、53 个文件/770 项测试、lint（0 错误/132 条既有警告）及 production build；定向 2 个文件/21 项测试通过，测试和边界文件严格 ESLint 通过。来源组件 3 条原生图片警告从页面迁移保留，未关闭规则；后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、原展示分支、真值优先级、图片回退、快照事件与页面调用点：No findings。未验证真实浏览器折叠、图片加载/新窗口行为；未运行后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含来源组件/测试、页面/边界测试及架构/任务记录，不推送，保留既有无关文档/日志/小程序配置和资源删除。题干/选项/答案详情、题干表格编辑、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 与长期门禁仍待完成，整体目标保持进行中。

## 四十、第三十四批执行记录：审核题干与选项预览

- 新增 `components/review-question-preview.tsx`，按题干、普通/图片选项及多空选项划分展示组件，复用现有 `QuestionContentRenderer`、`MathFormula`、`MultiBlankChoicePreview` 和 `OptionVisualPreview`；页面保留草稿、视觉模型和运行时问题去重状态。
- 保留内容 fallback、代码文本保持、表格元数据展示、已消费片段 ID 过滤；有效多空分组优先于图片模式，无效/不完整分组仍回退；普通选项继续调用既有显示规范化，原前缀/空白不被修剪。图片错误通过原 callback 上报，不改变状态生命周期或请求。
- 新增 4 项测试覆盖内容渲染器参数、普通选项原值/空态、多空优先级/模型引用、图片模式回退/错误回调；组件纳入依赖/尺寸门禁。首轮普通文本断言误期望移除前缀，核对现有工具后修正测试，生产实现未变。临时提取 HEAD 旧 JSX，48 组题型/分组数量/图片模式的 SSR HTML 对照逐字一致。
- 管理端 `npm run check` 通过：typecheck、54 个测试文件/775 项测试、lint（0 错误/132 条既有警告）和 production build；新增组件/测试与边界文件严格 ESLint、后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程检查完整 diff、渲染参数、旧分支优先级、多空/图片预览接线、运行时问题回调和测试：No findings。未验证真实浏览器资产加载失败、公式布局或多空预览；未运行后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含题干选项预览组件/测试、页面/边界测试及架构/任务记录，不推送、不纳入现有无关文档/日志/小程序配置或删除。答案解析详情、题干表格编辑、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 与长期门禁仍待完成，整体目标保持进行中。

## 四十一、第三十五批执行记录：审核答案与解析预览

- 新增 `components/review-answer-preview.tsx`，承接答案状态、来源、普通/多空答案与解析展示，复用既有公式渲染和多空答案组件；页面继续持有审核数据和编辑草稿。抽出 `review-display-text.ts`，供来源定位和答案来源共同使用原有文本有效性判断，不改变大小写、空白或占位值过滤语义。
- 保留缺失答案与已导入状态例外、状态标签优先级、零置信度和取整、来源标签映射、有效多空分组优先级及空解析展示。新增 6 项回归和 2 项依赖/尺寸门禁；组件与纯规则均满足文件 300 行、函数 50 行预算。
- 首轮测试误期望带空白的 unknown 来源可见，核对原过滤规则后修正预期；类型检查发现测试夹具遗漏必需 AI 标记，改为允许部分输入并在构造时补齐默认值。临时从 HEAD 提取旧 JSX，168 组状态、来源、分组、置信度和解析组合的 SSR HTML 对照逐字一致。
- 管理端 `npm run check` 通过：typecheck、55 个测试文件/783 项测试、lint（0 错误/132 条既有警告）和 production build；新增组件/测试、纯规则和边界测试严格 ESLint 通过。后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整代码差异、旧展示分支、来源定位调用点、多空组件接线和新增测试：No findings。未验证真实浏览器公式布局和多空展开交互；未运行后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含答案解析预览组件/测试、文本规则、页面/边界测试及架构/任务记录，不推送，保留既有无关文档、日志、小程序配置和资源删除。题干表格编辑、全量业务盘点、小程序 controller、后端学习域/运行时/OCR 与长期门禁仍待完成，整体目标保持进行中。

## 四十二、第三十六批执行记录：审核题干与表格编辑

- 新增 `components/review-stem-editor.tsx`，收拢题干输入与表格编辑组合，复用 `StructuredTableEditor` 和既有规范化规则；只接收题干、片段及字段回调，页面继续持有审核草稿、片段状态、视觉编辑和保存生命周期。
- 保留显式 table/table_markdown 门禁：没有显式表格时不展示仅带 markdown 的片段；门禁通过后仍逐项规范化全部片段。保留无效表格的空容器、table_id/索引 key、原片段索引替换及按索引移除，不把过滤后的表格索引用于写回。
- 新增 4 项回归，覆盖文本原值/转义、空态与无效表格、旧表格/大小写/markdown 回退、混合片段精确写回、重复片段按位置移除和输入不变性；组件纳入依赖与尺寸门禁，文件/函数符合 300/50 行预算。52 组 HEAD 旧 JSX 与新组件 SSR HTML 对照逐字一致。
- 管理端 `npm run check` 通过：typecheck、56 个测试文件/788 项测试、lint（0 错误/132 条既有警告）及 production build；新增组件/测试与边界测试严格 ESLint 通过。后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、原表格门禁/规范化、原始索引回调、页面草稿接线和新增测试：No findings。未验证真实浏览器表格输入/合并单元格交互，未运行后端集成、微信开发者工具/真机、PostgreSQL/Redis 或生产集成。
- 本批独立本地提交，仅含题干编辑组件/测试、页面/边界测试及架构/任务记录；不推送，保留既有无关改动与资源删除。后续继续全量业务盘点、审核页状态/组件组合、小程序 controller、后端学习域/运行时/OCR 和长期门禁；整体目标保持进行中。

## 四十三、第三十七批执行记录：全栈结构盘点与后端依赖门禁

- 新增 `docs/architecture/REFACTOR_INVENTORY.md`：直接解析当前 523 个后端 Python 模块及 2,095 条模块导入边；读取 26 个 Public、24 个 Admin 路由注册与内部 OCR 路由，枚举 32 个管理端页面和 app.json 中 25 个小程序页面，按七个业务域记录入口、实现、消费者、回归入口、热点及待处理边界。结构枚举不代替逐用例语义审查，阶段 0 保持未完成。
- Codebase Memory CLI 确认索引仍为 2026-10-15 且 scope 有缺口/截断，本批结构结论均来自当前源码；未依据图索引缺失判断死代码。记录旧静态循环的具体导入语句和迁移前需补的验证条件，不将局部或类型导入形成的静态循环误报为启动失败。
- 新增纯 AST 扫描器 `tests/architecture/dependency_scan.py` 和测试 `test_dependency_direction.py`：覆盖相对/函数内/TYPE_CHECKING 导入、动态导入别名与字面量相对 package、源码语法错误及缺失/空扫描目录；不执行应用或建立连接。service/feature 静态导入 API 为零，不设例外。
- 新循环门禁计算强连通分量内部全部边，`import_cycle_baseline.json` 逐边登记 8 组/124 条既有循环边及原因；不以模块组白名单放行新边，新增循环模块/边均失败，已解除边必须从基线移除。现有循环尚未修复；不扩大本批至模型注册、队列/OCR 或导出状态机行为变更。
- 新增 20 项测试验证真实应用与注入反例，完整架构目录 109 项全部通过；新增 Python 严格 Ruff、全应用 `ruff check app/ --ignore I001,F401,N818`、compileall 与 Git diff 检查通过。CI YAML 解析通过，新增测试接入已有静态架构回归步骤；未另造测试入口或更改生产服务。
- 按 review-agent 只读流程核对扫描覆盖/模块解析、强连通算法、基线边与实际源码、反例测试、CI 接线和文档证据：No findings。未运行 GitHub CI、PostgreSQL/Redis、OCR/AI、真实后台浏览器或微信编译/模拟器/真机；静态门禁不证明运行时资源或业务正确性。
- 本批本地提交仅含后端架构工具/测试/基线、CI 接线及架构/任务文档，不推送、不改应用协议/数据库/配置，保留既有无关改动和资源删除。下一步仍需完成全量用例审查、页面/controller 收敛、后端学习域/运行时/OCR 与其余长期门禁，整体目标继续进行。

## 四十四、第三十八批执行记录：解除向量配置与执行服务循环

- 新增 `services/embedding_endpoints.py`，原样迁移 `build_embeddings_url`；单条/批量向量请求和管理端连通测试直接引用同一纯规则，`vector_config_service` 不再导入 `embedding_service`。不新增转发函数，不改配置来源、凭据存储、SSRF、HTTP 请求、维度校验、错误或批量回退语义。
- 先在旧实现运行 26 项 URL/调用方刻画及 5 项现有加密测试，31 项通过；再迁移实现与测试导入。覆盖裸地址、兼容路径、已有端点、大小写/空白、指定供应商域名、非匹配域、query/fragment 旧行为及无效 URL 异常；3 组异步调用方回归核对单条/批量与管理端探测的 URL、输入、排序、验证器与请求参数。未发出真实外部请求。
- 302 组旧函数与新函数返回值/异常对照一致。新增架构检查限定纯规则仅依赖 urllib.parse、文件/函数不超过 300/50 行，两个真实服务消费者均接入且纯规则无循环依赖。
- 移除基线前，门禁实际失败并准确指出已解除的 embedding/config 两条循环边；仅删除该组基线后通过，其余组未扩增。当前全应用 524 个模块、2,096 条静态模块导入边，反向 API 导入为零，既有静态循环从 8 组/124 条边降至 7 组/122 条边。
- 扩大回归 `tests/architecture/`、端点/加密、模型能力分离 API、模型配置解析与快照测试：168 项通过。所有修改/新增 Python 严格 Ruff、全应用 Ruff、compileall 和 Git diff 检查通过；管理端/小程序本批无修改，未重复运行其测试。
- 按 review-agent 只读流程核对完整差异、纯函数迁移、所有调用点、请求替身与架构回归、基线精确缩减和配置边界；更新原已过时的循环导入注释后复核：No findings。未运行真实向量供应商、数据库/Redis 集成、GitHub CI、浏览器或微信环境；不能据本批推断其余循环与高风险业务已治理。
- 本批独立本地提交，仅含向量端点/服务、测试/基线与架构/任务文档，不推送、不修改生产或数据库，保留全部既有无关改动及资源删除。全量用例审查、管理端页面/小程序 controller、学习域、运行时/队列/OCR 和其余长期门禁仍需继续，整体目标未完成。

## 四十五、第三十九批执行记录：解除导出服务与处理器循环

- 新增 `services/export/state_machine.py`，原样迁移转换表和 `validate_transition`；业务服务与处理器均直接依赖该规则，不再由 service 局部导入 processor。状态枚举继续复用既有 schema，任务领取、事务、并发、超时、快照和重导出失败恢复均未更改。
- 新增 55 项状态规则刻画（全部枚举/字符串转换、未知状态/目标、默认及异常 task id），在旧实现上先运行；既有 phase3 的状态测试随后迁移至规则模块。新增架构门禁验证规则不依赖 service/processor、真实调用方接入、尺寸符合 300/50 行预算。
- 旧版定向基线为 148 通过、12 失败，另有并发/安全综合基线 43 项通过。12 项失败均为 `TestDocxAcceptance` 读取缺失的硬编码本机 `artifacts/libreoffice/phase3_acceptance.docx`；不跳过、不 xfail、不生成伪造产物掩盖基线问题。
- 迁移后完整架构、状态规则、phase3、一致性、超时和综合回归：302 通过、相同 12 项 DOCX 产物失败。逐项比较失败集合与重构前一致；900 组旧转换表/函数与新实现的返回值及异常对照一致。所有修改/新增 Python 严格 Ruff、全应用 Ruff、compileall 和 Git diff 检查通过。
- 精确移除 export service/processor 两条旧循环边，其他基线组不扩增。当前全应用 525 个模块、2,098 条静态导入边，service/feature → API 为零，循环降至 6 组/120 条边。
- 按 review-agent 只读流程检查完整差异、所有规则调用点、状态及恢复边界、反例测试和失败基线：No findings。DOCX 产物验收未通过；未运行生产 PostgreSQL/Redis、LibreOffice/真实下载、GitHub CI、浏览器和微信环境。本批不将导出完整链路或高风险运行时标为完成。
- 本批独立本地提交，仅含导出状态规则/消费者、测试/循环基线和架构/任务文档，保留全部既有无关改动与资源删除，不推送。后续先修复本机产物依赖以恢复可重复的导出验收，再继续全量用例、页面/controller、学习域/队列/OCR 与长期门禁；整体目标仍未完成。
