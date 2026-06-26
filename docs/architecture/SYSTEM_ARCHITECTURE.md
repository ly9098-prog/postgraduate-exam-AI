# 2240AI 系统架构

> 基于代码真实状态，不含未来设计。最后更新：2026-06-26

---

## 总体架构

```
管理端 (Next.js) ─┐
小程序 ───────────┼→ Nginx → FastAPI 单体后端 → PostgreSQL
                  │              ├─ AI 模块 (DeepSeek httpx)
                  │              ├─ OCR (可选/PaddleOCR)
                  │              └─ RAG (关键词检索)
```

### 核心设计原则

- **单体后端**，不分微服务，3 层：Route → Service → Model
- **暂存区模式**：所有导入/AI 生成数据先入 `question_imports`，人工审核后才进 `questions`
- **AI 降级**：DeepSeek 不可用时返回预置模板，不阻塞刷题
- **微信 openid 唯一身份**，无 email/password 体系

---

## 技术栈

| 层级 | 技术 | 版本/说明 |
|------|------|-----------|
| 后端框架 | FastAPI | 0.111.0, 异步 |
| ORM | SQLAlchemy 2.0 | async 模式 |
| 数据库(开发) | SQLite | aiosqlite |
| 数据库(生产) | PostgreSQL 15+ | asyncpg |
| AI | DeepSeek API | httpx 直连, 无 SDK |
| OCR | PaddleOCR | 可选依赖(~500MB) |
| PDF | PyMuPDF | 1.24.9 (fitz) |
| Excel | openpyxl | 3.1.5 |
| 前端（学员） | 微信小程序 | 原生框架 |
| 管理端 | Next.js 14 | Turbopack, shadcn/ui, TanStack Query |
| 容器 | Docker Compose | 多阶段构建 |
| 反向代理 | Nginx | 1.25-alpine, HTTPS |

---

## 项目目录

```
postgraduate-ai/
├── backend/app/
│   ├── api/v1/       # 路由层 (47个端点)
│   ├── core/         # 基础设施 (config/database/security)
│   ├── models/       # ORM 模型 (9表)
│   ├── schemas/      # Pydantic 模型
│   ├── services/     # 业务逻辑 (16文件)
│   ├── features/     # 导入管线 (ImportTextNormalizer 等)
│   ├── ai/           # DeepSeek 集成
│   └── main.py
├── admin-frontend/   # 管理端 (Next.js, shadcn/ui)
├── miniprogram/      # 微信小程序 (10页面)
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
| OCR 扫描 PDF | ✅ 代码就绪 | ocr_service.py, pdf_classifier.py |
| 批量图片导入 | ✅ 完成 | batch_image_import_service.py |
| 批量图片 SSE 流式追踪 | ✅ 完成 | sse.ts, admin_imports.py |
| 学习统计 | ✅ 完成 | stats.py, stats_service.py |
| 答题行为记录 | ✅ 完成 | behavior.py, behavior_service.py |
| 知识点标签 | ✅ 完成 | knowledge_points.py, knowledge_service.py |
| RAG 检索 | ✅ 未接入业务 | rag/retriever.py |

---

## 关键架构图

### AI 调用链

```
请求 → ai_service.py
  ├─ 缓存检查 (WrongQuestion.ai_analysis)
  ├─ token 估算 (硬限制)
  ├─ 构建上下文 → 构造 Prompt → 调用 DeepSeek
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
  ├─ 创建/更新 ReviewSchedule（主调度数据源）
  │   ├─ interval / ease_factor / repetitions
  │   ├─ next_review_at (datetime, utcnow 校准)
  │   └─ mastered
  └─ _sync_schedule_to_wq()
      └─ 回写 WrongQuestion 兼容字段
          (efactor / interval / repetitions / next_review_date / mastered)

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

- **ReviewSchedule 是主数据源**。WrongQuestion 上的 SM-2 字段（efactor/interval/repetitions/next_review_date/mastered）仅为历史兼容字段，不参与新版复习调度。
- **同步机制**：每次 ReviewSchedule 更新后，`_sync_schedule_to_wq()` 自动回写 WrongQuestion 对应字段，确保两表一致。
- **时区统一**：复习日期统一使用 `utcnow().date()`，避免服务器本地时区导致日期偏移。
- **Rating 0 是合法值**：SM-2 quality 评分范围 0-5，0 表示完全不会，会重置连续正确计数（repetitions=0）并缩短间隔。

**历史技术债（已全部清理）**：

| 问题 | 修复 |
|------|------|
| 旧接口未迁移 | ✅ P1-1 已修复（数据源切换 RS） → P2-1 已移除旧接口 |
| 旧 SM-2 路径残留 | ✅ P0-1 已修复（`update_quality()` 路由到 RS） |
| 双表维护 | ✅ P2-2 已移除 WQ SM-2 兼容字段（efactor/interval/repetitions/next_review_date/quality） |
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
