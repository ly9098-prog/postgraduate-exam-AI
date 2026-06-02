# 变更日志

> 记录项目重大变更。

---

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
