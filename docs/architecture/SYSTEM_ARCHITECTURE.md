# 2240AI 系统架构

> 基于代码与运行时索引（Codebase Memory）整理，不含未来设计。全篇核对：2026-09-02；2026-10-19/20 仅补充分批职责拆分说明，不代表全篇重新验收。

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
| `admin-frontend/src/app/(admin)/questions/page.tsx` | 同目录 `question-list-state.ts`、`question-api.ts`、`question-content-editing.ts` | URL/筛选、请求协议和题干编辑规则分别就近聚合；内容模块仅依赖已有代码识别规则，负责结构化文本、旧字段回退及代码块同步。页面保留 Query 缓存、mutation 回调、最小 PATCH、幂等键生命周期、权限、草稿与下载 UI；尚未抽取 hooks |
| `miniprogram/pages/pomodoro/pomodoro.js` | 同目录 `utils/timer-math.js`、`utils/session-storage.js`、`utils/pending-sync-queue.js` | 时间计算、存储异常适配和待同步队列分别由无页面依赖模块负责；Page 仍负责 `api.now()`、本地暂停修正、网络重试/冲突处理、生命周期与五小时上限。队列按 Page 实例注入存储适配器，持久化键与顺序、去重、容量阀值保持不变 |

这些是已接入实际入口的等价抽取，不代表长页面、底层选题实现或完整学习域已经治理完毕；GET 发题入口已收敛，提交链路和番茄钟 Page controller 仍待后续治理。请求范围、候选/最终守卫及签名响应模块只协调既有服务能力，不反向导入路由；API 路由定义、事务、存储键、界面和分包边界均未更改。小程序队列模块不依赖 `Page`、全局 `wx`、网络或共享可变队列，存储读写失败保持闭锁语义。

OCR 架构测试 `backend/tests/architecture/test_architecture_boundaries.py` 已修正仓库根路径；源码扫描必须发现非空 Python 文件集合，缺失/空目录直接失败，注入越界导入的测试验证扫描器能检出违规。刷题投影和请求筛选纯规则另有 AST 检查，禁止直接依赖路由、FastAPI、SQLAlchemy 或数据库会话模块；请求范围、候选策略、到期筛选、最终守卫和签名响应编排允许数据库会话类型，但禁止路由、FastAPI、数据库会话工厂依赖及 `commit`/`rollback` 调用。管理端新增 API 边界测试，限制题库 API 模块依赖既有 client/types，并检查不直接调用原生 fetch 和新增业务文件/函数预算。实际回归结果与历史失败修复见 `prompts/tasks/current_task.md` 执行记录。

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
│   ├── services/     # 业务逻辑 (16文件)
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
| SM-2 复习调度 | ✅ 完成 | review.py, sm2_service.py, review_service.py |
| AI 错题分析 | ✅ 完成 | ai.py, ai_service.py, ai/client.py |
| AI 学习建议 | ✅ 完成 | (同上) |
| 题库导入 | ✅ 完成 | imports.py, import_service.py |
| AI 辅助导题 | ✅ 完成 | ai_import.py, ai_import_service.py |
| OCR 扫描 PDF | ✅ 已接入 | `features/ocr_*`, `ocr_worker/`, PDF 页面流 |
| 批量图片导入 | ✅ 完成 | batch_image_import_service.py |
| 批量图片 SSE 流式追踪 | ✅ 完成 | sse.ts, admin_imports.py |
| 学习统计 | ✅ 完成 | stats.py, stats_service.py |
| 答题行为记录 | ✅ 完成 | behavior.py, behavior_service.py |
| 知识点标签 | ✅ 完成 | knowledge_points.py, knowledge_service.py |
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

自动批改 → grade_submit / grade_batch
  ├─ 未提供用户自评 rating 时:
  │   is_correct=True  → rating=4
  │   is_correct=False → rating=1
  └─ 同上调用 submit_review
```

**关键设计决策**：

- **ReviewSchedule 是唯一数据源**。`WrongQuestion` 不再维护旧版 SM-2 字段；复习历史写入 `ReviewRecord`。
- **时区统一**：复习日期统一使用 `utcnow().date()`，避免服务器本地时区导致日期偏移。
- **Rating 0 是合法值**：SM-2 quality 评分范围 0-5，0 表示完全不会，会重置连续正确计数（repetitions=0）并缩短间隔。

**历史技术债（已全部清理）**：

| 问题 | 修复 |
|------|------|
| 旧接口未迁移 | ✅ P1-1 已修复（数据源切换 RS） → P2-1 已移除旧接口 |
| 旧 SM-2 路径残留 | ✅ P0-1 已修复（`update_quality()` 路由到 RS） |
| 双表维护 | ✅ 已移除 WrongQuestion 上的旧 SM-2 字段，调度统一使用 ReviewSchedule |
| 时区混用 | ✅ P1-3/4 已修复（全部路径统一为 `utcnow()`） |

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
