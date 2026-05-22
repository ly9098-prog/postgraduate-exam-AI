# 22408 AI 考研学习助手 — CLAUDE.md

> 长期稳定的项目规则、架构约束、开发规范。**不包含阶段性开发任务或产品规划。**

---

## 项目基础信息

- **项目**：2240AI — 考研智能刷题小程序（数学二 / 408 / 英语）
- **技术栈**：FastAPI + SQLAlchemy + PostgreSQL + Redis | 微信小程序
- **AI**：DeepSeek API（httpx 直连，无 langchain/llamaindex）
- **认证**：微信 openid 唯一身份 + JWT 会话

---

## 明确不做什么

- ❌ OCR 识别手写题 / 复杂 OCR pipeline
- ❌ 复杂 AI 文档解析系统 / 全网自动爬虫
- ❌ 多媒体数据处理架构 / 分布式导题服务
- ❌ LangChain / Agent / 多模型编排
- ❌ 微服务 / Kubernetes
- ❌ 知识图谱 / 复杂推荐系统
- ❌ 多租户 / 权限体系
- ❌ 社区 / 论坛 / 排行榜
- ❌ 实时协同 / WebSocket
- ❌ 复杂 AI 工作流 / 多轮对话 Agent
- ❌ 强化学习 / AI 预测遗忘率
- ❌ 个性化机器学习推荐 / 实时动态调度系统
- ❌ 账号密码登录 / email + password 注册
- ❌ 忘记密码 / 重置密码流程
- ❌ 多方式登录体系（OAuth、第三方混合登录）
- ❌ 传统账号系统（本项目不实现传统账号系统，所有用户身份由微信 openid 驱动）

---

## 项目目录结构

```
postgraduate-ai/
├── backend/                    # FastAPI 单体后端
│   ├── app/
│   │   ├── api/                # 路由层
│   │   │   ├── v1/
│   │   │   │   ├── users.py
│   │   │   │   ├── questions.py
│   │   │   │   ├── wrong_questions.py
│   │   │   │   ├── practice.py
│   │   │   │   ├── review.py
│   │   │   │   ├── ai.py
│   │   │   │   ├── imports.py
│   │   │   │   └── __init__.py
│   │   │   └── __init__.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── database.py
│   │   │   ├── redis.py
│   │   │   └── security.py
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── question.py
│   │   │   ├── question_import.py
│   │   │   ├── wrong_question.py
│   │   │   ├── practice_record.py
│   │   │   ├── review_plan.py
│   │   │   └── ai_chat.py
│   │   ├── schemas/
│   │   │   ├── user.py
│   │   │   ├── question.py
│   │   │   ├── wrong_question.py
│   │   │   ├── practice.py
│   │   │   ├── review.py
│   │   │   ├── ai.py
│   │   │   └── question_import.py
│   │   ├── services/
│   │   │   ├── user_service.py
│   │   │   ├── question_service.py
│   │   │   ├── wrong_question_service.py
│   │   │   ├── practice_service.py
│   │   │   ├── review_service.py
│   │   │   ├── sm2_service.py
│   │   │   ├── import_service.py
│   │   │   └── ai_service.py
│   │   ├── ai/
│   │   │   ├── client.py
│   │   │   ├── prompts.py
│   │   │   ├── token_counter.py
│   │   │   ├── fallback.py
│   │   │   └── context.py
│   │   ├── utils/
│   │   │   ├── response.py
│   │   │   └── errors.py
│   │   └── main.py
│   ├── rag/                     # 代码级 RAG 检索（关键词匹配，无向量库）
│   │   ├── index.json
│   │   ├── retriever.py
│   │   ├── context_builder.py
│   │   └── chunker.py
│   ├── alembic/
│   │   ├── versions/
│   │   ├── env.py
│   │   └── alembic.ini
│   ├── tests/
│   │   ├── test_api/
│   │   └── test_services/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── miniprogram/
│   ├── app.js
│   ├── app.json
│   ├── app.wxss
│   ├── pages/
│   │   ├── home/
│   │   ├── login/
│   │   ├── practice/
│   │   ├── practice-result/
│   │   ├── wrong-book/
│   │   ├── wrong-detail/
│   │   ├── plan/
│   │   ├── import/
│   │   └── import-batch/
│   ├── components/
│   ├── utils/
│   │   ├── api.js
│   │   ├── auth.js
│   │   └── storage.js
│   └── config.js
│
├── docker-compose.yml            # 开发环境编排
├── docker-compose.prod.yml       # 生产环境编排
├── deploy/
│   ├── Dockerfile.prod           # 多阶段生产构建
│   ├── nginx.conf                # Nginx 反向代理 + HTTPS + 限流
│   ├── deploy.sh                 # 首次部署 / 日常更新
│   ├── backup.sh                 # 每日数据库备份
│   └── checklist.md              # 上线前检查清单
├── scripts/
│   ├── init_db.sql
│   ├── seed_questions.py
│   └── import_from_excel.py
├── .env.example                  # Docker Compose 环境变量模板
└── .gitignore
```

### 目录设计原则

- **单体项目不做模块拆分**，只在 backend/app/ 内按职责分层
- **AI 模块独立**为 `app/ai/`，便于后续替换模型或升级 prompt 策略
- **routes 只做参数校验和响应组装**，业务逻辑下沉到 services/
- **不引入 service 接口层**（不写 `IUserService` / `UserServiceImpl`），直接 import service 函数
- **导入模块单独**为 `import_service.py` + `imports.py`，不和其他业务混在一起

---

## 数据库设计

### 总览

| 表名 | 用途 |
|------|------|
| users | 用户信息 |
| questions | 题目库 |
| question_imports | 导入暂存区 |
| wrong_questions | 错题记录 |
| practice_records | 练习记录 |
| review_plans | 复习计划 |
| review_schedules | SM-2 调度记录 |
| ai_chats | AI 对话历史 |

### 核心设计原则

- **用户唯一标识：微信 openid**（不使用 email/username/password）
- **系统不保存密码**，彻底移除密码体系
- `subject_meta` 存各科学习进度，`user` 设置用 JSONB，不拆分独立表
- `knowledge_points` 用 PG 数组 + GIN 索引，支持高效查询
- `content` 为 JSONB，结构：`{"text":"...", "images":["url1"], "latex":"..."}`
- 不拆选择题/填空题子表，用 `question_type` 区分
- `source_type` + `source_file` + `import_batch_id` 三位一体，确保任意一道题可追溯来源
- `raw_content` 保留导入原始文本，后续 AI 可重新处理（如自动标知识点）
- 每次练习一条记录（`practice_records`），不拆到每题一条
- 按天为单位，每人每科每天一个复习计划（`review_plans`）
- `session_type` 区分 AI 对话场景，`context_snapshot` 保存调用时的上下文

### 认证系统设计原则

- **认证唯一来源：微信 openid** — 不存在第二套身份体系
- **用户体系 = 微信身份映射** — 不存储密码，不管理密码
- **JWT 仅用于会话管理** — 不用于身份认证，仅做会话 token
- **不设计传统账号系统** — 没有用户名/邮箱/密码字段
- **不允许引入多登录方式** — 不支持手机号、邮箱、第三方 OAuth 混合登录
- **登录流程保持 3 步以内**：`wx.login → 后端 → token`
- **用户注册 = 首次微信登录自动创建** — 无需注册页面
- **小程序端无登录表单** — 用户无感登录（首次需授权）

```
后端不实现：
  POST /auth/register        ✗ 不需要注册
  POST /auth/reset-password  ✗ 不需要密码重置
  GET  /auth/verify-email    ✗ 不需要邮箱验证
```

---

## API 设计规范

### 基础

- Base URL: `/api/v1`
- 统一响应格式：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

### 认证

- **唯一登录方式**：微信小程序 `wx.login()` → code → `POST /api/v1/auth/login` → openid → JWT
- **不实现任何其他登录方式**，无 email/password、无注册接口、无密码重置
- Header: `Authorization: Bearer <token>`
- Token 有效期：7 天（小程序常驻，过期需重新 wx.login）
- **用户首次使用自动创建**，无需注册表单

### 命名规范

- 路径：小写 + 连字符（`wrong-questions` 而非 `wrongQuestions`）
- 查询参数：小驼峰（`pageSize`、`questionType`）
- 请求体：小驼峰（与 Python 变量一致）
- 响应体：小驼峰

### 分页规范

```json
// 请求参数
{ "page": 1, "pageSize": 20, "subject": "math2" }

// 响应
{
  "code": 0,
  "data": {
    "items": [],
    "total": 100,
    "page": 1,
    "pageSize": 20,
    "totalPages": 5
  }
}
```

### 错误码约定

| code | 说明 |
|------|------|
| 0 | 成功 |
| 40001 | 参数错误 |
| 40101 | 未登录/token 过期 |
| 40401 | 资源不存在 |
| 50001 | 服务器内部错误 |
| 50002 | AI 服务不可用 |

---

## AI 模块设计原则

### 架构原则

> AI 是辅助功能，不是项目主体。Simple is better.

```
用户请求 → 构造 Prompt → 调用 DeepSeek API → 解析响应 → 缓存结果 → 返回
```

没有 Chain、没有 Agent、没有 Tool Calling。一条请求一次调用。

### 文件职责

```
app/ai/
├── client.py          # DeepSeek HTTP 客户端（基于 httpx）
├── prompts.py         # 所有 Prompt 模板
├── token_counter.py   # Token 估算与限额控制
├── fallback.py        # API 不可用时的降级方案
└── context.py         # 上下文构建（组装题目、错题等信息）
```

### 技术约束

- 使用 httpx 异步请求，不引入 langchain/openai sdk
- 每个场景一个 Prompt 函数，返回 messages list
- Prompt 明确要求返回 JSON 格式，中英混合提示词，中文输出
- Temperature = 0.3（数学场景要准确，不要创造性）

### Token 成本控制

- 每次 AI 调用前估算 token
- 日/月 token 限额（配置化）
- 缓存 AI 结果到 `wrong_questions.ai_analysis`，相同内容不重复调用
- 长文本分段（408 题目可能较长）
- 模型选型：日常用 `deepseek-chat`（便宜），长分析用 `deepseek-reasoner`
- 每次调用记录 `ai_chats` 表，方便核算成本

### AI 降级方案

当 API 不可用或超时时：

1. **静默降级**：返回预置的通用分析模板
2. **本地缓存命中**：检查 `wrong_questions.ai_analysis` 是否有缓存
3. **排队重试**：写入 `ai_retry_queue`，下次请求时重试
4. **前端提示**：小程序提示"AI 分析暂时不可用，请稍后重试"

不允许：
- 不让用户感知到系统崩溃
- 不阻塞刷题流程（AI 是辅助，没 AI 也能刷题）

---

## 开发规范

### Python 规范

- Python 3.11+
- 类型注解全覆盖（所有函数参数和返回值标注类型）
- 使用 `ruff` 做 lint + format（配置见 `pyproject.toml`）
- 不使用 `__init__.py` 做重导出（直接 `from app.models.user import User`）
- Service 层不写抽象类/接口
- Model 层不使用 `__tablename__` 以外的魔法方法（不写 `__repr__`、不写自定义 Query）

### FastAPI 规范

```python
# ✅ 好的写法：直接在路由函数中校验参数
@router.get("/questions")
async def list_questions(subject: str = Query(...), ...):
    ...

# ❌ 不要这样写：
# 1. 不要在路由中写业务逻辑
# 2. 不要套三层以上的依赖注入
# 3. 不要为每个路由单独建一个文件
```

### Git 提交规范

```
<type>: <简短描述>

<body (可选)>
```

type 类型：`feat` / `fix` / `refactor` / `perf` / `docs` / `chore`

示例：
```
feat: 新增 AI 错题分析接口
fix: 修复复习计划日期重复问题
refactor: 抽离 AI 客户端为独立模块
```

### Docker 规范

- 多阶段构建（`python:3.11-slim`），开发 `docker-compose`，生产 `gunicorn + uvicorn workers`
- 不引入 k8s、swarm 等编排工具

### 环境变量规范

```bash
# .env.example — 所有环境变量写在这里，不放在代码里硬编码
# 必填变量：APP_SECRET, DATABASE_URL, DEEPSEEK_API_KEY, WECHAT_APP_ID, WECHAT_APP_SECRET
```

---

## Claude Code 工作流

### 核心原则

> **先实现功能，再优化架构。** > **能跑就比什么都强。**

### AI 协作约定

1. **加功能**：优先给最简单能跑的方案，不要提前抽象。三个重复再考虑抽函数，六个重复再考虑抽类。

2. **不主动提议加新依赖**：除非明确要求，不准引入新的数据库、消息队列、缓存中间件、AI 框架、监控工具。

3. **代码约束**：
   - 一个文件不超过 300 行，一个函数不超过 50 行
   - service 层可以直接调用另一个 service，不需要经过 controller
   - 不写 interface/abstract class，不写 decorator 以外的 AOP
   - 不写工厂模式/策略模式（除非明显需要）
   - 尽量少用 `@property`，直接暴露字段
   - 能用 list 不用 QuerySet，能用 dict 不用 dataclass

4. **文件结构**：
   - 一个 model 一个文件，不要拆 base/mixin/interface
   - service 里一个业务场景写一个函数，不需要分多个类
   - 当文件超过 300 行时再考虑拆分
   - 不要创建 `__init__.py` 做重导出

5. **AI 模块**：
   - 不要引入 langchain / llamaindex
   - 直接 httpx 调 DeepSeek API
   - Prompt 直接写在 prompts.py，不引入 prompt 管理平台
   - 失败降级优先于重试

6. **数据库**：
   - 不提前建索引（等慢查询出现再加）
   - 不写 migration 的回滚脚本（个人项目不需要）
   - 不用 database router / read-write separation
   - 不要 join 超过 3 张表。超过时考虑反范式或 service 层拼接

7. **改 bug**：先给最小修复，不要顺手重构旁边代码。修复后问"要不要清理"，确认再做。

8. **优化**：先给数据（哪个接口慢、哪个查询慢），不要凭感觉优化。

9. **测试**：
   - 只写核心 service 的单测（AI 模块 + 业务核心逻辑）
   - 不写 controller 层的集成测试（手动测更高效）
   - 不追求测试覆盖率，追求核心功能稳定

### 题库导入特别约定

1. **不要花时间优化 PDF 解析准确率**。能分出 60% 就算成功，剩下的交给人工。
2. **Excel 是第一优先级**。如果某个需求用 Excel 能解决，就不要写代码。
3. **不要设计可视化导题界面**。小程序端只做审核列表，Excel 编辑在本地完成。
4. **导入脚本可以用同步命令**，不需要做后台任务队列。
5. **不接受纯 AI 自动入库**。所有题目必须经过 `question_imports` 暂存区，人工确认。

### 沟通风格

- 简单直接，不要长篇分析
- 给我选项时先给推荐方案
- 告诉我预估工时（小时级），我判断要不要做
- 觉得我在过度设计时直接提醒我

---

## 重要开发原则（最终检查清单）

每次提交代码前，过一遍：

- [ ] 1. 这个功能的复杂度能再降低吗？
- [ ] 2. 它真的能提高我的学习效率吗？
- [ ] 3. 我现在真的需要它吗？（不要超前）
- [ ] 4. 如果 AI 不能工作，功能还能用吗？（AI 是辅助）
- [ ] 5. 几个月后我还能看懂这段代码吗？（可维护性）
- [ ] 6. 有更简单的方式实现吗？（Python 之禅）
- [ ] 7. 服务器挂了怎么恢复？（后端优先稳定）
- [ ] 8. 这个改动会影响什么已有的功能？（回归风险）

### 题库导入专项检查

- [ ] 9. 这道题能追溯到来源吗？（source_type + source_file + import_batch_id）
- [ ] 10. 如果明天 AI 不能用了，今天导入的题还能用吗？（人工确认过）
- [ ] 11. 三个月后我还能读懂这批导入逻辑吗？（代码简单）
- [ ] 12. 这个解析步骤能用手工替代吗？（不要依赖自动化）

### 用户认证专项检查

- [ ] 13. 这个功能依赖 email/password 吗？（本项目不使用传统账号）
- [ ] 14. 用户身份是否通过 openid 而非自定义字段标识？（openid 是唯一 ID）
- [ ] 15. 是否引入了多登录方式？（必须只有微信登录，无其他方式）
- [ ] 16. 如果微信服务不可用，降级方案是什么？（token 有效期内可继续使用）

### SM-2 复习系统专项检查

- [ ] 17. 这次改动会破坏现有的 review_plans 接口吗？（不能影响现有功能）
- [ ] 18. SM-2 参数更新能回滚吗？（幂等更新，不丢数据）
- [ ] 19. 如果用户不做质量评分，系统还能正常运行吗？（降级为二值评分）
- [ ] 20. 这个调度策略在只有 10 条错题时合理吗？（小数据量边界）
- [ ] 21. 用户能理解"为什么今天复习这 5 道题"吗？（可解释性）
