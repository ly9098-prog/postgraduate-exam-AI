# 重构执行记录 · 第 02 卷

> 原记录编号：§107–§204；98/100 批次。保留原编号和原文顺序，合并标题按覆盖编号计数。历史状态不代表当前验收结论。

[任务入口](../current_task.md) · [原计划](plan.md) · [上一卷](history-01.md) · [下一卷](history-03.md)

<!-- original-history:start -->

## 一百零七、第一百零一批执行记录：知识状态与图谱扩展提取（2026-10-21）

- `get_smart_scored_questions` 的知识状态加载和图谱候选扩展阶段拆分为四个模块级函数：`_load_knowledge_and_graph_context`（47 行，加载 UserKnowledgeState 并编排图谱扩展）、`_expand_graph_candidates`（36 行，SAVEPOINT 隔离的弱 KP 选择+图谱获取+候选扩展）、`_fetch_graph_context`（26 行，调用 adaptive_learning_service）、`_extend_with_graph_question_candidates`（43 行，查询前置链题目并扩展候选列表）。所有函数≤50 行。
- 保留原 SAVEPOINT 隔离、Settings 开关检查、异常回退到空 graph_context、弱目标选择和图谱候选查询。函数从 412 行降至 318 行。
- 原 208 项 practice 测试通过，0 循环/0 反向 API/33 保护哈希通过/review-agent 只读 No findings。严格 Ruff/compileall/diff 通过。
- 仅本地提交，不推送、不操作生产。`get_smart_scored_questions` 仍超 50 行预算——后续继续提取状态加载/评分/降级编排。


## 一百零八、第一百零二批执行记录：scored 状态加载与直接行为契约（2026-10-21）

- 继续未提交的状态加载抽取，分离 `_load_candidate_states`（题目状态、最近20条练习知识点和QKP映射）、`_load_kp_names`、`_extract_graph_context` 与异步 `_compute_recommendation_weights`。入口保留同一session、原查询和graph字段读取顺序；权重调用显式await，普通错误回退与取消传播不变。评分、多样性和随机补齐仍由原入口编排，本批没有完成整个practice领域治理。
- 直接契约发现并纠正第一百零一批迁移回归：图谱查询上限误用候选池大小，已恢复 `max(count * 3, 30)`；图谱结果误用dict.update合并，已恢复provider原对象与字段集合。本轮未提交状态抽取中的漏await同时修正。此前208项外围测试及“No findings”不足以证明scored原实现等价，相关旧记录须结合本条更正阅读。
- 新增16项直接契约，实际调用完整 `get_smart_scored_questions`，仅SQL/外部服务/评分端口替身，覆盖请求题量1/11/20、系统×用户权重、普通错误、取消、SAVEPOINT进入/释放/回滚、空/非法图谱结果和独立开关；另验证provider对象归属。先复现8失败/2通过，再修复通过，后扩充至16项。夹具同时恢复sys.modules与父包属性，修复独立通过/混合失败的问题，无skip或xfail。
- 与 `e8a045c0` 原完整入口比较的15组场景，结果/元数据/SQL调用轨迹/图谱SQL参数/错误及取消相同（固定时钟；该临时对照不放入CI）。练习域与API/既有链混合224项通过，10条警告包含既有datetime弃用和aiosqlite线程收尾警告，未因此宣称真实数据库事务验收。
- 新契约接入原YAML静态步骤；本地完整CI步骤结果在本条后续验证记录。严格Ruff、全应用Ruff、compileall与33保护路径哈希通过。主agent按只读缺陷审查流程核对全部diff、原完整函数、实际调用方、异常/取消/事务边界与新旧对照；上述迁移问题修正后未发现其他本批阻断问题。无子agent、无push、无生产操作。
- 验证口径更正：第96至98批将分组命令称作“完整静态CI”，且部分分组包含重复测试，不作为原YAML步骤或去重通过数依据；本批单独读取当前YAML并重放实际三步骤。当前静态扫描571模块/2,240边/零循环/反向API为本轮实测，不能证明全栈完成。
- 最终原YAML三步骤：静态2,015项通过（2条既有弃用警告）、readiness69项通过、云OCR30项通过。日志 `/tmp/scored-phase-ci-status.log`、`/tmp/cloud-isolation-{ci,readiness,cloud}.log`；直接红/绿 `/tmp/scored-pipeline-{red,green}.log`，混合 `/tmp/scored-phase-targeted.log`，原实现参数/结果/轨迹对照 `/tmp/scored-phase-comparison.log`。本批首次混合/CI失败为新夹具父包引用未替换，修正后实际重放全过，不通过取消选择掩盖该问题。
- 当前practice_service4,254行、入口239行，四个新增helper47/17/7/33行。仅提交本批源码/测试/CI/任务/盘点；context保持未跟踪。后续先建立评分/多样性/补齐分支的直接契约，再按业务职责治理，避免继续只以外围通过数或函数行数作为验收。


## 一百零九、第一百零三批执行记录：scored 选题策略与补齐直接契约（2026-10-21）

- 在原实现上先通过15项评分/多样性/补齐契约，使用完整scored入口与真实calculate_smart_score/解释构建，仅上游加载和补齐DB端口替身。覆盖真实权重、稳定同分排序、单/多KP最小计数规则、放宽多样性、随机补齐total<=remaining/<=2000/>2000三分支、最终重复限制放宽、重复ID跳过、超量返回时元数据保留、普通错误/取消和非正count原行为。
- 新增中立 `practice/scored_selection.py` 的 `select_scored_candidates`，拥有两轮多样性选择，显式接收已打分候选、题量、QKP映射和原元数据工厂；在原选中位置生成解释元数据，入口仍持有评分、解释权威实现、fallback日志级别和DB补齐。保留多KP计数取min的规则，不夹带改成每KP硬50%上限，也不裁剪原本额外保留的元数据。
- 新模块47行/函数36行，practice_service4224/完整入口208行；评分与随机补齐编排仍待继续。新增3项依赖/尺寸/唯一真实消费者/惰性导入无配置、ORM和任务副作用门禁，生产静态图572模块/2242边/零循环/反向API。
- 扩充metadata错误/取消和空候选后，新直接契约共18项；与旧82fb84eb完整入口18组新旧结果/元数据/SQL与参数/随机偏移/日志/错误取消逐项相同。当前新旧入口均实际执行，不以单独helper测试替代实际消费者；临时对照脚本不作为长期CI依赖。
- 新契约与架构门禁接入原CI。定向37项通过，练习域混合242项通过（11条警告包含既有datetime弃用及aiosqlite线程收尾错误，未将其认定为真实DB验收）。严格Ruff/全应用Ruff/compileall/diff与33项保护哈希通过；原YAML三步骤结果见后续验证记录。
- 主agent只读审查完整diff/原两轮选择/元数据生成次序/真实调用方及新旧轨迹后，未发现本批阻断问题；无子agent、无生产操作、无push。API、权限、事务和任务协议不变，整体全栈目标仍未完成。
- 最终原YAML静态2,036通过（2条既有警告）/readiness69/云OCR30均通过。两轮选择循环在显式变量名/元数据工厂端口绑定后AST相同，service其余61函数AST未变。日志 `/tmp/scored-selection-{baseline,targeted,comparison,mixed,ast,ci-status}.log` 及 `/tmp/cloud-isolation-{ci,readiness,cloud}.log`，未用人工拼接的测试列表冒充原CI。
- 下一步继续评分/随机补齐职责边界，并用本批真实分支契约保留过滤、随机阈值、字段和错误口径；完整目标保持active。只显式暂存本批7文件本地提交，context保持未跟踪，其他33保护路径及删除状态保持。


## 一百一十、第一百零四批执行记录：scored 补齐查询边界（2026-10-21）

- 原入口的随机补齐与最终重复限制放宽查询归 `practice/scored_fallback.py`：`build_random_fill_query`拥有total<=remaining/<=2000/>2000三分支，`load_random_fill_questions`负责原count→query→execute→scalars.all，`load_repeat_fill_questions`显式消费原`_random_sample_query`，保留原参数与原DB session。模块不commit/rollback/begin，不创建engine、配置或任务。
- caller继续拥有原subject/revision/active/candidate-selected/history排除条件、fallback级别、放宽顺序、metadata与合并/去重；不把两个不同随机口径合并：首次total<=remaining不加limit且按ID，最终仍用原sampler随机/offset规则。保留补齐返回多余metadata、最终duplicate跳过等原行为。
- 扩充现有完整入口契约11项：四个count/rows查询分别普通错误/取消、最终sampler参数/offset、None/0计数短结果；总29项先在未修改实现通过。迁移后直接与架构定向51项通过，练习域混合253项通过（12条警告含既有datetime弃用和aiosqlite线程收尾问题）。新增3项架构门禁并接入原YAML，已有选择门禁跟随真实新query消费者。
- 29组与旧27af0505完整函数对照，结果/metadata/SQL参数/随机偏移/日志/错误取消一致；61个其他service函数AST未变，两补齐guard/level/remaining/filter赋值与合并loop body AST保持。日志/tmp/scored-fill-{baseline,targeted,comparison,mixed,ast}.log；对照是隔离端口，非真实PG/生产链验收。
- 新模块95/函数34、14、27行；practice_service4191/入口171行。静态图573模块/2244边/零循环/反向API。严格Ruff/全应用Ruff/compileall/diff及33保护路径哈希通过。主agent按只读缺陷审查核对全部差异、实际调用点、参数/取数时机/原循环与错误边界，未发现本批阻断问题；不创建子agent、不push/生产/清理。
- 原YAML静态/readiness/云OCR三步骤结果将在最终验证行记录。整体全栈目标仍active，评分编排、其他长函数、业务域与客户端尚未完成，不因入口收缩声称完成。
- 最终原YAML步骤：静态2,050通过（2条既有警告）/readiness69/云OCR30全过；日志/tmp/scored-fill-ci-status.log与/tmp/cloud-isolation-{ci,readiness,cloud}.log。严格检查及旧新对照均覆盖最终代码；仅显式暂存本批8文件，本地提交，不把context或其他改动纳入。
- 下一步继续scored评分编排与加载边界，优先用现有直接契约防止模型/权重/解释次序漂移；保留其他领域与客户端阶段待办、HTTP/独立runner失败清理等已知限制，目标仍active。


## 一百一十一、第一百零五批执行记录：scored 评分排序边界（2026-10-21）

- 原入口逐题调用 `calculate_smart_score`、按原位置参数/关键字收集分数与解释、稳定降序排序的完整循环迁至 `practice/scored_ranking.py` 的 `score_and_rank_candidates`。模块只拥有候选遍历与排序，不读取DB、不写日志、不生成元数据、不补齐题目；入口显式传入原 scoring 权威函数和全部上下文端口，不保留旧评分循环壳。
- 原直接契约29项先在未修改实现通过；迁移后新增3项：每个候选的原question/state/KP/mastery/recent/now位置参数与全部关键字精确一致、原候选列表保持输入顺序、同分保持原序；普通错误与取消均止于失败候选，不执行后续评分、top-5日志、解释元数据和补齐查询。最终直接契约32项通过，另架构门禁3项通过。
- 与旧入口完整代码比较同32场景结果、元数据、SQL/参数、随机偏移、日志、错误和取消一致；临时对照排除两个monkeypatch scorer场景，避免同一测试内旧/新骨架交错消耗同一mock，这两项由直接入口契约独立覆盖。未宣称未归一化的整套AST等价；原评分循环的精确实参和稳定排序由直接契约验证。
- 新模块49行/函数36行，practice_service4180/完整入口159行；生产静态图574模块/2,246边/零循环/零反向API。严格Ruff/全应用Ruff/compileall/diff、CI路径与33保护路径哈希通过；练习/API混合256项通过（11条既有弃用/aiosqlite线程收尾警告，不代表真实DB验收），原YAML静态2,056项（2既有警告）/readiness69/云OCR30通过。主agent按只读缺陷审查核对实际调用、原参数/排序/错误边界与新旧证据，未发现本批阻断问题；无子agent、无push/生产/资源清理。
- 本批只本地提交 `.github/workflows/ci.yml`、practice_service、新增评分模块/测试、选择边界测试、架构盘点和本任务记录；context继续保持未跟踪，其他33保护路径不变。评分/加载等剩余长函数、管理端/小程序、任务队列/OCR/导入、真实外部服务与阶段0/1/3/4仍未完成，整体goal保持active。


## 一百一十二、第一百零六批执行记录：scored 补齐结果合并边界（2026-10-21）

- 入口的随机补齐和最终重复限制放宽两段结果合并迁至 `practice/scored_fallback_merge.py` 的 `merge_fill_questions`，显式传入原 `selected`/`selected_ids`/provider行/`metadata`/reason/strategy/原元数据工厂；首次补齐保持不去重，最终补齐保持跳过已选ID，metadata仍在原行追加位置生成。入口继续拥有过滤条件、count/sampler查询、fallback级别、最终日志和响应slice，不把两个补齐策略合成一套查询语义。
- 先补2项完整入口契约：首次返回重复ID照样追加、最终跳过重复且不覆盖已有metadata、provider顺序和元数据调用点保持；第二轮普通错误/取消冻结已追加结果，并确保后续最终查询不发生。原有29项契约与新增后共31 direct项通过，4个scored架构门禁及依赖图28项通过。
- 第105批评分helper保持原精确实参语义，不修改其调用表达式；第105批未归一化AST比较仍只作为已知限制，不作为等价证明。评分函数38行，`get_smart_scored_questions`仍159行，后续还要继续拆分收尾编排，不因本批裁剪把整个practice域视为完成。
- 本批新增模块33行/函数19行，practice_service4181行；静态图575模块/2,248边/零循环/零反向API。定向47项、练习/API混合201项通过；原YAML静态2,062项（2条既有警告）/readiness69/云OCR30通过；严格Ruff/全应用Ruff/compileall/diff/CI路径/33保护路径哈希通过。未验证真实PostgreSQL或外部推荐服务。


## 一百一十三、第一百零七批执行记录：scored 补齐编排边界（2026-10-21）

- 原入口的level 3随机补齐与level 4重复限制放宽两个完整`if`块迁至`practice/scored_fallback_flow.run_scored_fallback`，由`ScoredFallbackRequest`显式传入DB/已选题目/ID/metadata/count/原fallback级别、subject条件、候选ID、excluded子查询、scope、revision条件、两个查询函数、sampler、merge函数及metadata工厂。查询、sampler、元数据策略仍由入口的既有权威实现提供，module只保留原顺序和level/remaining规则。
- 保留两个层级分别重新计算remaining；level 3条件顺序为active→subject→revision→candidate/selected排除→可选excluded；level 4才去掉重复历史条件并改为selected排除。保留第一次补齐重新加入重复ID、最终补齐跳过重复ID，以及每次merge在原行位置生成metadata。没有合并两种sampler，也没有改变事务边界。
- 新增2项flow直接契约覆盖excluded有/无时base→subject→revision→候选/已选排除→可选excluded顺序、每级remaining与两级merge参数顺序；3项flow架构门禁验证惰性依赖/预算/无SQL执行/真实入口全部17个端口与条件AST/无内联fallback及无导入副作用，并接入原YAML静态步骤。已有4个scored架构门禁同步跟随真实flow消费者。首次只读审查发现上述基础条件与`request.db.execute`门禁不足，已修正后复审确认关闭。
- 新模块98行/函数8、22、22行，practice_service4170/完整入口144行；图576模块/2,250边/零循环/零反向API。定向68项、练习/API混合206项通过；最终原YAML静态2,067项（2条既有警告）/readiness69/云OCR30均通过；严格Ruff/全应用Ruff/compileall/diff/CI路径与33保护路径哈希通过。真实PostgreSQL/外部推荐服务仍未验收；不把入口行数收缩视为practice域或全栈完成。


## 一百一十四、第一百零八批执行记录：smart scored 补充编排边界（2026-10-21）

- `get_smart_practice_questions` 的 scored 策略分支迁至中立模块 `practice/smart_scored_supplement.run_scored_supplement`；`ScoredSupplementRequest` 显式传入 DB、用户/科目/题量、过滤与复习参数、scope、收尾开关、实验上下文、原 logger、scored/fallback/merge/finalize 端口。模块只保留“scored 满额直接收尾，否则按缺口补齐、合并后截断、失败后返回 None 以继续原 weakness 路径”的原顺序，不执行查询、持久化或事务操作。
- 完整 scored 结果仍以 `scored[:count]` 和原 metadata 直接收尾；缺口只请求 `count - len(scored)`，排除全部已选 ID，合并后才截断。实验 `experiment_id`/`variant_key`、逐题 strategy/score/config 元数据和 `skip_finalize` 聚合行为保持；普通异常仍回到原内联 weakness/随机路径，`CancelledError` 继续向调用方传播。
- 按要求保留旧 logger 身份，两个日志仍由 `app.services.practice_service` 发出；日志文本、级别和异常信息不变。新增 4 项完整入口契约覆盖满额、短补、失败回退与取消传播，3 项架构/新进程门禁精确约束 17 个请求端口、scored 分支无内联旧 try、流程顺序及无 I/O 依赖；两文件接入原 YAML 静态步骤。
- 修复既有 smart/path 测试接线：补异步 `db.scalar`，对齐真实 knowledge-path 与 isolated recommendation-log patch 目标，并让 sequential 测试显式替换真实顺序服务，不再以 SQL 模拟掩盖分支。未修知识路径在练习过滤前写日志/提交请求会话的既有缺陷，登记为独立行为批次。
- 新模块 100 行，`run_scored_supplement`/`_finalize` 分别为 49/16 行；`practice_service.py` 4,132 行，`get_smart_practice_questions` 446 行，`get_smart_scored_questions` 144 行。当前图 577 模块/2,251 边/零静态循环/零反向 API。
- 新 smart/架构/phase2 定向 11 项、修复后旧 smart/path 子集 8 项、练习/API 混合 270 项通过（13 条既有弃用/aiosqlite 线程收尾警告）。原 YAML 三步原样重放：静态 2,075 项、readiness 69 项、云 OCR 30 项全部通过（静态 2 条既有弃用警告）；严格 Ruff、全应用 Ruff、compileall、diff 均通过。SQL/推荐服务均为端口替身，未验证真实 PostgreSQL/Redis、外部推荐服务、管理端浏览器或微信端。
- 仅本地提交本批源码、测试、CI、任务记录和架构盘点；`prompts/tasks/context.md` 保持未跟踪，其他 33 项既有改动/删除保持原状态。不推送、不操作生产，不把本批边界收缩视为 practice 域或全栈治理完成。


## 一百一十五、第一百零九阶段：本地练习接口与管理端浏览器验证（2026-10-21）

- 本轮没有修改生产源码，只使用已运行的本地后端（`127.0.0.1:8000`，开发 SQLite）和管理端（`localhost:3000`）验证现有刷题链路。测试用户为隔离开发夹具 ID `658`，未写入真实用户、生产凭据或仓库文件；临时 token、响应和截图仅保存在 `/tmp/postgraduate-practice-e2e/`。
- 实际 `GET /api/v1/practice/subjects` 返回根科目 `1/2/3/4`，科目 `2` 下有叶子 `7/8/9/10`。随机科目 `7`、`smart_strategy=scored`、`smart_strategy=path`、`weakness_vector`、空科目、非法题号、缺失/越界参数、缺失/无效 token 和不存在科目均按预期返回 200/400/401/403/404/422；GET 响应不泄露答案/解析字段，并带 `Cache-Control: private, no-store` 与 `Pragma: no-cache`。
- 补验父学科和知识点层级：`GET /api/v1/practice/questions?subject_id=2&include_children=true&count=10` 返回跨 `7/8/9/10` 的 10 道签名题；同一父科目 `include_children=false` 返回空结果且无签名。`knowledge_point_id=1&include_descendants=false` 只返回根知识点直属题 `2970`，`include_descendants=true` 的 `knowledge_scope` 含根及 6 个后代、共 7 个知识点，返回题目均属于科目 `7` 且落在该范围内。
- 真实 `POST /api/v1/practice/batch-submit` 先以畸形载荷得到 400 `PRACTICE_BATCH_INVALID` 且无新记录；随后两个新批次成功写入练习记录 `419/420`、会话 `70/71`、错题/复习行 `285` 和诊断 `274`。确定性题号批次 `2998,510` 的提交结果为 1 正确、0 错误、1 跳过，并保留签发版本 `5070`；未出现答案或 token 泄漏。
- 管理端浏览器实际登录 `localhost:3000` 后，`/dashboard`、`/questions`、`/review`、`/recommendation/strategies`、`/recommendation/experiments`、`/recommendation/reports` 在首次访问和刷新后均成功加载；捕获的 Admin API 请求均为 200，无页面错误、失败请求、控制台错误或 500。截图和机器可读报告位于 `/tmp/postgraduate-practice-e2e/admin-browser-refresh-1792584329/`（`report.json`、`01-login.png` 至 `08-recommendation_reports-reload.png`）。随后独立复跑同一 `localhost` 登录/六页脚本，登录 API 200 并跳转 `/dashboard`，`admin-browser/report.json` 中六页均为 200 且 `console`/`page_errors`/`failed_requests` 为空；日志为 `/tmp/postgraduate-practice-e2e/admin-browser-final-recheck.log`。
- 发现并记录地址级问题：`http://127.0.0.1:3000/login` 点击登录后没有发出登录请求且停留在 `/login?`，而 `http://localhost:3000` 可用；CORS 预检允许两个 origin，根因尚未证明，未修改产品逻辑。另有既有 `path` 策略日志缺陷：实际返回题 `459,460`，推荐日志 `115` 记录了未返回的 `461`；该问题按交接要求单列，不在本阶段顺手修复。
- 微信开发者工具进程日志显示项目已打开、模拟器编译和 appservice 重启，但没有可用的 DevTools MCP 或截图/交互证据，`cli.bat` 仍报 `Maximum setlocal recursion level reached`；因此只能记为“已触发打开/编译”，不能声称编译、页面交互、渲染、提交或真机通过。未执行 PostgreSQL/Redis、外部推荐/OCR/AI、生产部署或真实用户验收。
- 本轮已运行 `git diff --check`，并重新核对 33 个既有保护路径的 SHA-256：全部一致，未覆盖或恢复用户的未提交改动/删除。`prompts/tasks/context.md` 仍未跟踪，不应纳入提交；本轮未暂存、提交或推送。
- 用户明确允许后，已按精确范围删除数据库合成用户 `658` 及其关联数据，共 8 张表 18 行；事务提交后独立只读复核 8 项计数均为 0。SQLite 数据库大小仍为 90,755,072 字节，未执行 `VACUUM`，因此文件不会立即缩小。清理预览保留在 `/tmp/postgraduate-practice-e2e/cleanup-preview.json`。
- 用户明确允许后，已终止仅匹配 `C:\Temp\codex-postgraduate-e2e-edge` 的隔离 Edge 进程，并删除该临时 profile；复核目录不存在、匹配进程为 0。未触碰个人 Edge、微信开发者工具或其他浏览器数据；`/tmp/postgraduate-practice-e2e/` 验证证据继续保留。


## 一百一十六、第一百一十阶段：练习提交半状态与孤儿 outbox 修复（2026-10-21）

- 真实微信模拟器复现首次失败：5 题已答完并出现确认弹窗，点击“确认交卷”后 API 返回 `400 PRACTICE_PAYLOAD_INVALID`；运行日志为 `Non-terminal outbox record exists for task_id=answer_projection:419 status=pending`，前端通用提示为“交卷内容未通过校验”。这不是用户 payload 或批次签名问题，而是 SQLite 删除记录后复用主键、旧 outbox 仍 pending，且 ID 序列未回退。
- 数据库核对确认半状态：旧 `practice_sessions.id=70/user_id=659/request_id=practice_2fcebb...` 已可见，`question_count=answered_count=5`、`submission_payload_hash` 非空，但 `submission_response=NULL`，无对应 `practice_records`、错题、复习或 outbox；旧 trace 为 `tr_mvi3suuou4bhgno4lb`，首次请求 `req_mvi3wms7mare0q9opv`。`_replay_committed_submission` 对该缺失 canonical response 稳定抛出 `PracticeSubmissionConflictError`，即新请求会映射为 409 而不是伪造重放结果。
- `batch_submit_answers` 原先在 `PracticeSession` 上使用独立 `begin_nested()` flush，再在后续 outbox 失败时向外抛异常。SQLite 释放该 savepoint 后，异常请求依赖只关闭 session、未显式 rollback，导致会话单独可见而 records/response 不可见。当前修复先用 SQLite 显式外层事务包住 savepoint 占位，占位成功后 session/records/wrong/review/outbox/response 最终只由一次 `db.commit()` 提交；后续异常整体 rollback，savepoint 不再拥有独立持久化结果。
- `create_outbox` 对 `answer_projection` 的非终态任务增加源记录权威校验：仅当同 ID 记录已被删除，或记录时间晚于旧 outbox（主键复用）时，原位重绑该 outbox 到新记录，保留原 `task_id`/id/created_at，写入 `recovered_from_orphan` 和错误说明，重置 pending 状态/租约/重试；活记录的真实并发冲突仍抛原错误，其他任务类型行为不变。
- 新增真实 SQLite 事务回归 2 项：旧 pending outbox 与新记录复用同 ID 时成功重绑；模拟 outbox 写失败后 session/records 均不可见。前一项先按失败行为红测，事务修复后 7 项 sequential 定向全过。练习域混合 250 项、扩大链路 303 项通过；严格 Ruff、`compileall -q`、`git diff --check` 通过。测试中的 aiosqlite “Event loop is closed” 收尾告警为既有问题，未将其算作真实 DB 验收。
- 复审后修正事务设计：恢复 `IntegrityError`/`_is_unique_violation`，SQLite 先显式 `BEGIN`，再以 `begin_nested()` savepoint 占用 `(user_id, request_id)`。若并发唯一冲突，savepoint 回滚后读取已提交 winner 并做内容哈希重放，不让事务进入 poisoned 状态；占位成功后 session/records/wrong/review/outbox/response 统一由外层事务持有，后续任意 `BaseException` 都显式 `db.rollback()` 再传播。同步抽取 `_payload_with_trace()`，新任务与孤儿重绑共用原请求关联语义。
- outbox 新鲜度判定从 `answered_at` 改为 `PracticeRecord.created_at`：仅源记录创建时间严格晚于旧 outbox 才允许重绑，等时或更早均 fail closed。测试改为：旧 outbox 显式早于新记录以确定性覆盖复用 ID；活源使用正常创建行保持等时拒绝；新增快查未命中后唯一冲突重放，以及 outbox 失败时 session/records 整体回滚。最终 9 项定向与练习域扩大链路 305 项通过（20 条既有 datetime/aiosqlite 线程收尾告警），严格 Ruff/compileall/`git diff --check` 通过；两文件仍有先于本阶段存在的 Ruff format 漂移。当前无 Docker，未验证 PostgreSQL 并发，不把 SQLite 回归冒充真实 PG 验收。
- 真实 HTTP 隔离批次（用户 659）成功：2 题提交 200，session `71` 响应完整，records `419/420`、错题/复习同步生成；新记录复用并重绑了旧 outbox `419/420`，证明实际运行路径恢复。旧 session `70` 未删除、未改写，只作为确定性冲突边界保留。
- 微信模拟器完整重跑 5 题 `[2417,277,302,3043,2651]`，答案 `A/B/C/D/B`；确认弹窗显示“已完成 5/5 题”，真实确认后进入结果页并显示 1 对 4 错、总题 5、正确率 20%。对应数据库 session `72`（`request_id=practice_7acd3f81...`）`submission_response` 完整，records `421-425`、错题 `286-289`、复习调度同批存在；截图证据在 `/mnt/c/Temp/codex-wechat-e2e/evidence/practice-fixed-round-q1.png`、`practice-q1-selected.png` 至 `practice-q5-selected.png`、`practice-fixed-submit-confirm-or-result.png`、`practice-fixed-after-confirm.png`。日志中提交、结果页诊断和趋势请求均为 200；本地 AI 模型未配置导致预热降级，未阻塞结果页。
- 仍未验证：真机、PostgreSQL/Redis、外部推荐/AI/OCR、生产部署与历史数据迁移；旧 session `70` 的 canonical response 缺失属于已产生的历史半提交，当前修复不作自动补写，也不清理用户 659、session 70/71/72、截图或诊断证据。`current_task.md` 只记录本阶段事实，不声称全栈目标完成。


## 一百一十七、第一百一十一阶段：独立缺陷修复（2026-10-22）

### 111.1 path 候选日志与提前提交

- 复现依据沿用第一百零九阶段：`path` 实际返回题 `459,460`，推荐日志却记录了未下发的 `461`。根因位于 `knowledge_path_service.get_user_path_recommendations`：它在返回候选后立即调用 `create_recommendation_logs`，该函数内部 `commit()` 提前提交请求会话；随后 `practice_service` 才执行活动态、科目范围、不可变版本和 repeat-window 最终守卫并截断题目，因此日志可能包含被守卫裁掉的候选，且提前提交破坏了请求事务所有者的边界。
- 修复保持独立知识路径 API 行为：`get_user_path_recommendations` 增加 `write_logs: bool = True`，默认仍写 `scene='knowledge_path'` 日志；Admin/用户侧 `/api/v1/knowledge-path` 调用不改。smart 刷题 `path` 分支显式传 `write_logs=False`，候选阶段不再提交请求会话；最终仍由 `_finalize_smart` 在守卫后的实际返回题上写 `scene='practice_smart'` 日志，并保留 request/experiment/variant 上下文。
- 新增 4 项契约回归：路径独立 API 仍写自身日志；刷题路径必须关闭端点日志；最终守卫后只记录实际返回的 `459,460`，不记录候选 `461`；路径失败时仍走既有 weakness/random fallback，且只记录最终返回题。定向练习域 198 项、架构 + 知识图谱 + 练习 API 301 项、练习/API 混合 87 项均通过；严格 Ruff、`compileall -q`、`git diff --check` 通过。
- 该修复改变 `knowledge_path_service` 内部函数签名但保持默认行为和 HTTP 契约不变；未删除历史日志、未改写数据库、未补写旧记录。真实 PostgreSQL/Redis/外部推荐服务仍未验证，SQLite/端口替身结果不冒充生产事务验收。

### 111.2 127.0.0.1:3000 登录不触发请求

- 复现确认：Next.js 16.2.12 dev server 监听 `localhost` 时，浏览器访问 `http://127.0.0.1:3000/login` 会收到服务端 HTML，但 `/_next/webpack-hmr` 被 Next 的开发跨源保护返回 403/非法握手；App Router 客户端未完成 hydrate，表单仍以原生 GET 提交，因此 URL 变为 `/login?`、输入被清空且没有 `/api/admin/v1/auth/login` 请求。`localhost` 同时受默认允许，故可正常登录。
- 已在 `admin-frontend/next.config.ts` 的开发分支显式设置 `allowedDevOrigins: ["127.0.0.1"]`，只放开开发内部资源和 HMR，不放宽生产 CORS、Admin JWT、refresh cookie 或后端 TrustedHost。生产构建不包含该 dev-only 配置。
- 真实浏览器复测 `127.0.0.1:3000`：登录 POST 200，跳转 `/dashboard`，`sessionStorage` 有 access token；`dashboard/questions/review/recommendation strategies/experiments/reports` 六页均 200，Admin API 无 4xx/5xx，控制台错误、页面错误和失败请求均为空。证据位于 `/tmp/postgraduate-practice-e2e/admin-browser/report.json` 与对应截图。
- 管理端 `npm run typecheck`、`npm run lint`（0 errors，132 条既有 warning）、`npm run test`（56 files/788 tests）、`npm run build`（33 routes）全部通过。该验证是本地 dev + Chrome headless；不等于生产部署、真实用户浏览器矩阵或微信端验收。


## 一百一十八、第一百一十二阶段：运行时启动与关闭失败边界（2026-10-22）

- HTTP lifespan 改为 startup 与 `yield` 共用同一个 `try/finally`：db、executor、OCR Gateway 等 yield 前失败也会执行既有有序清理；启动异常仍保持原对象/取消身份，清理普通错误不再覆盖启动错误。Standalone runner 新增独立 `StandaloneRuntimeResources(role, registry, ocr)`，worker 启动、signal 等待、signal 取消和 shutdown 都由一个资源所有者传递，避免失败时 registry/task 或 OCR client 失去引用。
- OCR 所有权收紧：HTTP 与 worker 在 `create_ocr_worker_client()` 成功后立即把 client 保存在 `HttpOcrResources.worker_client`，只在 `OCRGateway` 构造成功后转移并清空；gateway 构造失败时由 cleanup 关闭暂存 client。gateway 与暂存 worker 同时存在时两条路径都尝试关闭，gateway 普通失败或取消不跳过 worker/shared client；任一关闭阶段取消时继续清理剩余资源，最终传播第一个取消对象。显式传入 `ocr_resources` 时不再读取全局 gateway singleton。
- Standalone 启动失败清理拆至 `core/runtime_startup_cleanup.py`，普通异常、`CancelledError` 和 cleanup logger 自身失败都要保留原启动失败；已存在的 `SystemError` 原样重抛。worker OCR 使用 client 自身 `shutdown()`，不反射私有 `_client`。readiness 将 Alembic `stale` 纳入关键失败并返回 503，生产模式继续隐藏 checks 明细。
- 回归：OCR shutdown 定向 47 项、全量 `tests/architecture` 255 项通过；全量 `tests/core` 1,620 passed、4 skipped、3 failed。3 项失败均在本轮前交接中已登记为既有：`safe_remote_fetch` redirect FakeConnection 不接受 `connect_timeout`，`staging_storage` 两个 orphan cleanup 用例未删除过期文件。独立审查发现的 cleanup 取消覆盖、gateway 失败跳 worker、logger 抛错跳后续资源和 worker 取消失跳 shared client 问题均已修复并有真实失败回归；最终只读复审无 findings，剩余 3 项 core 失败与本轮源码无关，仍保持既有待办。
- 验证命令：`.venv/bin/python -m pytest tests/core -q --tb=short`、`.venv/bin/python -m pytest tests/architecture -q --tb=short`、`ruff check app/ --ignore I001,F401,N818`、`compileall -q app`、`git diff --check` 均完成（pytest 保留上述 3 项既有失败）。PostgreSQL/Redis/OCR/AI 外部服务、真实生产角色退出和客户端验收仍未执行；不把端口替身、SQLite 或结构门禁冒充生产验收。已按 40 个显式路径本地提交为 `5c62d707 fix(runtime): 收紧角色启动与关闭失败边界`，文档收尾提交随后续最终 HEAD 记录；提交后无暂存内容；保留 36 个用户既有改动/删除及未跟踪 `context.md`，不推送、不操作生产。


## 一百一十九、第一百一十三阶段：恢复 3 项既有 core 测试契约（2026-10-22）

- 仅修复测试，不改生产逻辑：`safe_remote_fetch` 的 redirect FakeConnection 补齐 `connect_timeout`、`connect()` 与 `sock`；staging 两项测试显式把临时文件或对象 data/meta 时间戳移动到 1 小时 orphan grace 之外，并对只读 metadata 临时恢复写权限后回滚，保持“负数 age 也不能绕过 grace”的生产语义。
- 修复后 3 项定向通过；两个测试文件 58 项通过；完整 `tests/core` 1,624 passed、4 skipped、0 failed。严格 Ruff、compileall 与 diff 通过。Alembic stale readiness 保持第 112 批已实现的 503 行为，无需重复修改。

## 一百二十、生产更新前只读预检（2026-10-22）

- 本轮按 context → current_task → 当前 DEPLOY_PLAN 继续，仅执行本地读取、rsync dry-run 和服务器只读查询；未备份、同步、构建、迁移、重启、删除或推送。HEAD 为 `1f4a5064`；当前本地 `origin/main` 引用也指向该提交，原交接的 ahead 8 已过时，未联网 fetch 验证远端分支。
- 生产根盘 40G、使用约 13G、可用约 28G；app/scheduler/worker/admin/nginx/PostgreSQL/Redis 七个容器运行，app/PostgreSQL/Redis 容器健康。生产配置为 production/cloud_api，Alembic current=head=`v19_pomodoro_subject_allocations`。Redis AOF 已启用，最近写入与 RDB 状态均为 ok。
- 带 `Host: www.xzshub.top` 的 app 内部 `/health`、`/health/live`、`/api/v1/health` 均为 200；Nginx 公网 `/health/live` 为 200。未带允许的 Host 时 400 是 TrustedHost 限制，不是服务不可用。Nginx 容器直连 app `/health/ready` 为 200，响应 `status=ok,degraded=false`；公网 readiness 为 403，符合 allow/deny。宿主机 HTTPS loopback readiness 为 404，当前 Nginx 精确 location 只有访问控制而无 proxy_pass，后续需先验证并修复代理，再将其作为 HTTPS 验收入口；本轮未修改。
- PostgreSQL 备份位于 Docker 命名卷 `deploy_backup_data`，不是宿主机 `postgres_backups/`。最近文件 `postgraduate_postgres_20261021_143615.dump` 为 23,137,065 字节、权限 644、文件头 PGDMP；SHA-256 与 manifest 一致，manifest 记录 TOC 982 项；本轮未恢复验证。Redis 宿主机两份备份为 `redis_20261021_143619.rdb`（23,167 字节）与 `redis_20261021_231951.rdb`（23,256 字节），文件头 REDIS0012、权限均为 600。
- 发现定时备份故障：timer 已启用，但 2026-10-22 03:23:51 的 postgres-backup.service 退出 226/NAMESPACE；journal 明确报 `/opt/22408-ai/.docker` 不存在导致 mount namespacing 失败。服务器根目录也没有 Dockerfile.backup 所需的 `scripts/postgres_backup.py`，而 `.deployignore` 排除了根 scripts；已有备份镜像存在，但重新构建备份镜像会缺失 COPY 源。修复缺失目录、备份构建输入并执行一次新备份，应作为部署前独立步骤，等待生产变更授权。
- rsync dry-run（无 --delete）列出 14 个文件：后端 12 个、管理端 2 个（next.config.ts 与仅时间戳变化的 next-env.d.ts），另有目录时间戳。预演证据为 `/tmp/postgraduate-ai-rsync-dryrun.txt`。未涉及迁移文件，当前没有执行 schema migration 的依据。`deploy.sh update` 只构建/替换 app+scheduler，worker 必须按 DEPLOY_PLAN §9.1 单独构建和替换；管理端配置变更为开发专用，需要评估是否有必要重建生产 admin。
- 后续建议顺序：明确生产变更授权 → 修复备份运行/构建前置并完成 PG+Redis 新备份与权限/校验 → 保存远端待覆盖源码与三个角色镜像回滚点 → 复核同步预演后同步 → 分角色更新 app/scheduler/worker并 reload nginx → 验证 readiness、角色启动日志及允许范围内的接口；不默认迁移，不清理数据，不推送。现有全部 36 项用户修改/删除保留，context.md 保持未跟踪；本轮仅追加任务记录并更新交接。

### 部署前置本地修复（生产仍待授权）

- `.deployignore` 改为仅放行根 `scripts/postgres_backup.py`，其余根 scripts 子项继续排除。使用真实 rsync 在独立临时目录验证精确输出集合：7 项必需源码/部署文件保留，13 项开发脚本/嵌套脚本/凭据/数据库/测试/文档/小程序/日志排除；包含 Admin recommendation/reports 路由保留场景。未同步到服务器。
- `deploy/nginx/nginx.conf` 的精确 `/health/ready` location 补齐 backend 代理、Host/转发头和禁用 access log，沿用原有 allow/deny；未扩大公网访问范围。未修改 metrics location，也未 reload 生产 Nginx。本地无 nginx/Docker，尚未通过真实 `nginx -t` 或请求级验证，部署前须在隔离配置上验证，再 reload 并复测内网 ready=200、公网 ready=403。
- 现有备份脚本测试：`APP_ENV=test DEPLOYMENT_PROFILE=local_import APP_SECRET=<synthetic> DATABASE_URL=sqlite+aiosqlite:///:memory: REDIS_URL='' SENTRY_DSN='' backend/.venv/bin/python -m pytest backend/tests/test_scripts/test_postgres_backup.py -q --tb=short`，64 passed。只验证备份工具单元契约，不代表生产新备份或恢复成功。
- 获生产授权后，先只读复核 systemd `ReadWritePaths` 与 `DOCKER_CONFIG`，按实际缺失路径建立受限目录；将唯一备份脚本加入同步预演后提供给 backup 构建。执行新备份前盘点保留策略是否会删除已有文件，有删除候选则单列范围等待授权。PG 文件权限、TOC、manifest 哈希和 Redis 文件头/权限均需现场核验；全程保留既有备份及数据，不默认执行恢复、迁移或清理。
- 本地变更仅为上述两项部署配置与本任务/交接记录；既有用户修改及删除保留，未暂存、提交或推送。生产变更授权仍未获得，不把自动 goal 继续信号当作审批。

## 一百二十一、授权生产更新与基础验收（2026-10-22）

- 用户明确“确认授权”后执行本节操作；生产服务器及目录按当前 DEPLOY_PLAN。先保存旧源码、Nginx/systemd 配置、三个角色的镜像归档与容器元数据到 `/opt/postgraduate-ai-deploy-rollback/20261022_095116`；归档 SHA-256 已记录，目录 700/文件 600，容器 metadata 的 Env 值已脱敏。镜像归档供 `docker load` 恢复旧标签，源码归档用于回退；禁止以数据库 downgrade/删卷回退。
- 修复备份运行前置：建立 `/opt/22408-ai/.docker`（root、700），保留实际 systemd service 的其它配置；补同步 `scripts/postgres_backup.py` 并修复 `.deployignore` 唯一放行规则。`systemctl start postgres-backup.service` 完成 backup 镜像构建与新备份，Result=success/ExecMainStatus=0；timer 仍 enabled，下一次定时执行结果尚未观察。旧备份保留，无过期清理候选。
- Nginx readiness 精确 location 补代理并保留原 ACL。发现生产 bind mount 仍指向已删除的旧 inode，单纯 rsync/reload 不会更换该挂载；新建临时只读挂载容器确认新文件后，通过 Compose 仅重建 nginx 修复挂载。新配置真实 `nginx -t` 通过（已有 http2 directive 弃用 warning）。宿主机 `curl --resolve www.xzshub.top:443:127.0.0.1` 完整 TLS 验证的 readiness 为 200；独立外网 live=200、ready=403。以后单文件 bind mount 更新需核对容器内哈希，避免把 reload 误当作新配置生效。
- Redis 备份发现“文件生成并校验成功、最终退出 1”的缺陷：保留策略最后的 `[ "$deleted" -gt 0 ] && info ...` 在无过期文件时作为函数返回值。仅将该处改为完整 if，保留用户既有全部脚本修改。`bash -n` 通过、同步后真实备份返回 0，旧备份未删除。备份脚本现有 BGSAVE 超时后仍尝试复制旧 RDB 等其它语义未在本轮扩展。
- 代码同步使用 `.deployignore` 和 rsync，无 `--delete`；预演证据 `/tmp/postgraduate-ai-rsync-authorized-dryrun.txt` 与 `/tmp/postgraduate-ai-rsync-final-dryrun.txt`，关键源码/备份脚本/Nginx 本地与远端 SHA 一致。未覆盖服务器 `.env`、证书或私钥；未执行 migration。管理端只有开发专用配置变化，本轮同步源码但未重建或替换生产 admin。
- 角色更新使用 `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml build app scheduler worker`，构建退出 0，日志包含 `Skipping optional OCR dependencies (INSTALL_OCR=false)`；随后逐项 `up -d --no-deps app`、scheduler、worker，并 reload nginx。app 镜像 `85c3fbedba81`、scheduler `ea144ddc803c`、worker `680a629fba60`；三者 running/重启计数 0，app healthy。PostgreSQL、Redis、admin 未替换，七个服务运行正常；scheduler/outbox/reconciler/export 和 worker v2 dispatcher/prewarm 均有实际启动日志。
- 本地部署门禁：228 项启动/关闭/readiness/practice 契约测试通过（9 项 datetime 弃用与 1 项既有 aiosqlite 线程收尾告警）；变更后端严格 Ruff、全应用 Ruff（既有忽略项）、compileall、diff-check 通过。前序备份单测 64 passed 和真实 rsync 7 包含/13 排除仍作为本地证据；不将其计为生产业务验收。
- 生产基础验收：`deploy.sh status` 通过；容器内部 live、Nginx TLS live/API health、内网 ready 均 200，ready=`{"status":"ok","degraded":false}`；Alembic current=head=`v19_pomodoro_subject_allocations`，PG SELECT/Redis PING 成功；新角色日志无生产配置失败、schema divergence、ModuleNotFoundError、Traceback 或 ERROR。管理端 `/admin/login`、dashboard、questions、review 的 HTTP 响应均 200，未完成实际登录后的浏览器交互。新镜像 PyMuPDF 在内存中建页/写字/提取/渲染成功，伴既有 fitz API 弃用提示。
- 两轮备份分别覆盖部署前和部署后：部署前 PG `postgraduate_postgres_20261022_015340.dump`、Redis `redis_20261022_095425.rdb`；最终统一 `bash deploy/scripts/deploy.sh backup` 返回 0。最终 PG 在 `deploy_backup_data` 卷：`postgraduate_postgres_20261022_020908.dump`，23,137,065 字节、600、PGDMP、TOC 982，SHA `8d58a1ca6f44bec0f609962ffd7b8f0514f08f1d4da58bc7305a112b17eddb87`；Redis 宿主机 `/opt/22408-ai/redis_backups/redis_20261022_100911.rdb`，16,431 字节、600、REDIS0012。PG 文件名使用备份容器 UTC，`020908` 对应北京时间 10:09:08，不能按本地时区误读。未执行恢复演练。
- 验收限制必须保留：OCR readiness 的连接检查既有实现将 HTTP<500（含 401）视为可达；实际 health 请求为 401，所以 ready 非 degraded 不证明外部 OCR 可工作，未执行真实导入/OCR/AI。受保护科目接口通过一次运行时签发的用户 token 返回 200，但临时发题验证器先有导入路径、后有 `id`/`subject_id` 接线错误，未完成发题/提交/推荐日志契约验收；不据此宣称完整业务链通过，也不把该 token 验证冒充微信登录。未执行微信登录/刷新、SSE、真实提交、真机和真实 PostgreSQL 并发故障注入。
- 最终机器记录 `/opt/postgraduate-ai-deploy-rollback/20261022_095116/acceptance-summary.json`，构建与统一备份日志同目录；根盘约 26G 可用。临时验证脚本已从宿主机及 app 容器精确清理，未清理用户数据或既有证据。没有业务提交/导入验收写入，没有 schema 迁移、down、无缓存构建、镜像/卷清理、提交或推送。当前结论是“部署与基础设施验收通过，完整业务验收仍未完成”；后续先补业务验收，不以本轮结果宣称全栈重构完成。

## 一百二十二、部署镜像隔离 PostgreSQL/Redis 业务验收（2026-10-22）

- 在已授权服务器使用部署 app 镜像 `85c3fbedba81`，建立独立 PG15 + Redis7 临时容器：PG network none，Redis/app 共享该隔离网络命名空间，无发布端口、生产网络或数据卷；PG/Redis 数据仅 tmpfs，资源分别限 384m/64m，测试 app 限 512m。全部合成账号/题目/密钥，不读取生产凭据或业务数据。API 通过真实 Uvicorn TCP 发请求，采用 test/local_import、lifespan off；不将其称为 production/cloud_api 全生命周期验收。
- API 32 项通过：匿名拒绝、测试登录/refresh 轮换及旧 token 拒绝、`subject_id` 契约、random/scored/path 实际发题、修订签名/科目活动态守卫/答案与解析隔离/private no-store、path 最终下发日志且无候选 knowledge_path 日志、非法 count422、顺序重试题目与 batch token 相同。两个真实 PG 并发同载荷提交均200且 canonical 业务结果相同，各自 trace 不同；重放200、同 request 改载荷409；独立查询确认仅一 session/两 records/两 outbox，孤儿 outbox 恢复。
- 在合成 PG 上临时注入 outbox CHECK 约束，第三条答题故意得到500，独立会话查询确认 session/records 均整体回滚；移除仅该合成故障约束后同请求成功200。日志中的该500为预期故障注入，不是生产业务报错；生产库未创建约束或提交答题。
- 合成 Admin bcrypt 登录/HttpOnly refresh cookie、问题读取 RBAC、用户/Admin token 双向拒绝、Admin refresh 轮换通过；ready 明细中的合成 PG/Redis 为 ok。实际 TCP SSE 订阅合成 Redis Pub/Sub 后收到 trace/done，Content-Type 与 X-Accel-Buffering 符合契约。测试登录使用开发确定性 code，不等同真实微信 jscode2session；SSE 使用合成事件，不证明真实 OCR 任务成功。
- 投影追加 15 项通过：真实 outbox dispatcher + queue adapter 将三条 outbox 标记 published，Redis v2 ready/claim/complete 及错误 owner 拒绝，真实 `_process_answer_projection_task` 将三条记录投影为 completed、生成各一条 AnswerBehavior，重复处理不增行，answer_projection ready/processing 均0。覆盖实际生产 handler，但未启动完整 worker 主循环，未注入 Redis 中断、lease 过期/回收或多 dispatcher 并发。
- 临时验收脚本修正过程留证：API 首轮误比较每请求不同的 trace_id，后改为比较其余 canonical 内容并独立确认 trace 不同；投影首轮漏 await stop 函数，并误把 Task dataclass 的 generation 当成 Lua 权威代际，实际 Lua 比较 Redis stored/fencing generation。错误脚本提前完成一个队列任务，随后按该 outbox 原 payload 用新合成 ID 重投，三个真实 handler 均完成且业务无重复；中间一次误重跑旧脚本也保留日志。没有为通过验收修改生产源码，不能据此宣称“首轮全部通过”或覆盖了 stale generation 故障。
- 回滚目录 `/opt/postgraduate-ai-deploy-rollback/20261022_095116` 保存 `isolated-acceptance.py/.log`、`isolated-projection.py/.log`、失败尝试日志、`isolated-acceptance-summary.json`；后者记录 32+15 检查、隔离拓扑/资源、镜像身份与脚本/日志 SHA。总 `acceptance-summary.json` 已追加结果并保留生产限制；目录700、产物600。
- 精确核对 `memograd.acceptance=20261022-practice` label 后依次停止本轮 Redis/PG，容器按 --rm 自动移除、tmpfs 释放，证据保留。2026-10-22 10:32（北京时间）复查该 label 残留容器为0；生产七容器 running/重启0，app healthy，完整 TLS ready=200、degraded=false。未迁移、未清理生产数据/备份/卷、未提交或推送，用户既有工作区改动保留。
- 尚待真实条件验收：真实微信登录/真机、外部 OCR/AI/导入、生产 Admin 浏览器登录交互、Redis 中断恢复/lease 回收/完整 worker 循环、多 dispatcher 并发、生产角色退出与备份恢复演练。PG 同载荷并发和 PG 事务故障回滚已通过合成真库验证，不能再笼统标作“PG/Redis 全未验证”；亦不能把本节扩大为完整生产业务或全栈治理完成。后续仍按交接的阶段0语义审查/兼容基线及各域剩余治理顺序推进。

## 一百二十三、第一百一十四批：学习数据语义基线与科目投影（2026-10-22）

- 按交接回到阶段0，新增 `docs/architecture/LEARNING_DATA_COMPATIBILITY.md`：登记专注动作/设置/统计/history、用户 stats/report、学习计划与 Admin dashboard 的真实入口、消费者、事务与时间/次数口径、迁移/保留理由。纠正旧清单将 `/sync/import` 归学习数据的错误：实际为 Admin `sync:write` 题库同步导入。图工具不可用，调用关系以当前源码核实，不据旧索引缺失判断死代码；全域语义审查仍未完成。
- 原 `pomodoro_service` 四个纯 helper 迁至 `pomodoro_subject_projection.py`：旧会话科目可用性、持久化/lite 快照优先级与顺序、删除科目分组身份、整数秒最大余数分配。服务实际 snapshot 直接消费新函数，不保留旧私有定义/转发壳；开始校验与投影统一使用已有中立 `EXAM408_CORE_CODES`，与旧 tuple 严格同序。无路由/schema/model/事务/客户端/生产改动，四科均分方案保持原行为。
- 发现学习计划的相似分配函数在原始权重分母、异常/非正权重处理、输入裁剪和顺序上与统计不同，因此本批明确不合并；stats/report 的自然日、accuracy 比例与百分数、待复习事实来源也不能仅凭命名合并。后续需先刻画实际消费者，不能通过通用 helper 偷换口径。
- 先在原实现运行新增22项刻画，全部通过，再迁移；含实际 snapshot 跨日调用，确认两个每日1秒先分科后加总为第一科2秒，而非合计后1/1；开始日次数、参与次数及一次有界加载同时受约束。迁移旧权重3测试，新架构3门禁接入原 CI，约束唯一 core 依赖、新进程无配置/数据库/模型/任务副作用、实际接线/无重复定义及100行/50行预算。
- 临时差分290组返回值/异常一致；四个函数除改名/文档外 AST 一致，服务剩余实现经精确符号重命名和常量迁移归一化后 AST 一致；旧常量与中立 tuple 相同。独立进程重构前后完整 OpenAPI 都328路径、SHA相同。新模块75行，最长函数29行，service1756行，snapshot仍338行，后续继续治理聚合编排。
- 扩大定向125项中112通过、13失败；独立进程加载抽取前 service 复跑对应文件同样13失败/19通过。根因是旧 `test_practice_session_stats.py` 的 batch-submit 必填参数、缺失 session、answered_count、超墙钟 duration 等预期已过时，不放宽当前生产提交语义。另运行 stats/report 两文件得到24通过/8失败，失败均是异步 `db.connection()` 被旧 fixture 配成普通 MagicMock，两个服务文件本批未变。这21项已登记后续独立测试修复，不隐瞒为全部回归通过。
- 原 YAML 三步骤真实重放全部退出0：static/non-GPU 2,144通过（2条既有 datetime 弃用告警）、mocked readiness 69通过、cloud OCR 30通过。日志 `/tmp/memograd-subject-projection-ci-{static,readiness,cloud}.log`、`/tmp/memograd-subject-projection-ci-status.json`；定向/旧实现失败对照及290组差分脚本同前缀保存。严格 Ruff、全应用 Ruff、compileall、diff-check通过；当前图580模块/2259边/零静态循环/零反向API。
- 本批不创建子agent、不操作生产或数据库、不改客户端、不删除资源、不推送。开始时记录40个既有工作区路径的内容/删除状态，记录本节前逐项一致；后续只允许任务记录/context变化，其余保持。代码/测试/CI/架构文档使用8个显式路径本地提交，部署相关改动和当前任务前序记录继续保留在工作区，context仍未跟踪。
- 下一顺序：先独立修复上述统计测试契约，恢复可信学习数据基线；再扩充 snapshot 组合/错误/取消入口契约并治理窗口/累计/响应职责。完整阶段0、管理端 imports/review 组合、小程序完整controller、学习域/队列/OCR与真实provider/设备验收仍待继续，整体目标保持active。
- 本批已按上述8文件提交为 `b3fd0967 refactor(pomodoro): 分离统计科目投影与兼容基线`。未把本任务的前序部署记录、context、部署配置或用户既有修改纳入；当前任务记录继续保留未提交，暂存区为空，不推送。

## 一百二十四、第一百一十五批：恢复学习数据统计测试契约（2026-10-22）

- 按交接修复第114批发现的13+8项既有测试缺口，只改测试/CI/架构记录，`backend/app` 无差异。没有放宽签名批次、session、版本、request_id、时长、用户或科目边界，不添加 skip/xfail，不将旧客户端的过时预期恢复进生产实现。
- `test_practice_session_stats.py` 使用规范学科码、真实 `ensure_question_revision`/最新修订查询与真实 HMAC signer；只将 signer 的签发时钟固定在本次合法会话开始时间，保留实际解码、归属、时序和过期校验。重试复用同一完整 payload/token，确认响应一致且 session/record/outbox 各1；双题提交验证正确/错误计数、canonical response、pending记录与outbox来源关联。
- 原“无session仍写答案”“超墙钟裁剪”“超长request_id哈希”“无效科目回退”的断言改为当前协议的拒绝与三表零残留。明确 session/batch token/skipped IDs 必填、answered_count 与实际一致、104/128字符原样保存、129/255/263字符拒绝、时长墙钟/上限及负值/缺省退化规则。非法 session 整笔拒绝，不能误写成仍保留答案。
- used_time 用例先确认提交后只存在pending答题和outbox、没有行为记录，再对正确/错误题调用真实 `project_practice_answer`，确认分别40/120秒、每条行为关联正确源记录。临时SQLite fixture 重置本模块自建库全部表以排除无FK cascade时的outbox/错题/掌握度残留，不清理用户数据或仓库数据库。
- `test_stats_service.py`/`test_study_report_service.py` 补齐 awaitable `db.connection()` 与真实dialect名称，固定北京时间日期。新增SQLite/PostgreSQL SQL编译检查，验证+8小时分桶、用户/科目过滤、365日与指定天数窗口，以及date/string两类返回值的确定结果；PostgreSQL未实际执行，不称真库验收。
- 新增真实SQLite日期聚合链：两条有效修订答题在UTC 2026-10-21 15:59:59和16:00:00分别进入北京时间21/22日，连续2天、报告100%/0%、无数据补零和另一用户仅1天均通过实际查询。与原时长合并/暂停/跨日/历史分页用例一起保持覆盖。
- 扩大相关回归174通过（7条既有datetime弃用告警），随后新增的SQLite零点/隔离用例独立1通过；修复过程中规范学科码后同步修正一处旧code断言。最终CI结果另记下行。三份恢复测试全部加入原YAML static步骤，不使用手工拼接列表代替原门禁。
- 严格Ruff、全应用Ruff、compileall、diff-check已通过；本批新写/重写helper与用例均不超过50行。开始时登记40个既有工作区路径，更新任务前逐项哈希/删除状态保持一致；部署脚本/配置、用户改动与删除不纳入本批。按6个显式测试/CI/架构文档路径本地提交，不push、不部署、不触及生产数据；context与当前任务继续保留未提交。
- 后续恢复既定顺序：先扩充338行 `build_pomodoro_statistics_snapshot` 的组合维度、空窗口、加载/归属失败与取消真实入口契约，再分离窗口/累计/响应职责；阶段0全量语义审查及管理端/小程序/队列/OCR深层治理、真实provider/设备验收仍未完成。
- 最终原YAML重放：static/non-GPU 2,226通过（8条既有datetime弃用告警）、mocked readiness 69通过、cloud OCR 30通过，全部退出0。日志 `/tmp/memograd-stats-contract-ci-{static,readiness,cloud}.log` 与 `...-status.json`；没有将编译的PG SQL或SQLite结果称为PG真库验收。
- 独立review-agent对本批6文件及当前权威实现做只读静态审查，未发现可行动findings；未修改文件、未重跑CI、未访问生产。主agent持有的实际测试结果与审查分开记录，保留PG真实聚合/完整worker消费未验收限制。
- 已提交为 `745403f0 test(stats): 恢复签名提交与日期统计契约`，仅6个既定路径；当前任务与context继续留在工作区，暂存区为空，未推送。

## 一百二十五、第一百一十六批：统计快照窗口与响应边界（2026-10-22）

- 开始前读取 context/current_task；记录并保护40个既有工作区路径的哈希/删除状态。所有原有内容及删除状态复核仍一致；本批仅新增模块/测试和改动 `pomodoro_service.py`、原CI清单与本交接文档，无部署/生产动作。
- 在未改实现上先新增完整入口 `test_pomodoro_snapshot_contract.py`，177项通过：四个 need 维度16组合 × `range_include_subjects` × `day_start_minute`(0/360) × 空/非空；精确结果、union窗口、一次双loader及with_subject选择；无维度时只取settings与today且不查询；完整 helper 次序；40余个边界阶段逐个普通异常/`CancelledError` 对象身份与短路；非法range先执行之前维度的边界调用再拒绝且不加载；range禁用时忽略range输入；互不相交窗口的并集；真实 attribution 下0秒终态仍计次数、无subject切片/active day。测试只用拒绝所有DB访问的对象及受控IO helper，时间归属/秒分配仍走真实实现。
- 第116批原实现契约发现并修正仅测试里误算的stats窗口结束边界（实际是周窗口右端，不是今日+7天），修正后抽取前整套177项通过。普通/取消注入覆盖settings、today、全部日期/周边界helper、两类loader、session active/拆日、科目projection/秒分配、练习拆分及响应builder。
- 窗口范围纯规则抽至 `pomodoro_statistics_window.py`，单向、无SQL/框架/运行资源依赖。service明确传入所有flags/date/DM及原 `study_day_utc_range`、`study_week_utc_range` 端口；保留stats→trends→daily→range计算和验证顺序，service保留settings、请求上下文、双loader、第二次周界读取、来源循环、归属与异常所有权。两来源仍严格一次同union window加载。
- 响应DTO抽至 `pomodoro_statistics_response.py`：只按请求维度生成旧字典，保留键/子字段、timezone/DM、range日期、subject排序只按duration稳定降序；不排序/修改输入groups，不归属/查询/提交。service仍拥有累积和source loop，避免第二次扫描替换原源数据顺序。零数据、零秒、平手顺序、范围禁用/空字段已有入口和纯builder契约。
- 改动初期静态CI路径误引用尚不存在的独立响应边界文件，真实YAML重放立即失败并已修正：响应纯性/维度AST/预算/真实调用/新进程无副作用门禁合并在 `test_pomodoro_statistics_window_boundaries.py`，原CI只添加实际存在路径。readiness/cloud两步此前均通过，修正后原YAML三步均通过，最终数见本节末尾。
- 定向全链（快照入口、既有study-day/科目projection/分配、review/practice/report及两个架构门禁）353项通过、8条既有时间弃用警告；新增纯builder平手/不修改输入契约后尚需复跑包含该新增用例的相关门禁。focused snapshot相关251项通过。严格Ruff、全应用Ruff、compileall、diff-check曾在最终一项builder测试增加前通过，增加后要重跑；真实PostgreSQL未使用。
- 主agent请求独立agent只读审查窗口与响应抽取，agent未发现可行动findings；它未编辑文件、未运行CI。最终测试/YAML门禁由主agent实跑，不把review替代测试。
- 抽取后新增平手builder纯契约（输入顺序稳定、相同duration不重排、输入group未变）后，相关焦点回归255通过（2条既有datetime弃用告警）；严格Ruff、全应用Ruff、format check、compileall、diff-check通过。原CI最终重放全绿：static/non-GPU 2,411通过（8条既有datetime弃用告警）、readiness 69通过、cloud OCR 30通过；一轮最初重放因新增门禁文件名写错立即失败，修正到实际存在的合并门禁文件后完整原步骤成功。日志 `/tmp/memograd-snapshot-contract-corrected-ci-{static,readiness,cloud}.log` 与 status JSON。
- 窗口模块55行/最长函数32行，响应模块99行/最长函数47行；统计snapshot约280行，数据库加载、累计循环仍由service拥有。重构前后完整328路由OpenAPI保持前序证据，本批没有修改HTTP契约。真实PostgreSQL日期/并发、外部provider/设备不在本批范围。
- 主agent发起的独立review-agent只读审查未发现可行动finding；该审查未跑门禁，由主agent的上述结果提供执行证据。按六个显式路径本地提交为 `2753ccf9 refactor(pomodoro): 分离统计窗口与响应组装`；未包含current_task/context和其他既有修改，无推送/生产操作。下一步继续拆累计状态初始化与双来源累计，不能把整个snapshot宣称治理完成。

## 一百二十六、第一百一十七批：统计来源累计边界（2026-10-22）

- 按第116批交接继续，先复核工作区：HEAD `2753ccf9`、暂存区空；保护基线中 38 个非任务记录路径的内容/删除状态全部一致，仅 `prompts/tasks/current_task.md` 与 `prompts/tasks/context.md` 在本轮发生允许的任务记录变化。所有部署配置、小程序资源删除等用户改动保持原样。
- 新增 `pomodoro_statistics_accumulation.py`（225行）：`StatisticsAccumulationState` 由调用方构造并拥有，专注与补充累计按 sessions 列表顺序遍历；传入 `terminal_statuses`、active/拆日/排除累计、study-day、resolve_allocations/allocation_group_key/allocate_seconds_by_weight、resolve_subject 全部显式端口。模块依赖图为空，不执行 SQL、commit、rollback、flush 或 create_task。
- 快照保持窗口加载→week 计算→状态初始化→focus accumulate→supplemental accumulate→response 的原顺序；`counted_spans` 仍只由专注来源填充并被补充来源消费。顶层番茄次数、每日/范围逐日先分科再汇总、终端态参与口径、补充会话科目 sessions 不计参与均保留。未启用 trends 时不再构造空 trends dict，避免响应误取空内容。
- 新增跨日暂停重叠与来源顺序刻画：专注 30 分钟横跨午夜且暂停30分钟，补充会话从专注暂停起点开始并重叠；两源 3600 秒分别进入两天，range 合计7200秒、active_days=2，响应科目按时长稳定排序（平手保持专注先插入）。另补专注/补充两来源的普通异常与 `CancelledError` 对象身份及响应短路契约。
- 架构门禁新增：累计模块依赖为空、225行/最长函数50行内、无禁用 I/O 调用；snapshot 顶层按 focus→supplemental 顺序调用且共享同一 `state`；新进程导入累计模块不加载 config/database/models/service/runtime。原科目投影门禁改为校验 snapshot 将真实投影符号作为端口传给累计器，不再要求留在 service 内直接调用。
- 定向回归从初始243项到最终257项通过，含2条既有 datetime 弃用告警；readiness 69项与 cloud OCR 30项通过。原 CI static manifest 由 YAML 原样抽取 129 文件，首轮 2,419项中2,418通过、1项失败，正是上表旧投影调用门禁；按新边界修正后对应196项聚焦回归通过。
- 严格 Ruff、全应用 Ruff（忽略 I001/F401/N818）、新增文件与测试 ruff format check、compileall、`git diff --check` 均通过。service 净减约127行，snapshot 保留窗口加载、来源顺序、状态与响应所有权，不宣称所有统计职责已收尾。
- 独立只读 review-agent 审查最终累计边界后返回“无 findings”；未运行测试，测试证据由主 agent 实跑获得。未修改 HTTP schema/OpenAPI，未部署生产，未操作数据库，未推送。
- 本批显式提交 5 个路径：`backend/app/services/pomodoro_service.py`、新增累计模块、两个统计测试文件、原 CI 中已存在的实际门禁路径无需修改。不包含 current_task/context 和其他既有工作区改动。

## 一百二十七、第一百一十八批：共享学习统计自然日投影（2026-10-22）

- 按第117批交接顺序回到阶段0/学习数据域，读取 context、current_task 并复核 HEAD=`8da10326` 与现有脏工作区。保护基线中非任务记录的既有部署、小程序资源/配置路径均保持原内容/删除状态；本批只改两个后端 service、趋势测试、CI、学习数据兼容文档、架构盘点及当前任务/context。
- `stats_service` 与 `study_report_service` 重复的 `_china_date_expr` 收敛到 `learning_time_projection.china_date_expr`；SQLite 使用 `date(column, '+8 hours')`，PostgreSQL 保持 `CAST(column + INTERVAL '8 hours' AS DATE)`。同时共享 stats 使用的小时 SQL 表达式、SQLite 字符串/PostgreSQL date 的 coerce、北京时间自然日 UTC 起点与 range 转换。`shanghai_today`、`shanghai_date_utc_range` 仍从 `core.time_utils` 直接引用，保留原唯一时区事实来源。
- 两消费者通过原私有符号名直接导入唯一函数对象，不保留函数体或转发壳。连续日365天边界、stats trends 查询起点、遗忘趋势界限、study report days 起点均切换到共享 date range helper；accuracy、待复习模型/状态、用户过滤和各自聚合协议保持原样，未将两域业务语义强行合并。
- 原 `test_trends_previous_period.py` 在当前 schema 下未提供必填 `question_version_id`，且 dashboard 测试只冻结 `utcnow`、未冻结实际用于趋势窗口的 `shanghai_today`。只补该非空 fixture 字段，并同时冻结两个既有时间源；不放宽 DB schema、生产提交或日期边界。将这份15项趋势回归及新架构测试加入 CI 静态清单。
- 新增架构门禁约束中立模块只依赖 `core.time_utils`、消费者引用共享函数对象、无服务重复定义、函数/文件预算与新进程导入无应用配置/模型/runtime副作用。模块按 dialect 读取 `db.connection()` 保持原有行为，这不是无 DB 调用的纯模块；其职责是共用 SQL 时间投影，不负责查询/事务。
- 先运行 stats/report/trend/真实 SQLite 跨零点/隔离与新边界组合回归，153项通过、6条既有 `datetime.utcfromtimestamp` 弃用告警。最终原 YAML static/non-GPU manifest 从131条明确测试路径收集2,437项，全通过（8条既有 datetime 弃用警告）；mocked readiness 69项、cloud OCR 30项通过。SQL dialect覆盖为 SQLite 真实执行与 PostgreSQL SQL 编译/既有替身，不宣称本批执行真实 PostgreSQL。
- 严格 Ruff、全应用 Ruff（忽略既有 I001/F401/N818）、compileall、diff-check通过。趋势测试最终仅保留15行必要变更，没有整文件格式化噪声。独立只读 review-agent 对完整最终差异无 findings；审查未运行测试，主 agent 的测试结果单独记录。
- 本批已本地提交为 `039537f2 refactor(stats): 共享自然日时间投影`，仅含 backend helper、两个消费者、趋势/架构测试、CI 和两份学习数据架构/兼容文档；current_task/context 与所有既有部署、小程序等工作区改动不纳入。未改 API、schema、数据库、外部配置或生产镜像；不推送、不部署。
- 下一步继续全量阶段0语义审查/兼容基线，之后按计划推进 Admin imports/review 剩余组合、小程序番茄钟 controller、学习闭环及任务队列/OCR；全栈目标保持未完成。

## 一百二十八、第一百一十九批：审核来源定位规则（2026-10-22）

- 按第118批交接继续处理 Admin imports/review 的剩余页面组合。先复核 HEAD=`039537f2`、暂存区为空和既有工作区改动；只改审核页、其来源规则/边界测试及本任务/架构盘点，不触碰部署配置、小程序资源删除或其他用户改动。
- 将页面私有的 `getSourceQuestionNo`/`getSourceLocator` 迁至 `imports/review/review-source-location.ts`。模块只依赖 API 类型和既有 `review-display-text.isMeaningfulText`，拥有显式题号/标签/原文题号解析及图号、文件名、起止页、来源类型定位拼接；页面继续拥有列表/批量结果上下文，调用点不改。
- 保留旧行为：第一个非空原文字段作为题号解析输入，不在格式不匹配后继续尝试后续字段；`source_type` 继续经 `isMeaningfulText` 过滤 `unknown`/空占位；图号使用 nullish 合并、页码单页/跨页分支及 ` · ` 分隔顺序不变。
- 新增4项规则测试覆盖显式优先级、三种原文题号格式、原文字段优先、显式定位优先、图名/页码组合、raw_data 回退、source_type 过滤和空来源。临时转译新旧实现做 3,766,532 组字段/假值/页码组合差分，结果逐字一致；该差分是静态规则对照，不是浏览器或生产验收。
- 管理端定向 29 项、完整 Vitest 57 文件 793 项通过；`npm run typecheck`、`npm run lint`（0 errors，132 既有 warnings）、`npm run build`（33 路由）通过。新模块51行，页面 2496→2455 行；边界门禁新增依赖/300/50预算。未改请求、mutation、审核状态、JSX 或 API 契约；浏览器交互、微信端、真实 provider/生产未验证。
- 独立只读 review-agent 核对旧函数逐分支与调用点后，仅提出一项 P2：测试未覆盖 `source_type` 大小写变体。补 `uNkNoWn` 原样保留断言，确认继续忠实复用 `isMeaningfulText` 的精确大小写过滤，未顺手改变共享规则；复审后无剩余 findings。审查未运行测试，主 agent 的测试/构建证据单独记录。
- 最终复核相关27项、完整57文件793项、typecheck与lint（0 errors/132既有warnings）通过；Next build此前在最终测试断言加入前已通过33路由，本次改动仅测试文件，不重复构建。显式提交5个源码/测试/架构盘点路径为 `8d7c6787 refactor(review): 分离审核来源定位规则`，不含任务记录/context或既有部署、小程序、日志改动；未推送、未部署、未操作数据库。
- 下一步继续审核页的筛选/预览/弹层状态组合，随后按阶段0盘点推进小程序番茄钟 controller、学习闭环及任务队列/OCR；完整全栈治理仍未完成。

## 一百二十九、第一百二十批：审核 AI 建议与答案等价规则（2026-10-22）

- 按第119批交接继续审核页剩余组合，先复核 HEAD=`8d7c6787`、暂存区为空及既有工作区改动。只改审核页、AI建议/答案规则与边界测试、本任务/架构盘点；未改请求、mutation、审核状态或 JSX 结构。
- 将 `completeSuggestionFromItem`、`stringSuggestion`、`normalizeAnswerForCompare`、`answersEquivalent` 迁至 `review-completion-suggestion.ts`。模块只依赖 API 类型；页面直接引用四个函数，不保留旧私有实现或转发壳。建议仍只接受非数组对象，字符串建议仍 trim 后要求非空，答案仍把中英文逗号/顿号/分号/空白统一为逗号、去首尾逗号、纯字母选项排序，其他文本保持原格式。
- 新增4项测试覆盖非对象建议拒绝、字符串建议、答案分隔符/大小写/空值及等价判断；特别钉住旧实现的空白转逗号行为（`c, a` → `c,,a`，`选项 A` → `选项,A`），不以重构顺手修复业务规则。
- 新旧实现转译差分 457 组全部一致，覆盖建议对象/数组/原始值、字符串 trim、答案规范化与等价组合；独立只读 review-agent 另做 735,386 次新旧结果对照并核对页面 `answerSuggestionApplied` 接线与页面其余 AST，未发现 P0-P3 findings。两者的差分均为纯规则对照，不是浏览器或生产验收；审查未运行完整门禁。
- 管理端完整门禁通过：58 文件 798 项 Vitest、typecheck、lint（0 errors/132 既有 warnings）、build 33 路由。页面 2455→2433 行；新模块 32 行，依赖/300/50预算门禁已登记。真实浏览器交互、微信端、真实 provider/生产仍未验证。
- 显式提交5个源码/测试/架构盘点路径为 `e53a88d3 refactor(review): 分离AI建议与答案等价规则`，不含任务记录/context或既有部署、小程序、日志改动；未推送、未部署、未操作数据库。

## 一百三十、第一百二十一批：审核列表与表格徽章规则（2026-10-22）

- 按第120批交接继续审核页剩余组合，先复核 HEAD=`e53a88d3`、暂存区为空及既有工作区改动。只改审核页、徽章规则与测试、审核边界与两份架构文档；未改请求、mutation、审核状态、JSX 结构或 API 契约。
- 将列表/表格的答案状态、风险和原题来源徽章投影迁至 `review-queue-badges.ts`，保留两种视图原有的已知/未知状态回退、空答案判断、`source_image_seq=0` 和显式来源字段语义；页面 2433→2399 行。新增 22 项规则刻画，完整 Vitest 59 文件 821 项、typecheck、lint（0 errors/132 既有 warnings）、Next build 33 路由通过。主 agent 对 181,440 组输入的两种视图结果逐项对照，共 362,880 个结果一致；独立 review-agent 另对 16,128 组边界及叶级 JSX 核对后返回 No findings。新模块 49 行，已加入依赖/300/50 预算门禁。
- 本批未改变请求、mutation、审核状态、JSX 结构、API 或数据库；未执行浏览器渲染、微信端、真实 provider/生产验收。一次额外 AST 打印比较脚本因提取旧源码片段的比较方式不成立而退出非零，未作为验收证据；行为差分、独立审查、类型、测试、lint 和 build 均通过。
- 已显式提交 5 个源码/测试/架构路径为 `00324328 refactor(review): 抽取列表状态徽章规则`；不包含 `current_task.md`、`context.md` 或任何既有部署、小程序、日志改动。未推送、未部署、未操作数据库。

## 一百三十一、第一百二十二批：审核筛选默认值与抽屉状态规则（2026-10-22）

- 按第121批交接继续审核页“筛选、预览与弹层状态组合”，先复核 HEAD=`00324328`、暂存区为空及既有工作区改动。只改审核页、筛选/抽屉规则与测试、审核边界及两份架构文档；不触碰部署配置、小程序资源/配置、日志和其他用户改动。
- `review-query-state.ts` 新增 `createDefaultReviewFilters()` 与 `shouldShowReviewFilterReset()`：默认筛选固定为 `status: "pending"`，其余为空；重置可见性继续忽略 `status` 与 `source_type`，只看 `batch_id/subject_id/risk_level/answer_status/keyword`。重置按钮仍只重置筛选，不清空 `selectedIds`、预览或编辑状态；队列请求仍使用独立的 `debouncedKeyword`，未改变 URL batch id 回退和 query key/请求生命周期。
- 新增 `review-drawer-state.ts`，承接预览 JSON 快照、segments 序列化/深拷贝、编辑会话初始化及未保存修改检测。保留点击时快照、`null`/`undefined`/空 segments 在克隆时均为 `null` 而序列化均为 `"[]"`、未编辑时不比较、编辑时分别比较编辑状态与 segments 的既有语义；`window.confirm` 同步时序、取消后提前返回、异步保存/审核/AI/批量回调顺序均未改。
- 页面 2399→2410 行（`ImportReviewPage` 2223 行）；新增模块 63 行、测试 125 行，边界门禁登记依赖与 300/50 预算。完整 Vitest 60 文件 831 项、typecheck、lint（0 errors/132 既有 warnings）、Next build 33 路由通过；最终复核 typecheck 与 3 个定向文件 37 项通过，`git diff --check` 通过。筛选重置可见性对照 16,384 组、未保存检测对照 216 组、预览/segments/编辑会话新旧结果均一致。
- 独立只读 review-agent 基于冻结补丁 SHA256 `e5d8b4c8…b7bb` 核对 6 个 diff（含 2 个新增文件）、3 个定向文件 37 项及 review 目录 30 文件 277 项，未发现本次补丁引入的 P0-P3 行为回归；审查未修改文件或操作 Git/数据库/生产。该差分是纯规则对照，不能替代浏览器、微信、真实 provider 或生产验收。
- 已显式提交 8 个源码/测试/架构路径为 `5366b506 refactor(review): 分离筛选与抽屉状态规则`；不包含 `current_task.md`、`context.md`、`AGENTS.md` 或任何既有部署、小程序、日志改动。未推送、未部署、未操作数据库。

## 一百三十二、第一百二十三批：审核批量补全草稿适配（2026-10-22）

- 按第122批交接继续“批量 AI 补全草稿适配”，先复核 HEAD=`5366b506`、暂存区为空及既有工作区改动。只改审核页、批量补全草稿规则/测试、审核边界及两份架构文档；不触碰部署配置、小程序资源/配置、日志或其他用户改动。
- 新增 `review-batch-complete-draft.ts`，承接十个可补全字段及前四项默认值、字段切换、localStorage 读写/清除、旧草稿策略修复。页面保留草稿恢复提示、3 秒提示、自动保存 effect、批量请求字段/strategy、执行锁、结果展示和 `batch-complete-draft` 键对应的生命周期。
- 保留既有语义：保存 payload 仍为 `{fields,strategy,savedAt}` 且时钟只在 JSON 序列化时读取；缺失 key、空字符串、非法 JSON、`null`、非数组 `fields`、storage provider/读/写/删抛错各自按原路径保守回退；任意非 `force_overwrite` 策略归一为 `fill_empty`；字段切换保持原重复项删除和追加顺序；清空草稿恢复四字段默认值。
- 页面 2410→2407 行（`ImportReviewPage` 2213 行），新增模块 82 行、测试 134 行；依赖/300/50 预算已登记。草稿新旧转译差分 302 组及默认值/全字段顺序一致；完整 Vitest 61 文件 839 项、typecheck、lint（0 errors/134 既有 warnings）、Next build 33 路由通过，review 目录 31 文件 285 项、定向 35 项通过。
- 曾尝试增加 jsdom 集成测试，但项目未声明 `jsdom`，Vitest 无法启动该文件；未安装依赖、未修改锁文件，已移除该测试。最终证据仅来自 Node 存储替身测试、真实转译差分和现有 React 构建，不能据此声称真实浏览器 localStorage 交互验收通过。
- 已显式提交 6 个源码/测试/架构路径为 `5987b6fc refactor(review): 分离批量补全草稿规则`；不包含 `current_task.md`、`context.md`、`AGENTS.md` 或既有部署、小程序、日志改动。浏览器、微信、真实 provider 与生产仍未验证；未推送、未部署、未操作数据库。

## 一百三十三、第一百二十四批：审核确认弹层展示状态（2026-10-22）

- 按第123批交接继续审核页剩余弹层编排，先复核 HEAD=`5987b6fc`、暂存区为空及既有工作区改动。只改审核页、确认弹层规则/测试、筛选类型测试、审核边界及两份架构文档；未触碰部署配置、小程序、日志或其他用户改动。
- 新增 `review-confirm-dialog-state.ts`，按 `ReviewActionState | null` 与已选数量生成弹层标题、说明、确认文案、危险态及驳回原因输入可见性。保留低风险批次固定文案、单题通过/驳回文案、已选批次通过/驳回数量说明、无选择批次回退 `question_imports` 说明，以及仅 `reject`/`batch-reject` 显示原因输入。
- 页面仅接入该纯函数；`ConfirmDialog` 开关、取消/确认回调和 `actionMutation` 仍在页面。新旧动作×选择数 36 组展示状态逐项一致；完整 Vitest 62 文件 852 项、typecheck、lint（0 errors/134 既有 warnings）、Next build 33 路由通过。页面 2407→2399 行（`ImportReviewPage` 2213→2204 行），新模块 32 行/测试 51 行，依赖/300/50 预算已登记。
- 读取上一批审查时发现一项 P3：`review-query-state.test.ts` 未表达 `ReviewFilters` 不应直接传给请求参数 builder 的类型排除契约。已补 `satisfies Parameters<typeof buildReviewQueueParams>[0]` 的编译期守卫；运行调用未改，类型检查通过。该修复随本批测试提交，不单独改变生产行为。
- 已显式提交 7 个源码/测试/架构路径为 `52bfbb6c refactor(review): 分离确认弹层展示状态`；本批未改请求、mutation、审核状态、API 或数据库。浏览器弹层交互、微信端、真实 provider/生产仍未验证；未推送、未部署、未操作数据库。

## 一百三十四、第一百二十五批：快速补充答案弹层视图状态（2026-10-22）

- 按第124批交接继续审核页剩余弹层编排，先复核 HEAD=`52bfbb6c`、暂存区为空及既有工作区改动。只改审核页、快速补充答案视图规则/测试、审核边界及两份架构文档；未触碰部署配置、小程序、日志或其他用户改动。
- 新增 `review-batch-answer-view-state.ts`，集中文本/图片页签的结果优先级、状态栏文案、页签/输入/预览/结果可见性及加载遮罩文案。保留 `batchAnswerApplyResult → batchAnswerPreview → imageApplyResult → imagePreviewResult` 的跨页签文案优先顺序、文本/图片结果均存在时隐藏页签、文本 tab 只显示文本步骤、图片 tab 只显示图片步骤，以及“解析/识别/写入”三类既有加载文案。
- 页面只接入纯视图状态；请求 hooks、预览 token/操作 ID、文件选择/移除、重置、mutation、执行锁和关闭回调均留在原位置。新旧页签×四类结果状态 36 组对照一致；完整 Vitest 63 文件 865 项、typecheck、lint（0 errors/134 既有 warnings）、Next build 33 路由通过。页面 2399→2407 行（`ImportReviewPage` 2204→2207 行），新模块 66 行/测试 80 行，依赖/300/50 预算已登记。
- 已显式提交 6 个源码/测试/架构路径为 `44aaa899 refactor(review): 分离快速补充答案视图状态`；本批未改请求、mutation、审核状态、API 或数据库。浏览器弹层交互、上传/文件选择、微信端、真实 provider/生产仍未验证；未推送、未部署、未操作数据库。

## 一百三十五、第一百二十六批：批量补全结果状态（2026-10-22）

- 按第125批交接继续审核页剩余弹层编排，先复核 HEAD=`44aaa899`、暂存区为空及既有工作区改动。只改审核页、批量补全结果规则/测试、审核边界及两份架构文档；未触碰部署配置、小程序、日志或其他用户改动。
- 新增 `review-batch-complete-result-state.ts`，集中批量补全结果摘要及“失败/跳过明细”的筛选、顺序和展示样式。保留摘要固定格式与前后空格、仅排除 `success`、未知状态按跳过样式展示、失败/跳过容器和文字/错误文本颜色，以及按服务端 `items` 输入顺序输出。
- 页面只替换结果摘要和明细渲染条件；批量请求、`executing` 执行锁、草稿清理、详情刷新、完成/取消按钮和弹层开关仍在原位置。新旧 3 项状态组合 216 组对照一致；完整 Vitest 64 文件 870 项、typecheck、lint（0 errors/134 既有 warnings）、Next build 33 路由通过。页面 2407→2403 行（`ImportReviewPage` 2207→2202 行），新模块 43 行/测试 76 行，依赖/300/50 预算已登记。
- 已显式提交 6 个源码/测试/架构路径为 `d692dd90 refactor(review): 分离批量补全结果状态`；本批未改请求、mutation、审核状态、API 或数据库。浏览器弹层交互、上传/文件选择、微信端、真实 provider/生产仍未验证；未推送、未部署、未操作数据库。下一步继续审核页剩余弹层编排，再按阶段 0 推进小程序 controller、学习闭环及队列/OCR。

## 一百三十七、第一百二十七批：审核图片答案流程（2026-10-22）

- 按第136节继续审核页“筛选、预览与弹层状态组合”，先复核 HEAD=`d692dd90`、暂存区为空及既有工作区改动。只改审核页、图片答案流程 hook/测试、审核边界及两份架构文档；不触碰部署配置、小程序资源/配置、日志或其他用户改动。
- 新增 `hooks/use-review-image-answer-flow.ts`，用可刻画 reducer 管理图片文件追加顺序、按索引移除、识别模式、预览/写入结果与错误，并消费既有 `useReviewImageAnswerMutations`。保留首批实现的实际语义：添加或移除文件会清空预览、结果和错误但保留已选模式；重置同时清空文件但保留模式；预览开始清空全部输出与错误，预览失败保留文件/模式并覆盖错误；写入开始仅清错误，成功后保留预览并显示结果；`Error.message` 原样显示，未知错误分别回退“预览生成失败”/“写入失败”。
- 页面只把当前批次传入预览/写入命令，仍保留 `currentBatchId` 的筛选优先、URL 回退顺序；无批次、无文件、无 `preview_token` 时不发请求，`operation_id` 空值仍传空字符串。mutation 路径、FormData/token payload、审核队列失效、加载锁、弹层关闭和图片 tab 可见性未改变。页面 2,403→2,355 行（`ImportReviewPage` 2,202→2,154 行），新模块 217 行/测试 227 行；依赖与 300/50 预算门禁已登记。
- 新增 12 项状态/请求输入/mutation 反馈/文件输入清理刻画；独立只读审查 P0-P2 无发现，提出的 3 项 P3 测试覆盖缺口已补齐。完整门禁 `npm run check` 通过：typecheck、lint（0 errors/133 既有 warnings）、Vitest 65 文件 883 项、Next build 33 路由。`git diff --check` 通过；审查确认图片执行期间仍可关闭弹层属于批次前既有行为，本批未改变也不夹带修复。本次未执行浏览器文件选择/上传交互，也未验证真实 provider、微信或生产。
- 已显式提交 6 个源码/测试/架构路径为 `84e8dc66 refactor(review): 分离图片答案流程状态`；不包含 `current_task.md`、`context.md`、`AGENTS.md` 或任何既有部署、小程序、日志改动。未推送、未部署、未操作数据库。

## 一百三十八、第一百二十八批：审核结果反馈与确认状态（2026-10-22）

- 按第127批交接继续审核页最终弹层编排，先复核 HEAD=`84e8dc66`、暂存区为空及既有工作区改动。只改审核页、审核结果反馈/确认状态规则与测试、审核边界及两份架构文档；不触碰部署配置、小程序资源/配置、日志或其他用户改动。
- 新增 `review-action-feedback.ts`，按单题通过/驳回、已选批量通过/驳回、整批通过/驳回和低风险批量通过生成原提示及是否关闭抽屉；保留部分失败按服务端 `errors` 顺序拼接 ID、无 `errors` 时成功文案、无 `affected_count` 时回退 0、低风险仅 `skipped_count>0` 追加“部分高风险/需检查题已跳过”，以及单题成功先提示后关闭抽屉的时序。
- 新增 `review-action-dialog-state.ts`，集中选择集、确认动作、驳回原因和提示消息。保留打开确认不清选择/原因、取消只关弹层、输入独立更新、审核成功后同时清选择/确认/原因，以及提示仍由 5 秒 effect 清除；页面仅用 reducer dispatch 接线，未改变 mutation、请求、权限、缓存失效或弹层 UI。
- 兼容基线发现：审核页选择集在队列刷新后仍保留不当前页/已消失 ID，`allChecked` 只按当前页 ID 判断，批量请求仍使用保留集合；这与公式页的 `safeSelectedIds` 不同，属于本批前既有行为。本批未改选择过滤，只在架构盘点注明，避免顺手改变批量审核范围。
- 新增 10 项审核反馈/确认状态刻画；独立只读审查发现 2 项 P2、2 项 P3，均已修复：选择集函数式更新改为 reducer action 保留排队语义，补齐真正缺 `affected_count`/空 `errors` 覆盖，未知反馈不再提前跳过 mutation 清理，连续更新与 dismiss 语义已有测试。完整门禁 `npm run check` 通过：typecheck、lint（0 errors/133 既有 warnings）、Vitest 67 文件 894 项、Next build 33 路由。页面 2,355→2,351 行（`ImportReviewPage` 2,148 行），新模块 58/56 行，依赖与 300/50 预算门禁已登记。浏览器弹层、真实审核 provider 与生产仍未验证。
- 已显式提交 8 个源码/测试/架构路径为 `f4e60284 refactor(review): 分离审核反馈与确认状态`；不包含 `current_task.md`、`context.md`、`AGENTS.md` 或任何既有部署、小程序、日志改动。未推送、未部署、未操作数据库。

## 一百三十六、截至 2026-10-22 的未完成项与交接顺序

> 本节保留 2026-10-22 当时的状态快照，不再作为当前状态索引；最新执行进度和继续范围见 §276。下列历史行数、HEAD、测试计数与当时验收缺口不可直接当作当前状态；§136.3 的实现状态已按后续代码校正。

### 136.1 当前已完成的边界

- 本地 HEAD 为 `f08fd17b`，提交后暂存区为空，`main` 比当前本地 `origin/main` 引用 ahead 61；未 fetch，不据此判断真实远端。
- 审核页第119至128批已分别提交 `8d7c6787`、`e53a88d3`、`00324328`、`5366b506`、`5987b6fc`、`52bfbb6c`、`44aaa899`、`d692dd90`、`84e8dc66`、`f4e60284`。审核页现为 2,351 行，`ImportReviewPage` 为 2,148 行；图片答案完整流程、审核结果反馈与确认/选择状态已由 hook 或 reducer 承接，文本批量请求、权限、跨刷新选择清理、异步刷新与剩余弹层编排仍在页面。
- 第128批管理端门禁：Vitest 67 文件 894 项、typecheck、lint（0 errors，133 条既有 warnings）、Next build 33 路由通过。批次差分为状态/规则与构建证据，不是浏览器、弹层交互或生产验收。

### 136.2 架构重构未完成项

1. **阶段 0：全量语义基线**仍缺逐业务域的入口、消费者、事务/状态机、异常/取消、旧数据兼容和回归结论；`REFACTOR_INVENTORY.md` 的静态枚举和当前热点不能替代逐用例审查。
2. **阶段 1：管理端**仍需收敛 `questions/page.tsx` 的剩余展示/编辑组合、审核页的权限/跨刷新选择/异步刷新及最终弹层接线；图片文件状态、审核结果反馈和确认/选择 reducer 已承接，但真实文件选择、上传和弹层交互仍未验证。页面变短不等于纵向样板完成。
3. **阶段 1：小程序番茄钟**仅完成计时计算、持久化/同步队列及恢复局部模块；完整 Page controller、确认/计时/画布/统计生命周期和页面接线仍未闭合。`pomodoro.js` 仍为 3,631 行。
4. **阶段 2：后端学习域**仍需按“刷题提交 → 错题/复习 → 考试 → 计划/推荐 → 统计/番茄钟”核对事务、版本约束、时间/科目口径、投影一致性并逐域拆分；不得把各域相似函数强行合并。
5. **阶段 2：管理端其余域**仍包括 AI 配置、任务页、公式编辑、知识图谱、考试和权限管理；`questions/page.tsx` 2,397 行、`system/tasks/page.tsx` 1,599 行等仍需证据驱动治理。
6. **阶段 2：小程序其余业务**仍需处理刷题/考试会话、错题/今日复习、结果页、dashboard/计划、公式/导出；`study/practice/practice.js` 2,633 行、`productivity/pomodoro-stats/index.js` 2,570 行。主包/分包边界和双份渲染一致性必须保留。
7. **阶段 3：共享运行时**仍需治理 `main.py` 的生命周期/健康指标剩余职责、`task_queue_service.py` 3,535 行的状态迁移/租约/重试/死信边界、`pipeline_orchestrator.py` 7,151 行的 OCR/导入阶段编排，以及 `ai_service.py` 2,301 行的分析执行；必须保留角色隔离、幂等、检查点和人工审核链路。
8. **阶段 3：高风险验收**仍缺完整 worker 循环/lease 回收、Redis 中断恢复、多 dispatcher 并发、生产角色退出、备份恢复演练及真实 OCR/AI/导入链；静态循环为零、端口替身和 SQLite 不能替代这些证据。
9. **阶段 4：长期门禁**仍需覆盖管理端其余 feature 越界、小程序全仓分包依赖/双份代码一致性、后端热点文件的 300/50 预算和未治理增长基线；当前番茄钟门禁只覆盖 9 个模块（本次静态复核通过：9 modules / 1 internal edge），后端预算与全栈基线未完成。
10. **阶段 4：兼容清理**仍需在静态调用、动态注册、字符串入口、分包配置和回归都确认后，删除旧转发与重复实现；任何文件/资源删除继续走单独确认，不夹带重构提交。

### 136.3 已实现但仍待真实环境验收的功能项（不属于等价重构）

- 已入库题目 `re_pending` 写入、重审工作台与版本回滚已实现：提交 `8829a49f` 增加状态迁移、单题/批量重审及回滚端点，修复 `7ea3dc2a` 补齐重审回滚批次缺陷；`docs/admin/REVIEW_FLOW.md` 已同步为 v2.4 实现说明。当前剩余边界是真实角色组合、生产 Admin 浏览器交互和上线后审计验收，不是功能缺失。
- `practice_service.use_leitner` 在相似/智能召回后的到期过滤与随机补题已实现并由 `backend/app/services/practice/candidate_schedule.py` 统一承接，`question_issuance.issue_practice_questions` 在签发前调用。当前剩余边界是生产候选供给/补题分布观测，不是 TODO(V3) 未实现。

### 136.4 生产与真实环境验收缺口

- 真实微信 `jscode2session`/刷新、真机、外部导入/OCR/AI、生产 Admin 登录后的浏览器交互仍未验证；HTTP 200、测试登录和合成 provider 不能替代。
- OCR readiness 对 HTTP<500（含 401）仍视为可达；ready 非 degraded 不等于 OCR 可用。探测真实 provider 时不得打印或擅自修改密钥。
- PG 同载荷并发、事务故障回滚及 outbox 投影已有合成真库证据；但 Redis 中断/lease、完整 worker、多 dispatcher、生产角色退出和恢复演练仍未验证。部署基础设施/隔离验收通过不等于完整生产业务验收。
- 本轮浏览器弹层、localStorage 草稿、文件选择/上传和微信页面交互未执行；jsdom 测试曾因依赖未安装而无法启动，测试已移除且未改依赖/锁文件。

### 136.5 下一批建议顺序

1. 先完成审核页剩余权限/选择/异步刷新与弹层接线的行为刻画，再决定是否继续抽取；图片答案流程已收口，下一步不重复拆同类小模块。
2. 回到阶段 0，对 `questions`、学习闭环和导入/运行时热点补齐逐用例兼容基线，按风险选择下一批。
3. 小程序优先收敛番茄钟完整 controller，再做刷题/考试会话；只有真实微信工具/设备可用时才记录设备验收。
4. 生产侧只按用户新的明确授权处理；默认继续不推送、不部署、不迁移、不删除数据或诊断证据。

## 一百三十九、V6 自适应并发 claim 统一治理与学习域审查（2026-10-23）

- 新增 `backend/app/services/unique_conflict.py`，集中唯一冲突识别和 SQLite 显式事务启动；adaptive_learning_service 和 mastery_service 复用共享 helper，消除重复实现。
- `adaptive_learning_service.py` 三类状态（UserAdaptiveProfile/UserKnowledgeAdaptiveState/UserQuestionDifficultyState）统一使用 savepoint claim + 唯一冲突 reload winner；批量知识点状态创建用 `_claim_knowledge_state` + `_reload_knowledge_adaptive`，`dict.fromkeys` 去重防重复更新。
- `mastery_service.py` `UserKnowledgeState` 批量创建改为按 missing 逐个 claim/reload，避免并发首次答题整笔回滚。
- 考试终态锁：`exam-runner/index.js` `submitExam()` 首行显式拒绝 `_attemptTerminal || _navigationLocked`，不再只依赖 readonly 覆盖层；导航失败后保持锁 + `resultRecoveryPending`，`retryResultNavigation` 可单独重开结果页。
- 新增测试：`test_adaptive_learning_concurrency.py`（5 项真实 SQLite 竞争）、`test_mastery_concurrency.py`（1 项）、`test_unique_conflict_boundaries.py`（2 项架构门禁）、`test-exam-terminal-navigation.js`（终态锁拒绝二次 submit）。
- CI 接入：`ci.yml` 增加并发测试和架构门禁；`reliability.yml` 增加小程序 terminal-navigation 和 storage-session-cleanup。
- 验证：后端 214 passed（6 既有 datetime 弃用告警）；Ruff/compileall/diff-check 通过；管理端 628 passed；小程序 terminal-navigation + storage-session-cleanup 通过；review/wrong-question 域 63 passed。
- 学习域审查结论：review/wrong-question 的 `record_wrong` + `auto_schedule_wrong_question` 在 PostgreSQL 由 advisory lock 保护，SQLite 由写序列化 + 调用方显式 rollback 覆盖，exam `start_attempt` 用全事务 rollback + 重查 winner；该路径是残留风险而非当前活跃 bug，因为投影 worker 拥有独立会话才使 claim 竞态可执行。
- 未执行：真实微信工具/真机、外部 OCR/AI、生产 PG/Redis、admin 浏览器交互、完整 worker 循环、备份恢复演练。
- 本批未提交、未推送、未部署、未操作数据库；保留全部既有工作区改动与资源删除。

## 一百四十、阶段0学习决策并发基线与查询边界（2026-10-23）

- 新增 `docs/architecture/LEARNING_DECISION_COMPATIBILITY.md`，登记推荐实验分组、学习计划/日快照、stats/study-report 趋势、推荐日指标和错题编辑缓存的真实入口、消费者、事务、时间与剩余边界；不把本批扩大为学习闭环或全栈阶段0完成。
- `recommendation_experiment_service` 首次分组改为显式外层事务 + savepoint claim；唯一冲突只回滚 savepoint 并重读 winner，不再让推荐请求事务进入 aborted 状态或静默回退默认策略。交通 cap 仍对历史用户实时生效。
- `study_plan_service` 首次计划与日快照使用同一 claim 模式；日快照冲突后保留外层已加载计划和未提交修改，不再全事务 rollback。revision、快照 basis 和完成量投影口径未改。
- `recommendation_metrics_service` 修复 `variant_key IS NULL` 时唯一约束无法防重复的并发风险：PostgreSQL 按日期/科目获取事务级 advisory lock，SQLite 使用 `BEGIN IMMEDIATE`。未改表、迁移、API 的 `null` 语义或覆盖式聚合字段。
- `stats_service.get_trends` 与 `study_report_service.get_study_trend` 增加半开窗口上界，历史/当前周期不再扫描窗口外或未来记录；accuracy 格式和来源口径保持不同。
- `PUT /wrong-questions/{id}` 成功后失效 `wrong_questions:*:{uid}*` 与 `stats:*:{uid}*`，404 不失效；保留原 AI prewarm、响应和提交语义。
- 新增 `test_recommendation_assignment_concurrency.py`、`test_recommendation_metrics_concurrency.py`、`test_study_plan_concurrency.py`、`test_learning_stats_query_bounds.py`、`test_wrong_question_update_cache.py` 并接入 `.github/workflows/ci.yml` static 步骤。
- 定向回归 110 项通过（推荐 phase4/4.5/并发/指标、学习计划保存/并发、stats/report/窗口、错题缓存）；严格 Ruff、compileall、YAML 解析和 `git diff --check` 通过。SQLite 真实并发已覆盖分组、null variant 聚合和日快照冲突，非唯一完整性错误不会被 claim 吞掉；本机无 PostgreSQL 服务端，未把 SQL 构造审查冒充 PG 并发验收。
- 本地重放 CI `Static architecture & non-GPU regression tests` 完整步骤通过：2,513 passed、8 个既有 datetime 弃用 warning。该步骤仍不包含 PostgreSQL、Redis、真实 OCR/AI/微信或浏览器交互。
- 未执行真实微信/真机、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker、备份恢复演练。`re_pending` 重审/回滚和 `use_leitner` 的上述状态为 2026-10-23 当批记录；两项后续均已实现，当前状态以 §136.3 为准。
- 已本地提交为 `e7345130 fix(learning): 收敛学习决策并发与查询边界`；未推送、未部署、未操作数据库，保留全部既有工作区改动、证据目录和资源删除。

## 一百四十一、第一百二十九批：任务队列脚本绑定与语义基线（2026-10-23）

- 新增 `backend/app/services/task_queue_script_bindings.py`，集中 20 个 Lua 脚本的实例属性、加载顺序与源绑定；`task_queue_service.py` 不再逐个导入/赋值/清空 `_LUA_*`，由 `SCRIPT_BINDINGS` 统一驱动 `SCRIPT LOAD` 和 NOSCRIPT 全量重载。
- 保留原 Redis 键空间、脚本源文本、加载顺序、SHA 缓存判断、单连接/共享池用途和所有入队/认领/完成/失败/取消语义；服务从 2,763 行降至 2,676 行，架构尺寸基线收紧至 2,690。
- 新增 `test_task_queue_script_bindings.py`：首次加载 20 个脚本、重复加载幂等、NOSCRIPT 后重载全部绑定并重试；新增架构门禁校验绑定属性顺序、协议源文本和模块预算。
- 新增 `docs/architecture/TASK_QUEUE_COMPATIBILITY.md`，登记 v1/v2 入口、消费者、键空间、owner/generation fencing、状态返回、reaper、健康错误、死信/损坏管理、脚本缓存和已知迁移风险；仍不宣称完整 worker、Redis 中断或多 dispatcher 验收。
- 定向回归 50 项通过（脚本绑定/协议架构/队列指标/runtime metrics 端口）、严格 Ruff、compileall、YAML 与 diff-check 通过。当前没有 redis-server 二进制，3 个集成文件 69 项全部因缺少 `--run-integration` 收集门禁而 skipped，不能记为真实 Redis 通过。
- 已知风险继续保留：`drain_v1_to_v2` 在 LPOP 后队列满/payload 缺失/连接异常时可能失去 ready-list 位置，下一批优先修复并补替身/真实 Redis 证据；完整 worker、多 dispatcher、lease 回收、生产 Redis 中断与备份恢复仍未验证。
- 本批尚未提交、未推送、未部署、未操作数据库；保留全部既有工作区改动、证据目录和资源删除。
- 该批已显式提交为 `84f64b5a refactor(queue): 集中Lua脚本绑定`；未推送、未部署。

## 一百四十二、第一百三十批：v1→v2 原子迁移（2026-10-23）

- 新增 `task_queue_lua_v1_to_v2.py` 与单一任务迁移脚本；脚本先读取 v1 队头并校验 payload 的 task_id/task_type，完成 v2 hash、admission guard、ready-list 写入后才移除 v1 位置。v2 满时不消费 v1 队头；缺失或错配 payload 原子转入 v2 corrupt 诊断并保留可检查原文。
- 修复“LPOP 后入队失败导致 ready-list 位置丢失”的已知风险。半写 v2 hash 但无 admission guard 时，迁移返回 conflict 并保留 v1 位置，不把不完整 v2 状态误判为已完成重复入队。
- `task_queue_service.py` 改为按任务调用原子脚本，保留 batch_size、返回迁移数量、已有 v2 guard 幂等跳过和共享池关闭语义；脚本绑定增至 21 个，原 20 个脚本顺序/哈希不变，服务仍为 2,690 行，尺寸门禁不放宽。
- 新增 fakeredis + Lua 直执行回归 8 项：成功迁移、迁移中途 v2 满保留剩余 v1、缺失 payload/身份/类型/JSON 错配转 corrupt、已有 guard 去重、半写 hash 冲突保护。连同脚本绑定/架构/队列指标/runtime metrics 共 58 项通过。
- 严格 Ruff、compileall、diff-check 通过。fakeredis 只证明 Lua 协议契约，不等于真实 Redis 集成；本机无 redis-server，真实迁移并发、容量竞争和故障注入仍待有 Redis 环境时验证。
- 本批尚未提交、未推送、未部署、未操作数据库；完整 worker、多 dispatcher、Redis 中断恢复和备份恢复演练继续列为未验证。

## 一百四十三、第一百三十一批：审核全失败重试与详情会话（2026-10-23）

- 审核队列动作反馈新增 `resetSelection` 决策：已选批量部分成功或成功、单题成功、整批成功及低风险完成仍清空选择/确认/驳回原因；已选批量全部失败显示“全部失败”，保留选择与确认状态供重试，同时仍失效审核队列、批次及按动作需要的题目缓存。
- 修复查看模式脏草稿回归：队列摘要切换为完整详情、保存成功、单题/批量 AI 补全和取消编辑时统一重建 `editState` 快照；编辑模式下非活动 segment 变化仍不视为脏。
- 新增 `useReviewQuestionDetail` 与纯 `review-detail-session` 控制器。每次打开抽屉都开启新会话、清除旧同步标记并强制刷新当前详情；只有本次刷新完成且详情 ID 匹配时才允许进入编辑，关闭/切换会作废迟到响应。保存成功先将完整响应写入 `import-question-detail` 缓存，再退出编辑态和后台失效，避免旧缓存覆盖刚保存内容。
- 新增/更新动作反馈、mutation 顺序、抽屉快照、详情会话及页面边界回归；只读审查经历 3 轮，最终 `No findings.`，未留 P0-P3。完整 `npm run check` 通过：typecheck、lint（0 errors/135 既有 warnings）、Vitest 80 文件 1003 项、Next build 33 路由；`git diff --check` 通过。
- 审核页 2,355 行，`ImportReviewPage` 仍承担筛选 interaction、权限、跨刷新选择、异步刷新和剩余弹层编排；本批不宣称审核页纵向样板完成。
- 已显式提交 15 个源码/测试/架构路径为 `f08fd17b fix(review): 保留全失败批量选择并收敛详情会话`；不包含 `current_task.md`、`context.md`、`AGENTS.md` 或既有后端测试/部署/小程序改动。未推送、未部署、未操作数据库。
- 真实 Admin 浏览器中的迟到响应、快速关闭/重开、缓存时序、真实权限拒绝和弹层交互仍未验证；外部 OCR/AI、真实微信/真机、生产 Redis/worker 与备份恢复演练缺口不变。

## 一百四十四、第一百三十二批：后端当前契约回归夹具（2026-10-23）

- 接续上一轮 16 个后端测试文件的契约对齐，先复核 `HEAD=f08fd17b`、暂存区为空及全部既有工作区边界；本批只改测试/夹具与一个真实 SQLite 回归文件，不改生产代码、API、数据库、部署配置或小程序。
- 修正独立只读审查提出的 4 个 P2 与 3 个 P3：AI token 超限测试改走真实 `repair_questions` 预算路径并断言不发 `chat`；健康检查统一 stub 异步任务诊断并断言 warning 下顶层 `ok=true`；发布科目以冲突 sentinel `999` 验证导入记录权威值；推荐实验安全阀改为 `result.one()`；删除无意义的 overview mock；补齐推荐指标 7 日回补/失败禁止清理覆盖；移除陈旧 xfail 并修正批量响应形状。审查代理随后复核为 `No findings`，逐项确认关闭。
- 新增 `test_review_overview_dirty_schedule.py`，使用真实 `sqlite+aiosqlite` 与 `Base.metadata.create_all` 调用真实 `get_today_review_overview`，构造有效 revision、题目/版本错配和 revision 缺失三类 schedule，断言概览只返回 `[1, 2]`。该证据是 SQLite 服务路径，不是 PostgreSQL 验证；`PRAGMA foreign_keys=OFF` 仅用于注入故意损坏的测试数据。
- 定向联合回归 `375 collected`，最终 `374 passed, 1 xfailed`；严格 Ruff、`compileall`、`git diff --check` 通过。唯一 xfail 是 `test_import_to_practice_e2e.py` 的既有标记，不是本批新增；其余原两个 stale xfail 已移除并转为真实通过。
- 已显式提交 17 个测试路径为 `9ac1679b test(backend): 对齐当前契约回归夹具`；不包含 `current_task.md`、`context.md`、`AGENTS.md`、部署/小程序路径或既有删除。未推送、未部署、未操作数据库。
- 真实 PostgreSQL/Redis、外部 AI/OCR、真实 Admin 浏览器、微信/真机、完整 worker 与备份恢复演练仍未验证；阶段 0 全量语义审查、管理端 questions/review 剩余组合、小程序完整 controller、学习域/队列/OCR 编排和长期门禁继续待办。

## 一百四十五、第一百三十三批：倒计时冷恢复 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/countdown-session-restore-controller.js`，承接倒计时冷恢复的确认快照守卫、无效/存储失败 fail-closed、暂停时长合并、科目/任务投影、paused 写回与 `nextTick` 重绘、running `startTimer`，以及过期完成的重试/冲突/统计/振动/庆祝时序。页面 `_restoreSession` 只保留 free 分流和 controller 懒创建/委托，页面从 3,084 行降至 2,950 行。
- 修复合并后的本地暂停修正被 `computeCountdownRestore` 内部重算覆盖的问题：`computeCountdownRestore` 和 `computeFreeRestore` 支持可选 `totalPausedMs` override，倒计时恢复以一次 `now()` 采样贯穿暂停计算、剩余时间、pauseStartTime 和持久化。既有 free 恢复、确认快照、终态冲突和统计口径不变。
- 倒计时边界收紧至 28 个模块、4 条内部依赖，页面预算降至 2,950 行；AST 门禁要求 free 恢复壳为“守卫赋值 + return 委托”，倒计时恢复壳为“free 分流 + 守卫赋值 + return 委托”，拒绝工厂未赋值、不可达赋值、裸委托、重复委托、前置 return 和顺序错误。新增 controller 9 项与边界变异回归；独立只读审查历经多轮 P3 修复后为 `No findings.`。
- 验证通过：31 个 `test-pomodoro-*.js` 文件 122/122、resilience 106、free-limit 39、stability runtime 46、resume latency 12；`node --check`、YAML 解析和 `git diff --check` 通过。`docs/architecture/REFACTOR_INVENTORY.md` 与 `SYSTEM_ARCHITECTURE.md` 已同步 controller、页面上限和门禁口径。
- 已显式提交 12 个源码/测试/文档/CI 路径为 `4777caa5 fix(pomodoro): 修正倒计时冷恢复暂停口径`；不包含 `AGENTS.md`、`current_task.md`、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、弱网进程终止、设备时钟回拨、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百四十六、第一百三十四批：启动仪式 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/start-session-controller.js`，承接启动 in-flight 锁与生命周期 generation、未知启动 Reconciliation 前置、pending queue flush、科目校验、free/倒计时分流、ceremony 延迟、启动成功投影、409 active fetch/restore、存储错误与通用错误收口。页面只保留 `_getStartSessionController()` 懒创建及 `startSession` / `_startFreeSession` 单次委托，页面从 2,950 行降至 2,833 行。
- 逐分支保留旧页面语义：free 模式无 pending 时即使页面已隐藏仍发起原请求，由既有 unknown-start/free late-response reconciliation 负责取消；pending drain 后失去页面可见性则在 POST 前停止；free 通用失败不强制改 phase，倒计时失败重置 idle；409 的 storage error 与 `_restoreSession(false)` 分流保持 fail-closed。
- AST 门禁增至 29 个模块、4 条内部依赖，页面预算收紧至 2,833 行；要求启动壳精确懒创建单一 controller，并分别以 `start()` / `startFree(existingStartSeq)` 返回委托。新增 controller 14 项独立回归，包括启动锁、debug 延迟、free late-response、pending 后隐藏、409 各分支、迟到响应和错误文案；boundary 16 项回归；CI 接入新测试。
- 验证通过：32 个 `test-pomodoro-*.js` 文件 137/137、stability 46、resilience 106、resume latency 12、free-limit 39；`node --check`、YAML 解析和 `git diff --check` 通过。两个现有只读审查代理均因外部 LobsterAI 月度额度耗尽返回 systemError，本批未取得独立审查结论；已按 HEAD `4777caa5` 旧方法逐分支自审，不以额度错误冒充 `No findings.`。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `dc80cb76 refactor(pomodoro): 收敛启动仪式控制器`；不包含 `AGENTS.md`、`current_task.md`、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百四十七、第一百三十五批：未知启动恢复 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/unknown-start-controller.js`，承接 unknown-start 持久化凭据与最新取消意图优先、同一 `client_start_id` 幂等重放、offline/5xx 保留、永久错误清理、payload/mismatch 校验、cancelIfFound active 取消、active restore、terminal settled、迟到响应转 interrupt、pending 失败保留取消凭据及 accepted marker 清理 fail-closed。页面仅保留 `_getUnknownStartController()` 懒创建和 `reconcile` / `postStart` 单次委托，页面从 2,833 行降至 2,680 行。
- AST 门禁增至 30 个模块、4 条内部依赖，页面预算收紧至 2,680 行；未知启动恢复壳必须懒创建单一 controller，并精确委托 `reconcile(explicitAttempt)` / `postStart(payload, startSeq)`，拒绝工厂未赋值、错误 delegate 和页面回长。边界回归增至 17 项。
- 新增未知启动恢复 controller 独立 16 项回归，覆盖 POST 前持久化与写失败拒绝请求、存储读取/无效 attempt/payload、最新 stored attempt 与显式 mismatch、offline/5xx/永久错误、active cancel 与 pending 失败、visible/hidden restore 及 restore false、terminal settled、迟到响应最新取消意图、late pending 失败保留凭据和 accepted cleanup 失败；已接入 `.github/workflows/reliability.yml`。
- 验证通过：33 个 `test-pomodoro-*.js` 文件共 154 项；reliability 步骤中的 13 个 `node --test` 文件共 134 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `dbae2c72 refactor(pomodoro): 收敛未知启动恢复控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百四十八、第一百三十六批：待同步队列与终态动作 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/pending-sync-controller.js`，承接 pending queue 严格按 head drain、成功确认、终态状态 mismatch 冲突记录/清理、`client_action_at` 重放、可选时间格式化、404/409 reconciliation、clock-skew 校准重试、stale/not-ready active restore、drop-session 与 complete/interrupt 终态入队。页面仅保留 `_getPendingSyncController()` 懒创建及 `reconcileFailure` / `drain` / `complete` / `interrupt` 单次委托，页面从 2,680 行降至 2,594 行。
- 逐分支保持原行为：队列读取失败 fail-closed 并提示持久化错误；成功后先确认本地队列再按需清理本地暂停修正；终态响应不符合 expected status 时先持久化 conflict marker、再清理同会话动作；transient 错误只在 404/409 reconciliation 后继续，否则调度既有 bounded retry；terminal queue 满额时继续保留终态容量。
- AST 门禁增至 31 个模块、4 条内部依赖，页面预算收紧至 2,594 行；精确校验待同步壳懒创建单一 controller，并分别委托 `reconcileFailure(pending, error)` / `drain()` / `complete(sessionId, clientActionAt)` / `interrupt(sessionId, clientActionAt)`。边界回归增至 18 项。
- 新增待同步 controller 独立 17 项回归，覆盖空队列/读取失败、head FIFO、client timestamp、成功确认失败、terminal mismatch 及持久化失败、transient retry、404/409 acknowledge、clock-skew 重放、stale active completion 清理/恢复、hidden restore、drop-session、complete/interrupt、入队失败、storage conflict 和 drain 单飞；已接入 `.github/workflows/reliability.yml`。
- 验证通过：33 个 `test-pomodoro-*.js` 文件共 172 项；reliability 步骤中的 14 个 `node --test` 文件共 152 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `853da42f refactor(pomodoro): 收敛待同步队列控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百四十九、第一百三十七批：终态冲突 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/terminal-conflict-controller.js`，承接跨进程终态冲突标记的 `record` / `read` / `consume` / `consumeAny` / `ack` / `handle`：持久化写入并缓存内存冲突、内存优先读取、存储不可读 fail-closed 标记、匹配/任意消费、仅在本地清理完成后确认删除，以及 drop-session → 完成标记读取/清理 → break/pause_adjustment best-effort 清理 → ack → breakSec null → clearTimer → setData → resetIdle → toast → stats 的编排顺序。controller 经显式能力回调访问页面，不再持有页面 `this`。页面仅保留 `_getTerminalConflictController()` 懒创建及六个精确单次委托，页面从 2,594 行降至 2,579 行。
- 逐分支保持原行为：`record` 在标记未落到本地存储前返回 false 且不缓存；`read` 内存优先、无效值返回 null、读取失败返回 `{ storageUnreadable: true }`；`ack` 拒绝 null/storage conflict 且删除失败时保留 marker 与内存；`handle` 在 drop/完成标记读取或删除/ack 任一失败时 fail-closed 并提示持久化错误，cleanup 成功后才确认 marker。
- AST 门禁增至 32 个模块、4 条内部依赖，页面预算收紧至 2,579 行；精确校验终态冲突壳懒创建单一 controller，并分别委托 `record(sessionId, requestedAction, serverStatus)` / `read()` / `consume(sessionId, requestedAction)` / `consumeAny()` / `ack(conflict)` / `handle(sessionId, conflict)`。边界回归增至 19 项（新增终态冲突壳的未赋值与六个精确 delegate 变异回归）。
- 新增终态冲突 controller 独立 16 项回归，使用真实 `terminal-conflict-state` / `terminal-conflict-handler`：record 持久化/写失败、read 内存优先/有效/无效/读取失败、consume storage error/匹配/不匹配、consumeAny、ack 空与 storage conflict/成功/删除失败/保留较新内存冲突、handle null/不可读/drop 失败/完成标记读取与删除失败/ack 失败保留 marker 与内存/成功清理顺序/无关完成记录保留；已接入 `.github/workflows/reliability.yml`（node --test 文件数 14→15）。同时把 resilience 静态测试改为从 controller 与 handler 抽取 `record` / `ack` / `consume`，保持 drop→ack、completion read/remove→ack 顺序断言。
- 验证通过：35 个 `test-pomodoro-*.js` 文件共 189 项；reliability 步骤中的 15 个 `node --test` 文件共 169 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `715517e9 refactor(pomodoro): 收敛终态冲突控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十、第一百三十八批：今日统计 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/stats-controller.js`，承接今日统计加载：向前取请求序号、`GET /pomodoro/stats`、仅最新响应写回 `todaySessions` / `todayDurationText` 并记录 `today_duration_sec` 供本地快照复用，`invalidate()` 使在途请求失效，请求异常静默吞掉不写视图。controller 经显式能力回调访问页面 `api.get`、`_timerState.todayDurationSec` 与 `setData`，不持有页面 `this`。页面仅保留 `_getStatsController()` 懒创建与 `loadTodayStats()` 单次委托，`onUnload` 改为调用 `this._getStatsController().invalidate()`，页面从 2,579 行降至 2,577 行，删除页面私有 `_statsRequestSeq` 字段。
- 行为保持：并发/生命周期/冲突刷新时仍只有最新请求可更新 UI，较慢的完成后旧响应不能覆盖新总量；请求失败或非今日数据时维持原静默兜底与「0分钟」格式化（含 `>=60` 分钟折算 `X时Y分`）。
- AST 门禁增至 33 个模块、4 条内部依赖，页面预算收紧至 2,577 行；精确校验统计壳懒创建单一 controller 并委托 `load()`，边界回归增至 20 项（新增统计壳未赋值与错误 delegate 变异回归）。resilience 静态测试改为从 `stats-controller.js` 抽取 `load`，断言 `seq !== state.requestSeq` 与 `onUnload` 的 `invalidate()`。
- 新增今日统计 controller 独立 5 项回归：请求路径与分钟格式（<60/`X时Y分`）、缺省字段按 0、较慢旧响应不覆盖新总量、`invalidate()` 丢弃在途响应、请求拒绝静默不写视图；已接入 `.github/workflows/reliability.yml`（node --test 文件数 15→16）。
- 验证通过：36 个 `test-pomodoro-*.js` 文件共 195 项；reliability 步骤中的 16 个 `node --test` 文件共 175 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、页面行数 2,577、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `007195de refactor(pomodoro): 收敛今日统计控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十一、第一百三十九批：主题 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/theme-controller.js`，承接主题视图模型（light/dark 滑块与庆祝色，含非法模式归一化）、从存储恢复主题（始终重设原生导航/背景主题、仅当与当前模式不同才 patch 视图）、切换主题（`persist`/`animate`，切换期 `themeSwitching` 与 520ms 计时器生命周期）以及页面卸载时清理在途切换计时器。controller 经显式能力回调访问 `pomodoroTheme`、`setData`、`setTimeout`/`clearTimeout` 与页面画布回执，不持有页面 `this`。页面仅保留 `_getThemeController()` 懒创建及 `_getThemeViewModel` / `_syncThemeFromStorage` / `_applyTheme` / `toggleTheme` 单次委托，`onUnload` 改为 `this._getThemeController().clearSwitchTimer()`，移除页面私有 `_themeSwitchTimer`，页面从 2,577 行降至 2,564 行。
- 行为保持：切主题后会清空 `_ringCache` 与上帧进度并在运行/暂停可见且无结束确认弹层时重绘圆环；重复切主题会先取消上一个 `themeSwitching` 计时器；持久化仍经 `pomodoroTheme.setTheme`，原生主题仍经 `applyNativeTheme`，`toggleTheme` 仍按当前 `themeMode` 取反。
- AST 门禁增至 34 个模块、4 条内部依赖，页面预算收紧至 2,564 行；精确校验主题壳懒创建单一 controller，并分别委托 `viewModel(mode)` / `sync()` / `apply(mode, persist, animate)` / `toggle()`，边界回归增至 21 项（新增主题壳未赋值与四个 delegate 变异回归）。
- 新增主题 controller 独立 7 项回归：视图模型 light/dark 映射与归一化、`sync` 仅在模式变化时 patch 但始终重设原生主题、`apply` 持久化/动画/520ms 复位与回调、非动画 apply 不计时、重复 apply 取消旧计时器、`toggle` 取反、`clearSwitchTimer` 幂等；已接入 `.github/workflows/reliability.yml`（node --test 文件数 16→17）。
- 验证通过：37 个 `test-pomodoro-*.js` 文件共 203 项；reliability 步骤中的 17 个 `node --test` 文件共 183 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、页面行数 2,564、YAML 解析及 `git diff --check` 通过。
- 已显式提交 9 个源码/测试/文档/CI 路径为 `8803e9d5 refactor(pomodoro): 收敛主题控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十二、第一百四十批：确认窗口快照纯规则（2026-10-23）

- 新增纯模块 `miniprogram/pages/pomodoro/utils/end-confirm-snapshot.js`：`isValidConfirmSnapshot(snapshot, nowMs)` 校验 sessionId/mode/`confirmVisible`/`openedAt` 与 1 小时过期口径，`buildFreeConfirmSnapshot` / `buildCountdownInterruptSnapshot` 组装 free-complete 与 countdown-interrupt 的持久化字段（含 `pausedByConfirm`、`backendPauseDone:false`、`confirmVisible:true`）。模块无副作用、无 require、无全局依赖；存储、pending queue、计时器与画布替代仍留在页面。页面改为以 `isValidConfirmSnapshot(snapshot, api.now())` 校验、以两个 builder 组装快照，`_showEndFreeConfirm` / `_pauseCountdownForEndConfirm` 只保留副作用编排；页面从 2,564 行降至 2,554 行。
- 行为保持：两处快照字段、顺序与默认值逐字段一致（`wasPaused`、`pausedByConfirm = !wasPaused`、剩余/总量/进度、`pauseStartTime`、`sessionStartTime`、`countdownEndAt`、`freeDisplayOffsetMs:0`），确认操作、取消/确认编排与计时/画布流程未变。
- AST 门禁增至 35 个模块、4 条内部依赖，页面预算收紧至 2,554 行；边界回归增至 22 项（新增确认窗口快照模块的页面接线回归）。模块门禁要求页面继续 `require('./utils/end-confirm-snapshot')`。
- 新增确认窗口快照独立 4 项回归：校验器拒绝缺失/隐藏/过期并接受有效快照、free-complete 与 countdown-interrupt 字段逐一比对、`pausedByConfirm` 在已暂停时为 false；已接入 `.github/workflows/reliability.yml`（node --test 文件数 17→18）。
- 验证通过：38 个 `test-pomodoro-*.js` 文件共 208 项；reliability 步骤中的 18 个 `node --test` 文件共 188 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、页面行数 2,554、YAML 解析及 `git diff --check` 通过。
- 已显式提交 9 个源码/测试/文档/CI 路径为 `35770914 refactor(pomodoro): 抽出确认窗口快照规则`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十三、第一百四十一批：活动会话轻同步 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/active-sync-controller.js`，承接活动会话轻同步：`canLightSync(active)` 判定本会话是否可轻同步（sessionId/phase/暂停态/preset/启动时间一致性），`syncLight(active, failClosed)` 以服务端 `start_time` 重设时钟原点、按 `allocation_mode` 更新 408 均分选择、合并本地暂停补偿（`mergeLocalPauseAdjustment` fail-closed）、free 分支按墙钟重算显示并在缺失画布时重建、到 5 小时上限自动结束或重启 tick、倒计时分支在暂停时仅重建画布、在剩余时间耗尽时收口完成、其余情况以墙钟剩余时间 `startTimer(remainingMs, forceRunning, reuseCanvas)`。controller 经 21 项显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getActiveSyncController()` 懒创建及 `_canLightSyncActive` / `_syncActiveSessionLight` 单次委托，页面从 2,554 行降至 2,495 行。
- 行为保持：语句顺序与旧实现一致（取 `now` → 应用服务端启动时间 → allocation → 合并暂停 → 写回 `totalPausedMs` → 分支），`_timerState.progress = 1` 仅在 free 画布缺失分支内触发，暂停补偿合并失败仍按 `failClosed` 决定是否提示持久化错误，画布重绘的 `nextTick` 守卫（可见/运行中/冻结态）不变。
- AST 门禁增至 36 个模块、4 条内部依赖，页面预算收紧至 2,495 行；精确校验活动会话轻同步壳懒创建单一 controller，并委托 `canLightSync(active)` / `syncLight(active, failClosed)`，边界回归增至 23 项（新增未赋值与两个 delegate 变异回归）。
- 新增活动会话轻同步 controller 独立 9 项回归：资格判定矩阵、倒计时墙钟重启、已耗尽收口、暂停倒计时画布重建、free 上限显示与间隔重启、free 超限自动结束、暂停 free 不重启、暂停补偿 fail-closed、allocation 变更/不变；同时把 resilience / resume-latency / free-limit 三处页面源码断言迁移到 controller 源码，覆盖画布重建、墙钟推导、free 间隔重启与 `FREE_TIMER_MAX_MS` 上限注入；已接入 `.github/workflows/reliability.yml`（node --test 文件数 18→19）。
- 验证通过：39 个 `test-pomodoro-*.js` 文件共 218 项；reliability 步骤中的 19 个 `node --test` 文件共 198 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、页面行数 2,495、YAML 解析及 `git diff --check` 通过。
- 已显式提交 12 个源码/测试/文档/CI 路径为 `c33fb21a refactor(pomodoro): 收敛活动会话轻同步控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十四、第一百四十二批：暂停切换 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/pause-toggle-controller.js`，承接 tap 冷却锁（`acquire` / `release`，500ms 自动解锁计时器）与 `toggle` 分发（拒绝非运行态/无会话/actionLoading/结束确认弹层，然后按 free/countdown × 暂停/继续分发到四个页面方法）。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getPauseToggleController()` 懒创建及 `_acquirePauseToggleLock` / `_releasePauseToggleLock` / `togglePause` 单次委托，移除页面私有 `_pauseToggleLocked` / `_pauseToggleUnlockTimer`，页面从 2,495 行降至 2,489 行。
- 行为保持：tap 冷却仍为 500ms 独立锁，不复用 `actionLoading`；`onUnload` 仍调用 `_releasePauseToggleLock()`；拒绝条件顺序与原 `togglePause` 一致（phase → sessionId → actionLoading → showEndConfirm → acquire）。
- AST 门禁增至 37 个模块、4 条内部依赖，页面预算收紧至 2,489 行；新增 `callsControllerCall` 辅助校验 void delegate（非 return 语句），精确校验暂停切换壳懒创建单一 controller 并委托 `acquire()` / `release()` / `toggle()`，边界回归增至 24 项。
- 新增暂停切换 controller 独立 6 项回归：acquire 一次/自动解锁、release 取消计时器、release 空操作、toggle 拒绝四种无效态、toggle 四路分发、快速二次 tap 被拒绝；resilience 静态测试改为从 controller 源码抽取 `acquire` / `release` / `toggle`，断言 `state.locked` / `options.cooldownMs` / `options.clearTimeout(state.unlockTimer)` 等；已接入 `.github/workflows/reliability.yml`（node --test 文件数 19→20）。
- 验证通过：40 个 `test-pomodoro-*.js` 文件共 225 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、页面行数 2,489、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `9386a00c refactor(pomodoro): 收敛暂停切换控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十五、第一百四十三批：恢复错误 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/resume-error-controller.js`，承接 `/resume` 404 后的恢复错误编排：非 404/null 错误直接提示重试，404 时拉取权威 `/pomodoro/active`，会话消失/ID 不匹配则 reset idle，非 running 则提示稍后重试，running 则按 free/countdown 分支修复本地状态（服务端 start_time、暂停补偿合并、free 显示/间隔重启或倒计时剩余/进度/重启）并清理对应暂停快照。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getResumeErrorController()` 懒创建及 `_reconcileAfterResumeError` 单次委托，页面从 2,489 行降至 2,453 行。
- 行为保持：free 分支的 `sessionStartTime`/`totalPausedMs`/`pauseStartTime`/`elapsedSec`/`freeDisplayTime`/`ringCanvasVisible`/`startFreeTimerInterval`/`removeStorage('pomodoro_free_pause')` 顺序与原实现一致；countdown 分支的 `now`/`totalSec`/`effectiveTotalPausedMs`/`elapsed`/`remainingSec`/`progress`/`displayMin`/`displaySec`/`startTimer`/`removeStorage('pomodoro_pause')` 顺序与原实现一致；toast 文案和 catch 兜底不变。
- AST 门禁增至 38 个模块、4 条内部依赖，页面预算收紧至 2,453 行；精确校验恢复错误壳懒创建单一 controller 并委托 `reconcile(e, sessionId)`，边界回归增至 25 项。
- 新增恢复错误 controller 独立 8 项回归：非 404/null 错误、会话消失、ID 不匹配、非 running、free running 恢复、countdown running 恢复、网络失败兜底；已接入 `.github/workflows/reliability.yml`（node --test 文件数 20→21）。
- 验证通过：41 个 `test-pomodoro-*.js` 文件共 234 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、页面行数 2,453、YAML 解析及 `git diff --check` 通过。
- 已显式提交 9 个源码/测试/文档/CI 路径为 `430db6f8 refactor(pomodoro): 收敛恢复错误控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十六、第一百四十四批：庆祝消除 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/celebration-dismiss-controller.js`，承接 `dismissCelebration`：读取完成标记（fail-closed）、`resolveBreakSec` 解析休息秒数、清理标记、清空 `_completionBreakSec`、隐藏庆祝层，然后按 breakSec > 0 分发到 `_startBreak` 或 `_resetToIdle`。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getCelebrationDismissController()` 懒创建及 `dismissCelebration` 单次委托，页面从 2,453 行变为 2,459 行（accessor 比内联多 6 行，但逻辑已独立）。
- 行为保持：完成标记读取失败仍提示持久化错误并返回；`resolveBreakSec` 参数顺序（completionFlag, completionBreakSec, data）不变；清理顺序（removeStorage → setCompletionBreakSec(null) → setData → startBreak/resetIdle）不变。
- AST 门禁增至 39 个模块、4 条内部依赖，页面预算设为 2,459 行；精确校验庆祝消除壳懒创建单一 controller 并委托 `dismiss()`，边界回归增至 26 项。resilience 静态测试改为从 controller 源码断言 `options.resolveBreakSec(completionFlag`。
- 新增庆祝消除 controller 独立 3 项回归：有 break 时启动休息、无 break 时 reset idle、标记读取失败 fail-closed；已接入 `.github/workflows/reliability.yml`（node --test 文件数 21→22）。
- 验证通过：42 个 `test-pomodoro-*.js` 文件共 238 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `c302f042 refactor(pomodoro): 收敛庆祝消除控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十七、第一百四十五批：休息恢复 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/break-restore-controller.js`，承接 `_restoreBreak`：从存储读取 `pomodoro_break` 快照，校验 startTime/totalSec，按墙钟计算剩余时间，过期时清理并 reset idle，否则以原始 startTime 和 remainingMs 重启休息计时器。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getBreakRestoreController()` 懒创建及 `_restoreBreak` 单次委托，页面从 2,459 行降至 2,457 行。
- 行为保持：存储读取异常仍静默返回 false；过期休息仍清理 `pomodoro_break` 并 reset idle；有效休息仍以 `Number(saved.totalSec)` 和 `{ startTime: Number(saved.startTime), remainingMs }` 调用 `_startBreak`。
- AST 门禁增至 40 个模块、4 条内部依赖，页面预算收紧至 2,457 行；精确校验休息恢复壳懒创建单一 controller 并委托 `restore()`，边界回归增至 27 项。resilience 静态测试改为从 controller 源码断言 `startTime: Number(saved.startTime)` 和 `Number(saved.totalSec)`。
- 新增休息恢复 controller 独立 5 项回归：无快照、格式错误、过期清理、有效重启、存储异常静默；已接入 `.github/workflows/reliability.yml`（node --test 文件数 22→23）。
- 验证通过：43 个 `test-pomodoro-*.js` 文件共 244 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `23664f4f refactor(pomodoro): 收敛休息恢复控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十八、第一百四十六批：完成庆祝 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/completion-celebration-controller.js`，承接 `_showCompletionCelebration`：构建庆祝视图（`buildCompletionCelebration`）、记录任务类型归属、清理全部运行快照（running_state/pause/free_pause/confirm_pause/pause_adjustment）、清空确认快照与 endConfirmMode、设置 completionBreakSec、持久化完成标记、失效画布（canvasInitSeq++/clear ctx/ringCache/pendingDraw）、写入 viewData。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getCompletionCelebrationController()` 懒创建及 `_showCompletionCelebration` 单次委托，页面从 2,457 行降至 2,454 行。
- 行为保持：清理顺序、完成标记持久化、画布失效字段和 `setData(viewData)` 均与原实现一致；`selectedTaskType` 存在时仍调用 `pomodoroTaskTypes.recordSession`。
- AST 门禁增至 41 个模块、4 条内部依赖，页面预算收紧至 2,454 行；精确校验完成庆祝壳懒创建单一 controller 并委托 `show(sessionId, options)`，边界回归增至 28 项。resilience 静态测试改为从 controller 源码断言 `options.removeStorage` / `options.setStorage` / `options.setData`。
- 新增完成庆祝 controller 独立 3 项回归：清理/持久化/画布失效顺序、有 selectedTaskType 时记录、无时不记录；已接入 `.github/workflows/reliability.yml`（node --test 文件数 23→24）。
- 验证通过：44 个 `test-pomodoro-*.js` 文件共 248 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `719fbdca refactor(pomodoro): 收敛完成庆祝控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百五十九、第一百四十七批：工作完成 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/work-complete-controller.js`，承接 `_onWorkComplete`：无会话时 reset idle，否则取 completedAt、清计时器、振动、发起 retryable completion 并在 .then 中消费终态冲突或刷新统计/提示，最后展示完成庆祝。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getWorkCompleteController()` 懒创建及 `_onWorkComplete` 单次委托，页面从 2,454 行降至 2,453 行。
- 行为保持：无会话仍直接 reset idle 不振动；有会话时振动/clearTimer/completeWithRetry/showCompletionCelebration 顺序不变；.then 中冲突优先、synced 刷新统计、未同步提示文案不变。
- AST 门禁增至 42 个模块、4 条内部依赖，页面预算收紧至 2,453 行；精确校验工作完成壳懒创建单一 controller 并委托 `complete()`，边界回归增至 29 项。resilience 静态测试改为从 controller 源码断言 `options.completeWithRetry`。
- 新增工作完成 controller 独立 4 项回归：无会话 reset、有会话振动/清理/同步/庆祝、同步失败提示、终态冲突优先；已接入 `.github/workflows/reliability.yml`（node --test 文件数 24→25）。
- 验证通过：45 个 `test-pomodoro-*.js` 文件共 253 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `edac26ea refactor(pomodoro): 收敛工作完成控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百六十、第一百四十八批：自由计时启动 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/free-timer-begin-controller.js`，承接 `_beginFreeTimer`：解析 server start_time、计算 totalPausedMs、以 `now - startTime - totalPausedMs` 得 elapsedMs、截断至 maxMs、formatElapsedSec 得展示文本、清旧计时器并创建新 timer 对象（sessionId/sessionStartTime/totalPausedMs/freeDisplayOffsetMs=0/pauseStartTime/elapsedSec/freeFriendlyText/progress）、setData（phase/ringCanvasVisible/isFreeTimer/isPaused/freeDisplayTime/showEndConfirm）、updateComputedFields、elapsedMs≥maxMs 时 autoFinishFreeTimer 否则 startFreeTimerInterval 并 nextTick 初始化画布。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getFreeTimerBeginController()` 懒创建及 `_beginFreeTimer` 单次委托，页面从 2,453 行降至 2,441 行。
- 行为保持：server start_time 仍为唯一时钟原点，freeDisplayOffsetMs 固定为 0（不隐藏 /start 网络延迟）；elapsedMs 截断、计时器字段、setData 顺序和画布初始化均与原实现一致。
- AST 门禁增至 43 个模块、4 条内部依赖，页面预算收紧至 2,441 行；精确校验自由计时启动壳懒创建单一 controller 并委托 `begin(session)`，边界回归增至 30 项。resilience 静态测试改为从 controller 源码断言 `now - startTime - totalPausedMs` / `freeDisplayTime: fmt.display` / `freeDisplayOffsetMs = 0`。
- 新增自由计时启动 controller 独立 3 项回归：正常启动设置计时器字段与展示、达到上限触发自动结束、server start_time 为唯一时钟原点；已接入 `.github/workflows/reliability.yml`（node --test 文件数 25→26）。
- 验证通过：46 个 `test-pomodoro-*.js` 文件共 257 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `560a0aed refactor(pomodoro): 收敛自由计时启动控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百六十一、第一百四十九批：取消结束确认 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/cancel-end-confirm-controller.js`，承接 `cancelEndConfirm`：解析 endConfirmMode 与确认快照（内存优先、回退存储）、递增 confirmActionSeq、调用纯 `buildCancelEndConfirmPlan`、应用快照/timer 状态补丁、暂停调整持久化与 setPendingSync、setData、移除确认存储/清空快照、按 plan 分发 startTimer/startFreeTimerInterval/restartFreeTimerInterval/画布重绘/redrawFreeRingAfterOverlay/retryPendingSync。controller 经显式能力回调访问页面，不持有页面 `this`，内部拆分为 `resolveSnapshot`/`buildPlan`/`applyAdjustment`/`executePlan` 四个 ≤50 行辅助函数。页面仅保留 `_getCancelEndConfirmController()` 懒创建及 `cancelEndConfirm` 单次委托，页面从 2,441 行降至 2,419 行。
- 行为保持：快照解析顺序、plan 字段分发、暂停调整存储键与错误路径、画布重绘 nextTick 顺序和 retryPendingSync warn 文案均与原实现一致。
- AST 门禁增至 44 个模块、5 条内部依赖（controller→cancel-confirm-state），页面预算收紧至 2,419 行；精确校验取消结束确认壳懒创建单一 controller 并委托 `cancel()`，边界回归增至 31 项。resilience 静态测试改为从 controller 源码断言 `options.redrawFreeRingAfterOverlay()` / `options.initCanvas(true)` / `options.drawRing(plan.redraw.totalSec`。
- 新增取消结束确认 controller 独立 5 项回归：actionLoading 早退、快照缺失且存储失败显示持久化错误、从存储读取快照后继续、递增 confirmActionSeq、setPendingSync 失败路径；已接入 `.github/workflows/reliability.yml`（node --test 文件数 26→27）。
- 验证通过：47 个 `test-pomodoro-*.js` 文件共 263 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 10 个源码/测试/文档/CI 路径为 `8d697745 refactor(pomodoro): 收敛取消结束确认控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百六十二、第一百五十批：自由结束确认 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/show-end-free-confirm-controller.js`，承接 `_showEndFreeConfirm`：校验 sessionId/actionLoading、计算 elapsed 与 formatElapsedSec、递增 confirmActionSeq、调用纯 `buildFreeConfirmSnapshot` 构建快照、持久化 confirm_pause、非暂停时 setPendingSync pause（失败回滚存储并报错）、设置 confirmTimerSnapshot、清 free interval、更新 timer 字段（elapsedSec/pauseStartTime/freeFriendlyText/endConfirmMode）、setData（含 `buildEndConfirmViewModel`）、非暂停时异步 postPauseWithRetry 并在 .then 中按 confirmActionSeq 守卫刷新 backendPauseDone。controller 经显式能力回调访问页面，不持有页面 `this`。页面仅保留 `_getShowEndFreeConfirmController()` 懒创建及 `_showEndFreeConfirm` 单次委托，页面从 2,419 行降至 2,406 行。
- 行为保持：快照构建字段、存储键与错误路径、setPendingSync 回滚顺序、timer 字段更新、setData 视图模型和 postPauseWithRetry 守卫逻辑均与原实现一致。
- AST 门禁增至 45 个模块、7 条内部依赖（controller→end-confirm-snapshot/end-confirm-view-model），页面预算收紧至 2,406 行；精确校验自由结束确认壳懒创建单一 controller 并委托 `show()`，边界回归增至 32 项。
- 新增自由结束确认 controller 独立 6 项回归：无 sessionId 早退、actionLoading 早退、非暂停时持久化+同步+视图更新、已暂停时跳过后端 pause、存储失败显示错误、setPendingSync 失败回滚+错误；已接入 `.github/workflows/reliability.yml`（node --test 文件数 27→28）。
- 验证通过：48 个 `test-pomodoro-*.js` 文件共 270 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 9 个源码/测试/文档/CI 路径为 `1d774471 refactor(pomodoro): 收敛自由结束确认控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百六十三、第一百五十一批：倒计时暂停确认 controller（2026-10-23）

- 新增 `miniprogram/pages/pomodoro/utils/pause-countdown-end-confirm-controller.js`，承接 `_pauseCountdownForEndConfirm`：校验 sessionId/actionLoading、计算 remainingMs/remainingSec/progress、递增 confirmActionSeq、调用纯 `buildCountdownInterruptSnapshot` 构建中断快照、持久化 confirm_pause、非暂停时 setPendingSync pause（失败回滚+报错）、设置 confirmTimerSnapshot、清计时器、重置 countdownEndAt、formatCountdownDisplay、更新 timer 字段（pauseStartTime/remainingSec/progress/endConfirmMode）、setData、drawRing、非暂停时异步 postPauseWithRetry 并在 .then 中按 confirmActionSeq 守卫刷新 backendPauseDone。controller 经显式能力回调访问页面，不持有页面 `this`，内部拆分为 `computeRemaining`/`buildSnapshot`/`persistSnapshot`/`applyPause` 四个 ≤50 行辅助函数。页面仅保留 `_getPauseCountdownEndConfirmController()` 懒创建及 `_pauseCountdownForEndConfirm` 单次委托，页面从 2,406 行降至 2,372 行。
- 行为保持：剩余时间计算、快照构建字段、存储键与错误路径、setPendingSync 回滚顺序、timer 字段更新、drawRing 调用和 postPauseWithRetry 守卫逻辑均与原实现一致。
- AST 门禁增至 46 个模块、8 条内部依赖（controller→end-confirm-snapshot），页面预算收紧至 2,372 行；精确校验倒计时暂停确认壳懒创建单一 controller 并委托 `pause()`，边界回归增至 33 项。
- 新增倒计时暂停确认 controller 独立 6 项回归：无 sessionId 早退、actionLoading 早退、非暂停时完整流程、已暂停时跳过后端 pause、存储失败返回 false、setPendingSync 失败回滚+返回 false；已接入 `.github/workflows/reliability.yml`（node --test 文件数 28→29）。
- 验证通过：49 个 `test-pomodoro-*.js` 文件共 277 项；stability runtime 46、resilience 106、resume latency 12、free-limit 39、storage cleanup、考试终态、渲染不变式 43 和渲染 fixture 31 全部通过；`node --check`、YAML 解析及 `git diff --check` 通过。
- 已显式提交 9 个源码/测试/文档/CI 路径为 `d6b1ba5d refactor(pomodoro): 收敛倒计时暂停确认控制器`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实微信开发者工具/模拟器/真机、真实弱网/进程终止、外部 OCR/AI、生产 Admin 浏览器、Redis 故障恢复、完整 worker 与备份恢复演练仍未验证。

## 一百六十四—一百六十六：倒计时中断确认/idle 重置/自由计时展示更新 controller（2026-10-23）

三批连续提交：

1. `b6ddb543 refactor(pomodoro): 收敛倒计时中断确认控制器` — `_confirmInterruptCountdown`（37行）→ `confirm-interrupt-countdown-controller.js`，承接暂停补偿累计、终态意图持久化、待同步重试、终态冲突消费与 idle 重置。页面 2,372→2,366。独立 5 项回归。门禁 47 模块/8 边。

2. `a9c2c442 refactor(pomodoro): 收敛 idle 重置控制器` — `_resetToIdle`（43行）→ `reset-to-idle-controller.js`，承接计时器清理、画布失效、7 个存储键全量清理与 idle 视图恢复。页面 2,366→2,356。独立 4 项回归。resilience 和 free-timer-limit 静态测试迁移到 controller 源码。门禁 48 模块/8 边。

3. `bfea2a88 refactor(pomodoro): 收敛自由计时展示更新控制器` — `_updateFreeElapsed`（26行）→ `update-free-elapsed-controller.js`，承接暂停/运行分支展示、5 小时上限截断与 elapsedSec 去重更新。页面 2,356→2,352。独立 4 项回归。free-timer-limit 静态测试迁移到 controller 源码。门禁 49 模块/9 边。

验证通过：52 个 `test-pomodoro-*.js` 文件共 293 项；stability 46、resilience 106、resume 12、free-limit 39、storage、考试终态、渲染 43 和 fixture 31 全部通过。未推送、未部署、未操作数据库。

## 一百六十七、第一百五十二批：OCR 导入与 AI 分析执行兼容基线（2026-10-24）

- 新增 `docs/architecture/OCR_IMPORT_COMPATIBILITY.md`（70 行）：登记上传准入五步顺序（validate→admit→reserve→stage→queue）、格式路由与 pipeline_id 命名（pdf/txt=pl_、excel=xl_、image=img_+hash）、暂存不可变性与预约释放（release 恰好一次、reserve 失败不释放）、worker 分派与 fence（_FENCING_TASK_TYPES 六类 fence、formula_batch/answer_projection/error_diagnosis/prewarm_analysis 不 fence）、OCR 修复链（paddleocr-vl→openai-compatible→rule_fallback、CandidateEvaluator 门禁、乱码持久性拒绝、deepseek 兼容别名）。
- 新增 `docs/architecture/AI_ANALYSIS_COMPATIBILITY.md`（109 行）：登记 `analyze_error` 版本守卫（current_version_id≠wrong_version_id 时比较 grounding_fact_signature，不匹配返回 revision_guard 安全文案、tokens_used=0、不调 LLM）、缓存新鲜度（_meta prompt 版本/模型签名/输入签名/视觉证据校验）、认证隔离（model_config_id+provider+model 短暂隔离、跳过失效模型）、视觉证据与回退（typed worker failure）、`repair_questions` 两阶段（Roman 决策+通用修复）、令牌预算门禁（Redis 共享计数、生产 fail-closed、超限跳过）、不可变选项保护（Layer 4 四规则）、能力解析（AICapability.AI_REPAIR、db=None 降级、加密凭据）和禁用/跳过。
- 新增 `backend/tests/test_services/test_ai_analysis_compatibility.py`（227 行）：4 项真实 SQLite 测试覆盖版本漂移返回 revision_guard（model/tokens_used/revision_guarded/content）、签名匹配不守卫、缺失错题抛 ValueError、同版本不守卫。测试在版本守卫边界内完成，不调用任何 LLM。
- 更新 `docs/architecture/REFACTOR_INVENTORY.md` 导入与 AI/OCR 行，引用两个新基线文档。
- 接入 `.github/workflows/ci.yml` 显式测试列表（test_ai_analysis_compatibility.py）。
- 验证通过：4 项新测试 + 30 项 admission + 5 项 repair config + 9 项 prewarm 共 48 项全部通过；ruff check、compileall、YAML 解析、git diff --check 通过。
- 已显式提交 5 个路径为 `eb656e70 docs(architecture): 登记 OCR 导入与 AI 分析执行兼容基线`；不包含 `AGENTS.md`、本任务记录、`context.md` 或既有删除。未推送、未部署、未操作数据库。
- 真实外部 OCR/AI、生产 Redis 令牌预算共享、worker 多进程并发 fence、真实微信/真机、生产 Admin 浏览器、备份恢复演练仍未验证。

## 一百六十八—一百七十：AI 建议/预热、流水线编排兼容基线（2026-10-24）

三批连续提交：

1. `caa33f9f docs(architecture): 登记 AI 学习建议与预热执行兼容基线` — 新增 `AI_ADVICE_PREWARM_COMPATIBILITY.md`（83 行）：`generate_advice` 无模型回退/错题聚合/LLM 持久化、`prewarm_wrong_question_analysis` 独立会话/跳过与取代/失败转换/成功与缓存命中、`_resolve_healthy_analysis_runtime` 认证隔离跳过。新增 `test_ai_advice_compatibility.py`（2 项真实 SQLite：无模型回退不持久化、有错题仍回退）。

2. `7065768f docs(architecture): 登记流水线编排检查点与工件恢复兼容基线` — 新增 `PIPELINE_ORCHESTRATOR_COMPATIBILITY.md`（90 行）：27 阶段定义表、检查点 write/read/clear 生命周期（轻量元数据/Redis TTL 24h/prune 200）、工件恢复优先级与 `stages_before` 推导、大字段内存释放时序、review 失败跳过。新增 `test_pipeline_checkpoint_compatibility.py`（6 项：往返/clear/缺失/大字段剥离/失败记录/prune 驱逐）。

验证通过：2 项 advice + 6 项 checkpoint + 既有 prewarm/definition/artifact 测试全部通过；ruff、compileall、YAML、git diff --check 通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署、未操作数据库。

## 一百七十一：分段图片替换纯函数收敛（2026-10-24）

- 新增 `admin-frontend/src/app/(admin)/imports/review/review-segment-replace.ts`（50 行）：`executeSegmentReplace` 承接分段图片替换的 canWrite 守卫、previewId 身份检查、上传、segment 更新和错误处理；`resolveSegmentFileChange` 承接文件选取与 input 重置。
- 页面 `handleSegmentReplace` 改为委托 `executeSegmentReplace`（上传函数经闭包注入），`handleSegmentFileChange` 改为委托 `resolveSegmentFileChange`。移除 `updateSegUrl` 直接导入。
- 新增 `review-segment-replace.test.ts`（8 项）：canWrite=false 早退、空文件早退、正常上传+更新+成功消息、previewId 变化跳过更新、上传失败错误消息、非 Error 抛出通用消息、文件选取+input 重置、无文件返回 null。
- 验证通过：typecheck 0 errors、lint 0 errors（10 既有 warnings）、vitest 118 文件 1121 项全部通过、next build 33 路由成功。
- 已显式提交 3 个路径为 `98b3e290 refactor(review): 收敛分段图片替换为纯函数`；不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百七十二：科目应用控制器收敛（2026-10-24）

- 新增 `miniprogram/pages/pomodoro/utils/apply-subjects-controller.js`（37 行）：`buildApplySubjectsPlan` 承接科目列表归一化、路由选择（fromSubjectId/fromSubjectCode）和旧会话 legacy 选择，返回 patches 数组供页面顺序 setData。
- 页面 `_applySubjects` 改为委托 `buildApplySubjectsPlan`，循环应用 patches 并在多 patch 时调用 `_updateComputedFields`。移除 `normalizeCachedSubjects`/`findRouteSubject`/`findLegacySubject` 直接导入。页面从 2,180 行降至 2,160 行。
- 新增 `test-pomodoro-apply-subjects-controller.js`（5 项）：基础 patch 含 choices/loading、无路由选择单 patch、fromSubjectId 匹配添加路由 patch、legacy 选择添加 patch、空 flat 仍产生基础 patch。
- AST 门禁页面预算收紧至 2,160 行；65 模块/17 内部依赖通过。
- 验证通过：118 个 `test-pomodoro-*.js` 文件共 642 项全部通过；`node --check`、YAML 解析、`git diff --check` 通过。
- 已显式提交 5 个路径为 `ece467a8 refactor(pomodoro): 收敛科目应用控制器`；不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百七十三：仪表盘归一化兼容基线（2026-10-24）

- 新增 `backend/tests/test_services/test_dashboard_stats_compatibility.py`（114 行）：20 项测试覆盖 `_extract_json_object`（空/Markdown 包裹/文本环绕/无效 JSON/数组拒绝/嵌套）、`_normalize_text_list`（非列表/非字符串过滤/空串过滤/limit 截断/长文本截断）和 `_normalize_dashboard_actions`（非列表/非 dict/有效动作/无效类型/缺标题/标题描述截断/默认 limit 4/类型小写归一化）。
- 验证通过：20 项全部通过；ruff、compileall、YAML、git diff --check 通过。
- 已显式提交 2 个路径为 `518dc03f test(stats): 固化仪表盘归一化兼容基线`；不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百七十四—一百七十八：复习调度/错因诊断/题型切换/有效暂停兼容基线与收敛（2026-10-24）

五批连续提交：

1. `f77f66a3 test(review): 固化复习调度归一化与SM-2兼容基线` — 35 项纯函数测试：`review_mastery_percent`（7 参数化）、`review_auto_mastered`（8 参数化）、`_sanitize_review_text`（3）、`_sanitize_review_content`（5）、`_sanitize_review_options`（4）、`_sanitize_review_option_value`（2）、SM-2 集成（4：重置/EFactor 下界/间隔序列/非法 quality）。

2. `a9f5517c test(diagnosis): 固化错因诊断分类与归一化兼容基线` — 26 项纯函数测试：taxonomy_items（2）、`normalize_error_type`（12 参数化含 legacy 映射）、`normalize_secondary_types`（6：去重/排除 primary/排除 unknown/limit 3/legacy 归一化）、LEGACY_TYPE_MAP 自映射（2）。

3. `7d97fbd4 refactor(review): 收敛题型切换决策为纯函数` — 新增 `review-question-type-change.ts`（63 行）：`buildQuestionTypeChange` 承接题型切换的 noop/clear_multi_blank/update_type/init_multi_blank 四种决策。页面 `handleQuestionTypeChange` 改为委托。7 项测试覆盖全部分支。

4. `770487dc refactor(pomodoro): 收敛有效暂停时长计算为纯函数` — 新增 `effective-paused-ms.js`（20 行）：`buildEffectivePausedMs` 承接 server base + 活跃暂停 + local adjustment 合并。页面 `_getEffectivePausedMsFromSession` 改为委托。页面 2,160→2,155。5 项测试。

验证通过：后端 61 项新测试 + 管理端 1,128 项 + 小程序 647 项全部通过；typecheck/lint/ruff/compileall/YAML/build/boundaries 全部通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百七十九：图片引用异常检测兼容基线（2026-10-24）

- 新增 `backend/tests/test_services/test_coverage_service_compatibility.py`（119 行）：21 项纯函数测试覆盖 `_image_ref_from_value`（8：字符串/dict/多键/空/空白/无键/非字符串非 dict）和 `_has_image_reference_anomaly`（13：干净内容/有效段/空 URL/缺 URL/非图片段/隐藏段/image_url 列表/非列表/无效条目/options 有效/options 空/math_image/table_image）。
- 验证通过：21 项全部通过；ruff、compileall、YAML、git diff --check 通过。
- 已显式提交 2 个路径为 `92d69004 test(coverage): 固化图片引用异常检测兼容基线`；不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百八十—一百八十二：答题行为/错题记录/科目解析兼容基线（2026-10-24）

三批连续提交：

1. `3fc3b152 test(behavior): 固化答题行为记录与统计兼容基线` — 6 项真实 SQLite 测试：新建行为、同 practice_record_id 更新、无 practice_record_id 总新建、空用户零统计、正确率与均时聚合、零耗时不计入均时。

2. `79f31481 test(wrong-question): 固化错题记录与统计兼容基线` — 4 项真实 SQLite 测试：新建错题、重复答错 review_count 递增、重复答错清除 ai_analysis 缓存、空用户零统计。

3. `26704629 test(subject): 固化科目解析与后代遍历兼容基线` — 9 项真实 SQLite 测试：None 返回 None、int ID 解析、code 大小写不敏感、空串返回 None、未知 code 返回 None、不含后代、含后代 BFS、根含全部、未知返回空列表。

验证通过：19 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百八十三：上传校验器兼容基线（2026-10-24）

- 新增 `backend/tests/test_services/test_upload_validator_compatibility.py`（79 行）：12 项测试覆盖 `validate_file`（6：允许扩展名/拒绝不允许的 source_type/拒绝超限/接受限内/0=无限/未知扩展名通过）、`validate_pdf_pages`（3：0=无限/超限拒绝/恰好在限）和 `validate_batch_size`（3：0=无限/超限拒绝/恰好在限）。
- 验证通过：12 项全部通过；ruff、compileall、YAML、git diff --check 通过。
- 已显式提交 2 个路径为 `44a7b108 test(upload): 固化上传校验器兼容基线`；不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百八十四—一百八十六：计划令牌/水印/资产引用兼容基线（2026-10-24）

三批连续提交：

1. `5950bbd4 test(study-hub): 固化计划归因令牌签发与校验兼容基线` — 15 项纯函数测试：签发（3：非空/不同用户不同/相同参数相同）、校验（12：有效匹配/None/garbage/错用户/错科目/错模式/错数量/错知识点/错 descendants/题目 ID 摘要匹配/摘要不匹配/篡改签名）。

2. `8299ee59 test(watermark): 固化水印匹配与正则校验兼容基线` — 14 项纯函数测试：`match_watermark`（7：空/空白/匹配/不匹配/页码/多模式/无模式）、`_validate_pattern`（5：有效/过长/嵌套量词/无效正则/简单）、`get_default_patterns`（2：编译模式/已知水印匹配）。

3. `7a198985 test(asset): 固化资产URL提取与存储键转换兼容基线` — 13 项纯函数测试：`url_to_storage_key`（5：static/COS/普通/无前导斜杠）、`extract_asset_urls`（8：空/COS/嵌套/列表/无资产/同串多资产/field_name）。

验证通过：42 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百八十七—一百八十九：批量答案/审计文本/AI导入辅助兼容基线（2026-10-24）

三批连续提交：

1. `c1ec2ea9 test(batch-answer): 固化批量答案解析与标准化兼容基线` — 18 项纯函数测试：`parse_answer_string`（9：空/紧凑/逗号/中文逗号/竖线/空格/多选/小写/换行）、`normalize_single_answer`（9：空/单选有效/小写/长度错误/超范围/多选去重排序/判断题 T/判断题 F/不支持题型）。

2. `511fb679 test(audit): 固化审计题目内容文本提取兼容基线` — 11 项纯函数测试：None/字符串/dict text/dict stem/JSON 回退/空串跳过/列表 dict/列表字符串/空列表/非标准类型/键优先级。

3. `9b71fd21 test(ai-import): 固化AI导入辅助函数兼容基线` — 16 项纯函数测试：`extract_json`（5：空/明文/Markdown/文本环绕/无效）、`normalize_enrich`（11：空/科目保留/科目丢弃/类型保留/类型丢弃/难度范围/难度越界/知识点过滤/置信度钳位/章节 trim/未知键丢弃）。

验证通过：45 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百九十—一百九十一：公式表达式校验/AI教师辅助函数兼容基线（2026-10-24）

二批连续提交：

1. `03d8c223 test(formula): 固化公式图表达式校验兼容基线` — 13 项纯函数测试：空/多项式/三角/abs/语法错误/过长/属性访问/lambda/下标/下划线名/未知函数/嵌套/算术。

2. `0c6d29f3 test(ai-teacher): 固化AI教师408辅助函数兼容基线` — 22 项纯函数测试：`_stem_text`（5：text/stem/segments/string/None）、`_bounded`（4：短串/长串/小 dict/大 dict）、`_clean_str`（3：trim/截断/None）、`_clean_points`（4：非列表/空串过滤/limit/截断）、`_parse_json_object`（6：空/明文/Markdown/文本环绕/无效/数组拒绝）。

验证通过：35 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百九十二—一百九十三：安全远程URL/视觉区域bbox兼容基线（2026-10-24）

二批连续提交：

1. `1ea61171 test(remote-fetch): 固化安全远程URL校验兼容基线` — 12 项纯函数测试：`validate_remote_url`（6：HTTPS 接受/HTTP 默认拒绝/HTTP allow_http/凭据拒绝/无 hostname 拒绝>返回 parsed+addresses）、`is_safe_remote_url`（6：HTTPS true/HTTP false/HTTP allow_http true/凭据 false/garbage false/空 false）。

2. `b20ba315 test(visual-region): 固化视觉区域bbox校验兼容基线` — 11 项纯函数测试：None/有效 tuple/list 转 tuple/x 反转/y 反转/零面积/负坐标/荒谬坐标/错误长度/非数值/浮点坐标。

验证通过：23 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百九十四：视觉区域类型与工作者凭据兼容基线（2026-10-24）

- `ac64d72c` — 新增 `test_worker_credential_service_compatibility.py`（10 项：`hash_key` 4/`generate_key` 2/`constant_time_compare` 4）和 `test_visual_region_types_compatibility.py`（14 项：`contains_visual_reference` 4/`get_blocking_risk_flags` 4/segment builders 6）。
- 验证通过：24 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。
- 已显式提交 3 个路径；不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百九十五—一百九十六：任务健康观测/嵌入端点兼容基线（2026-10-24）

二批连续提交：

1. `5c2cf7c8 test(observability): 固化任务健康观测规则兼容基线` — 11 项纯函数测试：健康返回 ok/Redis 未配置/Redis 不可用/非异步不检查 Redis/outbox 停滞/队列停滞/死信高/投影积压/outbox 失败/警告级别/issue 字段完整性。

2. `87925e4f test(embedding): 固化嵌入端点URL构造兼容基线` — 11 项纯函数测试：空/None/OpenAI v1/尾斜杠/完整 embeddings 保留/compatible-mode 追加 v1/compatible-mode/v1 追加 embeddings/阿里云裸主机/阿里云 workspace/裸主机追加 v1/api/v3 路径。

验证通过：22 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。已显式提交，不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百九十七：任务队列键构造与指标格式化兼容基线（2026-10-24）

- `3536f45b` — 新增 `test_task_queue_keys_compatibility.py`（17 项：v1 keys 8 + v2 keys 9）和 `test_task_queue_metrics_compatibility.py`（5 项：空指标全零/全指标/部分指标/额外指标忽略/追加到已有列表）。
- 验证通过：22 项新测试全部通过；ruff、compileall、YAML、git diff --check 通过。
- 已显式提交 3 个路径；不含 AGENTS.md/任务记录/context.md/既有删除。未推送、未部署。

## 一百九十八—二百零四：预热收尾/分析响应/Leitner分层/图片导入收尾/分析校验（2026-10-26）

七批连续提交：

1. `e88bb070 refactor(ai): 拆分预热结果收尾契约` — `finish_prewarm_result` 承接同步 fallback/cache 结果到 worker 成败语义的转换；16 项 prewarm/compatibility/architecture 测试、Ruff、format、`git diff --check` 通过。

2. `9a20088b refactor(ai): 拆分错误分析响应契约` — 新增 `app/services/ai/analysis_responses.py`：生成中、视觉缺失、模型未配置、提供方失败、视觉 ACK 失败、解析失败、grounding 修复与成功响应统一为字段级构造器；新增 6 项响应契约测试，`analyze_error` 533→427 行。

3. `f0bdcd06 refactor(practice): 拆分Leitner分层调度契约` — 新增 `app/services/practice/leitner_layers.py`：new+due→due+1d→oldest→V1 fallback 四层调度、排除集、缺口 limit 与逐层日志由 provider 编排；service 保留 SQL 条件与 V1 loader。新增 3 项分层契约测试，76 项 practice service/API 测试通过，`_get_questions_with_leitner` 121→70 行。

4. `9d1e2bcd refactor(import): 拆分图片导入收尾契约` — 新增 `app/services/import_image_completion.py`：图片导入状态投影、批次缺失降级、错误追加、OCR runtime/raw/cleaned 诊断与 question_count 构造。新增 3 项契约测试，53 项导入/OCR/架构测试通过。

5. `b03126cf fix(import): 保留图片流水线失败原因` — 修正上一拆分中 checkpoint `error_message` 引用被删除局部变量的问题，改从投影后的 `diagnostics.failure_reason` 读取；Ruff F821 捕获并修复，53 项相关测试复跑通过。

6. `a7e03be2 refactor(ai): 拆分分析校验契约` — 新增 `app/services/ai/analysis_validation.py`：解析有效性、answer check、诊断矛盾与视觉 ACK 重试/用量累计由注入式 provider 承接；新增 5 项校验契约测试，30 项 AI 相关测试通过。

7. 同轮此前已提交的 OCR 布局块、图片 OCR 阶段、章节范围读取、相似题元数据和薄弱向量 provider 契约见 `2c8cef15`、`1d3cd20f`、`caa484fb`、`c68d5514`、`d16519a7`。

- 当前超限：`analyze_error` 427 行、`prewarm_wrong_question_analysis` 86 行、`practice_service` 4 项（smart 113、legacy weakness 262、scored 183、batch submit 298）、`import_pipeline_service` 2 项（image 177、generic 124）。`task_queue_service` 已清零。
- 验证均为本地 SQLite/单元/架构证据；未推送、未部署、未操作数据库。真实微信、外部 OCR/AI、生产 Admin、Redis 故障恢复、完整 worker、备份恢复演练仍未验证。
