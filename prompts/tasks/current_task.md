# 全栈高内聚、低耦合重构实施计划

> 编制日期：2026-10-19；更新日期：2026-10-20。状态：前七十批已提交，第七十一批分离后台任务取消与等待；阶段 0/1/3/4 部分完成，完整治理尚未完成。
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
  - 第六十批分离公开 HTTP 错误契约和处理器，第六十二批分离安全头/CORS/Host/追踪日志中间件；main 继续持有生命周期和健康/指标，完整角色验收未完成。
- [ ] 按生产者、状态迁移、存储操作、重试与消费者职责拆分任务队列；保留现有任务版本、锁、租约、去重、ack、重试及死信行为，不合并不同协议的语义。
- [ ] 使用既有 OCR pipeline stages 拆编排器；先确定阶段输入/输出与上下文所有权，再迁移实现。保留恢复检查点、失败传播、人工审核和 OCR/AI 配置边界。
- [ ] 对 service/feature 中的公式、导出、存储、AI 等剩余热点按已盘点问题治理；不重做已经稳定的基础设施，也不因当前代码少被调用就删掉运行入口。
- [ ] 高风险批次必须通过对应数据库/队列/故障注入测试后才标记完成；外部服务不可用时如实记为未验证，不以 mock 单测替代集成验收。

阶段出口：角色生命周期、任务与导入状态机回归等价；没有新增第二套队列、OCR 或网关；人工审核及安全门禁保持有效。

### 阶段 4：长期门禁、收尾与交接

- [x] 后端增加 AST 依赖规则和新循环依赖检查；禁止业务层反向依赖 API、越界访问私有 OCR/AI 实现，并对错误示例验证检查确实会失败。
  - 第三十七批全应用静态扫描确认 service/feature → API 为零；新门禁逐边限制循环，初始登记 8 组/124 条既有静态循环边；第三十八批解除 embedding/config、第三十九批解除 export service/processor、第四十九批解除 AI service/prewarm worker、第五十批解除 DOCX/OMML、第五十一批分离 ORM Base、第五十三批解除 OCR 包/适配器循环，第五十五/五十六批迁移题目 AI 与 writer 转发、第五十七批拆分公式批次、第五十八批分离上传入队后静态循环清零。新增边/模块不能通过，已解决边必须缩减基线。既有 OCR/AI 私有边界与注入反例测试继续通过；运行时循环和高风险迁移仍待专项验证。
- [ ] 管理端在现有 ESLint/测试体系中限制已治理 feature 越界和绕过请求 client；小程序用独立 Node 检查模块引用、分包边界与需要保持的双份代码一致性。
  - 第四十八批为番茄钟 9 个已治理模块增加 AST 导入/全局能力门禁，含原生页面接线与反例测试，接入可靠性 CI；其他模块、全仓分包及双份代码一致性仍待覆盖，该项未完成。
- [ ] 对现有超标记录有路径和原因的基线：未治理文件不得继续增长，新增/拆出业务文件遵守单文件不超过 300 行、函数不超过 50 行；非业务生成资源排除，已治理目标清零而非反复扩大白名单。
  - 第四十八批门禁约束上述 9 模块全部嵌套函数的 300/50 行预算，真实 Page 已治理方法保持 50 行，并登记剩余番茄钟页面 3,631 行上限；其他客户端/后端的全仓超标基线尚未完成。
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
| 3：运行时与导入 | 部分完成 | HTTP 错误策略与处理器已分离；上传 admission、公式批次及若干依赖边界已治理，完整角色、队列、OCR 集成/故障验证仍待完成 |
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

## 四十六、第四十批执行记录：恢复可重复的 DOCX 结构验收

- 新增 `tests/export/docx_acceptance_fixture.py`，用两道合成题调用真实 `DocxExporter.export`，在 pytest 临时目录生成样本；分别覆盖文本/富文本/表格片段与普通题干 LaTeX，不依赖机器路径、外部图片、真实用户数据、Word/LibreOffice 或预先生成的文档。不提交二进制产物。
- 旧 phase3 的 12 项 DOCX 验收改用模块级样本 fixture；生成时检查 ZIP CRC、所有 XML/rels 可解析及 python-docx 重开。保留表格、合并单元格、公式节点、中文、化学字符与文件大小验收，HTML 泄漏改用解析后的文本判断，矩阵由原始字符串匹配改为原生 m:m 节点及元素值序列。
- 旧 NUMPAGES 断言针对过时样本；核对当前 `_setup_header_footer` 与现有 DOCX 页脚测试后，改为严格验证首页/后续页两个页脚都仅有 PAGE 字段，未改变生产布局。首版样本将片段和 LaTeX 混写而未走公式路径，后按当前真实入口分别覆盖；进一步检查发现现有矩阵未保留行列包装，该格式问题单独记录，不夹带渲染行为修改。
- 按 docx 技能的验证流程，额外对合成文档运行严格 OOXML 校验，结果失败：header/document 属性元素顺序与 settings zoom 属性存在既有问题。当前应用源码未变，未修补生成后的字节以制造通过；矩阵包装和片段 LaTeX 行为也已记录于盘点文档。结构/内容测试通过不代表完整格式合规或真实 Word 渲染通过。
- 完整架构及导出 phase3、状态机、一致性、超时、综合回归共 314 项通过，恢复上一批缺失产物导致的 12 项失败；新/改 Python 严格 Ruff、全应用 Ruff、compileall 和 Git diff 检查通过。没有对原失败用例新增 skip/xfail。
- 按 review-agent 只读流程检查完整差异、真实生成链路、fixture 作用域和目录隔离、当前页脚契约、XML 内容断言及已知格式限制：No findings。本批未运行生产数据库/Redis、真实下载、Word/LibreOffice、GitHub CI、后台浏览器或微信环境；未把已知格式问题或完整导出域标记为完成。
- 本批独立本地提交仅含测试夹具/验收与架构/任务文档，不修改应用代码、数据库或生产设置，不推送，保留既有无关改动和资源删除。全量语义审查、页面/controller、学习域/运行时/队列/OCR 与剩余门禁继续待实施，整体目标保持进行中。

## 四十七、第四十一批阶段提交：独立同步重试控制器

- 按用户“先提交”要求，将 `miniprogram/pages/pomodoro/utils/sync-retry-controller.js` 及独立 Node 测试作为阶段性成果本地提交。控制器通过显式回调接收定时器、网络监听、队列重试和冲突处理能力，每个实例独立保存重试次数、定时器和监听回调。
- 保留原页面的错误分类、2/5/15/30/60 秒退避及封顶、重复定时器抑制、清理与重置区别，以及重连后先处理终态冲突再刷新统计的顺序。控制器没有直接访问 wx、Page、存储或 API。
- 本次尚未接入 `pomodoro.js`，不移除页面原实现，不迁移队列 drain/single-flight，也不将番茄钟页面重构标为完成。后续需接入生命周期 facade、调整原源码断言并补充真实页面接线回归。
- 独立控制器 9 项测试通过；原番茄钟 resilience 106 项、stability-runtime 24 项通过。覆盖错误分类、退避、重复调度、清理/重置、可见性与队列门禁、重连冲突顺序、异步返回可见性、失败日志、监听身份及实例隔离。尚未验证微信开发者工具/真机及页面接入后的行为。
- 本次仅提交控制器、独立测试和本记录；保留全部既有无关修改与资源删除，不推送，不操作生产。整体治理目标仍未完成。

## 四十八、第四十二批执行记录：同步重试控制器接入页面

- `pomodoro.js` 以每页独立、惰性初始化的 controller 管理网络监听与延迟重试，移除页面的监听回调、重试定时器、重试次数和退避常量。页面通过显式闭包提供当前可见性、待同步队列、原 drain、终态冲突和统计刷新能力；保留原生命周期 facade 名称及所有调用点。
- 隐藏时清理定时器但保留退避，卸载时重置退避并注销同一监听回调；无控制器时清理/注销不创建实例。注册仍要求 on/off 两种 wx API 同时可用，注销仍容忍 API 消失或抛错；原队列持久化、单次并发 drain 和冲突处理实现不变。
- 原源码检查仅保留页面接线和生命周期契约，移出的实现由真实控制器测试及 Page VM 运行测试验证，不拼接源码伪装旧实现。运行测试从 24 增至 29 项，覆盖实例隔离、动态页面依赖、重连冲突顺序、隐藏/卸载、API 能力变化；额外验证连续重连在真实队列 drain 中只发一次 POST。
- 验证通过：控制器 9 项、页面运行 29 项、resilience 106 项、timer-math 20 项、subject-cache 16 项、resume-latency 12 项、free-timer-limit 39 项、render-invariant 43 项、渲染 fixture 31 项，以及 pending-sync/storage 脚本。修改 JS 语法检查、后端全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程检查完整差异、控制器回调、所有清理/注册/调度调用方、队列 drain 和相关测试：No findings。未验证微信开发者工具、模拟器/真机或真实网络切换；本次不涉及后端行为与管理端构建。
- 页面由 3,866 行降至 3,830 行，但 `onShow` 恢复与视图编排仍待治理，不据行数变化或控制器局部接入标记全页面完成。本批独立本地提交仅含页面、两份回归脚本和架构/任务记录；保留既有无关修改与资源删除，不推送。整体目标继续进行。

## 四十九、第四十三批执行记录：活动会话恢复编排

- 抽取 `pages/pomodoro/utils/active-session-recovery.js`，以本地恢复、待同步动作处理、服务端状态应用三个职责函数组合恢复入口。模块不导入 Page/wx/API，不持有页面实例，页面仅提供显式能力回调及本次 `activeSyncSeq` 对应的有效性判断。
- 保留缓存先于网络恢复首帧、休息先于待同步 drain、离线保留乐观状态、冲突优先、存储失败停止、终态队列阻止复活、跨设备活动替换休息和服务端空响应清理旧缓存的顺序；所有轻量同步仍传入持久化参数 true，统计仍延迟 200ms。完成庆祝、结束确认与未知 start 前置处理未改变。
- 新增 10 项独立恢复测试，并将 Page VM 运行测试从 29 增至 33 项：完整 `onShow` 验证缓存首帧/异步请求顺序、onHide 后响应不写回，另覆盖旧 show 代次及 server-null 清理。移出的源码细节断言改为页面接线检查，实际顺序由独立模块和真实页面运行测试验证。
- 用 Git HEAD 原 `onShow` 尾部与新模块做 6,144 组旧/新调用轨迹及最终页面状态对照，覆盖缓存/服务端空值和存储错误、运行/休息、轻量同步、恢复失败、待同步成功/失败、冲突、终态动作和代次有效性；全部一致。该对照不代表微信真实运行环境验证。
- 验证通过：恢复模块 10 项、重试控制器 9 项、页面运行 33 项、resilience 106 项、resume-latency 12 项、free-timer-limit 39 项、timer-math 20 项、subject-cache 16 项、render-invariant 43 项、渲染 fixture 31 项，以及 pending-sync/storage 与倒计时样式脚本。全部修改 JS 语法检查、全应用 Ruff、compileall 与 Git diff 检查通过。
- 按 review-agent 只读流程检查完整差异、能力回调、旧/新分支、异步有效性判断及所有受影响测试：No findings。页面当前 3,782 行，`onShow` 210 行，庆祝/确认与剩余恢复视图编排仍待拆分；未将整页或学习域治理标为完成。
- 本批仅本地提交恢复模块/测试、页面接线、三份回归脚本及架构/任务文档。未运行微信开发者工具/模拟器/真机、真实网络或生产操作；不推送，保留既有无关改动和资源删除，整体目标继续进行。

## 五十、第四十四批执行记录：完成庆祝恢复数据转换

- 将完成标记到庆祝视图的数据转换抽取为 `pages/pomodoro/utils/completion-recovery.js` 的纯函数：科目与名称回退、408 聚合标记、预设/时长、任务类型及其标签、休息秒数和庆祝显示字段。显式接收当前视图与现有任务类型能力，不导入 Page/wx/API/存储。
- 页面继续负责读取和校验完成标记、首次振动、视图写入、待同步动作重试和延迟统计刷新。保持有效标记直至用户关闭庆祝才清理，保留字段不存在与显式无效任务类型的区别、旧数值转换/回退及休息秒数非负规则，不改变业务契约。
- 新增 6 项纯转换测试，覆盖旧标记回退、完整聚合快照、显式/继承任务类型、数值边界、科目引用与输入不变性；Page VM 从 33 增至 35 项，验证两次 onShow 保留同一完成标记且仅振动一次、跳过服务端复活，以及庆祝仍同步待处理动作并优先处理终态冲突。
- 使用 Git HEAD 原页面转换段与新纯函数做 1,920 组结果逐项对照，涵盖数值/任务类型/科目/聚合/显示状态组合，全部一致。修复原静态断言使用已经不存在的 wx 直接读取 token 导致空区间检查的问题；新断言定位真实 completionStored 分支，实际行为由 Page VM 验证。
- 验证通过：新增纯函数 6 项、活动恢复 10 项、重试 9 项、页面运行 35 项、resilience 106 项、恢复延迟 12 项、自由计时上限 39 项、timer-math 20 项、subject-cache 16 项、render-invariant 43 项、渲染 fixture 31 项及 pending-sync/storage、倒计时样式脚本。全部修改 JS 语法检查、全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、字段默认/引用与旧转换、页面副作用顺序、完成标记生命周期和相关测试：No findings。页面当前 3,753 行、onShow 180 行，结束确认与剩余恢复编排仍待治理；未运行微信开发者工具/模拟器/真机，未将全页面治理标为完成。
- 本批仅本地提交纯转换模块/测试、页面与两份回归脚本及架构/任务记录，不推送、不操作生产；保留既有无关改动和资源删除，整体目标继续进行。

## 五十一、第四十五批执行记录：结束确认快照恢复

- 新增 `pages/pomodoro/utils/confirm-recovery.js`：纯转换负责自由计时/倒计时的 timer/view 补丁，恢复入口组合确认序号、快照引用、视图、倒计时画布、后台暂停补偿及延迟统计；仅依赖已有 timer-math，通过显式回调接收页面能力。
- 合并原两种模式重复的暂停回执逻辑；仍只在 pausedByConfirm 且 backendPauseDone 未完成时请求，成功后要求快照 confirmActionSeq 等于页面当前序号且确认弹层仍显示，才更新原快照与持久化。失败继续保留恢复状态，不阻断首帧或统计，不新增请求或改变队列协议。
- 页面仍负责快照存储失败停止、有效性校验、失效快照清理和从统计页返回的导航保护。保留原 sessionStartTime 回退、暂停累计、自由计时偏移归零、倒计时 remaining/progress 与 break 阶段、nextTick 画布顺序；没有重写确认取消/提交业务。
- 新增 7 项模块测试；Page VM 从 35 增至 39 项，验证完整 onShow 的两种确认模式、后台暂停确认持久化、旧确认回执抑制、存储读取失败与失效快照清理。864 组 Git HEAD 原分支与新实现的 timer/view/快照/序号及回调轨迹对照通过，包含暂停失败、序号变化和关闭弹层。
- 验证通过：确认模块 7 项、庆祝转换 6 项、活动恢复 10 项、重试 9 项、页面运行 39 项、resilience 106 项、恢复延迟 12 项、自由计时上限 39 项、timer-math 20 项、subject-cache 16 项、render-invariant 43 项、渲染 fixture 31 项及 pending-sync/storage、倒计时样式脚本。修改 JS 语法检查、全应用 Ruff、compileall 和 Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、确认恢复副作用顺序、暂停回执版本保护、持久化与全部相关测试：No findings。页面现为 3,714 行，onShow 116 行，剩余生命周期编排、确认操作和页面其他业务仍待治理；微信开发者工具/模拟器/真机尚未验证，不据模块抽取标记整页完成。
- 本批仅本地提交确认恢复模块/测试、页面与运行回归脚本、架构/任务记录，不推送、不操作生产；保留全部既有无关修改和资源删除，整体目标继续进行。

## 五十二、第四十六批执行记录：onShow 恢复入口收敛

- 新增 `pages/pomodoro/utils/show-recovery.js`，以未知启动请求、终态冲突、完成标记、确认快照和活动会话的优先级组合恢复流程；完成与确认分支各自独立。仅显式调用最小页面能力，不依赖 Page/wx/API/存储实现，不把完整页面搬入新模块。
- `onShow` 收敛为 18 行，保留可见性/请求代次、主题、待处理动作快照读取及首帧显示，再调用恢复入口。页面以 `_showRecoveryOptions` 提供动态能力，庆祝视图与确认清理分别成为短适配函数；调用原活动会话、确认和庆祝模块，不创建第二套恢复状态。
- 保留待同步存储失败先于未知启动、未知启动响应过期停止、终态冲突先于庆祝、有效完成标记保留/同步重试、确认内存优先、存储读取失败停止、统计页返回清理及无 sessionId 确认的旧回退语义。统计延迟、队列 drain 和错误传播不变。
- 新增 11 项恢复入口测试，Page VM 从 39 增至 42 项，补充未知启动各结果短路、隐藏后的启动响应和统计页返回清理/当前代次传递。Git HEAD 完整旧 onShow 与新入口做 12,288 组调用轨迹/页面与计时状态/确认引用/导航/代次对照，全部一致。
- 验证通过：入口 11 项、确认 7 项、庆祝转换 6 项、活动恢复 10 项、重试 9 项、页面运行 42 项、resilience 106 项、恢复延迟 12 项、自由计时上限 39 项、timer-math 20 项、subject-cache 16 项、render-invariant 43 项、渲染 fixture 31 项及 pending-sync/storage、倒计时样式脚本；所有修改 JS 语法检查、全应用 Ruff、compileall、Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、恢复优先顺序、页面能力闭包、代次保护、原存储上下文/副作用及测试：No findings。当前页面 3,654 行，onShow 恢复编排已分解，但 onHide、确认操作、计时/画布和其他页面职责仍待治理，整个小程序样板项保持未完成；微信开发者工具/模拟器/真机仍未验证。
- 本批仅本地提交入口/测试、页面接线、三份回归脚本及架构/任务记录，不推送、不操作生产，保留既有无关改动和资源删除；后续继续剩余样板、全栈业务域与长期门禁，整体目标继续进行。

## 五十三、第四十七批执行记录：离页快照持久化

- 新增 `pages/pomodoro/utils/hide-storage.js`，集中未知启动取消意图、确认快照持久化和运行快照构建；显式接收存储、当前视图/计时状态/确认引用及可校准时钟，不直接依赖 wx、Page、API 或全局时钟。
- `onHide` 保留可见性/请求代次失效、重试清理、画布失效、仪式取消和最终计时器清理。保持未知启动取消先于画布失效、确认保存先于 completion 读取、运行快照保存先于计时器清理的顺序；完成标记读取失败、存在完成标记/庆祝、非运行阶段和缺少 sessionId 不覆盖运行快照。
- 运行快照保留科目/408 分配/任务类型、自由计时与暂停字段、偏移归零及原时钟调用语义：缺少 pauseStartTime 时单独取值，savedAt 再取一次；不以一次缓存时钟改变原逻辑。未知启动取消复制原标记，保持原幂等 key/payload，不修改旧对象。
- 新增 8 项模块测试；Page VM 从 42 增至 46 项，覆盖完整离页存储/清理顺序、完成读取失败、确认写入失败后独立保存运行快照及仪式取消。13,824 组旧/新完整 onHide 的存储/时钟/视图/清理轨迹和最终状态对照通过。
- 验证通过：离页模块 8 项、展示入口 11 项、确认 7 项、庆祝转换 6 项、活动恢复 10 项、重试 9 项、页面运行 46 项、resilience 106 项、恢复延迟 12 项、自由计时上限 39 项、timer-math 20 项、subject-cache 16 项、render-invariant 43 项、渲染 fixture 31 项及 pending-sync/storage、倒计时样式脚本。全部修改 JS 语法检查、全应用 Ruff、compileall、Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、离页副作用次序、存储键/上下文、暂停时间回退、失败停止/继续规则和相关测试：No findings。页面当前 3,631 行，onHide 30 行；确认操作、计时/画布、统计与其他页面职责仍待治理，微信开发者工具/模拟器/真机尚未验证，完整样板项仍未完成。
- 本批仅本地提交离页模块/测试、页面与两份回归脚本及架构/任务记录，不推送、不操作生产；保留既有无关修改和资源删除。全栈后续业务盘点、治理和长期门禁继续进行。

## 五十四、第四十八批执行记录：番茄钟模块门禁与 CI

- 新增独立 Node AST 检查 `miniprogram/scripts/architecture/pomodoro-boundaries.js`，复用管理端已声明的 TypeScript 开发解析器，不向小程序运行时添加依赖，不执行应用代码。固定覆盖 9 个已治理模块及真实 Page 上的生命周期/能力适配方法。
- 模块许可依赖仅为 confirm-recovery → timer-math，禁止反向页面/API/存储/第三方/分包导入、require 别名/计算参数及动态/ES 导入；限制隐式 this 和 wx/Page/时钟/网络等全局能力，允许显式注入的 options 回调。语法错误、空/仅注释源、缺失文件/方法/消费者不能静默减少扫描。
- 所有覆盖模块 <=300 行，全部嵌套函数/箭头/方法/访问器 <=50 行；Page 中已治理方法 <=50 行。为剩余未治理番茄钟页面登记当前 3,631 行上限及原因，后续抽取应缩减上限，不把页面现存体积视为治理完成。
- 新增 13 项反例/扫描测试，覆盖非法边、动态与别名逃逸、嵌套全局访问、注释/字符串不误报、语法/空源、函数形态/模块超限、Page 虚假同名方法、多定义、缺失文件及真实扫描注入。门禁在仓库根目录和 /tmp 工作目录运行均通过：9 模块、1 条内部依赖。
- 可靠性 workflow 在既有管理端依赖安装后、构建前加入门禁、9 份独立测试和页面/计时/渲染回归；不新增假定的小程序 npm scripts。解析 YAML 确认步骤位置和命令，并用 Bash 的失败停止模式执行新增步骤原始内容：85 项 Node 测试、页面运行 46 项、resilience 106 项、恢复延迟 12 项、自由计时上限 39 项、render-invariant 43 项及渲染 fixture 31 项通过。
- 全应用 Ruff、compileall、修改 JS 语法检查和 Git diff 检查通过。按 review-agent 只读流程核对扫描器、反例覆盖、真实策略/页面、路径独立性、CI 依赖顺序及文档：No findings。未运行远端 GitHub CI、管理端完整 check/build、微信开发者工具/模拟器/真机或生产环境；本批不改变应用行为和依赖锁文件。
- 门禁覆盖是局部的，不替代运行时测试，也不是安全沙箱；全小程序分包/双份代码一致性、其余超标基线和前后端业务治理仍未完成。本批仅本地提交检查器/测试、CI 及架构/任务记录，不推送，保留既有无关改动与资源删除，整体目标继续进行。

## 五十五、第四十九批执行记录：解除 AI service/预热 worker 循环

- 将原 `build_prewarm_revision` 原样迁至 `app/ai/prewarm_revision.py`，仅依赖 hashlib 和既有 prompt version；保持参数签名、计数/答案转换、原文本哈希输入、SHA-256 的 14 位截取及 r 前缀。worker 移除旧实现，不保留临时转发或重导出。
- AI service 校验方，以及刷题/考试/复习/错题更新/AI API 生产者共 6 个模块直接依赖中立协议；入队仍调用原 worker 入口。所有消费模块去除 import 节点后的完整 AST 与 HEAD 一致，revision 函数完整 AST 相同，70 组返回值及异常对照一致；未改变事务提交、payload/task id、预热失效、用户过滤或业务错误策略。
- 重构前相关基线 60 项及新增规则/协议基线 26 项通过。最终新增 18 项规则测试、9 项协议/入口启停测试和 3 项架构门禁，覆盖计数/空答案/版本变化、过期任务跳过、同版本生成/缓存、缺失错题、恢复生成基线、可重试/永久失败、真实 enqueue→process→service 交接、入口单次启动/退出取消与新进程无副作用导入。
- 完整架构及上述协议、错题、AI learning、生产预热资产挂载、复习调度、AI 能力隔离 API 和刷题链回归共 217 项通过。交接/服务端口使用合成数据与 mock，入口生命周期使用受控协程，不把这些本地证据写作真实 Redis/PostgreSQL、模型或完整部署角色验收。
- 精确移除已解除组的两条循环边，其他基线不扩增。当前 526 个应用模块、2,103 条静态依赖边、5 组/118 条循环边，service/feature → API 仍为零。新增架构测试约束协议依赖和 6 个真实消费者，禁止从 worker 取 revision；3 份新测试接入既有 CI 静态/非 GPU 步骤。
- 全部新/改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 检查通过，CI YAML 与测试路径验证通过。按 review-agent 只读流程核对完整差异、所有消费者、函数/签名等价、队列交接和生命周期测试及基线：No findings。未运行远端 CI、真实 Redis/PostgreSQL/模型、客户端或生产操作，剩余 5 组循环和完整学习/运行时治理继续待处理。
- 本批独立本地提交仅含中立协议/消费者、3 份新测试/循环基线、CI 及架构/任务记录；不推送，保留全部既有无关改动和资源删除，整体目标继续进行。

## 五十六、第五十批执行记录：解除 DOCX/OMML 循环

- 将 DOCX 六个字体策略常量及 East-Asian run 字体设置集中到 `services/export/docx_fonts.py`，导出器与 OMML 纯文本兜底直接依赖该最小模块。移除导出器原私有字体方法/旧常量定义，全部调用方迁移，不保留转发；未改变字体名称、字号、OOXML 操作或内容布局。
- OMML 在原纯文本兜底位置惰性导入字体规则，仍按 OMML → PNG → 原文降级；独立进程验证初始导入不加载 python-docx/字体模块，执行原文兜底也不加载完整导出器或 database。共享字体模块只依赖 python-docx 原语，不读取应用配置或创建任务/线程。
- 原 DOCX/OMML/表格/phase3 基线 132 项及新增字体/兜底基线 11 项通过。新增测试覆盖首次 rPr/rFonts 创建、重复更新不重复节点、Latin/复杂文字属性与字号/粗斜体保留、四种原文降级场景；3 项架构测试约束最小依赖、单向渲染调用及新进程导入边界。
- 字体值和 helper 函数体 AST 与 HEAD 一致；规范化字体所有权/调用名后，两类渲染器完整 AST 相同。108 组新旧 run XML、旧/新原文兜底段落 XML 和 6 份正常/强制原文、不同答案/解析位置文档的全部 ZIP 部件字节对照一致。
- 完整架构及字体、DOCX、OMML、表格、phase3、状态机、一致性、超时与综合导出回归共 391 项通过；最终惰性导入定向 14 项通过。全部新/改 Python 严格 Ruff、全应用 Ruff、compileall 和 Git diff 检查通过，新字体/架构测试接入既有 CI 静态/非 GPU 步骤。
- 从循环基线精确移除 DOCX/OMML 两条旧循环边，当前 527 个模块、2,104 条静态依赖边、4 组/116 条循环边，业务层反向依赖 API 仍为零。保留此前记录的 OOXML 元素顺序、zoom 属性、矩阵包装和片段 LaTeX 既有问题；没有夹带渲染纠错，输出一致不代表格式合规或 Word/WPS/LibreOffice 显示一致。
- 按 review-agent 只读流程核对完整差异、所有字体调用点、常量/函数体等价、导入时机、OOXML/完整文档对照、基线和测试：No findings。未运行真实 Office/LibreOffice、远端 CI、真实数据库/Redis、客户端或生产操作；剩余 4 组循环、导出完整用例与全栈治理继续待处理。
- 本批仅本地提交共享字体规则、两类消费者、字体/边界测试、循环基线、CI 及架构/任务记录，不推送，保留全部既有无关改动和资源删除，整体目标继续进行。

## 五十七、第五十一批执行记录：分离声明基类与运行时数据库

- 新增 `core/orm_base.py` 作为唯一 DeclarativeBase/metadata/registry 所有者，不依赖 settings、数据库引擎或模型注册。45 个模型/契约模块与 Alembic env 直接引用；运行时 database 引用同一个 Base，维持现有 database.Base 使用方兼容，不创建第二个 registry。
- 模型注册表及 schema_contract 执行顺序不变；database 的建引擎、session、画像判断、修复和 init_db 全部运行逻辑不变。45 模型与 Alembic 完整 AST 除 import 一致，database AST 去掉原 Base 定义/import 后一致，未修改表、列、约束、迁移历史或角色配置。
- 重构前/后独立进程逐项对照 79 张表、79 mapper、1,076 列、246 索引的字段属性、默认值、onupdate、server default、PostgreSQL/SQLite 完整建表和索引 DDL及 mapper 名称，结果完全一致。新进程完整模型注册/mapper 配置和 Alembic target_metadata 装配不加载 app.core.config/database。
- 新增 4 项 ORM 运行回归与 4 项边界门禁，覆盖唯一 Base 对象、临时 SQLite 真正建表/用户提交/重复初始化、cloud profile 不发本地 DDL、初始化异常退出事务、无引擎模型注册和 Alembic metadata。新测试接入既有 CI 静态/非 GPU 步骤；本机 PostgreSQL/Docker 命令不可用，不声称真实 PostgreSQL/部署角色验收通过。
- 原定向基线 10 通过/1 PostgreSQL 条件跳过；新增运行基线 4 项通过；迁移后定向 18 通过/1 条件跳过。广泛架构/数据库/迁移/错题/复习/API 回归 196 通过、1 失败、1 跳过；补充番茄钟迁移回归 24 通过、2 失败、8 条件跳过。
- 三项失败均在新进程加载 HEAD 原 database 与 45 模型源码复现：旧 PracticeRecord.answers 断言，以及两项番茄钟 runtime 用不可用“数学二”科目启动的夹具。原源码复跑对应文件为 38 通过/相同 3 失败，不修改工作区源码或生产行为、不 skip/xfail；后续需修复过时测试契约/夹具。
- 精确移除数据库/模型组 95 条旧循环边，当前 528 模块、2,105 静态依赖边、3 组/21 条循环边，service/feature → API 为零。所有新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 检查通过。
- 按 review-agent 只读流程核对完整差异、唯一 metadata 所有权、45 模型/注册顺序、Alembic、运行初始化/失败路径、元数据/DDL 对照和失败基线：No findings。3 项旧测试仍未通过；真实 PostgreSQL/Redis、生产迁移/启动、远端 CI和客户端未验证，剩余循环和整体治理保持未完成。
- 本批仅本地提交中立 Base、模型/Alembic/运行时导入、测试/循环基线、CI及架构/任务记录，不推送、不操作生产，保留既有无关改动和资源删除。后续优先恢复上述测试的可重复有效验收，再继续剩余学习域、运行时/OCR和客户端治理。

## 五十八、第五十二批执行记录：恢复当前 schema 与迁移回归

- 延续交接中的两份测试修改：PracticeRecord 断言按既有 `a4c5d6e7f8b9` 迁移检查 per-answer 字段与已退休批量字段，并显式检查 PracticeSession 聚合字段；番茄钟 runtime 使用 canonical `advanced_math` 科目和受控时钟，验证未到时拒绝、25 分钟完成及 4 分钟暂停的精确归属。不修改生产 schema、服务或迁移。
- allocation 冲突已定位为测试隔离：暂停测试单独运行通过，连续运行两个 runtime 用例为 1 通过/1 唯一约束失败；模块共享 SQLite 数据库未启用 FK cascade，reset_tables 未清理 allocation 子表，重用 session id 后撞上残留快照。显式先清理子表后，三份交接测试共 42 项通过，保留 9 条既有 SQLite datetime adapter 弃用警告，不加 skip/xfail。
- 扩大架构、ORM、数据库、schema、迁移、番茄钟分配/统计/调度回归：216 通过、13 失败、16 条件跳过。13 项全部来自未修改的 study_day_stats/scheduler；将两文件移至独立 pytest 进程，仍为相同 13 失败、35 通过，排除本批测试运行造成的跨模块污染。失败涉及旧随机科目不可用、统计归入未分类和依赖当前日期的趋势断言，继续登记为既有基线，不据此宣称全部番茄钟域通过。
- 两份测试严格 Ruff、全应用既有参数 Ruff、compileall 和 Git diff 检查通过。按 review-agent 只读审查完整测试差异、实际模型/迁移、服务完成与暂停规则和夹具重置次序：No findings。真实 PostgreSQL/Redis、远端 CI、客户端与生产未运行；16 项跳过不作为真实迁移/并发验收。
- 本批仅本地提交两份测试及架构/任务记录，保留交接摘要和所有既有无关改动及删除，不推送。后续继续 OCR 包/适配器循环、其他剩余循环和完整全栈治理；上述额外旧测试失败保留为明确待处理项。

## 五十九、第五十三批执行记录：解除 OCR 包与适配器循环

- `features/ocr_fix/__init__.py` 只保留包说明，不再加载/重导出实现；pipeline 与旧 OCR wrapper 直接引用 router，OpenAI 适配器直接引用 interfaces 模块，保留原模块别名和结果类型。全仓 Python 检索定位两个业务入口及四处测试 patch，全部迁移到真实定义；不新增兼容转发或动态导入。
- 三个生产消费模块除 import 外的完整 AST 与 HEAD 一致，未改配置、API、LLM 请求、降级、安全门、token budget、人工审核或事务语义。旧 DeepSeekFixer 和 correct_ocr_blocks 用例保留，不在本批扩大清理其他兼容实现。
- 新增 15 项真实适配器/路由契约，先在旧实现通过，迁移后继续通过：空输入/缺少配置不请求、配置完整时请求与 token/结果类型、DeepSeek 子类、空/异常/长度异常回退、惰性创建和模型别名缓存、纯规则回退。LLM transport 使用 AsyncMock，不请求外部服务。首次新增测试将消息列表字符串化后比较真实换行导致两处断言错误，已改为检查实际 message.content，生产逻辑未因此修改。
- 新增 7 项架构/新进程测试，覆盖空包无导出、业务直达定义、无 OCR 循环，以及无有效应用配置时导入包/interfaces/canonical_output/router 均不加载配置、AI client、数据库或适配器；从适配器先导入仍共享 canonical 结果类型且不加载 router/数据库。新测试已接入既有 CI 静态/非 GPU 步骤。
- 原 OCR 基线 112 通过、2 失败、1 xfail；扩大架构、OCR、协调器/回滚/恢复和 AI 能力 API 回归为 314 通过、相同 2 失败、1 既有 xfail。失败是现有 router 测试向自动链注入旧 `deepseek` 键，而当前链使用 `openai-compatible`；不跳过或修改生产链掩盖，后续修复测试契约。保留 11 条既有第三方弃用/AsyncMock 未 await 警告。
- 门禁先准确报告 6 条已解除边必须移除；精确缩减后当前为 528 模块、2,097 条边、2 组/15 条循环边，反向 API 为零。新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 与 CI YAML/路径检查通过。按 review-agent 只读审查完整差异、所有调用点、包导入时机、AST 等价与测试：No findings。
- 本批仅本地提交 OCR 导入/测试/循环基线、CI 及架构/任务记录，不推送，保留现有无关改动和资源删除。未运行真实 OCR/模型、PostgreSQL/Redis、远端 CI、浏览器或微信环境；剩余 question pipeline 与 import worker 循环、全栈业务盘点和高风险治理继续进行。

## 六十、第五十四批执行记录：恢复 OCR 自动降级测试

- 将 `test_ocr_service.py` 七处自动链的 LLM 替身注入键从旧 `deepseek` 改为当前 `openai-compatible`。DeepSeek 仍可作为模型/供应商，测试继续使用原结果与失败/安全门场景；不修改生产链、模型路由、降级规则或服务配置。
- 原 2 项失败恢复通过；原先未触发 LLM 的错误/空输出/安全拒绝和规则兜底用例现在实际注入当前链。单文件 24 项通过；OCR 协议/adapter、导入边界、服务、wrapper、故障注入、视觉回退和 Admin 配置回归 136 通过、1 既有 xfail，保留 11 条既有警告，不新增 skip/xfail。
- 修改文件严格 Ruff、全应用既有参数 Ruff、compileall、Git diff 检查通过；按 review-agent 只读审查完整 diff、真实自动链、七处测试调用和新旧失败证据：No findings。第五十三批的 2 项旧失败已关闭；第五十二批另外登记的 13 项番茄钟统计/调度旧失败尚未处理。
- 本批仅本地提交测试及架构/任务记录，不推送、不操作生产；所有既有无关改动和资源删除保持原状。真实外部服务与客户端未验证；剩余两个静态循环组和完整全栈治理继续进行。

## 六十一、第五十五批执行记录：题目 AI 入口依赖收敛

- 移除 question_pipeline 对 complete/enrich/draft 七个符号的兼容重导出。Admin service 直接依赖 question_ai_complete，App AI 路由直接依赖 question_draft_generator，日志继续读取 question_pipeline 的真实实现；两份测试 patch 跟随真实所有者迁移。writer 兼容导出与解析副本留待下一批，不将整个题目管线循环标记为完成。
- 新进程已复现旧代码先导入 question_ai_complete/enrich 的部分初始化 ImportError，迁移后恢复直接导入。新增 5 项架构/新进程与真实消费者测试，以及 2 项真实草稿降级/非法科目回归，结合已有 App 权限/生成路由共 10 项通过。降级只添加失败日志并按原位置提交，非法科目不请求/不写入；成功 AI 写入的完整数据库链路不由这些替身测试证明。
- 三个生产改动文件完整 AST 去掉 import 并归一化调用所有者后与 HEAD 一致。独立进程通过内存 import loader 分别装配 HEAD 原版和当前实现，运行时完整 OpenAPI 的 328 条路径完全一致；未覆盖工作区或启动服务。
- 变更前题目/Admin/科目/多空回归 156 通过、19 失败、8 xfail；变更后加入完整架构、App 权限和新测试为 294 通过、相同 19 失败、8 既有 xfail，逐项比较失败集合一致。旧失败来自 3 项科目管理夹具和 16 项多空题/管线断言，不在本批修改生产规则、skip/xfail 或掩盖。
- 精确移除 7 条已解除循环边，目前 528 模块、2,095 条边、2 组/8 条循环边；题目组仅剩 core/writer 2 条。新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 与 CI YAML/路径检查通过；新边界/降级回归接入原静态/非 GPU CI 步骤。
- 按 review-agent 只读审查完整差异、真实消费者、旧转发使用点、模块首导入、AST/OpenAPI 等价、权限和失败基线：No findings。本批仅本地提交相关代码/测试/基线、CI 及架构/任务记录，不推送，保留全部既有无关改动和资源删除。真实模型、PostgreSQL/Redis、客户端及生产未验证；writer 与 import worker 循环及全栈治理继续进行。

## 六十二、第五十六批执行记录：writer 调用迁移与题目管线循环收尾

- 将 App 导入、Admin 文本写入、两个 worker 分发分支、文本解析、AI 草稿和相关测试/独立脚本全部改为直接引用 question_import_writer；writer 源码完全未改。core 移除原 writer 重导出、旧 Excel/PDF 副本、关键词常量及行解析转发，不保留双份实现或兼容壳；同步更正实际职责和公式规范化调用位置说明。
- 已验证旧 core 转发的实际函数对象就是 writer 函数；四个旧解析 helper 去掉 docstring 后完整 AST 与 writer 相同。旧 _guess_subject 副本有过时判断，但早已被底部 writer 导出覆盖，删除不改变实际 canonical 分类。全仓定位消费者，剩余生产 AST 除明确移除内容/import/docstring 外相同；core 1,811 → 1,400 行，正常化/查重/AI 公共规则仍待继续治理，不以缩短文件标为完成。
- 独立进程分别装配 HEAD 原版与当前六个生产模块，完整运行时 OpenAPI 328 条路径完全一致。新增 4 项依赖/首导入回归，确保 core 不加载 writer/AI 业务入口、writer 与文本解析先导入不循环；新增 3 项严格解析契约覆盖真实 PDF 下游规则、canonical 科目、空提取拒绝及合成 Excel 的空行/零值/空列头。首次新 PDF 断言误期望空格和真实换行，已按原 writer 的无空格及字面量反斜杠 n 契约修正，未改生产输出。
- 原解析/导入基线 97 通过、3 失败、14 xfail；修改 import/patch 后相同 3 失败、97 通过、2 xfail、12 xpass。扩大完整架构、解析、导入、AI 降级/Admin 服务与 API 回归为 248 通过、相同 3 失败、2 既有 xfail、12 xpass；失败为两个旧 408 code 预期和一个 MagicMock scalar 不可 await 的夹具。未新增 skip/xfail，未改生产规则。
- 12 项 xpass 来自原测试 patch 指向被覆盖的 core helper，迁移到真实 writer 后才使用合成提取文本；既有数学脚本 check 只打印失败仍需加强，xpass 不能证明其每项内容断言生效。新解析契约直接 assert，不沿用该缺口；旧 xfail 标记与测试 helper 留作明确后续治理。
- 精确移除题目 core/writer 2 条循环边，当前 528 模块、2,093 条边、1 组/6 条循环边，service/feature → API 仍为零。全部新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 和 CI YAML/路径检查通过；新边界/解析契约接入原静态/非 GPU CI。
- 按 review-agent 只读审查完整差异、所有消费者、旧导出所有权、删除副本的实际覆盖关系、剩余 AST/OpenAPI、测试 patch 与失败/xpass 基线：No findings。本批仅本地提交相关源/测试/基线、CI 与架构/任务记录，不推送，保留全部既有无关改动和资源删除。未运行独立 phase8 外部依赖脚本、真实 OCR/模型、PostgreSQL/Redis、远端 CI、客户端或生产；剩余 import worker 循环、旧测试基线和完整全栈治理继续进行。

## 六十三、第五十七批执行记录：公式批次生产与执行职责

- 新增 formula_graph_batch_service、batch_runner 和 batch_state，分别持有批次创建/原入队、逐卡执行及唯一进程内 jobs/lock；原 graph_spec_service 只保留 preview/confirm 等单卡能力。Admin API 和两个 worker 分发分支直接消费定义模块，无重导出或新队列。新业务模块均满足 300/50 行预算。
- 先在原实现运行新增 11 项刻画及既有公式 API 117 项，全部通过。迁移后扩充至 17 项，覆盖队列拒绝、已有任务拒绝、相同状态对象、逐卡新事务、四次 ValueError 尝试、confirm 失败重新 preview、其他异常继续、跳过不增加 processed 的原口径、取消传播、空/未知任务及清理；真实 enqueue → legacy/v2 worker → runner 使用受控数据库/传输端口验证，不代表 Redis 集成。
- 111 组旧/新 0/1/2 卡组合的最终状态、事务/session/retry/confirm/cancel 调用轨迹一致；剩余 service、route、worker AST 除抽取/调用所有者外不变，独立进程完整运行时 OpenAPI 328 路径一致。
- 完整架构、公式 API、批次契约、上传与队列指标回归共 288 项通过，保留 5 条既有 API 测试 AsyncMock 未 await 警告。新增 2 项依赖/预算门禁并接入既有 CI；全部新改 Python 严格 Ruff、全应用 Ruff、compileall、diff 与 CI YAML/路径检查通过。
- 精确移除公式 service/worker 两条循环边，当前 531 模块、2,104 条边、1 组/4 条循环边，反向 API 为零。批次状态仍为原进程内字典，独立 worker 进程无法共享状态属于已存在限制，不夹带改为 Redis 或宣称部署验收完成。
- 按 review-agent 只读审查完整差异、状态所有权、重试与事务退出、队列交接、异常/取消、对照与边界测试：No findings。本批仅本地提交相关源/测试/CI/基线和架构/任务记录，不推送，保留全部既有无关改动和资源删除。真实 PostgreSQL/Redis、绘图进程、客户端与生产未运行；剩余 import/batch image/worker 循环及完整全栈治理继续进行。

## 六十四、第五十八批执行记录：上传 admission 与后台执行分离

- 新增唯一 import_upload_service、不可变 UploadRequest，以及 image/excel/document 三个格式 admission 模块，Public/Admin 两路直接共享原签名入口。上传按验证/准备、资源预留、暂存与状态、入队分成短函数；原 import_pipeline_service 继续拥有后台执行、图像/状态和预留辅助，移除原 start_import_pipeline，不保留兼容转发。输入快照只有原 12 个参数；新业务模块均满足 300/50 行预算。
- 后台服务不再导入 worker，worker 仍按原分发执行器处理，本地回退、租约/fencing、幂等键、payload、失败传播与事务规则均未改；精确移除最后 4 条静态循环边，基线为空。目前 536 模块、2,139 条静态边、0 循环边、service/feature → API 为零，未据此宣称完整运行时已治理完毕。
- 160 组新旧 PDF/TXT/Excel/图片/非法类型与参数、校验/页码/预留/暂存/状态/队列异常、拒绝和日志失败场景，响应或异常以及全部副作用轨迹一致。原异常分支末尾第二个不可达 raise 随抽取移除，不改变错误语义。自动 AST 生成初稿使用 Python 3.12 f-string 引号形式，格式化后符合项目 Python 3.11；另补全显式类型与遗漏 os 导入后完成检查，没有修改运行时环境。
- 原后台服务剩余非 import/docstring AST、两路路由完整非 import AST 与 HEAD 一致；独立进程装配旧/新实现，完整 OpenAPI 328 路径一致。原定向回归 32 通过/8 失败，修改后相同 32 通过/8 失败，逐项失败集合一致。
- 新增 29 项真实 admission 入口回归，验证格式 payload/页码、成功保留预留、预留失败不释放、stage/status/queue 错误后释放、队列拒绝先失败状态后释放，以及保留原 CancelledError 不释放预留的既有行为。新增 4 项架构/预算/实际调用方/新进程门禁；最后定向 33 项通过。传输、暂存和资源端口为替身，不是 Redis/真实文件存储集成验收。
- 扩大完整架构、上传、权限/页码/状态 API、故障注入、公式 enqueue→worker 回归为 226 通过、相同 8 项既有失败；8 项来自旧权限数据库夹具、400 错误脱敏预期和直接调用路由缺少 current_user，不加 skip/xfail 或改变生产权限/错误边界换取通过。随后增加的第 4 项首导入门禁已由 33 项定向复验。
- 新改 Python 严格 Ruff、全应用 Ruff、compileall、diff 与 CI YAML/路径检查通过；新增 admission/边界测试接入既有静态/非 GPU CI。按 review-agent 只读审查完整差异、请求字段、各格式顺序/错误与资源所有权、AST/OpenAPI/对照证据及失败基线：No findings。
- 本批仅本地提交相关源/测试/基线、CI 与架构/任务记录，不推送，保留全部既有无关改动和资源删除。真实 PostgreSQL/Redis、OCR/模型、完整部署角色、远端 CI、浏览器与微信环境未运行；静态循环治理已清零，完整业务域盘点、角色/队列/OCR 高风险验收、前端/controller 和全栈长期门禁仍未完成。

## 六十五、第五十九批执行记录：恢复上传与状态 API 回归

- 仅修复两份旧 API 测试：上传页码测试提供权限查询替身数据库并将权限缓存版本读取固定为 miss，继续执行真实 require_permissions 查询与子集判断；新增无权限返回 403 且不调用上传服务用例，不绕过生产 RBAC。旧 400 文案预期改为当前脱敏 envelope、HTTP_400、retryable=false 及请求/追踪 id，并断言原后端细节不泄露。
- 状态路由测试显式传入 User 和 SQLite 所有权数据库，使用真正 ORM 查询读取合成 import_pipelines 表，保留旧管线优先/图像回退；新增他人/不存在均 404 且不读取状态，以及拥有记录但运行态不存在映射 404。SQLite 只含该查询需要的两列，不声称完整生产 schema 或异步驱动集成。
- 原两文件 18 项中的 8 项旧失败全部恢复，加入 4 项新用例后 22 项通过。完整架构、admission、上传/页码/状态 API、共享入口、故障注入及公式队列交接共 239 项全部通过，无新增 skip/xfail。两文件已接入既有静态/非 GPU CI 步骤。
- 两份测试严格 Ruff、全应用 Ruff、compileall、Git diff 与 CI YAML/测试路径验证通过。按 review-agent 只读核对完整差异、真实权限依赖、错误脱敏契约、SQLite 所有权查询、缺失/他人同态拒绝与副作用停止：No findings。生产代码/配置、API、鉴权与资源规则未修改。
- 本批仅本地提交测试、CI 及架构/任务记录，不推送，保留全部既有无关改动和资源删除。真实 PostgreSQL/Redis、部署角色、外部 OCR/AI、客户端和远端 CI 尚未运行；零静态循环与本条链的回归通过不代替完整全栈治理验收，其余阶段与旧基线继续待处理。

## 六十六、第六十批执行记录：HTTP 错误契约与处理器

- 接续工作区已有抽取：`core/http_error_contract.py` 持有公开消息、机器码筛选、状态映射及关联 ID envelope；`core/http_error_handlers.py` 持有五类异常处理及注册函数。main 只在原位置注册，不保留转发；新模块不反向导入 main。状态码、脱敏、retryable、Retry-After、关联响应头与日志失败回退保持原行为。
- 本轮重新比较 HEAD 原 main：10 个迁移函数除原装饰器/新增返回类型注解外完整 AST 一致，其余 main 非导入 AST 一致；792 组新旧处理器的状态/正文/响应头/日志/context 轨迹一致。运行时完整 OpenAPI 328 条路径、异常处理器注册顺序一致。未使用摘要记载替代本轮验证。
- 69 项 HTTP 契约/边界用例已纳入扩大回归，完整架构、admission、上传权限/页码/状态、公式批次、隐私和 AI 能力 API 共 322 项通过，无新增 skip/xfail。首次未指定测试画像时因默认生产 staging 目录不存在而收集失败，随后显式使用 test/local_import、内存 SQLite 和临时 staging 路径通过；未修改生产配置。
- 新改 Python 严格 Ruff、全应用既有参数 Ruff、compileall、Git diff、CI YAML 与测试路径检查通过。当前静态图 538 模块、2,145 条边、0 循环边。main 2,156 → 1,843 行，lifespan、中间件与健康/指标仍待治理；两个新模块均满足 300/50 行预算。
- 按 review-agent 只读流程核对完整差异、真实注册位置/调用方、原函数及 logger 所有权、响应/日志对照、边界测试与 CI 接线：No findings。未创建子 agent；本批不证明真实 PostgreSQL/Redis、角色启动/退出、外部 OCR/AI、远端 CI 或客户端验收。
- 本批仅本地提交 HTTP 源码/测试、CI 及架构/任务记录，不推送、不操作生产，保留其他工作区改动与删除状态。后续优先核实并恢复登记的 13 项番茄钟统计/调度旧失败，再继续全量语义盘点、客户端 controller 与高风险运行时治理。

## 六十七、第六十一批执行记录：恢复番茄钟统计与生命周期回归

- 本轮先独立复现 study_day_stats/scheduler 两文件的 13 失败、35 通过。修复测试的随机/过时科目，改为查询或创建 canonical `advanced_math`；统计断言同时验证名称及科目 ID。停用科目案例使用受支持但停用的 `data_structure`，继续验证与无科目合并为未分类；不修改生产可用科目或归因规则。
- 趋势测试将学习日固定在合成记录对应的 2026-08-08；异常暂停数据的恢复/完成显式控制服务时钟，避免当前日期改变完成结果。保留不补造暂停区间的原断言，并精确验证异常完成的 1,500 秒。
- 生命周期测试以受控时钟验证未到时拒绝、25 分钟完成并关闭通知通道，以及真实 pause/resume 延长 expected_end_time 和 pause interval 恰好 90 秒；移除直接倒改数据库时间的模拟。SQLite 清理先移除 allocation 子表，避免 session ID 复用触发唯一约束；生产级联/并发规则未改。
- 两文件 48 项通过，关闭上述 13 项旧失败；扩大完整架构、HTTP、ORM、分配、归因与迁移回归 293 通过、9 项既有条件跳过、11 条既有弃用警告。跳过包含缺少真实 PostgreSQL URL 的模块及环境条件用例，不作为 PostgreSQL 验收。
- 两文件接入现有 CI 静态/非 GPU 步骤，并显式设置 test/local_import、合成 APP_SECRET、内存 SQLite、空 Redis/Sentry 和 runner 临时 staging，避免默认生产画像影响测试收集；不改变部署环境。新改测试严格 Ruff、全应用 Ruff、compileall、Git diff、CI YAML/路径检查通过。
- 本地执行该 CI 步骤的完整命令与环境，577 项全部通过、2 条既有弃用警告。首次转录脚本把虚拟环境 Python 符号链接解析为系统 Python，缺少 pwdlib 而收集失败；改用虚拟环境绝对路径后通过，未安装/改动依赖。按 review-agent 只读核对完整差异、科目可用性权威实现、真实完成门槛、暂停区间、清理顺序、CI 环境与结果：No findings。
- 本批仅本地提交测试、CI 及架构/任务记录，保留既有其他改动与删除，不推送、不操作生产。13 项已关闭不表示整个学习域、角色运行时或全栈治理完成；下一批继续 main 的 HTTP 中间件职责分离，先刻画安全头、追踪、日志及异常顺序。

## 六十八、第六十二批执行记录：HTTP 中间件职责分离

- `core/http_middleware.py` 持有安全头工厂、请求开始日志及追踪中间件和唯一注册入口；main 在原位置显式传入 hosts/origins/production_mode。注册顺序和全部参数保持不变，安全模式由各 app 闭包持有，模块不加载 settings、数据库或全局 app，不保留 main 兼容转发。
- 安全头及内联开始日志后的追踪函数 AST 与 HEAD 原实现归一化后相同，其余 main 非导入/装配 AST 一致。160 组安全头响应/异常、108 组追踪正文/头/异常/日志/context 对照一致；运行时完整 OpenAPI 328 路径和四层中间件注册选项/顺序一致。
- 先在原实现通过 18 项刻画，再迁移到真实模块，增加 app 间安全模式隔离及日志 finish/error 失败场景。保留认证前缀的 startswith、已有头 setdefault、非法 Host 原 400 正文、CORS 预检、W3C traceparent、查询仅记键、UA 200 字符、关联头覆盖、日志失败传播和取消后的 context 清理，不夹带错误策略修复。
- 完整本地 CI 静态步骤 599 项通过、2 条既有弃用警告；随后追加两项日志 finish/error 失败用例，定向契约/架构 24 项全部通过。3 项架构测试覆盖单向依赖、300/50 预算、真实 app 的注册对象/选项/顺序和新进程无配置导入；初稿依赖断言发现 `from app.core import log_context` 同时登记包级边，改为直接导入定义模块后通过，未放宽门禁。
- 新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff、CI YAML/测试路径检查通过。当前静态图 539 模块、2,147 边、0 循环；新模块 126 行，函数最长 42 行，main 1,843 → 1,729 行。按 review-agent 只读核对完整差异、所有消费点、装配顺序、闭包隔离、异常/日志/取消轨迹及 CI：No findings。
- 本批仅本地提交相关代码/测试、CI 及架构/任务记录，不推送、不操作生产，保留其他改动与删除。未验证真实角色启动/退出、PostgreSQL/Redis、外部 OCR/AI、后台浏览器、微信环境或远端 CI；后续继续健康/指标、生命周期和全栈业务域治理，完整目标保持未完成。

## 六十九、第六十三批执行记录：恢复健康/readiness 有效回归

- 初始 health/admin health/readiness 为 1 失败、9 通过、39 条件跳过：旧健康断言仍要求公开 env；readiness 被 integration 目录默认门禁跳过。逐项确认该文件没有使用真实 pg/redis fixtures 后，仅对这个指定文件启用 `--run-integration`，实际为 9 失败、30 通过；不将跳过记作验收。
- 只修复测试：公开 `/health` 精确检查 `{"status":"ok"}`；OCR profile patch 指向实际 `ocr_isolation` 导入位置；审计调度器用例显式禁用无关推荐指标调度，并新增启用后运行/停止两种状态。队列替身改用实际 ready_length_v2/processing_length_v2，生产/本地错误通过真实 `_production_mode` 分支验证，并增加三类任务的 100/101 临界深度和调用参数检查。
- staging 空间测试不再以空字典条件放行，使用受控 statvfs 验证精确 free/total/75% 占用。每例恢复 OCR hysteresis；移除把全局 app lifespan_context 永久置 None 的旧夹具，TestClient 不使用上下文管理器即可避免启动。端点测试默认替身 OCR，避免测试期间请求外部服务。
- 新增 16 个本地/云响应矩阵场景，覆盖数据库、Redis、staging、角色、OCR、队列和 Alembic，以及云端不泄露池详情。现有实现把失败 Alembic 标记为 stale，但 critical_failures 只收 unavailable，所以仍返回 200；已用原实现证实并登记为待单独修复的问题，不在等价重构中修改生产语义。队列 unavailable 原先也只作信息展示，Redis 是独立关键探针。
- 三文件合计 69 项通过，无新增 skip/xfail；新增 CI 独立步骤显式设置隔离环境，只运行这三文件及指定目录门禁，不扩大到整个 integration 目录，不依赖真实 PostgreSQL/Redis。完整执行该 CI 步骤本地通过 69 项；新改测试严格 Ruff、全应用 Ruff、compileall、Git diff 和 CI YAML/路径检查通过。
- 同进程包裹运行全部 69 项后，额外断言 app.router.lifespan_context 保持原对象、OCR 失败计数恢复原值，均通过；该包裹进程产生 1 条 anyio 提前导入引起的 pytest rewrite 警告，独立 CI 命令无该警告。按 review-agent 只读核对完整差异、真实 patch 所有者、v2 队列参数、调度器规则、脱敏及全局状态恢复：No findings。
- 本批只本地提交测试、CI 与架构/任务记录，生产代码/配置、健康行为和数据库未改，不推送、不操作生产，保留全部其他工作区状态。下一批继续健康/指标实际职责拆分；Alembic 判定缺口单独待办，真实依赖与部署角色验收尚未完成。

## 七十、第六十四批执行记录：指标访问策略与队列/推理采样

- 从 main 分离 `core/observability_access.py`、`services/task_queue_metrics.py` 与 `services/runtime_inference_metrics.py`，分别拥有指标访问策略、队列深度/计数输出和 OCR/AI 采样。权限先于实际采样；状态仍来自原 task_queue、queue_metrics、OCR gateway、AI guard 和 token budget，不建立新计数器或状态副本。main 继续持有系统/DB/SSE/调度器和最终文本响应的顺序组合。
- 原实现先通过 36 项刻画；首版测试向原本可缺失的 SSE 属性注入替身时缺少 raising=False 导致 23 项夹具错误，修正后原实现全过，未修改生产 fallback。迁移后新增取消传播及部分字段读取失败场景，保留原先“已追加行 + 错误兜底行”、队列整组零值、空 gateway 不输出 OCR、AI budget 出错仍保留前面 runtime 行，以及尾换行/content-type。
- 展开采样 helper 后指标端点完整 AST、显式参数归一化后的权限函数体及其余 main 非导入 AST 与 HEAD 相同；79 组完整响应/头/异常/采样轨迹对照一致，运行时完整 OpenAPI 328 路径一致。访问测试覆盖本地绕过、云空/错 token、scheme 大小写、token/header 空白及拒绝时队列/系统均不采样。
- 新增 3 项架构门禁检查实际调用方、单向依赖/无状态转发、300/50 预算及新进程导入不加载配置/数据库/运行时。三个新模块为 30/58/66 行，最长函数 39 行；main 1,729 → 1,607 行。当前静态图 542 模块、2,154 边、0 循环，service/feature → API 为零。新测试接入既有 CI。
- 完整本地 CI 静态步骤 644 通过、2 条既有弃用警告；独立 readiness 步骤 69 项通过。新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff、CI YAML/路径检查通过。按 review-agent 只读核对完整差异、访问先后顺序、原状态对象、部分输出/兜底边界、取消、AST/输出对照与 CI：No findings。
- 本批仅本地提交代码/测试、CI 和架构/任务记录，保留既有其他改动与资源删除，不推送、不操作生产。外部 OCR/AI、真实队列/Redis/PostgreSQL、部署角色、远端 CI 和客户端未验收；main 的剩余系统/DB/SSE/调度器指标与健康/生命周期继续治理。

## 七十一、第六十五批执行记录：指标组合与 SSE 计数所有权

- `runtime_system_metrics.py` 持有系统、两次 staging 读取、DB 数值过滤/查询、进程及 worker/scheduler 指标输出；`runtime_sse_metrics.py` 持有 SSE 健康/连接/导入计数采样。main 按原顺序采样并组合返回，metrics_endpoint 收敛为 36 行；不引入另一套监控协议或重复采样。
- `import_sse_metrics.py` 是原六个进程内计数的唯一所有者，Admin stream 直接写同一字典，SSE sampler 直接读取；路由不保留 `_sse_metrics` 转发，service 不再为采样反向引用 Admin API。per-user 连接表仍由原 batch service 持有，未改并发限额/超时/连接清理。旧 `active` 快照只在开启时刷新、关闭仅递减连接表的既有口径保留，后续若修复需单独验证。
- 迁移前扩充指标测试及真实 SSE 路由共 52 项通过，覆盖 50/5 连接限额优先级、断开、7,201 秒总时长与 301 秒空闲超时、订阅取消及计数。迁移后增加独立失败端口和实际 route → sampler 共用计数验证；系统采样错误仍传播，其他独立 try 块保持各自兜底，DB bool 仍按数值输出、staging cleanup 仍单独第二次取样。
- 展开辅助函数后端点 AST、其余 main 非导入 AST，以及按新计数所有者归一化后的 Admin route AST 相同；80 组完整响应/头/错误/队列采样轨迹一致，运行时 328 路径 OpenAPI 一致。新 SSE sampler 初稿包式导入多出 features 包边，改为直接导入实际模块后门禁通过，未放宽依赖约束。
- 完整本地 CI 静态步骤 665 项通过、2 条既有弃用警告；独立 readiness 69 项通过。随后按职责分开系统指标测试，复用原 fixture，最终指标/架构/SSE/Admin 回归 75 项通过，测试文件路径已同步 CI。新增模块 13/28/102 行，函数最长 27 行；main 1,607 → 1,521 行，当前图 545 模块、2,162 边、0 循环且无 service/feature → API。
- 新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff、CI YAML/路径验证通过。按 review-agent 只读审查完整差异、真实 SSE 写入/读取、限额/断开/超时与清理、采样顺序/部分失败/取消、AST/响应对照及门禁：No findings。本批仅本地提交相关代码/测试/CI/任务与盘点，不推送、不操作生产，保留其他工作区改动与删除。健康及角色生命周期、真实 Redis/PostgreSQL/SSE/外部服务与客户端验收仍未完成。

## 七十二、第六十六批执行记录：readiness 响应判定

- 新增中立 `core/readiness_response.py`，不可变 ReadinessSnapshot 明确容纳原探针结果，纯函数集中 checks 字段、关键失败判断、degraded、云端隐藏详情及状态码；不执行探针、不依赖 FastAPI/settings/数据库。main 仍持有原探针编排、draining 错误回退和 JSONResponse，未改变探针顺序或事务/网络规则。
- 先在原实现通过 15 项入口刻画：八种探针异常立即停止后续调用，正常路径严格 database → redis → alembic → staging → space → role → OCR → queue → draining → pool；draining 抛错按原规则退为 False，云端不泄露池/空间详情。迁移后加入 49 项纯响应矩阵、Redis 包含条件及原映射引用不变性检查。
- 4,096 组布尔探针、生产/Redis配置、OCR/queue 状态组合，旧原函数后半段与新规则 JSONResponse 的 status/body/headers 完全一致；探针前半段 AST、其余 main 非导入 AST 与完整 328 路径 OpenAPI 一致。保留 Alembic stale 不触发 503、queue unavailable 信息展示等已登记原行为，未用抽取修复业务。
- 定向契约/架构/原 readiness 共 125 项通过。新模块 75 行、函数最长 31 行；2 项门禁验证 main 唯一调用、单向依赖/尺寸和新进程不加载应用/配置/FastAPI。新测试接入现有 CI；main 1,521 → 1,491 行，探针和角色生命周期仍待治理。
- 完整本地静态 CI 731 项通过、2 条既有弃用警告；独立 readiness 69 项通过，严格 Ruff/全应用 Ruff/compileall/diff 与 CI YAML/路径验证通过。静态图 546 模块、2,163 边、零循环/反向 API。按 review-agent 只读核对全部差异、字段/引用/顺序、纯规则输入/输出、云脱敏及组合对照：No findings。
- 本批只本地提交响应规则、调用方/测试/CI及架构/任务记录，不推送、不操作生产，保留其他工作区改动和删除。未运行真实 PostgreSQL/Redis、OCR/AI、完整运行角色与客户端；健康探针边界和全量治理继续进行，Alembic 判定缺口保持单独待办。

## 七十三、第六十七批执行记录：基础依赖探针

- `services/readiness_dependency_probes.py` 持有数据库、Redis、Alembic、staging 可写/空间、队列和 DB pool 七个探针；main 直接调用定义，不保留原私有函数转发。会话工厂、Redis URL、production mode 和原 Alembic 路径显式传入；staging/池/缓存仍从原端口惰性读取，不创建新连接、引擎、缓存或状态。
- 先在原实现通过 33 项契约，验证真实 SELECT 文本/会话上下文、数据库错误与取消、Redis 真 PING/无缓存写入、无 Redis 时云和配置错误 fail-closed、Alembic 单 head/缺失/不匹配及原 script_location、staging mkdir→access 和池指标/错误。抽取后相关响应/指标/探针与原 readiness 共 208 项通过；全仓检索迁移独立 Redis PING 测试和所有 patch 至实际调用名称。
- 七个函数按显式端口/配置归一化后完整 AST 与 HEAD 相同，其余 main 非导入 AST 归一化后相同；76 组数据库/Redis/队列成功、异常、取消结果一致，运行时完整 OpenAPI 328 路径一致。取消不被普通 Exception 兜底吞掉；队列仍按三类 v2 ready/processing 汇总、100/101 临界和原本地/生产回退，不改变 readiness stale 已知问题。
- 新增 3 项实际定义/依赖/预算/新进程门禁；模块 156 行、函数最长 29 行，导入不初始化 app/settings/database/cache/queue。新探针与独立 Redis 回归接入既有 CI。main 1,491 → 1,358 行；当前图 547 模块、2,168 边、零循环/反向 API。
- 完整本地静态 CI 771 项通过、2 条既有弃用警告，独立 readiness 69 项通过。新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff、CI YAML/路径检查通过。按 review-agent 只读审查全部差异、显式参数、惰性端口、异常/取消和缓存 fail-closed、所有测试调用/patch及对照：No findings。
- 本批仅本地提交相关源/测试/CI/任务与盘点，不推送、不操作生产，保留其他改动与删除状态。未验证真实 PostgreSQL/Redis、生产迁移/队列/OCR/AI和客户端；OCR readiness/角色检查/生命周期、其他业务域与全栈长期门禁继续进行。

## 七十四、第六十八批执行记录：OCR readiness 状态与探针

- 新增 `services/ocr_readiness.py`，显式 Settings 与 OcrReadinessState 拆开配置检查、连续失败更新和远端健康探测；main 只持有唯一状态实例并直接调用，不保留旧计数或探针转发。Doctor CLI 直接消费探针定义，不再为了 OCR health 导入整个 main。新模块导入不加载配置/数据库/OCR/httpx。
- 迁移前 26 项刻画通过：连续失败 1/2 次正常、第三次降级、成功清零后重新计数，禁用/非法配置/非远端不重置；健康请求 `<500`、URL、超时、标准/自定义/缺 token 鉴权头及 trace；普通传输错误变 False 并增加计数，CancelledError 传播且计数不变。迁移后相关 OCR/响应/原 readiness 149 项通过，再增加独立 state 不互相污染测试。
- 展开 issues helper、显式配置/状态归一化后两个探针及其余 main AST 相同；3,072 组配置/云隔离/已加载模块/失败计数/远端结果/异常/取消组合，状态、计数、调用次数和结果一致。运行时完整 OpenAPI 328 路径一致。保留配置错误仍不改计数、远端 4xx 视为可达等原语义，未夹带安全策略变更。
- 3 项架构测试检查真实调用/Doctor 无 main 依赖、唯一状态、300/50 预算及新进程惰性导入，接入现有 CI。模块 105 行、函数最长 44 行；main 1,358 → 1,275 行，图 548 模块、2,172 边、零循环/反向 API。完整角色、生命周期和全栈治理仍未完成。
- 完整本地静态 CI 801 通过、2 条既有弃用警告；独立 readiness 69 项通过。新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 与 CI YAML/测试路径检查通过。按 review-agent 只读审查全部差异、唯一状态与 await 后计数、错误/取消、配置检查顺序、Doctor 真实导入及对照：No findings。
- 本批仅本地提交相关代码/测试/CI/任务及盘点，保留其他文件改动与删除，不推送、不操作生产。HTTP transport 为替身，未执行真实 OCR/Doctor 全链、生产数据库/Redis、角色启动/退出或客户端/远端 CI；事件循环 lag 仍由 main 持有，角色检查及生命周期下一批继续。

## 七十五、第六十九批执行记录：角色依赖检查

- `services/role_readiness.py` 持有显式 Settings 的角色检查，scheduler 审计/推荐指标检查独立函数；main 直接调用真实定义，不保留 `_check_role_deps`。保持相同 logger 名称、web 云隔离、worker/all draining 先于 OCR/调度器、scheduler/all 启用开关、ImportError 与普通异常日志和未知角色 False。
- 原实现先通过新增 22 项刻画：web/worker/scheduler/all/未知角色，云本地模块与大小写 backend、draining 的拒绝/普通错误回退/取消，以及两类 scheduler 的 import/access/cancel 错误和日志。迁移后契约/边界/响应/原 readiness 共 148 项通过；取消继续传播，不改变原 worker draining 查询失败继续的行为。
- 展开 scheduler helper、去除文档及显式参数归一化后角色函数与其余 main AST 一致；2,560 组角色/云/模块/backend/draining/开关/运行状态结果及日志顺序一致，完整 OpenAPI 328 路径一致。首轮 AST 对照未对 helper 展开后导入节点再归一化而失败，修正对照脚本后通过，未因此改生产语义。
- 新增 3 项依赖/预算/真实调用/新进程门禁并接入既有 CI，模块 97 行、两个函数为 41/43 行；main 1,275 → 1,184 行，图 549 模块、2,178 边、零循环/反向 API。模块导入不加载配置、数据库、OCR isolation 或 worker/scheduler。
- 完整本地静态 CI 826 项通过、2 条既有弃用警告；独立 readiness 69 项通过。新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 与 CI YAML/路径检查通过。按 review-agent 只读审查全部差异、原角色优先级、scheduler日志/错误/取消及真实消费者和组合对照：No findings。
- 本批仅本地提交代码/测试/CI/任务与盘点，保留其他工作区改动和删除，不推送、不操作生产。角色检查替身不等于真实 HTTP/worker/scheduler 启动/失败清理/退出；main lifespan、lag 单一所有权和全栈其他业务仍待治理，已登记 Alembic/SSE 原缺口未修。

## 七十六、第七十批执行记录：事件循环 lag 唯一状态

- `core/event_loop_health.py` 持有唯一进程内样本及显式 state 的监测协程；main 的 readiness/metrics 和 ResourceGuard 直接读取同一对象。移除原 main 标量/监测转发及 ResourceGuard 对 sys.modules 中 main 的隐式查找；中立模块不导入 app/settings/数据库，不在导入时创建任务。
- 原实现先通过 8 项刻画：sleep 后才发布、两位小数、负值不钳制、取消/普通错误不覆盖最后样本，ResourceGuard 读取值及没有 main 时默认零。迁移后独立进程验证 ResourceGuard 不加载 main 仍为零；真实 asyncio task 验证显式独立 state、取消传播/最后样本保留且无新增/遗留任务。
- 监测函数按 state 归一化后 AST 一致，其余 main/lifespan AST 除名称/显式状态外一致；36 组多 tick/间隔/初值/负值/取消轨迹一致，运行时完整 OpenAPI 328 路径一致。lifespan 仍在原执行器初始化后启动同名唯一任务，在原 drain 之后、export stop 之前 cancel/await；不为 worker/scheduler 新增监测任务。
- 定向 lag/架构/ResourceGuard/cloud resource/metrics/响应规则 164 项通过。新增 3 项依赖/状态/尺寸/生命周期位置和无导入任务门禁并接入 CI；整个 HTTP/worker/scheduler 启停仍未完成验收。
- 完整本地静态 CI 839 项通过、2 条既有弃用警告，独立 readiness 69 项通过。新改 Python 严格 Ruff、全应用 Ruff、compileall、Git diff 和 CI YAML/路径验证通过；模块22行、监测函数7行，main1,184→1,166行，图550模块/2,180边/零循环/反向API。
- 按 review-agent 只读审查完整差异、唯一状态、所有消费者、默认零语义、样本发布与取消、lifespan原位置及AST/轨迹/门禁：No findings。本批仅本地提交相关代码/测试/CI/任务/盘点，保留其他改动与删除，不推送、不操作生产；真实角色启停、外部依赖和客户端/远端CI仍未验收。

## 七十七、第七十一批执行记录：后台任务取消与共享等待

- `core/runtime_task_shutdown.py` 持有原后台任务顺序取消与共享30秒等待，main 显式传入原九个任务名称/引用，仍拥有任务生命周期。保持缺失/已完成跳过、取消顺序、一次 asyncio.wait、完成/取消/异常日志、pending警告后第二次cancel；不新增重试、单任务等待或超时延长。
- 原lifespan真实片段在不启动外部服务的隔离函数中通过7项刻画，迁移后测试直接调用新实现；补共享wait取消传播和真实task取消/吞取消正常完成/取消时失败，结合lag/边界定向25项通过。真实任务全部收尾，无遗留测试任务；未等待真实30秒超时，pending使用受控wait端口。
- 343组缺失/已完成/取消/完成/异常/exception取消/pending组合的done/cancel/wait/log轨迹与旧实现一致；helper展开后的完整main/lifespan AST、共享等待块AST和328路径OpenAPI一致。调用位置仍在export stop之后、scheduler stop之前，lag停止位置未变。
- 新增3项依赖/尺寸/真实调用/标签顺序/关闭位置及无导入副作用门禁接入CI；模块40行、函数31行，main1,166→1,126行，lifespan870→829行；图551模块/2,181边/零循环/反向API。剩余启动、资源清理和真实角色启停仍待治理。
- 完整本地静态CI851项通过、2条既有弃用警告；独立readiness69项通过。严格Ruff/全应用Ruff/compileall/diff/CI YAML与路径检查通过。按review-agent只读检查全部差异、原标签/取消顺序、一次共享等待、异常/取消传播、真实task及AST/组合轨迹：No findings。
- 本批仅本地提交相关代码/测试/CI/任务与盘点，保留其他改动和删除，不推送、不操作生产。受控task/替身不证明真实Redis/worker/scheduler优雅退出，完整阶段和外部/客户端/远端CI验收仍未完成。
