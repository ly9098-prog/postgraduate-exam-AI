# 管理端题库编辑与即时写入兼容基线

核对日期：2026-10-23。范围是 Admin `/questions` 列表、详情抽屉、草稿保存，以及题干图片/选项的即时写入；不包含 `re_pending` 重审工作台、版本回滚或生产浏览器验收。

## 1. 入口与权威实现

| 用例 | 前端入口 | 后端入口 | 权威状态 |
| --- | --- | --- | --- |
| 科目筛选选项 | `questions/question-api.ts::fetchSubjectOptions` | `GET /api/admin/v1/questions/subject-options` | `admin_subject_service.list_subject_tree(include_inactive=False)`，只返回启用科目。 |
| 列表与详情 | `question-queries.ts`、`questions/page.tsx` | `GET /questions`、`GET /questions/{id}` | 数据库题目与最新版本；TanStack Query 只缓存服务端结果。 |
| 编辑保存 | `use-question-update.ts`、`question-edit-patch.ts` | `PATCH /questions/{id}` | `admin_question_service.update_admin_question` 是版本快照、知识点和审计的事务所有者。 |
| 题干图片/选项即时写入 | `QuestionImageField`、`QuickAddOptions`、`use-question-immediate-mutations.ts` | `POST/DELETE /questions/{id}/images`、`POST /questions/{id}/options` | 服务端返回完整题目；本地只合并 `content`/`options`。 |

`/questions/subject-options` 只要求 `question:read`，不允许题库读者为了筛选而获得科目治理权限。响应保持启用科目的树结构与顺序；前端深度优先扁平化，并沿用既有规则只展示 `level > 1` 的可选题库叶子/子科目。

## 2. 草稿与即时写入组合

- 编辑表单的标量字段（答案、难度、解析、知识点等）属于本地草稿；题干图片或选项写入成功后，只采用服务端 `content`/`options`，不能覆盖同时存在的其他未保存字段。
- 即时写入前若存在脏草稿，先调用同一保存入口。相同题目的并发点击复用同一 pending promise，避免重复 `PATCH`。
- 保存失败、结构化表格未核验或存在空代码块时，不执行后续图片/选项写入。错误提示只对仍选中的同一题目生效。
- 每次选中题目获得一个 `(questionId, generation)` owner。题目切换会推进 generation；旧 owner 的图片/选项响应不得写入新题目的表单。
- 旧 owner 的响应仍可以更新其对应题目的详情缓存并触发失效，但不能改变当前表单。关闭抽屉后迟到的响应同样只刷新旧详情缓存，不重新打开或填充表单。
- 先保存脏草稿期间切换题目，服务端保存结果保留在原题详情；当前题表单不被覆盖，并提示用户重新执行图片或选项操作。

## 3. 权限、缓存与事务边界

- 列表、详情、导出和科目选项均保留 Admin JWT、RBAC 与既有错误 envelope；本次没有改变 Admin/Public 身份边界。
- 保存 mutation 成功后失效题目列表与对应详情范围；即时写入成功后合并返回题目并失效同一范围。404 与失败请求不得伪装成成功缓存。
- 前端不提交、回滚或重建后端事务。图片上传、选项合并、题目版本、知识点链接和审计仍由对应后端服务在同一既有边界内完成。
- 科目选项接口是只读轻量视图，不替代 `/subjects` 管理页面，也不改变科目启停、层级或 408 产品身份规则。

## 4. 回归基线

- 前端：`question-immediate-owner.test.ts`、`question-immediate-mutations.test.ts`、`question-immediate-mutation-integration.test.ts`、`question-option-editing.test.ts`、`question-api.test.ts`。
- 后端：`tests/test_api/test_admin_questions.py`、`tests/test_services/test_admin_question_mutations.py`、`tests/test_services/test_admin_question_service.py`。
- 已验证：切换题目/关闭抽屉后的迟到写入隔离、同题 pending 去重、空 PATCH 继续、脏草稿合并、科目选项权限和详情/版本保存契约。

## 5. 尚未完成的边界

- `questions/page.tsx` 仍承担筛选、列表/表格、抽屉展示、版本比较和多类编辑组合；本基线不宣称页面控制器已拆完。
- 未在真实 Admin 登录会话中执行文件选择、上传、删除图片、快速添加选项和浏览器网络竞态验收。
- 已入库题目 `re_pending`、重审 approve/reject 与 rollback 已在 Admin 题库域实现；本兼容基线原先的“设计预留”结论已被 2026-10-24 实现取代。

## 6. ADM-01 有限领域保留评估（2026-10-30，§325）

本节补充并取代 §5 中作为未完成项的页面职责判断，原先日期与范围保留为历史基线。按 [Admin 消费者映射](ADMIN_CONSUMER_MAP.md) 核查 `/questions`、`/review` 及17个题库消费契约；共享图片/选项组件及考试选题也消费其中接口，但不在此关闭其所属页面领域。另4个已注册但无当前浏览器静态消费的metadata/embedding/toggle端点保留，不据此判断废弃。

| 用例 | 当前权威职责与处置 |
| --- | --- |
| 查询、筛选、URL、选择与详情抽屉 | query/filter/selection/navigation hooks与展示组件已各有所有者；页面保留组合职责，RETAIN |
| 草稿、保存与图片/选项即时写入 | draft/patch唯一转换及owner/generation、QueryClient旧详情缓存隔离已有直接与集成测试，RETAIN |
| 版本比较、导出及批量删除 | 独立query key、历史标签/diff、导出payload/download、50项chunk及幂等key适配已有所有者，RETAIN |
| 重审与回滚 | 四类查询、三类mutation及共享review纯规则保持；补13项真实页面closure契约后RETAIN，不为既有页面长度新增控制器 |
| 后端题库与版本/审计 | 路由保留权限、commit/rollback及幂等认领/完成；service保留题目/KP/不可变revision/审计顺序，snapshot/revision/export/storage已有独立职责，RETAIN |

新增 `review/page.test.ts` 直接调用真实页面，以隔离hook/query/request端口捕获原mutation闭包，覆盖查询key与禁用条件、匹配预览复用/异题读取、表格审核阻断、单项与批量reason差异、有效选择、rollback目标/默认说明、成功后缓存范围与失败提示。它不挂载DOM，也不验证React调度、effect、真实JWT或浏览器文件操作。首轮12通过1失败为新表格夹具缺少requires_review标记，已修夹具，运行时不变；不能把首轮写成全部通过。

本轮5份既有后端测试119项通过；最终管理端143文件1769项通过，其中本域61文件508项，typecheck通过、lint0错误/138警告。无构建配置或运行时改动，未跑build。§323的473文件8155项固定后端CI及§321OpenAPI334快照按冻结输入不变复用，非本轮重跑。具体命令、源码哈希、复用范围和一次独立审查状态见 [结果清单](refactor-results/admin-question-retention-2026-10-30.json)。

本条只关闭有界结构评估；真实Admin登录/RBAC、浏览器交互/图片上传、PostgreSQL/Redis事务与幂等、对象存储和生产仍归最终环境验收。全部结构工作完成后再验收，生产最后且单独授权；ADM-02导入审核等领域继续。
