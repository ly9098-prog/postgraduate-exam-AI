# 本地→云端增量同步

## 概述

本地开发环境（i7 + RTX3060）执行大规模 OCR 导入后，通过增量同步将 `questions`、`tags` 以及题目知识点关联（`question_knowledge_points`）推送到云端生产服务器（2C2G PostgreSQL）。

设计原则：
- **单向同步**：仅本地→云端，不反向拉取
- **永不删除**：云端有但本地没有的记录不会被删除
- **冲突安全**：云端已有更新修改时跳过，记录冲突明细
- **知识点走关联表**：题目知识点以 `question_knowledge_points` 关联表为唯一事实源，`questions.knowledge_points` JSON 列已移除；同步时导出侧用 `load_question_kps()` 批量加载展示名列表，云端合并侧用 `sync_question_knowledge_points(source="sync", replace=True)` 重建映射

---

## 同步机制

每条记录通过 `sync_uuid`（UUID v4，跨数据库唯一标识）匹配身份，用 `updated_at` 时间戳判断新旧：

| 情况 | 动作 |
|------|------|
| sync_uuid 不存在于云端 | INSERT（新增） |
| 存在，本地 updated_at 更新 | UPDATE（覆盖） |
| 存在，云端 updated_at 更新或相同 | SKIP（记录冲突） |
| 云端有但本地没有 | 不处理 |

---

## 数据库字段

### questions 表新增

| 字段 | 类型 | 说明 |
|------|------|------|
| sync_uuid | VARCHAR(36), UNIQUE, INDEX | 跨库唯一标识，新记录自动生成 |
| sync_version | INTEGER, DEFAULT 0 | 版本号（预留冲突检测） |

> `questions.knowledge_points` JSON 列已移除，题目知识点改经 `question_knowledge_points` 关联表同步：
> - 导出：`scripts/sync_to_cloud.py` 通过 `load_question_kps()` 一次查询批量加载展示名列表写入 package
> - 云端合并：`sync_merge_service.merge_sync_package()` 在 flush 后对每道题调用 `sync_question_knowledge_points(source="sync", replace=True)`

### tags 表新增

| 字段 | 类型 | 说明 |
|------|------|------|
| sync_uuid | VARCHAR(36), UNIQUE, INDEX | 跨库唯一标识，新记录自动生成 |

> tags.subject 已改为 `subject_id`（FK → subjects.id）。

Python-level `default=lambda: str(uuid4())` 确保通过 ORM 创建的新记录自动获取 UUID。

---

## 文件清单

| 文件 | 用途 |
|------|------|
| `app/models/question.py` | sync_uuid + sync_version 字段 |
| `app/models/tag.py` | sync_uuid 字段（subject_id 外键） |
| `app/features/sync_merge_service.py` | 核心合并逻辑（批量预加载、时间戳比较、冲突记录、知识点 replace 重建） |
| `app/services/knowledge_point_service.py` | 知识点关联：`load_question_kps`（导出）/ `sync_question_knowledge_points`（云端重建） |
| `app/api/v1/sync.py` | POST /api/v1/sync/import 端点 |
| `app/schemas/sync.py` | Pydantic 请求/响应 schema |
| `app/core/database.py` | `_ensure_sync_columns()` 本地 SQLite 自动补列 |
| `app/services/admin_bootstrap_service.py` | sync:write 权限种子 |
| `scripts/sync_to_cloud.py` | 本地导出+上传 CLI |
| `scripts/backfill_sync_uuid.py` | 已有数据回填 UUID |
| `alembic/versions/m4c5d6e7f8g9_add_sync_columns.py` | PostgreSQL 迁移 |

---

## API 端点

### POST /api/v1/sync/import

需要 Admin JWT + `sync:write` 权限。

**请求体** (SyncPackage)：

```json
{
  "version": 1,
  "exported_at": "2026-06-04T12:00:00+00:00",
  "source_env": "local",
  "questions": [{
    "sync_uuid": "...",
    "sync_version": 0,
    "subject_id": 2,
    "question_hash": "md5...",
    "knowledge_points": ["导数", "求导公式"],
    ...
  }],
  "tags": [...],
  "manifest": {
    "question_count": 150,
    "tag_count": 20,
    "checksum": "sha256hex..."
  }
}
```

**限制**：
- 单次最多 5000 道题目
- 单次最多 1000 个标签
- manifest 中的 count 必须与实际数组长度一致

**响应** (SyncReportResponse)：

```json
{
  "success": true,
  "questions_new": 120,
  "questions_updated": 25,
  "questions_skipped": 5,
  "questions_conflict": 2,
  "questions_deduped": 3,
  "tags_new": 15,
  "tags_skipped": 5,
  "conflicts": [
    {"sync_uuid": "...", "reason": "cloud_newer"}
  ],
  "errors": []
}
```

> `questions_deduped`：本地重新导入的重复题（相同 `(subject_id, question_hash)` 但不同 sync_uuid）被跳过计数。

---

## 使用步骤

### 1. 回填已有数据的 sync_uuid

首次使用前，为已有的 questions 和 tags 生成 UUID：

```bash
cd backend
python3 -m scripts.backfill_sync_uuid --dry-run    # 预览
python3 -m scripts.backfill_sync_uuid --apply       # 执行
```

支持 `--batch-size 500` 控制批次大小。

### 2. 云端执行数据库迁移

```bash
alembic upgrade head
```

迁移文件 `m4c5d6e7f8g9_add_sync_columns.py` 添加 sync_uuid 和 sync_version 列。

### 3. 云端确保权限种子

重启云端服务或手动触发 bootstrap，确保 `sync:write` 权限已创建并分配给管理员角色。

### 4. 导出并上传

```bash
# 全量导出（首次）
python3 -m scripts.sync_to_cloud \
  --api-url https://your-server.com \
  --token <admin_jwt> \
  --full

# 增量导出（后续，自动读取 .last_sync 时间戳）
python3 -m scripts.sync_to_cloud \
  --api-url https://your-server.com \
  --token <admin_jwt>

# 指定时间起点
python3 -m scripts.sync_to_cloud \
  --api-url https://your-server.com \
  --token <admin_jwt> \
  --since 2026-06-01T00:00:00

# 仅导出 JSON 不上传（调试用）
python3 -m scripts.sync_to_cloud --dry-run
```

成功上传后，脚本自动保存 `.last_sync` 时间戳，下次运行自动增量。

---

## 本地开发环境

本地 SQLite 开发环境无需手动跑 alembic。`init_db()` 启动时自动调用 `_ensure_sync_columns()` 补齐 sync_uuid 和 sync_version 列。新创建的题目和标签自动获得 sync_uuid。

---

## 安全设计

- API 端点受 Admin RBAC 保护，需要 `sync:write` 权限
- 审核生命周期（2026-10-31 安全审计修复）：`review_status`/`is_active` 不再属于普通同步字段。仅同时持有 `question:review` 的调用方才会应用包内生命周期字段，且遵循 `_REVIEW_ALLOWED_TRANSITIONS`（仅 re_pending→approved/rejected、rejected→approved），激活仅限 approved；仅 `sync:write` 时新建题目一律落为 `re_pending` + `is_active=false`，已有题目保持原状态。每次成功提交写入 `sync.import` 审计记录（severity=important）。
- JWT token 通过 `--token` 传入，不持久化
- IntegrityError 捕获防止并发/重试导致的重复插入
- Payload 大小限制防止 2C2G 服务器 OOM

---

## 验证清单

- [x] 本地 `init_db()` 自动补齐 sync 列
- [x] 新建题目/标签自动获得 sync_uuid
- [x] `--dry-run` 导出 JSON 包内容正确
- [x] POST `/api/v1/sync/import` 返回 SyncReport
- [x] 重复提交同包 → 全部 skipped，无重复插入
- [x] 修改本地题目后重新同步 → 对应题目被 UPDATE
- [x] 云端更新时间更新的记录 → SKIP + 冲突报告
- [x] 题目知识点经关联表同步：导出 `load_question_kps`、云端 `sync_question_knowledge_points(source="sync", replace=True)` 重建映射（`sync_to_cloud.py` + `knowledge_point_service.py`）
- [x] 现有测试全部通过（554 passed）

---

## 相关链接

- [[docs/backend/API_SPEC.md|API_SPEC]] — App API 合约
- [[docs/backend/DB_SCHEMA.md|DB_SCHEMA]] — App 数据模型
- [[docs/backend/STORAGE_DESIGN.md|STORAGE_DESIGN]] — 存储设计
- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
