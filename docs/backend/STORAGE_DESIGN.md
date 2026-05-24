# 存储设计

> 2240AI 存储架构设计说明。

---

## 数据库

PostgreSQL 15+（生产）/ SQLite（开发）

### 设计原则

- **用户唯一标识**：微信 openid，不使用 email/username/password
- **系统不保存密码**，不存在密码字段
- `content` 为 JSON：`{"text":"...", "images":["url"], "latex":"..."}`
- 不拆选择题/填空题子表，用 `question_type` 区分
- SM-2 字段直接挂在 `WrongQuestion` 表上，不拆独立调度表
- 每次练习一条记录（`practice_records`），不拆到每题一条

### 表清单

| 表名 | 用途 | 行数预估 |
|------|------|---------|
| users | 用户信息 | 少 |
| questions | 正式题库 | 中 |
| question_imports | 导入暂存区 | 中 |
| practice_records | 练习记录 | 中 |
| wrong_questions | 错题 + SM-2 字段 | 中 |
| answer_behaviors | 答题行为日志 | 多 |
| ai_chats | AI 对话 + token 审计 | 中 |
| tags | 知识点标签(树形) | 少 |
| ai_generation_logs | AI 操作审计 | 少 |

详细字段见 `DB_SCHEMA.md`。

---

## 缓存

Redis 已声明（`backend/app/core/redis.py` 存在）但当前**未接入**任何业务逻辑。

### 预留场景

- 复习计划缓存（`get_due_reviews` 高频查询）
- AI token 限额计数器（当前查 `ai_chats` 表替代）
- Pipeline 任务状态（当前用内存 dict）

---

## 文件存储

- 用户上传文件：临时存储在 `/tmp/`（容器内），处理后清理
- 无持久化文件存储（图片等使用外部 CDN）
- 容器内不做本地文件持久化（无 volume 挂载静态文件）

---

## 归档

- 部署脚本在 `deploy/` 目录
- 历史开发阶段文档在 `docs/achieve/`
