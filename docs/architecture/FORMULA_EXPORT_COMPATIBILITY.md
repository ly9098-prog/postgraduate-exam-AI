# 公式与错题导出兼容基线

核对日期：2026-10-24。对应重构计划阶段 0；范围仅限 Public 公式库、公式阅读、收藏、错题导出任务/文件记录和小程序 `formulas`、`export` 分包消费者，不代表管理端公式编辑、任务队列全域、真实外部存储/Redis/微信环境或全栈语义审查全部完成。

## 1. 入口与消费者

| 用例 | 实现入口 | 当前消费者 | 兼容边界 |
| --- | --- | --- | --- |
| 公式目录 | `GET /api/v1/formulas/catalog` | 小程序公式库 | 只统计 `published` 且未软删除的卡片；目录计数与列表使用同一学科、题型、收藏、study-card-type 语义。 |
| 学习卡类型 | `GET /formulas/card-types` | 公式库/阅读页展示 | 固定 taxonomy，不在请求事务中写库。 |
| 固定标签 | `GET /formulas/tags` | 公式库筛选 | 按 `sort_order` 返回固定标签；客户端以 id 选择、以 code 组合请求。 |
| 公式列表 | `GET /formulas` | 公式库、阅读页序列补齐 | 只返回 `published` 且未软删除卡片；支持学科/章节/分组、标签 AND、搜索、收藏、函数图、408 速记类型和分页。 |
| 公式详情 | `GET /formulas/{formula_id}` | 公式阅读页 | 只返回已发布卡片；响应合并图资产、图规格和 legacy 平铺 URL，不暴露存储路径。 |
| 公式随机 | `GET /formulas/random/next` | 公式阅读页随机背诵 | 与列表共享过滤语义；候选耗尽时忽略 `exclude_ids` 重试一次。 |
| 收藏列表 | `GET /formulas/favorites/list` | 公式库/阅读页收藏补齐 | 只列当前用户收藏的已发布卡片；复用列表过滤与批量投影。 |
| 收藏/取消 | `PUT/DELETE /formulas/{formula_id}/favorite` | 公式库、阅读页 | 仅作用于已发布卡片，幂等；两次操作均返回同一 `status: ok` 形状。 |
| 导出能力 | `GET /exports/capabilities` | 导出配置/记录页 | 需用户 JWT；全局开启状态、PDF/DOCX/WebSocket、数量和保留期是能力快照。能力关闭时客户端按 `reason_code` 提示。 |
| 导出数量预览 | `POST /exports/preview-count` | 导出配置页 | 与创建任务使用同一 range resolver；预览不执行数量上限。 |
| 创建导出 | `POST /exports` | 导出配置页 | 先预校验范围和数量，再做 60 秒配置幂等、并发上限和任务落库。 |
| 导出列表/详情 | `GET /exports`、`GET /exports/{task_id}` | 导出记录页 | 只读当前用户任务；响应序列化 UTC ISO 时间并携带 `has_file`、重导出状态和队列提示。 |
| 下载信息/文件 | `GET /exports/{task_id}/download`、`/file` | 导出记录页预览 | 本地存储走认证流文件；COS 返回短时签名 URL，COS→local fallback 走认证流文件。导出域错误经全局 HTTP 处理器转成统一 `error.code`，客户端按安全状态文案展示。 |
| 删除导出 | `DELETE /exports/{task_id}` | 导出记录页 | 只能删除非 pending/processing 任务；先保留可回滚快照，再删文件，最后同一事务删除记录。 |
| 失败重试 | `POST /exports/{task_id}/retry` | 导出记录页 | 只允许 failed 源任务；创建新任务并记录 lineage/retry_count。 |
| 原位重导 | `POST /exports/{task_id}/re-export` | 导出记录页 | 复用原 task id、有效旧文件和快照；重导失败时保留上一版可下载文件。 |
| 导出状态推送 | `WebSocket /exports/ws` | `ExportStatusSyncManager` | 优先 bearer subprotocol；生产禁 URL token；事件只作提示，数据库校准仍是事实源。 |

注册以 `backend/app/api/v1/router.py` 与当前小程序请求为准。

## 2. 公式数据与投影语义

- `FormulaCategory` 是 subject/chapter/group 树，唯一性为 `(parent_id, code)`；`FormulaCard` 软删除由 `deleted_at` 表示，学生端只读 `status='published'`。历史 `approved` 已迁移为 `published`，不能在学生端重新引入第三种发布状态。
- `FormulaCardTag` 以 `(formula_card_id, tag_id)` 去重；多标签请求按 code 匹配并用 `HAVING count == tag 数` 表示 AND 语义，不是 OR。
- `study_card_type` 是 408 速记语义（formula/definition/complexity/protocol_rule/key_conclusion/confusable/trap/comparison），与渲染 `card_type`（auto/pure_formula/function_graph）不能合并。`library_type=formula` 表示不过滤而非“仅纯公式”；`function_graph` 表示显式函数图或存在可用图资产的非纯公式。
- 数学学科使用 `math` 逻辑 scope 合并历史 `elementary_math`/`math2_high_math`，列表、目录、随机和收藏必须共享展开；隐藏历史科目仍可被存储和返回的合并目录使用，不能删除数据。
- 章节 ID 校验只接受 active chapter，并验证其父级属于请求 subject 展开集合。列表章节过滤同时接受“卡片直接挂 chapter”和“挂 chapter 子 group”两种历史形状。
- `_card_to_response` 是学生端卡片投影：图资产 URL 会从 local-static/COS 内部形式重写为可访问 URL，但绝不返回服务器文件路径；legacy `graph_image_url`、`graph_thumbnail_url` 与新 `graph_asset`、`graph_specs` 并存。
- 列表/收藏批量预载 tags、specs 和 graph assets，避免 N+1；详情可单卡懒加载。图资产选择规则由 `choose_effective_graph_asset` 拥有，API 不另建第二套权威规则。
- `UserFormulaFavorite` 是收藏事实。API 响应不直接携带收藏集合时，小程序通过收藏列表补齐本地 `isFavorited` 展示；写请求成功后本地乐观更新并使较早的收藏列表响应失效。

## 3. 导出数据与状态机

- `ExportTask` 状态机由共享 `validate_transition` 约束：`pending→processing→completed/failed`，完成/失败可过期，完成/失败/过期可原位重导；API retry 不复活源行，而是创建新任务。
- `ExportSnapshot` 是首次生成时冻结的题目、配置和顺序快照。原位重导优先复用快照；快照丢失时才重建，且源题后续修正不影响旧导出重导结果。
- 快照上限 5MB、单题投影参与既有内容防御；导出内容绑定 `WrongQuestion.question_version_id` 对应的不可变 revision，题面/选项/解析/知识点来自 revision，用户专属 AI 分析优先取 wrong 行。多空题选项缺失、普通选择题选项缺失或空题面会进入 skip 统计，不能伪造成功导出。
- range resolver 只取当前用户 active 错题。`all` 不应用筛选；空 `filtered` 等价全量；`selected` 先去重且任一 ID 非本人/失效即整体拒绝，错误不泄露具体有效 ID。
- 排序和分组也以 wrong row + revision 为事实源。random 使用由排序 ID 派生的确定种子并冻结在快照；分组是排序后的物理分区，组内保持请求排序，不能另建随机顺序。
- 创建幂等 key 覆盖用户、范围、排序/分组/排版、标题、日期、格式和规范化 selected_ids，只匹配 60 秒内 pending/processing 任务；早期全局唯一索引冲突会回滚后重读 winner。
- 并发限制按用户 pending/processing 任务数计算。创建端先锁定既有 pending/processing 窗口再检查；SQLite `FOR UPDATE` 被忽略，存在至多多一个任务的竞态边界，processor 仍按用户处理上限防御。
- processor 用条件 UPDATE 从 pending 原子 claim，worker 心跳和 `GenerationToken` 支持超时丢弃；同一任务不会被两个 processor claim。全局与 PDF/DOCX 双层 semaphore 控制并发。
- 正常失败进入 failed 并保留快照到保留期；有效旧文件的原位重导失败则恢复 completed，标记 `reexport_failed`，旧文件继续可预览。
- 删除路径先检查快照是否仍被其他任务引用，快照 DELETE 先 staged，文件删除失败时 rollback 保留任务/快照/文件所有权；只有文件删除成功后才删除 task 并提交。

## 4. 文件、推送与客户端边界

- 下载端点不生成文件。pending/processing/failed 任务可保留并预览上一版有效文件；`completed` 过期后响应投影为 expired，本地/流文件与签名 URL 均拒绝过期 key。
- `file_key` 只能在 export storage root 内解析，`..`/绝对路径被拒绝。本地文件响应带 `Cache-Control: private, no-store`；COS 签名 URL 短时有效，不能回退为永久对象 URL。
- 导出 `ExportDomainError` 携带内部 snake_case 错误码，但全局 HTTP 错误契约会过滤为统一公开 envelope（小写 domain code 因不满足公开 code 白名单形态会转为 `HTTP_<status>`），且展示文案由小程序按 HTTP 状态生成；因此客户端不得依赖 `docx_disabled`/`task_not_found` 等原始 detail 字符串作为当前协议承诺。
- WebSocket 生产只接受 `bearer,<token>` subprotocol；本地/显式兼容开关才接受 query token。连接按用户归属过滤事件，单用户连接数有限，超限事件裁剪为轻量状态。
- Redis Pub/Sub 不可用时允许同进程推送或轮询降级；跨进程 scheduler→web 推送需要 Redis，这是部署能力边界，不伪装为强一致。
- 小程序导出记录页以 capability 作为入口门禁：本地配置和服务器能力都确认 PDF 可用后才加载/操作记录。能力检查、列表请求、状态更新均有 request token/页面生命周期守卫。
- 状态更新按 `version`、时间戳和终态保护拒绝旧快照；WS 部分事件在完成时可补 GET 详情。每次列表重建会重新校准非终态任务，单个页面只持有一个 sync manager。
- 预览缓存 key 由 task id、完成时间、文件大小和 generator version 组成；重导/删除会同时清理内存缓存和持久化 temp 文件登记。流式下载用同一 API auth/refresh 通道，401 后单次强制刷新。
- 公式库请求有 catalog/tags/favorite/replace 四类版本号和 `_pageAlive` 守卫；搜索防抖值必须等于当前输入才发起替换，卸载时清理所有版本与定时器。
- 公式阅读页按传入/缓存序列导航，序列缓存 30 分钟；随机模式最多保留 24 张历史并只提交最近 50 个 exclude id。收藏和阅读页均防重复点击，失败恢复原状态并提示重试。
- 公式业务时间以服务端同步时钟解析 UTC，展示固定 Asia/Shanghai；不能跟随开发者工具或手机本地时区。
- 导出能力重复实现位于 export 分包与 study 分包，这是微信独立分包不能互相引用下的有意双份代码；行为由 `test-export-capability-error.js` 约束，不能抽回主包或让两处错误文案漂移。

## 5. 旧数据与迁移兼容

- 公式表从初始迁移起包含卡片软删除；图 preview/asset、one-to-many graph spec、408 study-card-type 与复合索引由后续迁移补齐，`v15` 补齐 graph specs 主键。旧数据缺省 study type 为 formula。
- 导出任务初始 `idempotency_key` 是全局唯一；后续迁移改为普通索引并保留 IntegrityError 重读 winner 兼容路径，避免旧 schema/滚动部署下重复插入。
- `error_code`、`version`、processing 心跳和 generator version 是后续兼容字段；旧任务可能缺 `completed_at`/`expires_at`/`snapshot_id`，读取时不能假设非空。
- 失败任务也拥有快照并使用同一保留期，这是后续补上的数据边界；历史失败任务快照缺失时，retry/re-export 会按新任务语义重建。
- 数学逻辑 subject、408 canonical code、公式 `approved→published` 均由数据迁移处理；代码只做 strict canonical 匹配，旧 alias 必须失效而不是静默映射。

## 6. 可执行基线

后端现有回归入口：

```bash
cd backend
APP_ENV=test APP_SECRET=ci-refactor-test-secret-not-production \
DATABASE_URL=sqlite+aiosqlite:///:memory: REDIS_URL= SENTRY_DSN= \
STAGING_STORAGE_DIR=/tmp/formula-export-compat-staging \
.venv/bin/python -m pytest \
tests/test_api/test_formulas.py \
tests/test_api/test_formulas_api.py \
tests/test_api/test_formula_math_subject_scope.py \
tests/export/test_export_api_security.py \
tests/export/test_export_state_machine.py \
tests/export/test_export_comprehensive.py \
-q --tb=short
```

小程序现有脚本：

```bash
node miniprogram/scripts/test-formula-library-compact-ui.js
node miniprogram/scripts/test-formula-library-title-rendering.js
node miniprogram/scripts/test-formula-reader-rendering.js
node miniprogram/scripts/test-formula-graph.js
node miniprogram/tests/test-formula-reader-layout.js
node miniprogram/tests/test-export-capability-error.js
```

首轮本地重放（2026-10-24，SQLite in-memory，无 Redis/真实存储）：

```text
tests/test_api/test_formulas.py
tests/test_api/test_formulas_api.py
tests/test_api/test_formula_math_subject_scope.py
tests/export/test_export_api_security.py
tests/export/test_export_state_machine.py
tests/export/test_export_comprehensive.py
结果：159 collected，156 passed，3 failed
```

首轮失败均为既有测试期望与当前统一错误契约/测试环境不一致，不是该基线新增生产改动。次日测试对齐后复核：

- `tests/test_api/test_formulas.py + tests/export/test_export_api_security.py` 复核结果：47 passed。
- `test_export_api_security.py` 两个用例已从 FastAPI 原始 `detail.error_code` 对齐到当前全局处理器的 `error.code` envelope（404→`HTTP_404`，403→`HTTP_403`）。
- `test_formulas_api.py::test_favorites_list_endpoint_exists` 已改为显式 DB result double，覆盖收藏列表全部过滤参数与空页响应；不再让请求落到未建表的真实 in-memory DB。
- 复核完整首轮清单：159 passed，原有 3 项失败均清零。

首轮除上述 3 项外，公式 API/数学 scope、导出安全用例、状态机与 processor/快照/幂等/本地路径安全回归均通过；对齐后同一清单已全部通过。

首轮小程序重放（2026-10-24，Node 静态/单元脚本）：

- 通过：`test-formula-library-compact-ui.js`、`test-formula-library-title-rendering.js`、`test-formula-graph.js`、`tests/test-formula-reader-layout.js`、`tests/test-export-capability-error.js`（27/27）。
- 失败：`test-formula-library-classification.js` 期望目录保留高等数学旧科目，而当前数学逻辑 scope 已合并为一个 `math` 学科；该脚本还在异步 `run()` 外同步读取 `pageConfig`，脚本结构也已漂移。
- 失败：`test-formula-reader-rendering.js` 旧断言要求 KaTeX radical 保留 `.hide-tail` 包装节点；当前 `katex-mini`/组件渲染实现已改为其他 SVG containment 形状，需专项用真实渲染输出重新刻画，不能在本兼容文档中猜测哪一方是正确行为。

测试对齐复核（2026-10-24）：

- `test-formula-library-classification.js`：科目断言移入异步 `run()`，按当前数学逻辑 scope 同步断言 `elementary_math` 与 `math2_high_math` 均隐藏；脚本通过。
- `test-formula-reader-rendering.js`：当前实现实际仍保留 `.hide-tail`，但块公式节点已迁入 `readingRows[0].fullLineItem.mathNodes`；修正读取路径后原有 SVG containment 断言完整通过，未放宽任何宽度/裁剪约束。
- 上述两个脚本与 `node --check` 均通过；它们仍是 Node 静态/单元证据，不能升级为真实微信渲染验收。

## 7. 未完成与未验证

- 管理端公式创建/编辑、图 preview/confirm、批量生成和公式导入不在本 Public 基线内；不能据此宣称管理端公式域完成。
- 本轮未执行真实微信开发者工具/模拟器/真机、真实 COS/Redis/WebSocket、生产 Admin 浏览器、外部 OCR/AI、完整 scheduler/worker 或备份恢复演练；上述 SQLite/Node 结果不能升级为设备、生产或外部服务验收。
- 导出 Redis 集成测试需要显式集成环境；本机未启动 Redis 时不能记录为真实故障恢复通过。
- 已入库题目 `re_pending` 重审/回滚已由 Admin 题库域实现；公式/导出域不参与审核状态迁移。
- `practice_service.use_leitner` 仍有 TODO(V3)，实现会改变选题行为，需单独立项，不能混入公式/导出等价审查。
