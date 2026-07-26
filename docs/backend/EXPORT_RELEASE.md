# 错题导出功能 — 发布与回滚手册

> 适用范围：生产服务器 8.163.56.109，部署于 `/opt/2240ai-v2`

---

## 发布检查清单

### 1. 前置条件

- [ ] 数据库迁移已执行（`deploy.sh migrate`）
- [ ] API 容器已部署（`deploy.sh update`）
- [ ] scheduler 容器已部署
- [ ] Nginx 已更新（不暴露 `static/exports/`）
- [ ] Redis 运行正常
- [ ] 存储目录存在（`static/exports/`）
- [ ] 配置文件已更新（`.env` 含 EXPORT_* 配置）

### 2. 配置文件（`.env` 或环境变量）

```bash
# 按安全默认值配置
EXPORT_FEATURE_ENABLED=true
EXPORT_DOCX_ENABLED=true
EXPORT_WEBSOCKET_ENABLED=true
EXPORT_ALLOW_ALL_USERS=false    # 正式开放前改为 true
EXPORT_ALLOWED_USER_IDS=        # 内部测试用逗号分隔用户 ID
# 以下使用默认值即可：
# EXPORT_DIR=static/exports
# EXPORT_POLL_INTERVAL_SEC=5
# EXPORT_PROCESSING_TIMEOUT_SEC=900
# EXPORT_MAX_CONCURRENT=1
```

### 3. 发布步骤

```
Step 1: 设置 EXPORT_ALLOW_ALL_USERS=false，EXPORT_ALLOWED_USER_IDS=内部账号
         → 部署，用内部账号测试 PDF/DOCX/WebSocket 端到端

Step 2: 设置 EXPORT_ALLOW_ALL_USERS=true
         → 部署，重新获取 /api/v1/exports/capabilities 确认

Step 3: 验证真实用户：
   - 小程序错题本显示"导出"按钮
   - 导出设置页默认 PDF
   - 100 道以内可导出
   - 下载文件可打开
   - 导出记录可查看
   - 文件过期后不可下载
```

### 4. 发布后验证

| 检查项 | 方法 |
|---|---|
| 能力接口 | `GET /api/v1/exports/capabilities` → export_enabled=true |
| 预览计数 | `POST /api/v1/exports/preview-count` → 返回数量 |
| 创建任务 | `POST /api/v1/exports` → 返回 pending 任务 |
| 状态轮询 | 15s 后任务应为 completed |
| 文件下载 | 首次接口返回 stream，COS 返回短时签名 URL |
| 删除 | `DELETE /api/v1/exports/{id}` → 删除后不可下载 |

---

## 回滚步骤

### 优先级（从上到下，先止损、后根治）

```
P0 — 关闭 EXPORT_FEATURE_ENABLED=false     → 立即阻止新建
P1 — 关闭 EXPORT_DOCX_ENABLED=false        → PDF 继续可用
P1 — 关闭 EXPORT_WEBSOCKET_ENABLED=false   → 回落轮询
P2 — 回滚小程序代码
P3 — 回滚后端代码
P4 — 数据库表保留，不提交流程破坏性变更
```

### 关闭总开关

```bash
# 1. 设置环境变量
EXPORT_FEATURE_ENABLED=false

# 2. 重启 API 容器
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh update"

# 3. 验证
curl https://xzshub.top/api/v1/exports/capabilities
# → export_enabled=false
```

关闭总开关后的行为：

- 新建任务被拒绝（返回结构化错误码 `user_not_allowed`）
- 已有记录可查看
- 已完成且未过期的文件仍可下载
- pending/processing 任务继续处理完毕
- 错题本其他功能不受影响

### 恢复开放

```bash
# 1. 设置 EXPORT_FEATURE_ENABLED=true
# 2. 部署
# 3. 验证能力接口
```

---

## 配置含义速查

| 配置 | 默认 | 说明 |
|---|---|---|
| `EXPORT_FEATURE_ENABLED` | true | 总开关。false 时全部用户不能新建 |
| `EXPORT_DOCX_ENABLED` | true | Word 格式独立开关 |
| `EXPORT_WEBSOCKET_ENABLED` | true | 实时推送开关；关闭后小程序回落轮询 |
| `EXPORT_ALLOW_ALL_USERS` | false | true=全部用户可导出；false=仅白名单 |
| `EXPORT_ALLOWED_USER_IDS` | "" | 白名单，逗号分隔用户 ID |
| `EXPORT_DIR` | static/exports | 本地文件存储目录 |
| `EXPORT_POLL_INTERVAL_SEC` | 5 | processor 轮询间隔 |
| `EXPORT_PROCESSING_TIMEOUT_SEC` | 900 | 单任务超时（含生成→上传） |
| `EXPORT_MAX_CONCURRENT` | 1 | 进程级并发数 |

---

## 能力判断规则

### 新建权限（preview-count / create / retry / re-export / WS）

受以下条件控制：
- `EXPORT_FEATURE_ENABLED=true`
- （白名单判断）`EXPORT_ALLOW_ALL_USERS=true` **或** 用户 ID 在 `EXPORT_ALLOWED_USER_IDS` 中
- DOCX 额外检查 `EXPORT_DOCX_ENABLED=true`
- 并发不超过 `_MAX_PER_USER=2`

### 已有资源访问（list / detail / download / delete）

受以下条件控制：
- 任务属于当前用户
- 未删除
- （下载时）文件未过期且文件存在

当用户被移出白名单或总开关关闭时：
- 禁止新建任务
- 已有记录仍可查看
- 已完成且有效的文件仍可下载
- 已在 pending/processing 的任务继续处理
- 不自动删除文件

---

## 异常处理

| 错误码 | HTTP 状态 | 说明 | 用户提示 |
|---|---|---|---|
| `feature_disabled` | 403 | 总开关关闭 | "导出功能暂未开放" |
| `user_not_allowed` | 403 | 用户不在白名单 | "导出功能暂未开放" |
| `docx_disabled` | 403 | Word 已关闭 | "Word 导出功能已关闭" |
| `too_many_concurrent` | 429 | 超过并发上限 | "请等待当前任务完成" |
| `too_many_questions` | 400 | 超过 100 道 | "单次最多导出 100 道" |
| `task_not_found` | 404 | 任务不存在/不属于当前用户 | "导出任务不存在" |
| `file_expired` | 400 | 文件超过 7 天 | "文件已过期" |
| `file_not_found` | 500 | 文件已删除 | "文件不存在，请重新导出" |

---

## 日志事件

结构化日志事件名（通过 `logger.info("event_name", extra={...})` 发出）：

| 事件 | 位置 | 关键字段 |
|---|---|---|
| `export_task_created` | exports.py | task_id, user_id, format, range_type |
| `export_task_started` | processor.py | task_id, user_id |
| `export_task_completed` | processor.py | task_id, duration, question_count, file_size |
| `export_task_failed` | processor.py | task_id, error_message |
| `export_task_timed_out` | processor.py | task_id, timeout_sec |
| `export_task_retried` | exports.py | task_id, source_task_id |
| `export_task_reexported` | exports.py | task_id, source_task_id |
| `export_task_deleted` | exports.py | task_id, format |
| `export_cleanup_completed` | cleanup.py | tasks_expired, files_deleted |
| `export_websocket_connected` | exports.py | user_id |
| `export_websocket_failed` | exports.py | user_id, reason |
| `export_preview_count` | exports.py | user_id, range_type, count |
| `export_capability_checked` | capability.py | user_id, allowed |

日志不包含：题目全文、答案、JWT、openid、签名 URL、COS key。
