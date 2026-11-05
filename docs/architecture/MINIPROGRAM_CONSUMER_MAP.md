# 小程序页面与 Public API 消费者映射

> 2026-10-30，HEAD `d91fab53`。本轮为 `MP-00`/`MP-11` 的 L1 有界静态盘点；不是业务重构或真实环境验收。工作流和当前队列见 [收口账本](../../prompts/tasks/current_task/closure-ledger.md)。

## 范围与证据

- 从当前 `miniprogram/app.json` 核实25个注册页面（2个主包、23个分包页面）。从 Codebase Memory 取完924个模块结果，排除测试、脚本和第三方资源后，以当前 TypeScript AST 分析500个第一方运行时 JS；与 Git 已跟踪/非忽略未跟踪文件集合逐项一致。
- 索引 generation `2026-10-29T17:24:11Z`；509个初始候选路径元数据匹配，best effort 范围的140项排除/遗漏已检查，未把图缺失当无调用。require/页面与组件 JSON 建立可能可达关系，`app.js`及全局组件作为公共根。
- 按当前 Public router 的26个注册模块解析153项路由声明；84个可能消费的 method+path 形状均唯一匹配，其中83个HTTP、1个WebSocket。此处是代码注册/静态调用映射，未执行真实请求，也不是完整OpenAPI比较。
- [结果与源文件哈希](refactor-results/miniprogram-consumer-map-2026-10-30.json)记录每条端点、调用点行号、可能页面、后端函数及直接服务依赖。共享服务的整个模块可达不证明每个页面都会调用其所有导出；下表是可能归属，不能当运行轨迹或覆盖率。

## 页面归属

公共认证根：`utils/api*.js`、`utils/auth.js`、`app.js`，覆盖登录/刷新/退出和用户信息/头像6个契约，归 `MP-10`（请求传输）及 `MP-12`（身份/用户）。协议页与动画页仅有这些公共可达关系，没有登记独立业务API。

| 当前注册页面（相对 miniprogram/） | 页面及其可达模块的业务接口族 | 账本归属 |
| --- | --- | --- |
| `pages/login/login` | `/auth` | `MP-12` |
| `pages/home/home` | `/stats`, `/study-hub`, `/study-plan` | `MP-05`, `MP-08` |
| `pages/agreement/user` | 公共根；无独立业务请求 | `MP-10`/`MP-12` 公共根 |
| `pages/agreement/privacy` | 公共根；无独立业务请求 | `MP-10`/`MP-12` 公共根 |
| `pages/agreement/ai` | 公共根；无独立业务请求 | `MP-10`/`MP-12` 公共根 |
| `pages/dashboard/dashboard` | `/ai`, `/practice`, `/stats`, `/study-hub`, `/wrong-questions` | `MP-03`, `MP-04`, `MP-06`, `MP-08`, `MP-16` |
| `pages/pomodoro/pomodoro` | `/pomodoro`, `/practice` | `MP-04`, `MP-15` |
| `subpackages/animation/animation-index/animation-index` | 公共根；无独立业务请求 | `MP-10`/`MP-12` 公共根 |
| `subpackages/formulas/library/index` | `/formulas` | `MP-01` |
| `subpackages/formulas/reader/index` | `/formulas` | `MP-01` |
| `subpackages/productivity/pomodoro-stats/index` | `/pomodoro`, `/practice` | `MP-04`, `MP-15` |
| `subpackages/study/practice/practice` | `/practice` | `MP-04` |
| `subpackages/study/wrong-book/wrong-book` | `/ai`, `/exports`, `/practice`, `/stats`, `/wrong-questions` | `MP-02`, `MP-03`, `MP-04`, `MP-08`, `MP-16` |
| `subpackages/study/wrong-detail/wrong-detail` | `/ai`, `/wrong-questions` | `MP-03`, `MP-16` |
| `subpackages/study/review-today/review-today` | `/review` | `MP-08` |
| `subpackages/study/practice-result/index` | `/ai`, `/practice`, `/stats`, `/wrong-questions` | `MP-03`, `MP-04`, `MP-08`, `MP-16` |
| `subpackages/study/study-plan/index` | `/study-plan` | `MP-05` |
| `subpackages/exam/paper-list/index` | `/exams` | `MP-14` |
| `subpackages/exam/exam-runner/index` | `/exams` | `MP-14` |
| `subpackages/exam/result/index` | `/ai`, `/exams`, `/wrong-questions` | `MP-03`, `MP-14`, `MP-16` |
| `subpackages/exam/history/index` | `/exams` | `MP-14` |
| `subpackages/knowledge/knowledge-subject/index` | `/knowledge-map` | `MP-13` |
| `subpackages/knowledge/knowledge-detail/index` | `/knowledge-map` | `MP-13` |
| `subpackages/export/export-config/export-config` | `/exports` | `MP-02` |
| `subpackages/export/export-records/export-records` | `/exports` | `MP-02` |

## 后端契约与消费链

以下路径均位于 `/api/v1` 下，`{}` 表示路径参数；只统计匹配当前消费候选的路由，不把其余69个声明误当未完成业务任务。

| 契约 | 后端权威入口 | 账本 |
| --- | --- | --- |
| `POST /ai/408-teacher` | `api/v1/ai.py:408` / `ai_teacher_408` | `MP-16` |
| `POST /ai/error-analysis` | `api/v1/ai.py:97` / `error_analysis` | `MP-16` |
| `POST /ai/error-analysis/recover` | `api/v1/ai.py:159` / `recover_error_analysis` | `MP-16` |
| `GET /ai/error-analysis/status/{}` | `api/v1/ai.py:127` / `error_analysis_status` | `MP-16` |
| `POST /ai/feedback` | `api/v1/ai.py:436` / `ai_feedback` | `MP-16` |
| `POST /auth/login` | `api/v1/auth.py:34` / `login` | `MP-12` |
| `POST /auth/logout` | `api/v1/auth.py:170` / `logout` | `MP-12` |
| `POST /auth/refresh` | `api/v1/auth.py:83` / `refresh` | `MP-12` |
| `GET /exams/attempts/{}` | `api/v1/exams.py:73` / `get_attempt` | `MP-14` |
| `POST /exams/attempts/{}/abandon` | `api/v1/exams.py:117` / `abandon_attempt` | `MP-14` |
| `PATCH /exams/attempts/{}/answers/{}` | `api/v1/exams.py:88` / `save_answer` | `MP-14` |
| `GET /exams/attempts/{}/result` | `api/v1/exams.py:147` / `get_result` | `MP-14` |
| `POST /exams/attempts/{}/submit` | `api/v1/exams.py:129` / `submit_attempt` | `MP-14` |
| `GET /exams/history` | `api/v1/exams.py:171` / `history` | `MP-14` |
| `GET /exams/history/overview` | `api/v1/exams.py:159` / `history_overview` | `MP-14` |
| `GET /exams/papers` | `api/v1/exams.py:36` / `list_papers` | `MP-14` |
| `POST /exams/papers/{}/attempts` | `api/v1/exams.py:58` / `start_attempt` | `MP-14` |
| `GET /exports` | `api/v1/exports.py:160` / `list_exports` | `MP-02` |
| `POST /exports` | `api/v1/exports.py:143` / `create_export` | `MP-02` |
| `GET /exports/capabilities` | `api/v1/exports.py:123` / `export_capabilities` | `MP-02` |
| `POST /exports/preview-count` | `api/v1/exports.py:131` / `preview_export_count` | `MP-02` |
| `WEBSOCKET /exports/ws` | `api/v1/exports.py:259` / `export_status_ws` | `MP-02` |
| `DELETE /exports/{}` | `api/v1/exports.py:214` / `delete_export` | `MP-02` |
| `GET /exports/{}` | `api/v1/exports.py:174` / `get_export` | `MP-02` |
| `GET /exports/{}/download` | `api/v1/exports.py:186` / `download_export` | `MP-02` |
| `GET /exports/{}/file` | `api/v1/exports.py:202` / `stream_export_file` | `MP-02` |
| `POST /exports/{}/re-export` | `api/v1/exports.py:238` / `re_export` | `MP-02` |
| `POST /exports/{}/retry` | `api/v1/exports.py:226` / `retry_export` | `MP-02` |
| `GET /formulas` | `api/v1/formulas.py:283` / `list_formulas` | `MP-01` |
| `GET /formulas/catalog` | `api/v1/formulas.py:184` / `get_formula_catalog` | `MP-01` |
| `GET /formulas/favorites/list` | `api/v1/formulas.py:333` / `list_favorite_formulas` | `MP-01` |
| `GET /formulas/random/next` | `api/v1/formulas.py:372` / `get_random_formula` | `MP-01` |
| `GET /formulas/tags` | `api/v1/formulas.py:240` / `get_formula_tags` | `MP-01` |
| `GET /formulas/{}` | `api/v1/formulas.py:318` / `get_formula_detail` | `MP-01` |
| `DELETE /formulas/{}/favorite` | `api/v1/formulas.py:419` / `remove_formula_favorite` | `MP-01` |
| `PUT /formulas/{}/favorite` | `api/v1/formulas.py:407` / `add_formula_favorite` | `MP-01` |
| `GET /knowledge-map/points/{}` | `api/v1/knowledge_map.py:46` / `get_knowledge_point_detail` | `MP-13` |
| `GET /knowledge-map/subjects/{}` | `api/v1/knowledge_map.py:30` / `get_subject_knowledge_map` | `MP-13` |
| `GET /pomodoro/active` | `api/v1/pomodoro.py:181` / `get_active` | `MP-15` |
| `GET /pomodoro/daily-summary` | `api/v1/pomodoro.py:271` / `get_daily_summary` | `MP-15` |
| `GET /pomodoro/history` | `api/v1/pomodoro.py:282` / `get_history` | `MP-15` |
| `GET /pomodoro/range-summary` | `api/v1/pomodoro.py:244` / `get_range_summary` | `MP-15` |
| `GET /pomodoro/settings` | `api/v1/pomodoro.py:194` / `get_pomodoro_settings` | `MP-15` |
| `PUT /pomodoro/settings` | `api/v1/pomodoro.py:202` / `update_pomodoro_settings` | `MP-15` |
| `POST /pomodoro/start` | `api/v1/pomodoro.py:41` / `start_session` | `MP-15` |
| `GET /pomodoro/statistics-overview` | `api/v1/pomodoro.py:222` / `get_statistics_overview` | `MP-15` |
| `GET /pomodoro/stats` | `api/v1/pomodoro.py:213` / `get_stats` | `MP-15` |
| `POST /pomodoro/{}/complete` | `api/v1/pomodoro.py:73` / `complete_session` | `MP-15` |
| `POST /pomodoro/{}/interrupt` | `api/v1/pomodoro.py:104` / `interrupt_session` | `MP-15` |
| `POST /pomodoro/{}/pause` | `api/v1/pomodoro.py:156` / `pause_session` | `MP-15` |
| `POST /pomodoro/{}/resume` | `api/v1/pomodoro.py:131` / `resume_session` | `MP-15` |
| `POST /practice/batch-submit` | `api/v1/practice.py:171` / `batch_submit` | `MP-04` |
| `GET /practice/questions` | `api/v1/practice.py:64` / `get_practice_questions` | `MP-04` |
| `POST /practice/sequential/reset` | `api/v1/practice.py:141` / `reset_sequential_practice` | `MP-04` |
| `GET /practice/subjects` | `api/v1/practice.py:55` / `get_practice_subjects` | `MP-04` |
| `POST /review/grade-batch` | `api/v1/review.py:116` / `grade_batch` | `MP-08` |
| `POST /review/today/next-batch` | `api/v1/review.py:62` / `get_next_today_review_batch` | `MP-08` |
| `GET /review/today/overview` | `api/v1/review.py:47` / `get_today_review_overview` | `MP-08` |
| `POST /review/{}/master` | `api/v1/review.py:138` / `master_review_question` | `MP-08` |
| `POST /review/{}/unmaster` | `api/v1/review.py:161` / `unmaster_review_question` | `MP-08` |
| `GET /stats/ai-diagnosis` | `api/v1/stats.py:161` / `get_ai_diagnosis` | `MP-08` |
| `GET /stats/behavior` | `api/v1/stats.py:73` / `get_behavior` | `MP-08` |
| `GET /stats/dashboard` | `api/v1/stats.py:101` / `get_dashboard` | `MP-08` |
| `GET /stats/dashboard-insights` | `api/v1/stats.py:192` / `get_dashboard_insights` | `MP-08` |
| `POST /stats/dashboard-llm-analysis` | `api/v1/stats.py:179` / `post_dashboard_llm_analysis` | `MP-08` |
| `GET /stats/dashboard-v2` | `api/v1/stats.py:140` / `get_dashboard_v2` | `MP-08` |
| `GET /stats/growth` | `api/v1/stats.py:126` / `get_growth` | `MP-08` |
| `GET /stats/trends` | `api/v1/stats.py:58` / `get_trends` | `MP-08` |
| `GET /study-hub/knowledge-diagnosis` | `api/v1/study_hub.py:27` / `get_knowledge_diagnosis` | `MP-06` |
| `GET /study-hub/overview` | `api/v1/study_hub.py:17` / `get_study_hub_overview` | `MP-08` |
| `DELETE /study-plan` | `api/v1/study_plan.py:43` / `deactivate_plan` | `MP-05` |
| `PUT /study-plan` | `api/v1/study_plan.py:28` / `upsert_plan` | `MP-05` |
| `GET /study-plan/overview` | `api/v1/study_plan.py:20` / `get_overview` | `MP-05` |
| `GET /users/me` | `api/v1/auth.py:117` / `get_me` | `MP-12` |
| `PUT /users/me` | `api/v1/auth.py:125` / `update_me` | `MP-12` |
| `POST /users/me/avatar` | `api/v1/auth.py:137` / `upload_my_avatar` | `MP-12` |
| `GET /wrong-questions` | `api/v1/wrong_questions.py:247` / `list_wrong` | `MP-03` |
| `POST /wrong-questions/batch` | `api/v1/wrong_questions.py:408` / `batch_operate` | `MP-03` |
| `GET /wrong-questions/diagnosis/stats` | `api/v1/wrong_questions.py:330` / `get_error_diagnosis_stats` | `MP-03` |
| `GET /wrong-questions/stats` | `api/v1/wrong_questions.py:279` / `get_stats` | `MP-03` |
| `GET /wrong-questions/task-flow` | `api/v1/wrong_questions.py:292` / `get_task_flow` | `MP-03` |
| `GET /wrong-questions/{}` | `api/v1/wrong_questions.py:350` / `get_wrong` | `MP-03` |
| `GET /wrong-questions/{}/diagnosis` | `api/v1/wrong_questions.py:362` / `get_wrong_error_diagnosis` | `MP-03` |
| `PUT /wrong-questions/{}/diagnosis` | `api/v1/wrong_questions.py:373` / `confirm_wrong_error_diagnosis` | `MP-03` |

## 动态入口核对

- `practice-result/index.js:639` 的 `requestApi` 会移除 `/api/v1` 前缀再经统一 `api.get` 请求；其growth/dashboard-v2/behavior/trends调用已纳入统计族，未遗漏为动态未知调用。
- `formulas/library/index.js:281` 的目录 URL 由变量拼接查询串后传入 `api.request("GET", url)`，已补记 `GET /formulas/catalog`。
- 番茄钟 `pending-sync-controller.js` 使用动作模板；`pending-sync-queue.js` 读取时仅允许pause/resume/complete/interrupt，四种POST动作逐项映射到后端。记录的是当前队列消费者，不声称其他持久化数据已在运行环境验证。
- 导出 `export.js:58` 拼接 `/exports/{}/file`，记录页把下载信息转换为URL再通过 `wx.downloadFile`/失败后 `wx.request` 获取；外部返回的完整文件URL保留为文件能力，不枚举第三方host。
- `export_status_sync.js:263` 的 `_buildWsUrl` 生成 `/api/v1/exports/ws`，随后 `wx.connectSocket`；认证刷新 `_rawRequest` 对应 `POST /auth/refresh`，用户头像通过统一上传对应 `POST /users/me/avatar`。
- 本次500个第一方模块的调用/路径常量/模板与注册页面依赖映射中，没有发现 `/practice/records`、`/practice/knowledge-states`、`/practice/weak-knowledge-points` 的直接/静态消费者。三个后端端点继续保留；不由此推断不存在外部客户端、运行时构造路径或其他版本调用。

## 现有验证入口（本轮未运行）

| 链路 | 现有入口举例 | 下一步判定 |
| --- | --- | --- |
| 章节诊断规则 `MP-07` | `backend/tests/test_services/test_knowledge_diagnosis_logic_compatibility.py`、`backend/tests/knowledge/test_knowledge_diagnosis_ranking.py`、`test_rank_chapter_recommendations_compatibility.py` | 下一批先核查既有聚合/排名是否已有独立测试和单一职责，满足则保留，缺口须具体登记 |
| 复习/统计/学习中心 `MP-08` | `test_review_api.py`、`test_review_scheduler_compatibility.py`、`test_stats_service_contract.py`、`test_study_hub_overview_contract.py`及对应architecture门禁 | 按5个review、8个stats与1个hub overview实际契约逐项处置，不按服务长度开工 |
| 知识地图 `MP-13` | `test_knowledge_map_compatibility.py`、`test_knowledge_map_detail_contracts.py`、`test_knowledge_map_boundaries.py` | 后端两真实消费入口及两页面关联；已治理结构先核对是否可保留 |
| 考试 `MP-14` | `test_exam_attempt_semantics.py`、`test_exam_service_compatibility.py`及小程序exam页面/提交门禁 | 9个真实消费契约，答题/交卷事务与恢复需按现有测试核对 |
| 番茄钟 `MP-15` | `test_pomodoro_snapshot_contract.py`、`test_pomodoro_study_day_stats.py`、`test_pomodoro_postgres_concurrency.py`及小程序pomodoro门禁 | 13个接口、动作队列及统计窗口为同一用例边界；环境集成留置最终验收 |
| 身份/API/AI `MP-10`/`MP-12`/`MP-16` | `miniprogram/tests/test-api-client-contract.js`、`test-api-client-boundaries.js`、`scripts/test-408-ai-teacher.js`及现有后端AI兼容门禁 | 保留身份域、refresh single-flight、trace及AI人工确认边界，不混入Admin或OCR任务 |

## 本轮结论与后续边界

`MP-00`/`MP-11` 仅在“25个当前注册页面均有归属、84个静态候选契约均匹配、动态入口有解析记录”这个盘点范围收口。新增 `MP-12`–`MP-16` 对应此前账本未显式覆盖的真实消费族；这些条目均仍OPEN，不能因映射完成而声称结构已治理。`MP-09` 的考试职责转归 `MP-14`，三个无直接静态消费的practice读取端点保留现状。

下一批为 `MP-07` 的有界规则评估：读取已有调用链与测试，以职责、依赖方向、重复权威和独立测试能力决定RETAIN或登记具体重构缺口；不把356行作为缺陷。其后依次处置 `MP-08`、`MP-10`和新增消费族，再转Admin与OCR。所有生产验收继续留到全栈结构治理完成后的最后阶段。

本轮没有修改业务代码、测试、CI、鉴权、路由或数据库；未执行全量业务CI、微信工具、真实外部服务或生产请求。一次独立只读文档/映射审查及保护/链接/容量检查在批次收尾记录中登记。

---

## 相关链接

- [[docs/architecture/SYSTEM_ARCHITECTURE.md|SYSTEM_ARCHITECTURE]] — 系统架构
- [[docs/architecture/PRODUCTION_ARCH.md|PRODUCTION_ARCH]] — 生产架构
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/frontend/UI_RULES.md|UI_RULES]] — 小程序 UI 规则
