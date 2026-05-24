# 2240AI 系统架构

> 基于代码真实状态，不含未来设计。最后更新：2026-05-24

---

## 总体架构

```
小程序 → Nginx → FastAPI 单体后端 → PostgreSQL
                      ├─ AI 模块 (DeepSeek httpx)
                      ├─ OCR (可选/PaddleOCR)
                      └─ RAG (关键词检索)
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
| 前端 | 微信小程序 | 原生框架 |
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
