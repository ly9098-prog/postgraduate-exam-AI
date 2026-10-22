# 变更日志

> 记录项目重大变更。

---

## 2026-09-22 ~ 2026-10-23

对照已落地实现补记（重构战役收尾）。历史审计报告不改写。

- **运行时重构战役收尾（阶段完成）**
  - 第五十三至一百一十二阶段：HTTP lifespan / 独立 worker / scheduler 的启动、信号、关闭、失败清理边界逐批迁移至中立模块（`core/runtime_*`、`services/runtime_*`、`practice/scored_*` 等），登记见 `docs/architecture/REFACTOR_INVENTORY.md` §4/§6；后端静态依赖 584 模块 / 2,265 边 / 0 静态循环（2026-10-23 复跑 `backend/tests/architecture/dependency_scan.py`）。
  - observability（`d6c5232a`/`9f29e9fc`，2026-09-29）：Redis 容量监控与答题投影键监控，见 `docs/architecture/REDIS_USAGE.md` §7。
  - admin-auth（`beb1a0ca`，2026-10-04）：后台认证相关变更。
  - 2026-10-22 统计/番茄钟/复习重构系列（14 个 refactor 提交）：pomodoro 统计科目投影/窗口/来源累计/响应组装拆分、stats 共享自然日时间投影（`039537f2`）；复习流分离来源定位/AI 建议与答案等价/列表徽章/筛选与抽屉/补全草稿/确认弹层/快速补答案视图/批量补全结果/图片答案流程/审核反馈与确认状态（至 `f4e60284`）；新增 `docs/architecture/REVIEW_QUEUE_COMPATIBILITY.md` 登记审核队列排序/过滤/分页口径。
  - 番茄钟完成通知的微信订阅消息推送链路已于 2026-07-29（`0063f278`）移除；`pomodoro_sessions` 通知字段保留但无发送方，事实说明见 `docs/architecture/POMODORO_NOTIFICATION.md`。
- **Redis 备份目录改造**（commit 206efb60）
  - `deploy/scripts/redis_backup.sh` 默认归档到宿主机 `/opt/22408-ai/redis_backups`（`BACKUP_DIR` 默认 `PROJECT_DIR/redis_backups`，可用 `REDIS_BACKUP_DIR` 覆盖）；`redis_restore.sh` 用法同步；`deploy.sh` 暴露 `backup-redis` / `redis-restore` 子命令，`deploy/Makefile` 有 `redis-restore` 目标。文档口径见 `docs/project/DEPLOY_PLAN.md` 与 `docs/architecture/REDIS_USAGE.md` §8。
- **生产补录番茄钟记录（一次性运维留痕，2026-10-04/05）**
  - 生产 `pomodoro_sessions` 为用户 1 补录两条 `completed` 记录：ID 391（操作系统，2026-10-05 02:00–02:45 北京时间，2700 秒）与 ID 392（英语，2026-10-05 14:50:54–15:06:54 北京时间，960 秒）；均为 free 计时（`work_duration=break_duration=0`），无暂停记录；已通过生产数据库回查确认。原记录在 `DEPLOY_PLAN.md` §9.6/§9.7，因属一次性数据操作已移出部署文档。

---

## 2026-09-13 ~ 2026-09-21

对照 `e8beb2e2` 之后已落地的实现补记。历史审计报告不改写。

- **408 考试域**
  - 试卷增加稳定 `public_id`（32 位 hex，迁移 `e408examref20260913`）。管理端按数字 id 与 `public_id` 都能读、改、换题、发布、归档、恢复。
  - 用户端 `/api/v1/exams`：已发布试卷列表与详情、开始作答（`request_id`）、逐题保存、交卷、结果、历史。交卷可携带尚未单独 PATCH 的本地答案，同一事务落库并判分。
  - 未完成草稿：服务端按试卷 `duration_sec` 超时后记为 `expired`。小程序本地草稿离开作答页 60 分钟失效（`EXAM_DRAFT_TTL_MS`）；待提交快照保留 7 天。`POST /exams/attempts/{id}/abandon` 释放进行中的尝试，`abandoned` 不作为可续答记录，也不进历史列表。
  - 软删除（迁移 `e408examdelete20260915`）：写 `deleted_at`，`is_active=false`，非归档状态改为 `archived`；作答与审计保留。管理端列表排除已删除试卷。
  - 408 选择题卷结构：40 题 × 2 分。真题必须正好 40 道 `single_choice`，题号区间为数据结构 1–10、组成原理 11–22、操作系统 23–32、计算机网络 33–40。模拟卷最多 40 道。同一年未删除的真题，发布时不能已有另一份已发布试卷；从归档恢复时不能已有另一份草稿或已发布试卷。
  - 管理端 `POST /api/admin/v1/imports/questions-csv`（`import:write`）把导出的题目 CSV 直接写入题库，校验失败返回 `QUESTION_CSV_VALIDATION_ERROR` / `QUESTION_CSV_TOO_LARGE`，不是 AI/OCR 绕过人工审核的路径。
- **多空题型拆分**（`48c2cb60`，迁移 `v13_multi_blank_multiple_choice`）
  - `multi_blank_choice` 为每空单选；`multi_blank_multiple_choice` 为每空多选，答案形如 `①:A,C;②:B`。存量多字母槽位重分类为后者。判题按槽位集合比较，顺序无关。
- **错题分析锚定**（`c417af4c`）
  - `app/ai/answer_grounding.py` 用服务端已核对的漏选/错选事实约束模型；`answer_check` 不一致或诊断与事实矛盾时 fail-closed 修复后再缓存。细则见 `docs/ai/AI_PIPELINE.md`。
- **向量**
  - embedding 按 `(question_id, model_id)` 与 `content_hash` 增量写入，内容未变不重复调用模型。
- **番茄钟统计**（`b1685daa`）
  - `stats` / `daily-summary` / `statistics-overview` 只统计已结束的 `completed` / `interrupted`。`running` / `paused` 只走 `/pomodoro/active`。
- **公式图**
  - 生产 compose 的 app、scheduler、worker 挂载命名卷 `formulas_data:/app/static/formulas`，容器重建不丢上传图。
  - 新上传主图长边压到 ≤1600 并 PNG optimize；列表优先缩略图；阅读页固定宽高比视口，不再自动放大裁边。
  - 挂在章节上的卡片计入 408 科目与章节筛选。管理端公式/题目列表的筛选与选中态写入 URL。
- **小程序渲染**
  - 代码块抽成共享组件，SEGMENTS 模式保留 code segment。KaTeX 转原生 rich-text，并拆分过大的 vendor 文件。

## 2026-09-12 / 2026-09-13

- **AI 模型配置软删除（稳定模型 ID）**
  - `eeb7695f` `admin_ai_model_configs` 增加 `deleted_at` 软删除；删除模型后引用它的历史记录（如 `question_embeddings.model_id`）ID 保持稳定。Resolver 只解析未删除配置。新增迁移 `d5f6a7b8c9d0`。
- **question_embeddings 改 model_id 外键**
  - `033c3884` 以 `b3d4e5f6a7b8` + `c4e5f6a7b8c9` 两步迁移将 `question_embeddings.embedding_model` 字符串列替换为 `model_id` FK → `admin_ai_model_configs`；运行时向量服务改按 `subject_id` + `model_id` 过滤。已部署生产（2160 行回填 model_id=70）。
- **知识点唯一约束放宽**
  - `23905f44` 移除知识点全局/跨科目唯一限制，同科目内同名节点合法（迁移 `r408kpunique20260912`）；配套 408 知识图谱全量重构（499 节点/839 边）。
- **测试目录重组**
  - `59a8149e`/`14f9c660` 后端测试合并为规范包结构（architecture / test_api / test_services 等）；CI `ci.yml` 固定文件清单同步更新。
- **刷题 UX**
  - `770c544b` 练习科目选择底部弹层（学科图标 + 新样式）与 quiz-runner 推荐条；`365f0889` 修复 knowledge session subject_id 与发起批次科目对齐。

## 2026-09-07 ~ 2026-09-11：408 学习体系

- **408 智能学习中心域**（`5e810f6b`、`92798088`、`96f8d0cd`、`a8464975`、`6614f6ae`）：408 选择题考试域、知识地图、错因诊断、AI 教师、速记卡扩展（`826cf2a3`）、长期学习计划 `study_plan`（`0b026e73`）、题库覆盖率治理（`8b425a29`）、考纲版本治理 `syllabus`（`468c0557`，PostgreSQL 索引名缩短修复 `e41f8504`/`d99ebe5e`）、canonical 科目边界收紧（`78e27b30`）。
- **练习与投影稳定性**：顺序练习预约防重（`3ee9dc94`，迁移 `s408seq20260911`）、练习会话范围持久化（`84d2a2ca`，迁移 `s408pscope20260909`）、答案修订 current 一致性（`08c27ce1`）、outbox 修复与恢复（`f3a8e148`、`2453aa33`）、掌握状态并发安全与撤销（`a028ed92`）、题目版本与学习状态一致性（`1cc55b7e`，迁移 `e0f1a2b3c4d5`）、per-answer practice_records 强制（`ed8f8ab4`，迁移 `a4c5d6e7f8b9`）、practice_session 幂等 payload（`c8d9e0f1a2b3`）。
- **AI 分析**：错题 AI 分析流改进（`8f5a8c52`）、GPT-5.6 错误分析延迟上界（`5a7138d8`）、AI 分析超时降级（`93a1fd6c`）、AI 模型路由完善（`d46b8cfb`）、AI 教师知识点呈现结构化（`5faca505`）。
- **导入链路加固**：导入解析与 LaTeX 预览改进（`cf62a761`）、导入工作流与任务恢复加固（`38bce8b4`）。
- **小程序视觉与体验**：学习空状态刷新（`3baeb4b7`）、学习工作流改进（`ede05a14`）、首页薄荷主题（`b18b62df`）、学习看板/错题本视觉（`7393c4df`）、知识图谱交互多轮迭代（`827ce118`、`cf1a2024`、`c9acf1a8`、`1e25c868`、`f43ffcc9`）、主包体积缩减（`d1a24fcb`）。

## 2026-09-03 ~ 2026-09-06

- **AI 分析视觉链路收敛**（8 月 16 日系列提交的后续）：错题分析只读题库题图，移除用户截图上传与 vision 特征路由（`cab3585f`、`12b78d0c`）；缓存新鲜度体系——输入/模型双签名 + stale 状态 + 提交后预热（`d0583f9f`）；错误码体系——provider 异常分类 + prewarm 重试/死信语义（`a6d31524`）；纯文本题目缺视觉资源时 fail fast（`0f705e93`）；视觉证据探针修复（`fb205238`）。
- **RBAC 权限细化**：knowledge/recommendation 独立权限 + admin 角色权限集重构（`7cc68893`）；super_admin 专属角色页 + 管理员管理页（`9011e858`）。
- **头像与时间标准化**：用户头像持久化 `/static/avatars` 命名卷（`e788bb24`）+ 命名空间拆分（`4a0980a6`）；后端时间序列化统一 UTC Z 输出（`4ea1c0ef`），前后端接入 china-time 工具（`faa3d6f9`、`e46958b3`）；容器统一 `TZ=Asia/Shanghai`（`a8eca7f8`）。
- **生产 worker 服务**：新增 worker 服务消费 Redis v2 任务队列（`ae75de56`），OCR 仅走外部 API（`5834ec78`、`da37d342`、`f6604890`）。
- **管理端**：系统任务中心——调度任务目录 + Redis 遥测 + PG 备份观测/手动执行（`c1b0cd3f`）；公式库管理端改版（`6a1c9e9d`、`43f088a2`）；题库导出 CSV/DOCX（`dd2c47fd`、`629f0983`）；题目版本知识点规范化 + OCR 缓存指标（`bfdf6470`）。
- **异步任务体系**：AI 运行时统一准入控制——有界并发/限流/熔断/成本上限 + Redis 共享 token 预算（`e804809e`）；答案投影改事务性 outbox 异步化（`f03af645`）+ 对账器（`994b57b9`）+ Redis 故障遗留 failed 行恢复（`f3cb9f58`）；outbox/Redis 队列/投影回执三源健康诊断页（`0e9bda16`）。
- **番茄钟稳定性**：`/start` 幂等键 `client_start_id`（`0cfc64aa`）；专注生命周期离线/重试安全 + 单活跃会话约束（`b7d9f3aa`，迁移 `w7x8y9z0a1b2`、`x8y9z0a1b2c3`、`y9z0a1b2c3d4`）；错题首次复习从北京时间次日开始（`e8b97bdb`）。
- **OpenAPI 契约门禁**：关键前端操作类型化响应 + operationId 唯一性（`77b13717`）；`/api/v1/practice/questions` 补响应模型（`9ee1c581`）。

---

## 2026-09-02

- **安全边界与系统运维权限收敛**
  - 用户与 Admin JWT 使用独立签名域（可分别配置 `USER_JWT_SECRET` / `ADMIN_JWT_SECRET`，缺省时从 `APP_SECRET` 派生）。
  - `APP_ENV` 与 `DEPLOYMENT_PROFILE` 双向校验；生产必须使用 `cloud_api`，冲突配置启动失败。
  - 系统健康、任务、队列、trace 与 PostgreSQL 备份接口使用 `system:read` / `system:write` / `system:backup`，备份响应不泄露服务器路径。
  - 公开健康端点收敛响应信息，生产 metrics 需要 `OBSERVABILITY_TOKEN`。
  - 相关提交：`8382e78f`、`d4137a26`。

- **题目渲染与图片加载优化**
  - Admin 题目页对编程题使用专用代码渲染，默认筛选有效题目。
  - 小程序新增会话级题目图片预解码缓存，当前题优先预热相邻题图片；图片渲染使用缓存本地路径并减少布局抖动。
  - KaTeX 对圈数字符号做兼容标准化。
  - 相关提交：`b6232f33`、`5365f139`。

- **文档同步**
  - 更新总体架构、Admin API/RBAC/审计入口、复习数据库约束和 Memory System，移除与当前代码冲突的旧状态描述。

---

## 2026-08-10

- **题库知识点改为关联表单一事实源**
  - `e791c979` `question_knowledge_points` 关联表为唯一事实源，移除 `questions.knowledge_points` JSON 列（DB 结构性变更）。
  - `Question` 模型现通过 `knowledge_point_links`（`QuestionKnowledgePoint`，保留 role/weight/source/position 元数据）关联；`kp_links` 为 viewonly secondary 关系。`questions.knowledge_points` 列已不存在。
- **知识图谱相关服务同步调整**
  - `1e8e9022` `sync_to_cloud` 知识点改走关联表 `load_question_kps`。
  - `2421794e` 题库搜索匹配知识点名与别名 —— keyword 命中 `knowledge_points.name/aliases`。
- **管理端题目图片与选项管理**
  - `faa36879` 管理端题目图片/选项管理 —— 快捷加选项、题干与选项插图/替换/删除。
  - `4fbefd9e` 根相对资源 URL 解析失败致题图空白修复 + nginx CSP 放行资源源。
  - `d25cdd3f` 题干大图替换插入区 + 选项单行并列布局。
  - `bb5130e3` 题图上传先校验题目存在/权限；选项合并大小写不敏感并保留富键。
  - `b0190943` 公式卡 PUT 版本号与审计链去同步冲突 —— 行锁 + max 版本推导。
  - `29394c26` backfill 实写路径事务冲突修复。
- **受影响文档**：`docs/project/CHANGELOG.md`、`docs/project/POMODORO_V2_MIGRATION.md`（本批不涉）。

## 2026-08-09

- **刷题时长纳入番茄学习统计（大功能）**
  - `7b79ca2a` 新增 `PracticeSession` 模型（`backend/app/models/practice_session.py`）：一次完整刷题会话一条记录，与 `PracticeRecord`（单题）语义分离；`duration_sec` 纳入学习统计。
  - `(user_id, request_id)` 部分唯一索引幂等去重，网络重试不重复插 session；`started_at/finished_at/duration_sec` + subject/mode/question 计数。
  - 统计页 `build_pomodoro_statistics_snapshot` 混入 `_load_overlapping_practice_sessions`：刷题时长通过 `split_duration_excluding_intervals` 排除已计时的番茄 active 区间按比例归因，避免与番茄时长 double count。
  - `/pomodoro/history` 改为 `PomodoroSession + PracticeSession` 按 `start_time` UNION DESC 全局翻页混排，带唯一 `record_key`（`pomodoro:<id>` / `practice:<id>`）。
  - 受影响文件：`backend/app/models/practice_session.py`（新增）、`backend/app/services/pomodoro_service.py`、`backend/app/services/pomodoro_attribution.py`。
- `edd623ab` practice-result 错题列表定高滚动，切换筛选保持高度稳定
- `04cce17d` 管理端题目搜索框 300ms 防抖
- `d4ec0a7e` 小程序首页/Dashboard 进入后预下载 study 分包，降低核心学习首跳等待

## 2026-08-08

- **番茄钟统计页统计计算收敛（一次加载 + 一次归因）**
  - 统计页原先在一次页面加载里并行请求 4 个接口（`/stats` + `/trends` + `/daily-summary` + `/history`），三个统计接口各自独立重新加载重叠窗口并各自跑一次 Python 归因。本次收敛为一次窗口加载 + 一次归因。
  - 后端 `pomodoro_service.py` 新增内部服务 `build_pomodoro_statistics_snapshot(db, user_id, *, target_date, trends_days, need_stats, need_trends, need_daily_summary)`：按请求维度计算各自窗口，取 union 一次加载 sessions + pause intervals、每 session 归因一次，聚合出 stats/trends/daily_summary。归因引擎 `pomodoro_attribution.py` 未改动（仍是唯一真相源）。
  - `_load_overlapping_sessions(..., with_subject=False)` 按场景降载：stats/trends 只 select attribution 所需列且不加载 Subject、pause 走一次批量 IN 查询（分片 500）；daily-summary 才 JOIN subject。
  - `get_stats / get_trends / get_daily_summary / get_subject_breakdown` 全部改为 `build_pomodoro_statistics_snapshot` 的薄包装。
  - API 层新增 `GET /api/v1/pomodoro/statistics-overview?date=YYYY-MM-DD`（date 可选，默认当前学习日），一次返回 `{ stats, trends, daily_summary }`，`daily_summary` 内含 subjects。
  - 移除 `GET /api/v1/pomodoro/trends` 与 `GET /api/v1/pomodoro/subjects`（仓库全量确认零调用者）。保留 `/stats`（timer 页今日卡片仍用）、`/daily-summary`（历史日期导航仍用）、`/history` 等。
  - Schema：新增 `PomodoroStatisticsOverviewResponse`；删除 `PomodoroSubjectBreakdown`（被移除的 /subjects 路由专用）。
  - 小程序 `pomodoro-stats/index.js`：统计页 `loadData()` 从 4 个并行请求收敛为 `/pomodoro/statistics-overview` + `/pomodoro/history` 两个请求；历史日期导航仍调 `/pomodoro/daily-summary` + `/pomodoro/history`。
  - 性能：统计页首屏 DB queries 从 11 → 5，attribution runs 从 3 → 1。
  - 测试：新增 `backend/tests/benchmarks/bench_pomodoro_snapshot.py`（90 天 synthetic benchmark）；`test_pomodoro_study_day_stats.py` 新增 4 个 query-count 回归测试（组合计算恰 3 条语句、pause 批量无 N+1、get_stats 不加载 Subject、90 天不随天数线性）。
  - 受影响文件：
    - `backend/app/services/pomodoro_service.py`
    - `backend/app/api/v1/pomodoro.py`
    - `backend/app/schemas/pomodoro.py`
    - `miniprogram/subpackages/productivity/pomodoro-stats/index.js`
    - `backend/tests/benchmarks/bench_pomodoro_snapshot.py`（新增）
    - `backend/tests/test_services/test_pomodoro_study_day_stats.py`
  - 受影响文档：`docs/project/CHANGELOG.md`

## 2026-07-25

- **后端生产强化修复（P0/P1 安全审计）**
  - **任务队列 fencing**：`execution_generation` 递增后旧 worker 写操作被自动拒绝；owner loss 后 worker 立即取消处理，任务回队。
  - **Enqueue 回滚链修复**：全部 7 个 enqueue 调用点检查 `EnqueueResult.accepted`，拒绝时回滚 pipeline 状态并返回 503。
  - **BoundedExecutor**：新增有界线程池执行器，支持 atomic 准入控制、per-call 超时、异常安全 metrics（17 项单元测试覆盖全部路径）。
  - **PDF 流式内存治理**：`iter_pages()` 逐页渲染 + `RenderedPage.aclose()` 释放；`render_pages()` 全量接口在 cloud 部署中拒绝；`PdfResourceLimitError` 结构化错误码映射 HTTP 413/422/429/503/507。
  - **SSE 连接控制**：per-user 上限 5、全局上限 50；idle timeout 300s（从末次业务事件计算，heartbeat 不刷新）；低基数 Prometheus 计数器（无 user_id label）；指数退避 fallback polling（2s → 60s）。
  - **数据库连接池角色隔离**：web (pool 3 / overflow 5) × workers + worker (pool 2 / overflow 3) + scheduler (pool 1 / overflow 2)；启动时校验总预算 ≤ MAX_CONNECTIONS。
  - **ORDER BY random() 修复**：practice 补全题在表 >2000 行时改用 count + random offset。
  - **复合索引 v10**：5 个 composite btree 索引（CONCURRENTLY 创建），覆盖 due questions / pipeline 过滤 / practice 历史 / review 队列。
  - **Alembic chain**：`v10_performance_indexes` 继承 `v9_formula_approved_to_published_migration`。
  - **启动自检增强**：新增 PDF 规则检查（cloud: window>0, concurrency=1, pages≤30）和 DB 连接预算检查。
  - **生产配置 validator**修复：`set_draining` 异常处理从 `pass` 改为 `logger.warning`。
  - **测试**：17 项 BoundedExecutor 单元测试新增通过；73 项现有测试通过（1 项预存 OCR 测试失败，无关）。
  - **部署文档同步**：DEPLOY_PLAN.md 新增 Section 7（新增 env vars、部署顺序、回滚方案、启动自检清单）。

---

- **多空选择题前端性能审计与修复（Phase 6 完成）**
  - **quiz-runner 局部 setData 优化**：observer 通过 `_lastRenderModel` 引用比较区分题目切换与空选项更新；选项点击仅更新 `_blankOptionGroups` 路径，避免重新解析题干、代码块和图片。
  - **多空选项点击优化**：practice.js 和 review-today.js 的 `selectBlankOption` 改用路径精确 setData，合并多次调用为一次，移除 `_updateComputedFields` 等多余回调。
  - **修复多空选择题部分选项无法点击**：修正 touch/swipe 事件竞争条件，`swipeTapLockUntil` 锁定时长从 300ms 降至 100ms，避免误吞合法点击。
  - **修复多空选择状态更新抖动**：消除 observer 中 `_renderModel` 因引用变化触发的重复解析，确保仅选项选中状态变更时不影响题干和图片渲染。
  - **图片显示优化**：`computeExtraImages` 使用 SEGMENTS 模式图片去重，`wx.previewImage` 数据在题目变化时预准备，选项点击不触发图片重载。
  - **真机验证**：practice（连续点击/切题/提交）、review-today（加载下一批/逐空作答）、wrong-detail（只读详情/图片预览）全部通过。
  - 受影响文件：
    - `miniprogram/components/quiz-runner/quiz-runner.js`
    - `miniprogram/pages/practice/practice.js`
    - `miniprogram/pages/review-today/review-today.js`
    - `miniprogram/utils/question-runner-adapter.js`
    - `miniprogram/utils/answer.js`
  - 受影响文档：`docs/project/CHANGELOG.md`
  - 测试：446 项全部 PASS（含多空专项 45 项），JS 语法验证通过

- **多空选择题完整支持（Phase 1-4 完成）**
  - ...

## 2026-07-16

- **多空选择题上线前审计与修复（Phase 5 完成）**
  - **代码审计修复 3 项 Bug**
    - `answer_matcher.py`: 修复 `extract_explicit_answer` 对多空选择题圈号答案（①B、②D）的验证，此前 validation regex 拒绝以非 A-D 开头的内容，导致 OCR 多空答案从未被提取。新增圈号格式检测分支。测试：3 项。
    - `question_pipeline.py`: 修复 `normalize_answer` 对显式标记为 `multi_blank_choice` 的题目答案未规范化到 canonical 格式（①:B;②:D），此前非 auto-detect 路径保持原始格式，导致前端 `normalizeBlankAnswer` 解析失败。新增专有分支调用 `parse_multi_blank_answer` + `serialize_multi_blank_answer`。测试：3 项。
    - `answer.js`: 修复 `normalizeBlankAnswer` 仅支持 `slot:value` 格式，新增圈号对（①B、②D）、括号数字（(1)B、(2)D）、中文自然语言（第1空B）三种 fallback 解析器。测试：5 项新增。
  - **回填脚本安全强化**
    - `_assess_candidate` 新增 `ambiguous` 状态：空位数与答案槽位数不一致时标记为歧义并跳过，不再信任 answer 槽位定义。
    - 新增 OCR 圈号差异安全归一化（1 ↔ ①，匿名 ↔ 显式），仅当数量一致时允许。
    - 新增 `答案值不在组选项中` 检查。
    - 新增 CLI 参数：`--question-id`、`--import-id`（定点检查）、`--report-json`（机器可读报告）、`--yes`（非交互确认）。
    - apply 模式新增交互确认（除非 `--yes`）。
    - 新增 `_build_report` / `_print_report` 输出完整统计：扫描数、候选数、转换数、歧义数、跳过数。
    - 新增第二次 dry-run 幂等性验证提示。
  - **数据验证脚本**
    - 新增 `scripts/verify_multi_blank_choice_data.py`：只读扫描 10 种风险类别（missing_groups, duplicate_group_id, missing_answer_slot, extra_answer_slot, invalid_answer_option, legacy_answer_format, options_groups_conflict, hash_mismatch, suspected_misclassified, blank_count_mismatch）。
    - 高风险问题存在时返回非零退出码。
    - 支持 JSON 报告输出。
  - **小程序 practice-result 逐空展示**
    - 新增 `buildBlankResultsViewModel` 函数：按 blank_option_groups 顺序生成逐空视图模型（id, userKey, userText, correctKey, correctText, isCorrect, isAnswered）。
    - 逐空显示：错误状态高亮用户选错、未作答显示"未作答"、全部正确时显示"全部正确"。
    - 展示"答对 X/Y 空"统计。
    - WXML 新增 conditional 分支：`item._isMultiBlank` 触发多空布局。
    - WXSS 新增 80+ 行多空样式（圆角卡、颜色编码、状态标记）。
    - practice-result.js 内联 `normalizeBlankAnswer` 兼容 canonical 和圈号对格式。
  - **本地数据库回填演练说明**
    - 脚本已通过 Python 语法和导入验证
    - `_assess_candidate` 全部安全校验逻辑已在 Python 层测试通过
    - 执行完整回填需连接真实数据库（开发/测试环境），当前无可用 SQLite 测试数据库
  - **回归测试**
    - 后端 multi_blank_choice 专项：98 项全 PASS
    - 后端 service tests：1908 passed, 3 skipped
    - 后端 API tests：261 passed
    - 小程序 multi-blank 测试：45 项全 PASS
    - 后端 feature tests：12+ passed
  - **Runbook**
    - 新增 `docs/project/MULTI_BLANK_CHOICE_RELEASE_RUNBOOK.md`：发布前条件、数据库备份、部署顺序、回填 dry-run/apply/验证/幂等检查、API smoke test、小程序验收、监控、回滚步骤、禁止命令。
  - 审计发现的问题：3 项（均为 Bug）
  - 实际修复的问题：3 项（answer_matcher, question_pipeline, answer.js）
  - 受影响文件：
    - `backend/app/features/answer_matcher.py`
    - `backend/app/features/question_pipeline.py`
    - `backend/scripts/backfill_multi_blank_choice.py`
    - `backend/scripts/verify_multi_blank_choice_data.py`（新增）
    - `miniprogram/utils/answer.js`
    - `miniprogram/pages/practice-result/practice-result.js`
    - `miniprogram/pages/practice-result/practice-result.wxml`
    - `miniprogram/pages/practice-result/practice-result.wxss`
    - `miniprogram/tests/test-multi-blank-answer.js`
    - `backend/tests/test_services/test_multi_blank_choice.py`
    - `docs/project/CHANGELOG.md`
    - `docs/project/MULTI_BLANK_CHOICE_RELEASE_RUNBOOK.md`（新增）
  - 尚存风险：
    - 本地数据库回填演练因无可用的 SQLite 开发数据库无法执行；需在测试/开发 PostgreSQL 实例上运行 dry-run + apply + 二次 dry-run 完整流程
    - practice-result 页面使用内联 normalizeBlankAnswer 而非 answer.js 的版本（微重复）
    - wrong-detail 页尚未验证 per-blank 展示
  - **Phase 1 — 后端数据契约、答案解析、判题**
    - 新增 `backend/app/features/multi_blank_choice.py`：统一工具模块，提供 `extract_blank_slots`、`parse_multi_blank_answer`、`serialize_multi_blank_answer`、`build_blank_option_groups`、`validate_multi_blank_question`、`detect_shared_option_multi_blank`。
    - 答案兼容 12+ 种格式（canonical `①:B;②:D`、`①B、②D`、`第1空B`、位置型 `A,B` 等）。
    - 精确判题：槽位覆盖检查 + 多余槽位拒绝 + 顺序无关。
    - 发布校验：缺/多余槽位、非法选项、空组全部拒绝。
    - Hash 包含 `blank_option_groups`（`normalize_hash_blank_groups` 方法）。
    - 92 项单元测试通过。
  - **Phase 2 — 导入识别、审核与发布**
    - 导入管线自动检测共享选项多空题（2+ 空 + 选项 + 多槽位答案）。
    - `answer_matcher.py` 新增 `①B、②D` OCR 答案格式。
    - `admin_import_service.py` 保存时自动重建 `blank_option_groups`。
    - 管理端审核 UI：逐空选项按钮、可编辑选项文本、canonical answer 保存。
  - **Phase 3 — 小程序答题体验**
    - `answer.js`：`isAnswerCorrect` 拒绝多余槽位。
    - `practice.js`：`selectBlankOption` 使用 `isQuestionAnswered` 修正部分作答误标。
    - 小程序纯函数测试 37 项（parse/serialize/判题/多余槽位/旧格式兼容）。
  - **Phase 4 — 历史数据修复、端到端测试、文档**
    - `scripts/backfill_multi_blank_choice.py`：幂等回填脚本，扫描 `question_imports` + `questions` 中误分类的多空题（dry-run / apply）。
    - 端到端管道测试 22 项（11 用例矩阵 + 数据契约验证）。
  - 数据契约：`question_type=multi_blank_choice`、`options=null`、`parsed_options=null`、`answer="①:B;②:D"`、`content.blank_option_groups=[{"id":"①","options":[...]}]`。
  - 受影响文件：`backend/app/features/multi_blank_choice.py`（新增）、`backend/scripts/backfill_multi_blank_choice.py`（新增）、`backend/app/features/answer_matcher.py`、`backend/app/features/question_pipeline.py`、`backend/app/services/admin_import_service.py`、`backend/app/features/question_publish_service.py`、`admin-frontend/src/app/(admin)/imports/review/page.tsx`、`miniprogram/utils/answer.js`、`miniprogram/pages/practice/practice.js`、`miniprogram/tests/test-multi-blank-answer.js`（新增）。
  - 受影响文档：`docs/project/CHANGELOG.md`。## 2026-06-22

- **修复：OCR 代码块围栏断裂导致代码结构泄漏（BUG-001）**
  - `code_detector._fence_code_blocks()` 新增单行桥接规则：孤立低分行（score=0）相邻两行均为代码行（score≥1）时提升为 score=1，防止 OCR 单行乱码导致 ``` 围栏提前关闭。
  - 修改仅限 `code_detector.py` 5 行，不涉及 OCR 管线、清洗规则、code_integrity、AI repair。
  - 22 个 OCR 回归测试全部 PASS，实际图片端到端验证通过。
  - 受影响文件：`backend/app/features/code_detector.py`。
  - 受影响文档：`docs/BUGS.md`、`docs/BUGS_HISTORY.md`、`docs/project/CHANGELOG.md`。

## 2026-06-21

- **P8 功能冻结 + 回归加固 + 部署验证 + 种子数据完成**
  - 功能冻结检查：18 个模块全部冻结，仅允许 bugfix。
  - 回归测试加固：新增 52 个测试（ocr_alert_rules 28 tests + ocr_case_exporter 24 tests），覆盖 P7 新增模块。
  - pipeline_artifacts assertion 修复：cleanup_expired 返回值结构变更导致测试断言错误已修正。
  - 生产部署验证：5 容器健康 / 新模块加载正常 / HTTPS 可达 / API 端到端通过。
  - 清理 Dry-Run：scanned=18, would_delete=0，无异常。
  - subjects 种子数据：插入 10 条学科记录（4 一级 + 6 二级）。
  - Release Candidate 判断：`ready_for_beta`，无阻断问题。
  - 受影响文件：`backend/app/features/pipeline_artifacts.py`、`tests/test_pipeline_artifacts.py`、`tests/test_features/test_ocr_alert_rules.py`、`tests/test_features/test_ocr_case_exporter.py`。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

- **P7 生产运维 — 观测沉淀 + 告警 + 清理 + 样本导出 + 运维文档完成**
  - 观测指标沉淀：`GET /imports/pipelines` 端点，API 层聚合 quality_report，无 DB migration。
  - 告警规则：`ocr_alert_rules.py` 7 条规则（import_failed / high_risk / manual_review / ai_answer / cache_hit / duration / ocr_fail），pipeline 完成自动评估。
  - 清理任务：OCR cache TTL 14d + artifact dry-run + 统一 `POST /maintenance/cleanup` 端点。
  - 失败样本导出：`ocr_case_exporter.py` raw_data 截断 2000 字符 + expected_template 全部为空 + 单题/批量端点。
  - 管理端运维页：健康摘要 + 告警展示 + Dry-Run/确认清理 UI + layout 新增"运维" tab。
  - Preflight 检查：`scripts/ocr_preflight_check.py` 离线 5 项 + 可选在线 3 项。
  - 运维文档：`docs/ocr/OPERATIONS.md` + `TROUBLESHOOTING.md` + `DEPLOY_CHECKLIST.md`。
  - 受影响文件：`backend/app/features/ocr_alert_rules.py`（新增）、`backend/app/features/ocr_case_exporter.py`（新增）、`backend/app/api/v1/admin_imports.py`、`scripts/ocr_preflight_check.py`（新增）、`admin-frontend/src/app/(admin)/imports/maintenance/page.tsx`（新增）。
  - 受影响文档：`docs/ocr/*`、`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

- **P6 验收 + 性能 Profile + 失败归因 + 精调 + Dashboard + CI 策略完成**
  - 验收样本扩充：10 类样本模板（高数/线代/概率统计/408 代码/408 表格/多列/水印/计网/OS），含 case.json 元数据。
  - 性能 Profile：`PipelineStage` 内置 input_count/output_count/cache_hit/cache_miss/ai_calls/tokens_used，聚合到 diagnostics。
  - 失败自动归因：`ocr_failure_analyzer.py`（772 行）16 种失败分类 + 11 checker 函数。
  - 小范围精调：text_normalizer 扩充教育品牌水印 + 中文页码行过滤，code_detector 扩充 408 C/C++ 数据结构关键词。
  - 管理端 Dashboard：tasks 页面新增质量概览卡片（风险分布/AI 答案/公式截图/性能概览/高风险跳转）。
  - 三级测试策略：acceptance runner 支持 --strict 模式，CI 不依赖真实样本。
  - 受影响文件：`backend/app/features/ocr_failure_analyzer.py`（新增）、`backend/app/features/text_normalizer.py`、`backend/app/features/code_detector.py`、`admin-frontend/src/app/(admin)/imports/tasks/page.tsx`。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

- **P5 管线拆分完成**
  - P5-2：`pipeline_orchestrator.py` 渐进拆分 → 7 个 `pipeline_stages/` 模块（match/math_detect/table_detect/normalize_schema/repair/review），文件行数 4454→4081。
  - P5-3：`question_pipeline.py` 拆出 4 个子模块（question_ai_complete.py / question_ai_enrich.py / question_draft_generator.py / question_import_writer.py），保留全部向后兼容重导出。
  - Qwen 清除：删除 qwen_adapter.py（309 行），路由链简化为 PaddleOCR-VL → DeepSeek → Rule。
  - Vision 消费端落地：添加 feature="vision" 到 FEATURE_VALUES + admin UI；pipeline _run_extract 接入 resolve_active_model(feature="vision") 作为 PaddleOCR-VL 回退。
  - 受影响文件：`backend/app/features/pipeline_stages/*`（新增）、`backend/app/features/question_ai_complete.py`（新增）、`backend/app/features/question_ai_enrich.py`（新增）、`backend/app/features/question_draft_generator.py`（新增）、`backend/app/features/question_import_writer.py`（新增）、`backend/app/features/ocr_fix/qwen_adapter.py`（删除）。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`。

## 2026-06-20

- **P4 真断点恢复 + 幂等入库 + 导题验收报告完成**
  - 新增 `pipeline_artifacts.py` 提供文件级 artifact 存储（`.backend_cache/pipeline_artifacts/{pipeline_id}/`），支持 split / normalize_schema / repair / math_detect / table_detect / review 共 6 种 artifact 类型。
  - 真断点恢复：resume 时自动检测 artifact，从 normalize_schema / repair / math_detect / table_detect 恢复 questions，跳过已完成 stage，不再重跑 OCR 和 AI 修复。
  - 幂等入库：`submit_to_review` 通过 `subject + question_hash` 全库去重，`duplicates_filtered` 写入 review_commit diagnostics。
  - 导入质量报告：`_build_quality_report()` 在 pipeline 完成后输出风险分布 / AI 答案 / 公式截图 / 表格 / 缓存 / 去重统计，通过 `quality_report` 字段返回。
  - 清理策略：新增 `POST /cleanup/expired` 端点（completed: 24h, failed: 7d），artifact 目录写入 `.completed` / `.failed` marker。
  - 验收脚本：`tests/ocr_acceptance/run_acceptance.py` 支持真实样本验收。
  - artifact store 单元测试 18 项通过。
  - 受影响文件：`backend/app/features/pipeline_artifacts.py`（新增）、`backend/app/features/pipeline_orchestrator.py`、`backend/app/api/v1/admin_imports.py`、`backend/app/schemas/import_review.py`、`tests/test_pipeline_artifacts.py`（新增）。
  - 受影响文档：`docs/audit/ocr-pipeline-full-engineering-audit.md`、`docs/project/CHANGELOG.md`、`prompts/task/ocr-import-p4-true-resume-idempotency-acceptance.md`。

## 2026-06-18

- **修复：`_extract_stem()` 无选项时误剥离圈号前缀行**
  - `question_normalizer.py` 中 `_extract_stem()` 的 `_OPTION_LINE_RE` 缺少 `option_lines` 前置守卫，当上游未检测到选项时仍匹配 `① A. n + 1` 类行并从题干中剥离。
  - 修复：在 `_OPTION_LINE_RE.match()` 前增加 `option_lines and` 守卫。
  - `test_partial_missing` 测试数据补齐 Q1 完整 A/B/C/D 选项。
  - 新增 `test_cross_path_consistency()` 跨路径一致性冒烟测试，防止两条标准化路径（Path A: module-level `normalize_question()` / Path B: `QuestionNormalizer.normalize()`）功能发散。
  - 受影响文件：`app/features/question_normalizer.py`、`tests/test_services/test_question_normalizer.py`、`tests/test_question_pipeline.py`。
  - 受影响文档：`docs/ai/STANDARDIZATION_FLOW.md`、`docs/project/CHANGELOG.md`。

## 2026-06-10

- **AI 解析设置页面 — 配置接口实施完成**
  - 新增 `AdminAiModelConfig` 表（`admin_ai_model_configs`）：模型配置，API key 使用 Fernet 加密存储。
  - 新增 `AdminAiConfig` 表（`admin_ai_configs`）：键值对配置表，存储 17 个 AI Prompt / OCR / 补全策略配置项。
  - 新增 `GET /api/admin/v1/ai-models` — 模型列表（不含 api_key，含 `api_configured: bool`）。
  - 新增 `PATCH /api/admin/v1/ai-models/{id}` — 更新模型字段（api_key="****" 时不修改，设为 default 时自动清除其他 default）。
  - 新增 `GET /api/admin/v1/ai-configs` — 扁平 JSON 键值对读取。
  - 新增 `PATCH /api/admin/v1/ai-configs` — 部分更新（不存在的 key 忽略，prompt 字段 max_length=5000）。
  - 权限控制：使用已有 `ai_setting:read` / `ai_setting:write` 权限。
  - 审计日志：PATCH 操作记录 `severity=normal`，action=`ai_config.update` / `ai_model_config.update`。
  - 前端 ModelCards / OcrAccordion / AiCompletionPreview 三个组件对接后端 API，骨架屏加载态、错误态保留上次数据。
  - 模型卡片提示"当前版本实际使用模型为 DeepSeek V4 Flash，此处配置仅作为记录"；配置区域提示"配置已保存，将在后续版本中生效"。
  - 修复：prompt 字段 max_length=5000 校验、TypeScript 类型修正、文案修正 (DeepSeek → DeepSeek V4 Flash)、错误态保留上次值、配置区域提示文案补全。
  - 受影响文档：`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/AUDIT_LOG.md`、`docs/admin/ADMIN_ARCHITECTURE.md`、`docs/project/CHANGELOG.md`。

## 2026-06-02

- **真实题库相似匹配纠错层接入导入管线**
  - 新增 `backend/app/features/similarity_matcher.py`，位于 repair 与 review 之间。
  - 加载同科目已有正式题目，使用 difflib 计算相似度比率，阈值 >= 0.85 时附加 `similarity_suggestion` 字段。
  - 仅作为建议，不自动覆盖或纠正，结果供人工审核参考。
  - `pipeline_orchestrator` 已插入 `similarity_match` 阶段并输出诊断信息。
  - 19 项回归测试通过。
  - 提交：`affa30e feat: add similarity matching correction layer to import pipeline`。
  - 变更原因：为 OCR 导入提供基于已有题库的相似题建议，提升人工审核效率。

- **AI OCR Correction Layer 接入导入管线**
  - 新增 `backend/app/features/ocr_correction.py`，位于 `normalize_text` 与 `analyze_structure` 之间。
  - 自动检测 OCR 噪声信号（乱码字符、短行、缺失题号、选项碎片化），噪声超阈值时调用 DeepSeek AI 修复。
  - 使用独立 token budget，auto 模式下仅在检测到噪声时触发，AI 不可用时静默降级。
  - `pipeline_orchestrator` 已插入 `ocr_correction` 阶段并输出诊断信息。
  - 新增 `ocr_correction` system prompt（`backend/app/ai/prompts.py`）。
  - 20 项回归测试通过。
  - 提交：`e88a33b feat: add AI OCR Correction Layer to import pipeline`。
  - 变更原因：提升 OCR 导入成功率，修复换行错乱、选项错位、题号缺失等噪声问题。

- **OCR 结构分析接入导入主链路完成**
  - `DocumentStructureAnalyzer` 已接入图片导入管线，结构结果会传给 `split_questions(..., structure=structure)` 与 `match_answers(..., structure=structure)`。
  - `SEPARATED` 场景下，切题阶段会跳过纯答案页，避免答案页被重新切成假题目。
  - `answer_pages` 统一返回真实页码 `page`，不再使用 `block_index`，以便答案匹配与页码语义一致。
  - 结构分析补齐空输入诊断字段：`diagnostic_reason`、密度统计、OCR 噪声计数与布尔型存在标记。
  - 相关回归测试已补充并通过。
  - 变更原因：同步已完成的 OCR 结构分析与导入链路增强；本次仅更新文档，不改业务代码。

## 2026-06-01

- **OCR 图片导入诊断与失败分类完成**
  - 图片上传入队前校验 `OCR_ENABLED` 与 PaddleOCR 依赖可用性，避免后台任务延迟失败。
  - 图片导入状态保留 OCR 运行时诊断、原始/清洗文本预览、长度/行数差值、OCR stats 与切题诊断。
  - 切题诊断新增 `normalized_block_count`、`text_block_count`、`raw_question_count`、`raw_questions_preview`、`failure_reason`，fallback 区分 `text_present_but_no_question_boundary` / `no_text_blocks` 并标记 `fallback_created`。
  - 图片管线失败分类为 `ocr_empty_text`、`text_present_but_split_failed`、`missing_options`、`pipeline_failed`，审核边界不变：仍全部进入 `question_imports` 后人工确认。
  - 变更原因：同步已完成的 OCR image import diagnostics classification；本次仅更新文档，不改业务代码。

- **OCR 图片导入可靠性 P0/P1 完成**
  - 图片导入状态响应现在会返回 OCR 诊断与切题诊断：原始/清洗后文本长度、行数、预览、长度差值；清洗后为空时会标记 `ocr_empty_after_cleaning`。
  - 管线在“有规范化文本但找不到题号边界”时会生成低置信度 fallback 审核项，避免整批静默丢失。
  - 题目切分增强支持圈号前缀选项、紧凑 inline 选项与连续题号边界识别，文本标准化会更保守地保留结构化选项行。
  - OCR 图像预处理补充 `ImageOps.exif_transpose()`，减少手机拍照方向异常导致的识别偏差。
  - 变更原因：同步已完成的图片导入可靠性增强与回归验证结果；本次仅更新 OCR / 导入相关文档，不改业务代码或测试。

## 2026-05-31

- **文档整理与关键文档同步**
  - 对齐 `CLAUDE.md` 与当前 docs 索引，明确 App 仍坚持微信 openid + JWT、无传统账号系统；Admin RBAC 属于后台管理域，不改变 App 登录模型。
  - 同步 `question_imports` 当前字段：审核元数据、AI 辅助导题字段与数学公式图片化 `math_regions`，并强调 AI 结果必须进入暂存区人工审核。
  - 同步 AI 学习引擎端点：`/ai/explain`、`/ai/recommend`、`/ai/report`、`/ai/analyze-mistake`，记录 token 限额与基础 AI 服务剩余缺口。
  - 更新 OCR/导入文档中 Level 1 题目去重与文件级去重边界，避免把已实现题目 hash 去重误写成未实现。
  - 未删除文档：本次未发现可在当前证据下安全删除且不影响索引的明确冗余文档；保留不确定文档并通过索引限定用途。
  - 变更原因：执行 docs 目录整理任务，优先编辑现有关键文档，不修改业务/配置/测试代码。

- **Redis-backed 图片导入状态完成**
  - `GET /api/v1/import/pipelines/{pipeline_id}` 按 legacy `get_pipeline_status` → Redis `import:image:pipeline:{pipeline_id}` → 同进程 `_image_pipeline_store` 查询，只有 legacy 与 image 状态都缺失时返回 404。
  - 图片状态写入先更新内存，再 best-effort 写入 Redis，TTL 86400 秒；Redis 支持跨 worker 短期状态共享与 TTL 内重启恢复。
  - `REDIS_URL` 未配置或 Redis 不可用时回退为同进程内存状态，不保证跨 worker / 重启恢复。
  - 图片导入终态为 `completed` / `failed`，非终态包括 `queued` / `ocr_running` / `parsing`；前端仅应在终态停止轮询。
  - 生产 Docker Compose 默认注入 `REDIS_URL=redis://redis:6379/0`。
  - 变更原因：同步已完成的 Redis-backed image import status 实现；受影响文档为 `docs/backend/API_SPEC.md`、`docs/architecture/OCR_FLOW.md`、`docs/ai/OCR_STRATEGY.md`。

## 2026-05-30

- **题库 Level 1 完全重复检测完成**
  - 导入阶段 `question_imports` 新增 `question_hash`、`duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id` 字段；正式题库 `questions` 新增 `question_hash`。
  - 发布 / 审核通过阶段按 `subject + question_hash` 做完全匹配拦截，避免重复题进入正式题库。
  - 新增 Alembic migration `j1f2a3b4c5d6_add_duplicate_question_hash_fields.py`，并补充启动补列逻辑。
  - 审核队列、批次详情与 admin import schema 返回重复相关字段；日志统一使用 `[DuplicateCheck]`。
  - 变更原因：同步题库去重已实现状态；受影响文档为 `docs/backend/DB_SCHEMA.md`、`docs/ai/STANDARDIZATION_FLOW.md`、`docs/architecture/OCR_FLOW.md`、`docs/backend/API_SPEC.md`、`docs/admin/ADMIN_API_SPEC.md`、`docs/admin/DB_SCHEMA_ADMIN.md`、`docs/admin/REVIEW_FLOW.md`。

- **Admin Phase 7: 后台 AI 解析设置与全局月度额度完成**

- **Admin Phase 6: Next.js Admin Dashboard 前端主要实现完成**
  - 新增 `admin-frontend`，使用 Next.js 16、React 19、React Query、TanStack Table、Zustand、Recharts 与 Tailwind CSS 4。
  - 页面覆盖 `/dashboard`、`/login`、`/app-users`、`/admin-users`、`/questions`、`/review`、`/roles`、`/audit-logs`。
  - Phase 6 前端仅消费 `/api/admin/v1`，不修改后端 API、DB schema 或权限语义。
  - 修复 build/lint 问题，并同步 audit-log 查询参数别名：`pageSize`、`resourceType`、`from`、`to`。
  - 已通过 `npm --prefix admin-frontend run lint` 与 `npm --prefix admin-frontend run build`。
  - 变更原因：同步 Admin Phase 6 前端实现状态与文档边界；受影响文档为 `docs/admin/README.md`、`docs/admin/PHASE_PLAN.md`、`docs/frontend/ADMIN_UI_RULES.md`。

## 2026-05-29

- **Admin Phase 5: 审计日志与统计后端完成**
  - 新增 `GET /api/admin/v1/audit-logs` 与 `GET /api/admin/v1/audit-logs/{id}`，支持多维过滤、分页、默认近 183 天与 1 年跨度限制。
  - 新增 `GET /api/admin/v1/dashboard/overview`、`/daily`、`/questions-stats`，覆盖总览、每日趋势与题目分布统计。
  - Dashboard overview 使用现有 FastAPI `app.core.cache`，支持 TTL 抖动与防穿透锁；Redis 不可用时降级直查 DB。
  - 变更原因：同步 Admin Phase 5 后端实现状态与实际 FastAPI/SQLAlchemy 方案；受影响文档为 `docs/admin/*` API、审计日志与 Redis 规划。

## 2026-05-24

- **Stage 11: 刷题系统重构** — PracticeRecord 从会话级改为逐题记录
  - 新增 `GET /practice/questions` 支持随机/顺序模式 + 知识点筛选
  - 新增 `POST /practice/submit` 单题提交（大小写不敏感判题）
  - 新增 `POST /practice/batch-submit` 批量提交
  - 新增 `GET /practice/stats` 刷题统计（含连续天数）
  - 新增 `GET /questions/{id}/detail` 含答案详情（答后可见）
  - 答错自动同步错题本，错题重做触发 SM-2 更新
  - 小程序刷题页支持随机/顺序模式切换
- 文档结构重构：将 `/docs` 和 `/prompts` 按职责分类，建立 AI 工程化文档体系
- 新增导入管线开发 Prompt（stage1-9）
- 新增 features/ 目录架构设计

## 2026-05-22

- CURRENT_ARCHITECTURE.md 基于代码真实状态更新
- 记录 API 端点总数（47个）和已知技术债务

## 更早

- MVP 核心功能开发完成
- 各阶段开发文档归档到 `docs/achieve/`
