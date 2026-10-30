# Admin 公式、图资源与考试管理兼容边界

2026-10-30，§330 / ADM-06。六页、32 个消费契约及 19 个注册保留端点完成本轮有界核查；共享公式审核规则从 HTTP 路由移入 `formula_review_rules`，本条为 `DONE`。其余公式 CRUD、图资源和考试管理职责按现有边界保留，真实环境尚未验收。明细见 [结果清单](refactor-results/admin-content-refactor-2026-10-30.json) 和 [Admin 消费者映射](ADMIN_CONSUMER_MAP.md)。

## 1. 结构变化及停止条件

`admin_formulas` 原来同时持有协议/查询/事务编排和单条、批量审核共用的状态转换业务。现在 `formula_review_rules` 集中持有转换表、目标状态、驳回原因校验及卡片字段更新，104 行，最长函数 30 行，无数据库、版本快照、审计或提交操作。

原 `_apply_formula_action` 签名保留，传入路由当前的 `utcnow` callable；新规则在原时点调用时钟。原单条和批量处理器仍动态查找该 helper。它们的请求、SQL、快照、flush、审计、错误分类和 commit 顺序没有变化，其他 39 个原路由函数 AST 保持。规则继续抛既有 HTTPException 以保留内部调用和对外错误契约，没有另建异常转换体系。

本次按整组公式/图资源/考试消费者统一验证和交付。没有为文件长度继续拆 CRUD、查询、渲染器或现有考试服务，也不宣称整个公式路由已经只含协议代码。剩余 CRUD/版本职责在本轮范围内评估保留；之后没有新登记的问题或消费者，不继续扩展热点。

| 范围 | 现有归属及保留理由 |
| --- | --- |
| 公式列表、详情、新建与分类四页 | 页面拥有 URL 筛选、选中项、草稿、编辑和反馈；已有列表/分类纯规则、editor/workbench 组件。分类/卡片 CRUD、软删除、版本行锁、快照和审计保留现有 owner |
| 单条及批量审核 | 新规则模块是状态/字段的单一 owner；路由保留单条读取、批量去重与逐项错误、快照/审计/提交 |
| 图资源上传、元数据、预览、确认、重生与删除 | 已有 asset/spec/batch/storage 服务；流式上传限额、uploaded/generated/template 优先级、按来源删除、预览 token/checksum/版本/警告确认各有边界，不重拆生成器 |
| 考试列表、详情两页 | 页面拥有表单/题序/请求生命周期，已有 exam-paper/detail 纯规则；admin_exam_service 拥有试卷、题目、版本、校验和审计；路由拥有协议、错误映射及提交 |

19 个当前无静态浏览器形状的注册端点继续保留，含旧 numeric-id 写入、清空题目、真题候选及公式批生成/import/校验接口；没有当前页面映射不等于没有外部调用。worker、OCR 和批量恢复的剩余职责继续按各自账本条目核查。

## 2. 审核行为不变

- 非法转换仍先返回 422 和原 detail，不读取时钟、不修改卡片；合法转换在缺失驳回原因校验之前读取缺省时钟。
- 草稿 approve 仅提交到 pending_review；pending_review approve 自动发布；legacy approved publish 及 draft restore 回退保持。
- reject 原样 trim/校验原因；每次合法动作只增加一次 version，保留原字段写入顺序、审核人/时间与发布时间。
- approve 清除旧驳回原因；publish、offline、restore 继续保留旧原因，未顺手修正为其他语义。
- 单条和批量端点继续使用原权限、版本快照和审计。批量首次出现 ID 顺序、not_found/invalid_transition/missing_reason/error 分类和单次 commit 保持。

## 3. 页面和相邻边界

新增 `content-page-contracts.test.ts` 的 19 项直接调用真实六页和图资源/规格组件，核对：

- 创建试卷的分钟换算、公开 ID 导航以及缓存失效等待屏障；旧 numeric-id 读取后跳转到 public_id，写入沿用 public_id。
- 408 候选范围、题序/分值的最小写入载荷，以及空题目、重复题和空分值的精确错误；状态失败重取详情/列表，删除后等待失效再离开。
- URL 筛选/子分类、批量审核仅移除已成功处理的选择项、公式审核原因、详情缓存、受限返回路径及一秒删除反馈。
- 图上传使用 FormData，删除只针对 uploaded；图确认携带 preview token、checksum、card version 与显式警告接受值。

NewFormulaPage 用例只证明其交给既有 FormulaEditorForm 的 create 模式；分类更新用例证明 mutation 请求及失效范围，不证明完整表单归一化。hook/query/mutation/request 为替身，effect 只显式执行旧 ID 重定向，未执行 React/TanStack 完整调度、DOM、原生 multipart 网络或实际导航。

考试后端当前严格要求历年真题选择题 40 道，前端部分旧成功提示仍提及不足 40 道可发布。本轮保留这些字节，未实测该旧提示分支的实际可达性；不能把提示当作后端验收标准。真实浏览器检查继续留 ENV-02。

## 4. 验证和证据边界

- 原实现相关后端 9 文件、218 项通过；当前加新规则 17 项后，10 文件、235 项通过。
- 126 个有限状态/动作/原因组合对照原 helper，返回/错误、全部卡片字段和写入顺序一致。该证据不是数据库或 HTTP 并发验收；持久化测试仍是主要门禁。
- 管理端初次完整运行 148 文件、1856 项，本域 6 文件、152 项。随后把同 19 项中的非法题目断言补强为精确错误，最终 19 项、typecheck、单文件 ESLint 窄验通过；结果保留初次旧 SHA 和最终新 SHA，不冒称最终版本新跑了全套。全域 lint 0 错误、138 条既有警告；无前端运行时/构建配置变更，未跑 build。
- 本轮新跑固定静态回归 **474 文件、8172 项、64 警告**，运行前后 2248 项冻结输入不变；新增后端测试已登记 CI。冻结集合按已提交基线加显式变更/新增项重建，不复制此前整份哈希账本。
- 两个冷进程的全应用 OpenAPI 相等，334 个路径；readiness 69、cloud isolation 30 项通过。严格改动 Python Ruff、app CI 忽略集 Ruff、compileall、diff 检查通过。
- 一次独立只读审查完成，无 P0–P3 发现；独立后端规则/API 51 项、最终前端 19 项通过，等价与哈希核对一致。提交及文档/记忆/保护门禁后进入下一轮。

结果清单保存消费者、变更路径、哈希、原始/当前验证和限制；证据目录为 `/tmp/admin-content-assessment-2026-10-30/`。

## 5. 最终环境出口

真实 Admin/JWT/权限/审计、PostgreSQL 行锁/唯一约束并发、Redis、多 worker、对象存储/外部渲染服务与实际客户端均未验收，继续归 ENV-02..05。SQLite、替身、冷 OpenAPI 和环境画像测试不能代替这些证据。

本轮收尾后下一 ADM-07：dashboard 单页五契约，再 OCR-02/03 和 SHR-01..03。所有真实环境在结构条目全部处置后执行，生产验收最后，生产操作仍需另行授权。
