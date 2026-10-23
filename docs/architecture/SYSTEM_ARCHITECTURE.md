# 2240AI 系统架构

> 基于代码与运行时索引（Codebase Memory）整理，不含未来设计。全篇核对：2026-09-02；2026-10-19/20 补充分批职责拆分说明；2026-10-23 修正模块清单文件名、services 文件数、grade_batch 端点与时区表述，不代表全篇重新验收。

---

## 总体架构

```
管理端 (Next.js 16 / React 19) ─┐
微信小程序 ────────────────────┼→ Nginx → FastAPI 单体后端 → PostgreSQL
                               │              ├─ AI Gateway / 配置解析
                               │              ├─ OCR Gateway + Pipeline
                               │              ├─ Redis 任务队列 / 缓存
                               │              └─ 本地 / 云端存储
```

### 分批职责拆分（更新于 2026-10-20）

| 入口 | 规则归属 | 边界 |
| --- | --- | --- |
| `backend/app/api/v1/practice.py` | `backend/app/services/practice/response_content.py` | 学员题干/选项投影、代码格式保护与判断题选项回退集中在纯转换模块；继续复用既有正文协调与元数据裁剪规则，不持有 HTTP/数据库状态 |
| `backend/app/api/v1/practice.py` | `backend/app/services/practice/request_filters.py`、`request_scope.py` | 请求筛选解析、学科/知识点范围解析与错误优先级由无路由依赖的模块负责；路由保留 HTTP 映射，范围模块复用既有 `practice_service` 查询，不新增事务所有者 |
| `backend/app/api/v1/practice.py` | `backend/app/services/practice/candidate_selection.py`、`candidate_schedule.py` | 显式候选请求/结果承接策略分流及推荐日志容错；到期筛选负责 Leitner 复核与补题。复用既有 provider，不持有 HTTP 或最终发题事务 |
| `backend/app/api/v1/practice.py` | `backend/app/services/practice/final_candidates.py`、`batch_issuance.py`、`issued_response.py` | 最终守卫校验版本/学科及定向集合并对齐曝光；签名模块构建知识与计划归因上下文；响应模块只消费签发版本 |
| GET 发题请求 | `backend/app/services/practice/request_assembly.py`、`question_issuance.py`、`request_observability.py` | 装配按原顺序解析范围/trace/筛选，发题用例协调既有候选与签名模块，观测保留日志及快照；预约清理服务只执行同事务 SQL。路由负责参数/鉴权、HTTP 映射，以及完整响应与诊断成功后的最终提交 |
| 公共学习、共享查询与导入服务的科目解析 | `backend/app/services/subject_resolution.py` | 严格 ID/code 解析及包含停用后代的范围查询由中立模块提供；不依赖 Admin service、HTTP 或会话工厂，不写库/提交事务。Admin 写入与审计仍留在 `admin_subject_service.py` |
| `admin-frontend/src/app/(admin)/questions/page.tsx` | 同目录 `question-list-state.ts`、`question-api.ts`、`question-content-editing.ts`、`question-edit-patch.ts`、`question-edit-draft.ts`、`question-segment-editing.ts`、`question-option-editing.ts`、`question-queries.ts`、`question-version-comparison.ts`、`question-editor-events.ts`、`components/question-{code-editor,table-editors,option-editor,difficulty-badge,version-value,version-diff,version-comparison}.tsx`、`hooks/use-question-{queries,update,delete,immediate-mutations,editor}.ts` | URL/筛选、请求协议、题干/最小 PATCH/草稿转换和服务端状态分别就近聚合；query 模块集中 key、请求及占位数据，写入 hooks 持有保存/删除、缓存失效、实例级幂等键和即时操作前并发保存。编辑 hook 持有局部草稿、dirty 与进入/退出编辑流程，事件适配集中滚动锁、离页和 Escape 订阅/清理；页面保留权限、抽屉/列表选择、确认框展示、UI 反馈和下载编排；同一 PATCH 规则服务于 dirty 判定及两条保存路径。代码块/表格/选项组件通过明确 props 编辑，段落及选项更新规则由纯模块聚合；版本字段投影及比较展示就近聚合，查询/版本选择/加载标签继续由页面拥有 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `review-edit-state.ts` | 编辑状态类型、导入题干与选项旧字段解析、多空题状态初始化由无页面/网络/浏览器依赖的适配模块承接；审核草稿、交互状态及页面编排仍由页面拥有 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `review-query-state.ts`、`review-drawer-state.ts`、`review-batch-complete-draft.ts`、`review-batch-complete-result-state.ts`、`review-confirm-dialog-state.ts`、`review-action-feedback.ts`、`review-action-dialog-state.ts`、`review-batch-answer-view-state.ts` | review-queue 参数、默认筛选与重置可见性由纯函数承接；预览快照、编辑会话、段落克隆和未保存检测由独立规则模块承接；批量补全字段默认/切换及 localStorage 草稿读写/修复由可注入存储的规则模块承接，缺失、损坏或存储异常仍静默回退；批量结果按原顺序生成摘要和非成功明细；确认弹层按动作与选择数生成标题、说明、按钮文案、危险态和驳回输入条件，审核结果按动作生成提示与是否关闭抽屉，确认/选择/驳回原因由 reducer 保持打开、取消、函数式选择更新与成功重置语义；快速补充答案按结果优先级、页签和步骤生成状态栏/可见性/加载文案。页面仍拥有筛选、分页、debounce、query key、请求生命周期、API 调用、编辑确认、草稿恢复提示、执行锁与抽屉开关 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `review-subject-state.ts` | 科目叶节点优先读取显式 `is_leaf`，再按 `parent_id`、路径祖先推断；缺少层级元数据时保留全部候选。查询生命周期与下拉 UI 仍由页面持有 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `review-action-requests.ts` | 单题、批次与低风险审核请求路径、批量并发分块、部分失败汇总及幂等键参数由独立请求执行器承接；TanStack mutation、确认状态、提示、缓存失效和抽屉控制仍由页面持有 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `hooks/use-review-action-mutation.ts` | 审核 mutation 的请求执行、实例级幂等键、成功后的回调/选择重置及 review/batch/question 缓存失效由页面 feature hook 承接；页面仍拥有中文反馈、抽屉关闭和确认状态展示 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `review-save-request.ts`、`hooks/use-review-update-mutation.ts` | 普通/多空题保存 payload、段落编辑写回、视觉/表格阻断和保存 mutation 的请求/缓存生命周期由请求模块与 feature hook 承接；页面保留视觉状态计算、编辑草稿和保存后的 UI 状态 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `hooks/use-review-answer-mutations.ts` | 快速答案保存与人工确认的 PUT 请求、成功/失败回调和审核队列/详情缓存失效由 feature hook 承接；答案提示和快速答案草稿清理由页面提供回调 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `hooks/use-review-complete-mutation.ts` | 单题 AI 补全请求、错误包装、审核队列失效、详情缓存写回及页面状态接纳时序由 feature hook 与页面回调协作承接 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `hooks/use-review-batch-answer-mutations.ts` | 文本批量答案预览/应用请求、错误/加载生命周期与审核队列失效由 feature mutation hook 承接；页面保留草稿和预览结果展示 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `hooks/use-review-image-answer-mutations.ts`、`hooks/use-review-image-answer-flow.ts` | 图片批量答案 FormData 预览、token 应用、错误/加载生命周期与审核队列失效由 mutation hook 承接；完整流程 hook 持有文件追加/移除、导入模式、预览/写入结果及错误状态，保留批次/文件/token 前置条件、重置语义和 mutation 回调时序。页面只连接当前批次与展示 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/batch-answer-results.tsx` | 文本批量答案的统计、逐题状态表、警告和写入结果由无状态展示组件负责；页面保留显示条件、草稿、请求和关闭状态，使用写入/关闭回调连接 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/image-answer-results.tsx` | 图片答案的匹配统计、逐题表格、来源/置信度、警告及写入结果由无状态展示组件负责；页面保留文件、模式、请求及显示条件，通过写入/关闭回调连接 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-answer-editor.tsx`、`review-answer-selection.ts` | 答案/解析编辑展示与单选/多选切换规则分开；组件通过字段回调连接页面草稿，纯规则保留分隔、重复项、选项顺序和未知题型回退，多空题继续使用既有识别规则 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-visual-segment-editor.tsx`、`hooks/use-review-segment-drag.ts` | 视觉片段的展示、排序、归属和删除复用既有 segment-utils；页面实例级拖拽状态由 hook 持有，上传请求/异步写回与文件输入引用留在页面，卡片不接收输入 ref |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-option-editor.tsx`、`review-option-editing.ts` | 选项编辑按多空、图片选项、普通文本优先级组合；普通文本更新与选项片段移除由纯规则负责，页面保留草稿 setter、多空 reducer 和图片模式确认回调 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-json-view.tsx` | 审核详情 JSON 模式的基础信息、解析数据、重复检测和 OCR/AI 原始数据分组及折叠展示由无状态组件承接；页面保留模式切换与编辑状态 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-source-evidence.tsx` | OCR 原始文本/JSON、原题快照与旧版原图对照按独立展示职责组合；组件保留来源字段回退、整页快照提示和点击打开行为，无请求或编辑状态 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-question-preview.tsx` | 详情题干和选项的渲染组合复用内容渲染器、多空与图片预览；页面保留运行时问题去重状态，组件保留内容回退、已消费资产过滤与多空优先级 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-answer-preview.tsx`、`review-display-text.ts` | 答案状态、来源、普通/多空答案与解析由展示组件负责；来源定位与答案来源共用原有文本有效性规则，页面继续持有审核数据和编辑草稿 |
| `admin-frontend/src/app/(admin)/imports/review/page.tsx` | 同目录 `components/review-stem-editor.tsx` | 题干输入和结构化表格编辑组合复用既有表格规范化/编辑器；回调按原片段索引更新或移除，页面保留草稿、片段状态及保存生命周期 |
| `miniprogram/subpackages/study/practice/practice.js` | 同目录 `utils/subject-tree.js`、`utils/launch-preset.js`、`utils/question-batch.js`、`utils/recent-subjects.js`、`utils/question-load-state.js`、`utils/sequential-restart-controller.js`、`utils/answer-interaction-controller.js`、`utils/question-display-controller.js`、`utils/computed-fields-controller.js`、`utils/answer-feedback-controller.js`、`utils/render-invariant-controller.js` | 科目树别名/排序/孤儿子科目规范化、可选择科目扁平化、科目图标/标记、最近科目装饰、父科目/子科目关系、练习范围解析、启动参数解析、定向题约束覆盖、fast/完整启动视图、启动 override 写入、发题请求参数构建、章节后代范围契约、题目 ID/题型/科目范围校验、默认科目选择、最近科目去重/截断/持久化值构建、失败/成功/顺序重置视图、批次凭据写回和顺序计时重置由纯规则负责；顺序重置 controller 经显式能力回调承接完成确认、reset 请求、迟响应/卸载守卫、失败提示与重载分发。页面继续持有存储读写、请求发送和其余迟响应守卫 |
| `miniprogram/subpackages/study/review-today/review-today.js` | 同目录 `utils/group-submission.js`、`utils/submit-confirm-controller.js`、`utils/submit-request-controller.js`、`utils/submit-result-controller.js`、`utils/submit-entry-controller.js`、`utils/next-group-controller.js`、`utils/next-retry-group-controller.js`、`utils/next-remote-batch-controller.js`、`utils/result-dock-controller.js`、`utils/review-timer-controller.js`、`utils/master-controller.js`、`utils/start-batch-controller.js`、`utils/draft-controller.js`、`utils/answer-interaction-controller.js`、`utils/question-display-controller.js`、`utils/overview-vm-controller.js` | 小组复习提交 payload 的组内顺序、未答/版本/occurrence/request-id 校验和答案投影，批改结果按 schedule/version/occurrence 精确匹配后的 question-id 回退、提交/失败/缺结果/需刷新/可重试/跳过状态与复盘字段，失败提示、历史合并、重试组、今日进度和结果视图字段由纯规则负责；未答/全部完成两类提交确认、pending 锁、失败静默与页面存活/phase 守卫，批改请求、空/部分结果提示、页面死亡守卫和结果投影，已确认草稿清理、session 写入、计时暂停、结果视图与完成 dock，重复/忙碌入口拦截、异步后组身份与答案重校验、submitting 状态和日同步回滚，下一组入口忙碌拦截、flow 序号、日同步回滚、本地/远端优先级、请求异常、完成态与 dock 写回，本地重试组存在性校验、字符串/原始 schedule_id 答案键过滤、会话/视图切换、作答标记同步与计时重启，远端下一批次请求、题目规范化、草稿恢复、批次计数、静默刷新、空批次重试/完成判定、迟响应守卫与进入视图，以及完成 dock 展示、旧 fade 清理、5 秒隐藏及页面/phase/剩余任务守卫由显式能力 controller 负责。计时启动/恢复/暂停/重置/停止、tick 十秒截断、页面存活守卫、elapsed 视图写回和幂等时长快照由 timer controller 承接；标记掌握确认/提交/移除、5 秒撤销窗口、unmaster 恢复、跨天同步失败、inactive 任务与请求异常路径由 master controller 承接；首次启动批次的忙碌拦截、flow 守卫、题目规范化、草稿恢复、当前题装配、任务计数/视图写回、渲染检查与计时启动由 start controller 承接；草稿键构建、读写、持久化、恢复与已提交清理由 draft controller 承接；单选/多选/多空选项切换、答案持久化触发与视图写回由 answer interaction controller 承接；题目展示/当前题装配/已答计数/runner 字段/已答标记同步由 question display controller 承接；概览 VM 构建/建议文案/批次大小归一化由 overview VM controller 承接。页面继续持有能力注入和 controller 装配 |
| `miniprogram/pages/pomodoro/pomodoro.js` | 同目录 `utils/timer-math.js`、`utils/session-storage.js`、`utils/pending-sync-queue.js`、`utils/countdown-session-restore-controller.js`、`utils/free-session-restore-controller.js`、`utils/start-session-controller.js`、`utils/unknown-start-controller.js`、`utils/pending-sync-controller.js`、`utils/terminal-conflict-controller.js`、`utils/stats-controller.js`、`utils/theme-controller.js`、`utils/active-sync-controller.js`、`utils/pause-toggle-controller.js`、`utils/resume-error-controller.js`、`utils/celebration-dismiss-controller.js`、`utils/break-restore-controller.js`、`utils/completion-celebration-controller.js`、`utils/work-complete-controller.js`、`utils/free-timer-begin-controller.js`、`utils/cancel-end-confirm-controller.js`、`utils/show-end-free-confirm-controller.js`、`utils/pause-countdown-end-confirm-controller.js`、`utils/confirm-interrupt-countdown-controller.js`、`utils/reset-to-idle-controller.js`、`utils/update-free-elapsed-controller.js`、`utils/begin-countdown-controller.js`、`utils/pause-session-controller.js`、`utils/resume-session-controller.js`、`utils/show-countdown-interrupt-confirm-controller.js`、`utils/confirm-end-timer-controller.js`、`utils/end-session-controller.js`、`utils/pause-free-timer-controller.js`、`utils/resume-free-timer-controller.js`、`utils/interrupt-session-controller.js`、`utils/confirm-end-free-timer-controller.js`、`utils/free-timer-limit-controller.js`、`utils/free-elapsed-controller.js`、`utils/start-break-controller.js`、`utils/start-timer-controller.js`、`utils/canvas-init-controller.js`、`utils/draw-ring-controller.js`、`utils/end-confirm-snapshot.js` | 时间计算、存储异常适配、待同步队列、两种计时模式的冷恢复、启动仪式、未知启动恢复、待同步动作、终态冲突、今日统计、主题、活动会话轻同步、暂停切换、恢复错误、庆祝消除、休息恢复、完成庆祝、工作完成、自由计时启动、取消结束确认、自由结束确认、倒计时暂停确认、倒计时中断确认、idle 重置、自由计时展示更新、倒计时启动、暂停会话、恢复会话、倒计时中断确认展示、结束确认分发、结束会话、暂停自由计时、恢复自由计时、中断会话、自由结束确认分发、自由计时上限、自由计时已用时长、休息启动、计时启动、画布初始化/重试、画布绘制及确认窗口快照分别由无页面依赖模块负责；恢复 controller 只经显式能力回调访问页面并由适配壳创建/委托，启动 controller 承接启动锁、未知启动前置、pending flush、free/倒计时分流、ceremony、409 active 恢复和错误收口，未知启动 controller 承接同一幂等键重放、取消意图、active/terminal/迟到响应收敛及存储 fail-closed，待同步 controller 承接队列 head drain、终态冲突记录/清理编排、404/409 reconciliation、校准重试与 active restore，终态冲突 controller 持有跨进程冲突标记的读写/消费/确认与清理编排，并以显式能力回调完成 drop/完成标记清理/ack 顺序，统计 controller 持有单调请求序号并只让最新响应写回今日会话/时长，主题 controller 持有主题视图模型、原生主题应用与切换计时器生命周期，活动会话轻同步 controller 承接资格判定与按墙钟重算剩余时间、暂停补偿合并、缺失画布重建、free 上限/自动结束与倒计时重启，暂停切换 controller 承接 tap 冷却锁与 free/倒计时暂停/继续分发，恢复错误 controller 承接 /resume 404 后拉取权威 active 会话并按 free/countdown 分支修复本地状态，庆祝消除 controller 承接完成标记读取、break 秒解析与 idle/break 分发，休息恢复 controller 承接从存储读取休息快照、过期清理与重启，完成庆祝 controller 承接庆祝构建、任务类型记录、运行快照清理、完成标记持久化与画布失效，工作完成 controller 承接无会话 reset、振动、清理计时器、retryable completion、终态冲突消费与庆祝展示，自由计时启动 controller 承接 server start_time 解析、暂停补偿、已用时长计算、free 上限判定、计时器与画布初始化及自动结束分发，取消结束确认 controller 承接快照解析、cancel plan 编排、暂停调整持久化、计时器重启/画布重绘与待同步重试，自由结束确认 controller 承接快照构建、持久化、后端 pause 触发、计时器状态更新与视图模型组装，倒计时暂停确认 controller 承接剩余时间计算、中断快照构建、持久化、后端 pause 触发、计时器停止与画布重绘，倒计时中断确认 controller 承接暂停补偿累计、终态意图持久化、待同步重试、终态冲突消费与 idle 重置，idle 重置 controller 承接计时器清理、画布失效、存储键全量清理与 idle 视图恢复，自由计时展示更新 controller 承接暂停/运行分支展示、5 小时上限截断与 elapsedSec 去重更新，自由计时已用时长 controller 承接原始/effective elapsed 计算与本地暂停补偿合并，倒计时启动 controller 承接 server start_time 解析、暂停补偿、剩余时间计算、timer 状态与视图设置及自动完成分发，画布初始化 controller 承接初始化代际、选择器测量、稳定布局重试、DPR/尺寸绑定与 pending draw 冲洗，暂停会话 controller 承接 pause 意图持久化、计时器停止、暂停快照存储与待同步重试，恢复会话 controller 承接暂停补偿累计、resume 意图持久化、调整存储、计时器重启与待同步重试，倒计时中断确认展示 controller 承接倒计时暂停、确认视图模型组装与画布重绘，结束确认分发 controller 承接模式分发与异常 toast，结束会话 controller 承接计时器清理、retryable completion、终态冲突消费与 idle 重置，暂停自由计时 controller 承接 pause 意图持久化、elapsed 更新、free interval 清理与暂停快照存储，恢复自由计时 controller 承接暂停补偿累计、resume 意图持久化、调整存储、free interval 重启与待同步重试，中断会话 controller 承接 free\/countdown 中断确认分发，确认窗口快照模块只负责校验与字段组装。页面保留懒创建与单次委托，并继续负责 `api.now()` 注入、本地暂停修正、冲突存储适配、网络监听、生命周期与五小时上限。队列按 Page 实例注入存储适配器，持久化键与顺序、去重、容量阀值保持不变 |

这些是已接入实际入口的等价抽取，不代表长页面、底层选题实现或完整学习域已经治理完毕；GET 发题入口已收敛，刷题提交链路、刷题会话加载和番茄钟剩余 Page controller 仍待后续治理。请求范围、候选/最终守卫及签名响应模块只协调既有服务能力，不反向导入路由；API 路由定义、事务、存储键、界面和分包边界均未更改。小程序队列、两个冷恢复 controller、启动仪式 controller、未知启动恢复 controller、待同步动作 controller、终态冲突 controller、统计 controller、主题 controller、活动会话轻同步 controller、暂停切换 controller、恢复错误 controller、庆祝消除 controller、休息恢复 controller、完成庆祝 controller、工作完成 controller、自由计时启动 controller、取消结束确认 controller、自由结束确认 controller、倒计时暂停确认 controller、倒计时中断确认 controller、idle 重置 controller、自由计时展示更新 controller、倒计时启动 controller、暂停会话 controller、恢复会话 controller、倒计时中断确认展示 controller、结束确认分发 controller、结束会话 controller、暂停自由计时 controller、恢复自由计时 controller、中断会话 controller、自由结束确认分发 controller、自由计时上限 controller、自由计时已用时长 controller、休息启动 controller、计时启动 controller、画布初始化 controller、画布绘制 controller、确认窗口快照模块与复习计时 controller 不依赖 `Page`、全局 `wx`、网络或共享可变队列，刷题科目树纯规则不依赖 `Page`、全局 `wx`、网络或存储，存储读写失败保持闭锁语义。

OCR 架构测试 `backend/tests/architecture/test_architecture_boundaries.py` 已修正仓库根路径；源码扫描必须发现非空 Python 文件集合，缺失/空目录直接失败，注入越界导入的测试验证扫描器能检出违规。刷题投影和请求筛选纯规则另有 AST 检查，禁止直接依赖路由、FastAPI、SQLAlchemy 或数据库会话模块；请求范围、候选策略、到期筛选、最终守卫和签名响应编排允许数据库会话类型，但禁止路由、FastAPI、数据库会话工厂依赖及 `commit`/`rollback` 调用。管理端新增 API 边界测试，限制题库 API 模块依赖既有 client/types，并检查不直接调用原生 fetch 和新增业务文件/函数预算。实际回归结果与历史失败修复见 `prompts/tasks/current_task.md` 执行记录。

后端全应用依赖门禁位于 `backend/tests/architecture/test_dependency_direction.py`：service/feature 静态导入 API 必须为零，新增静态循环边必须为零。扫描包含相对、局部和可静态解析的字面量动态导入；6 组既有循环的 120 条具体边保存在同目录 `import_cycle_baseline.json`，逐组说明迁移条件，已解除的边必须移除。门禁已接入 CI 的静态架构回归步骤；扫描限制、全栈入口清单、当前热点与未完成验证见 `docs/architecture/REFACTOR_INVENTORY.md`，静态图不代替运行时或业务语义验收。

向量运行请求与管理端连通测试通过 `backend/app/services/embedding_endpoints.py` 共用端点构造纯规则；`vector_config_service` 不再反向导入 embedding 执行服务，两者的静态循环已解除。配置解析、凭据、SSRF 校验、请求序列化及向量维度/批量排序仍由原服务负责。

导出业务服务和 scheduler 处理器共用 `backend/app/services/export/state_machine.py` 的转换表/校验规则，service 不再反向导入 processor；任务状态枚举仍以现有 schema 为准。领取、并发、事务、超时和重导出恢复仍由原入口拥有，本次未改变状态机协议。

导出 phase3 验收样本由 `backend/tests/export/docx_acceptance_fixture.py` 调用真实 DOCX exporter，在 pytest 临时目录生成；不依赖本机 artifacts 目录或提交二进制样本。测试覆盖可解析性和内容结构，不代表完整 OOXML 合规；严格校验发现的现有属性顺序、zoom、矩阵包装及片段公式问题见 `REFACTOR_INVENTORY.md`，未在测试夹具重构中修改应用渲染语义。

### 核心设计原则

- **单体后端**，不分微服务，3 层：Route → Service → Model
- **暂存区模式**：所有导入/AI 生成数据先入 `question_imports`，人工审核后才进 `questions`
- **AI 降级**：统一 Gateway 负责并发、限流、熔断、Token 预算和 fallback
- **双身份隔离**：小程序用户使用微信 openid；Admin 使用独立用户名/密码与 JWT 域
- **导入暂存**：OCR/AI 结果先进入 `question_imports`，人工审核后才发布到 `questions`

---

## 技术栈

| 层级 | 技术 | 版本/说明 |
|------|------|-----------|
| 后端框架 | FastAPI | 0.111.0, 异步 |
| ORM | SQLAlchemy 2.0 | async 模式 |
| 数据库(开发) | SQLite | aiosqlite |
| 数据库(生产) | PostgreSQL 15+ | asyncpg |
| AI | OpenAI-compatible Gateway | 模型配置由 Admin API 管理 |
| OCR | PaddleOCR / PaddleOCR-VL | 本地进程或远程 HTTP，按部署画像选择 |
| PDF | PyMuPDF | 1.24.9 (fitz) |
| Excel | openpyxl | 3.1.5 |
| 前端（学员） | 微信小程序 | 原生框架 |
| 管理端 | Next.js 16.2 + React 19.2 | TypeScript, React Query, Zustand, Tailwind 4 |
| 容器 | Docker Compose | 多阶段构建 |
| 反向代理 | Nginx | 1.25-alpine, HTTPS |

---

## 项目目录

```
postgraduate-ai/
├── backend/app/
│   ├── api/v1/       # Public/Admin router 实现与聚合
│   ├── core/         # 基础设施 (config/database/security)
│   ├── models/       # SQLAlchemy ORM 模型
│   ├── schemas/      # Pydantic 模型
│   ├── services/     # 业务逻辑 (156个.py文件，另有 practice/export 等子包)
│   ├── features/     # 导入管线 (ImportTextNormalizer 等)
│   ├── ai/           # AI 集成（OpenAI-compatible 网关，模型由 Admin API 配置）
│   └── main.py
├── admin-frontend/   # 管理端 (Next.js, shadcn/ui)
├── miniprogram/      # 微信小程序主包与 study/formulas/export 等分包
├── deploy/           # 生产部署
├── docs/             # 文档 (按类别分目录)
├── prompts/          # AI Prompt 工程文件
└── docker-compose.yml
```

---

## 模块清单

| 模块 | 状态 | 文件 |
|------|------|------|
| 用户认证 | ✅ 完成 | auth.py, security.py, user_service.py |
| 题库 CRUD | ✅ 完成 | questions.py, question_service.py |
| 随机刷题 + 判分 | ✅ 完成 | practice.py, practice_service.py |
| 错题本 | ✅ 完成 | wrong_questions.py, wrong_question_service.py |
| SM-2 复习调度 | ✅ 完成 | review.py, sm2_service.py, review_scheduler.py |
| AI 错题分析 | ✅ 完成 | ai.py, ai_service.py, ai/client.py |
| AI 学习建议 | ✅ 完成 | (同上) |
| 题库导入 | ✅ 完成 | imports.py, import_service.py |
| AI 辅助导题 | ✅ 完成 | ai_import.py, ai_import_service.py |
| OCR 扫描 PDF | ✅ 已接入 | `features/ocr_*`, `ocr_worker/`, PDF 页面流 |
| 批量图片导入 | ✅ 完成 | batch_image_import_service.py |
| 批量图片 SSE 流式追踪 | ✅ 完成 | sse.ts, admin_imports.py |
| 学习统计 | ✅ 完成 | stats.py, stats_service.py |
| 答题行为记录 | ✅ 完成 | behavior.py, behavior_service.py |
| 知识点标签 | ✅ 完成 | knowledge_points.py, knowledge_point_service.py |
| RAG 检索 | 🟡 API/模块可用，业务接入范围有限 | `app/api/v1/rag.py`, `rag/` |
| 编程题渲染 | ✅ 已接入 | Admin 专用代码渲染；小程序 CODE 渲染路径 |
| 题目图片预加载 | ✅ 已接入 | `question-image-cache.js` 会话级预解码缓存 |
| Admin 运维中心 | ✅ 已接入 | 系统健康、任务、队列、追踪、备份权限隔离 |
| 408 选择题考试域 | ✅ 已部署 | `models/exam.py`、`/api/v1/exams`、`/api/admin/v1/exams`。试卷有 `public_id` 与软删除；作答绑定 `question_version_id`，可放弃或按时长过期 |
| 408 学习体系 | ✅ 已部署 | 学习计划（study_plan）、错因诊断（error_diagnosis）、408 大纲（syllabus）、知识地图 |
| 刷题稳定性 | ✅ 已部署 | 顺序预约（sequential_reservation）、答案投影 outbox（task_outbox）、会话 scope（practice_sessions.syllabus_version_id） |

---

## 关键架构图

### AI 调用链

```
请求 → ai_service.py
  ├─ 缓存检查 (WrongQuestion.ai_analysis)
  ├─ token 估算 (硬限制)
  ├─ 构建上下文 → 构造 Prompt → 调用 LLM（OpenAI-compatible 网关）
  ├─ 成功: 解析 JSON → 缓存结果
  └─ 失败: fallback.py 降级响应
```

### OCR 架构

```
PDF → pdf_classifier (逐页判断)
  ├─ 文本页 → 直接提取
  └─ 扫描页 → PaddleOCR → 文本清洗 → 结构化
```

### 导入流水线

```
上传 → 文本提取 → 结构分析 → 题目切分 → 答案匹配 → 标准化 → 暂存区 → 人工审核 → 题库
```

### SM-2 复习调度架构

```
做错题 → auto_schedule_wrong_question()
  └─ 创建/更新 ReviewSchedule（唯一调度数据源）
      ├─ interval / ease_factor / repetitions
      ├─ next_review_at (UTC)
      └─ mastered

复习 → review_scheduler.submit_review()
  ├─ 校验 rating 0-5（0=完全不会，5=完美回忆）
  ├─ calc_sm2() 计算新间隔/难度
  ├─ 更新 ReviewSchedule
  ├─ _sync_schedule_to_wq() 回写 WQ
  └─ 创建 ReviewRecord（历史记录）

自动批改 → grade_batch（`POST /review/grade-batch`）
  ├─ 未提供用户自评 rating 时:
  │   is_correct=True  → rating=4
  │   is_correct=False → rating=1
  └─ 同上调用 submit_review
```

**关键设计决策**：

- **ReviewSchedule 是唯一数据源**。`WrongQuestion` 不再维护旧版 SM-2 字段；复习历史写入 `ReviewRecord`。
- **时区统一**：复习日期按 Asia/Shanghai 日历日（`shanghai_today()`）计算，`next_review_at` 存为该日 0 点的 naive UTC 瞬时；其余时间戳用 `utcnow()`，避免服务器本地时区导致日期偏移。
- **Rating 0 是合法值**：SM-2 quality 评分范围 0-5，0 表示完全不会，会重置连续正确计数（repetitions=0）并缩短间隔。

**历史技术债（已全部清理）**：

| 问题 | 修复 |
|------|------|
| 旧接口未迁移 | ✅ P1-1 已修复（数据源切换 RS） → P2-1 已移除旧接口 |
| 旧 SM-2 路径残留 | ✅ P0-1 已修复（`update_quality()` 路由到 RS） |
| 双表维护 | ✅ 已移除 WrongQuestion 上的旧 SM-2 字段，调度统一使用 ReviewSchedule |
| 时区混用 | ✅ P1-3/4 已修复；产品日期口径为 Asia/Shanghai 日历日（`shanghai_today()`），存储为 naive UTC |

> 完整设计与技术债清单详见 [REVIEW_SYSTEM_DESIGN.md](REVIEW_SYSTEM_DESIGN.md)。

### 批量图片导入 + SSE 流式追踪

```
管理端选择图片 → 逐张上传 (FormData)
  ├─ 上传完成 → 服务端创建 ImportBatchJob + ImportBatchJobItem (status=pending)
  ├─ 返回 job_id → 管理端打开 SSE 连接
  ├─ 后台 Worker (asyncio, 信号量限并发)
  │   ├─ PaddleOCR → 文本清洗 → TXT 导入流水线
  │   └─ 状态变更 + trace event 同 DB 事务写入
  ├─ SSE 通道推送:
  │   event: trace { seq, step, status, message }  → 前端追加到 task.traceEvents
  │   event: done  { status, total_questions }     → 前端标记 task 完成
  └─ 全部完成 → 前端显示汇总消息, 刷新待审核队列

关键技术:
  - State machine guard: 非法 status 迁移被阻断 (queued→running→completed/failed)
  - 原子更新: item 状态 + trace event 同一 DB 事务, FOR UPDATE 行锁防并发
  - Idempotency: (batch_import_id, image_import_id) 唯一约束防重复提交
  - 自适应轮询: SSE 有事件 500ms, 空闲 1500ms (原固定 300ms)
```
