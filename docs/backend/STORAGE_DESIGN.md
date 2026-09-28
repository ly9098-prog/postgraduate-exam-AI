# 存储设计

> 2240AI 存储架构设计说明。本文已按当前 `backend/app/services/storage_backend.py` 与生产 Compose 配置同步（2026-09-02）。

---

## 数据库

PostgreSQL 15+（生产，`pgvector/pgvector:pg15`）/ SQLite（开发兼容）

### 设计原则

- **用户唯一标识**：微信 openid，不使用 email/username/password
- **系统不保存密码**，不存在密码字段
- `content` 为 JSON，题干图片以 segments 的 image segment 表达；选项图片保存在 options 的 image segment，`questions.image_url` 仅作冗余展示字段
- 不拆选择题/填空题子表，用 `question_type` 区分
- SM-2 参数统一存储在 `review_schedules`，`WrongQuestion` 不冗余保存复习参数
- `practice_records` 保存单题答题记录，`practice_sessions` 保存一次完整刷题会话；两者职责分离

### 表清单

| 表名 | 用途 | 行数预估 |
|------|------|---------|
| users | 用户信息 | 少 |
| questions | 正式题库 | 中 |
| question_imports | 导入暂存区 | 中 |
| practice_records | 练习记录 | 中 |
| wrong_questions | 错题与 AI 分析 | 中 |
| answer_behaviors | 答题行为日志 | 多 |
| ai_chats | AI 对话 + token 审计 | 中 |
| tags | 知识点标签(树形) | 少 |
| ai_generation_logs | AI 操作审计 | 少 |
| review_schedules / review_records | 复习调度与历史 | 中 |
| knowledge_points / question_knowledge_points | 知识点与题目关联 | 少/中 |
| task_outbox / import_* / ocr_jobs | 异步任务与导入流水线 | 中 |
| export_tasks | PDF/文档导出任务与文件索引 | 中 |

详细字段见 `DB_SCHEMA.md`。

---

## 缓存

Redis 用于任务队列、缓存、限流、幂等、JWT 黑名单/用户 nbf、权限缓存和部分可选运行时能力；不可用时按功能降级或返回结构化不可用错误。生产 Compose 独立运行 `redis:7-alpine`。

### 预留场景

- 任务队列与任务状态（含 outbox、重试、死信和 trace）
- Admin 权限、登录限流、幂等与统计缓存
- OCR/AI 任务状态与批次最新任务指针

---

## 文件存储

`STORAGE_BACKEND` 当前支持 `local`（默认）与 `cos`。业务通过 storage backend 抽象访问文件，不直接拼接物理路径。

- 用户上传原始文件：处理期间使用容器内 `/tmp/`，任务完成后清理
- 题目图片：`get_question_assets_storage()`，key 为 `static/question-assets/{question_id}/{uuid}.{ext}`；生产 Compose 挂载命名卷 `question_assets_data` 到 `/app/static/question-assets`
- 用户头像：`get_user_avatar_storage()`，命名空间为 `static/avatars/{user_id}/{uuid}.jpg`；旧 `static/formulas/avatars` 仅用于兼容清理
- 导出文件：`get_export_storage()` 管理 `export_tasks.file_key` 对应文件；生产可使用本地命名卷或 COS
- 题目图片删除前由 `AssetReferenceService` 检查引用；包括当前题目、导入记录，以及被试卷/练习/错题/复习记录引用的历史版本。未被持久记录引用的旧草稿版本不阻止删除。
- 引用扫描失败时保留文件；单次查询使用保存点隔离数据库异常，以免后续请求查询因事务中止而失败。PostgreSQL 版本快照的 `content`、`image_url`、`options` 为 JSON，筛选时统一转为 TEXT；不对 JSON 列去重，也不与空字符串合并。

生产 Compose 当前使用独立命名卷保存 PostgreSQL、Redis、题目图片、导出文件和备份数据；备份服务将 PostgreSQL 备份写入 `backup_data`。

---

## 归档

- 部署脚本在 `deploy/` 目录
- 历史开发阶段文档在 `docs/achieve/`
