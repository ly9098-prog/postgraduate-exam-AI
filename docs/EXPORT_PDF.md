# 错题导出为试卷 PDF

## 功能入口

1. **错题本页面** → 选择/全选 → 底部悬浮胶囊 → **导出**按钮 → 导出设置页
2. **错题本页面** → 顶部操作栏 → **导出记录**按钮 → 导出记录列表页
3. **导出设置页面** → 底部固定操作栏 → **导出记录**入口

## 用户操作流程

1. 进入错题本管理模式（点击"选择"或长按错题）
2. 勾选要导出的错题（支持跨分页、跨筛选状态保持）
3. 点击底部"导出"按钮（或直接在顶部点击"导出记录"查看历史）
4. 在导出设置页配置:
   - 导出范围（全部/当前筛选/已选）
   - 文件格式（PDF 默认选中；Word 不可选，标记"即将支持"）
   - 试卷标题（可编辑，默认按学科生成）
   - 日期（默认当天，可编辑、可关闭）
   - 排序方式（6种）
   - 分组方式（5种）
   - 答案位置（不打印/紧跟题后/集中末尾）
   - 解析位置（不打印/紧跟题后/集中末尾）
   - 答题空间（紧凑/标准/宽松）
5. 确认题数后提交（0道禁止，1-100道允许，超过100道禁止）
6. 自动跳转到导出记录页，轮询任务状态
7. 完成后可预览、保存、分享、重新导出或删除
8. 失败后可重试

## 数据库迁移

```bash
# 开发环境
cd backend
alembic upgrade head

# 生产环境
ssh root@8.163.56.109 "cd /opt/2240ai-v2 && bash deploy/scripts/deploy.sh migrate"
```

迁移文件: `backend/alembic/versions/v10_export_tasks.py`

### 新增表

- **export_tasks**: 导出任务记录（状态、配置、文件信息、快照引用）
- **export_snapshots**: 导出快照（题目数据 + 配置的 JSON 快照）

### 关键索引

- `ix_export_tasks_user_status`: (user_id, status)
- `ix_export_tasks_status_created`: (status, created_at)
- `ix_export_tasks_expires_at`: expires_at（定时清理查询）
- `export_tasks.idempotency_key`: 唯一（幂等键）

## 新增配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EXPORT_POLL_INTERVAL_SEC` | 5 | 后台处理器轮询间隔 |
| `EXPORT_PROCESSING_TIMEOUT_SEC` | 900 | 单任务最大处理时间 |
| `EXPORT_MAX_CONCURRENT` | 1 | 同时处理的导出任务数 |
| `EXPORT_DIR` | `static/exports` | PDF 存储目录 |
| `PRODUCT_NAME` | `MemoGrad` | 试卷头部产品名称 |

## PDF 依赖

### Python 依赖

- `fpdf2>=2.7.0`: 纯 Python PDF 生成库，无需系统级依赖

### 系统依赖

生产环境及 Docker 需要安装中文字体:

```bash
# Debian / Ubuntu
apt-get install -y fonts-wqy-zenhei

# 或使用 noto cjk 字体
apt-get install -y fonts-noto-cjk
```

### 中文字体要求

- 字体文件路径: `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`
- 许可证: GPL-2.0 with font exception（文泉驿正黑）
- 如使用其他字体，修改 `backend/app/services/export/pdf_exporter.py` 中的 `_DEFAULT_FONT_PATH`
- 字体必须支持: 中文、数学符号、上下标、粗体/常规字重
- 开发环境已有 `wqy-zenhei` 字体可用

## 本地开发

```bash
# 启动后端
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 异步任务处理器随 scheduler 角色自动启动:
PROCESS_ROLE=scheduler uvicorn app.main:app --reload

# 运行测试
python3 -m pytest tests/test_export.py -v
```

## 异步任务

导出任务由后台 `ExportProcessor` 异步生成，通过数据库轮询领取任务。

### 启动方式

处理器在 `PROCESS_ROLE=scheduler` 或 `all` 时自动启动:
- `backend/app/main.py` → `_periodic_export_processor()`
- 轮询间隔: `EXPORT_POLL_INTERVAL_SEC`（默认 5 秒）
- 单任务超时: `EXPORT_PROCESSING_TIMEOUT_SEC`（默认 15 分钟）

### 任务领取机制

1. 原子条件更新: `WHERE status='pending' ORDER BY created_at LIMIT 1`
2. 同一任务不能被两个实例同时处理
3. 状态转换受 `ExportTaskStatus` 枚举约束
4. Zombie 恢复: 处理中超时的任务（超过 `EXPORT_PROCESSING_TIMEOUT_SEC` 无心跳）会被标记为失败

### 后续升级

当前实现基于数据库状态机（原子状态转换 + 心跳刷新 + Zombie 恢复）。后续可升级为:
- **Celery**: 成熟分布式任务队列
- **RQ**: 轻量 Redis 队列
- **Arq**: asyncio 原生 Redis 队列
- 核心接口 `process_task()` 和 ExportTask 模型无需变更

## 定时清理

过期文件定时清理随 scheduler 角色自动启动（每小时执行）:

1. 查找 `expires_at < now` 的已完成/失败/待处理任务
2. 删除对象存储/本地文件
3. 删除关联快照
4. 标记状态为 `expired`

## 对象存储配置

PDF 文件复用项目现有 `StorageBackend`:
- 本地存储: `static/exports/{task_id}/{filename}`
- COS: 通过 `COS_*` 环境变量配置
- 切换方式: `STORAGE_BACKEND=cos`

## 测试命令

```bash
# 导出功能单元测试
python3 -m pytest tests/test_export.py -v

# 现有错题相关测试（确保无回归）
python3 -m pytest tests/test_wrong_question_batch.py -v
python3 -m pytest tests/test_services/test_wrong_question_service.py -v
```

## 部署注意事项

1. 确保生产服务器安装了中文字体（`fonts-wqy-zenhei`）
2. 处理器只在 scheduler 角色中运行，普通 web 实例不启动
3. 多实例部署时使用 DB 层面的心跳检测（heartbeat_at 字段），无需 Redis
4. PDF 文件默认存储在本地 `static/exports/`，通过鉴权接口 `/api/v1/exports/{id}/file` 提供下载。**不要**配置公开的 Nginx 静态文件路由，否则将导致越权访问。
5. 如使用 COS，需配置 `COS_ALLOW_LOCAL_FALLBACK` 和 `COS_*` 环境变量
6. 生产环境建议设置 `PROCESS_ROLE` 分开 web 和 scheduler

## 文件有效期

- PDF 文件从 `completed_at` 起保留 7 天
- 过期后状态变为 `expired`
- 过期文件不可预览、保存或分享
- 可通过"重新导出"基于原快照和配置创建新任务
- 新任务重新计算 7 天有效期

## 当前采用轮询

- 导出记录页面每 2-3 秒查询未完成任务
- 页面隐藏或离开后停止轮询
- 所有任务进入终态后停止轮询
- 防止重复定时器和页面销毁后的状态更新
- 状态刷新层已封装在 `miniprogram/services/export.js` 的 `pollTaskStatus()` 中

## 后续可升级

- WebSocket 或 SSE 实时推送
- 订阅消息通知
- 导出完成后推送更高效的状态通知

## DOCX 尚未实现

- 导出器接口（`Exporter` ABC）已预留
- `DocxExporter` 可实现 `Exporter` 接口
- Word 选项在前端显示但禁用，标记"即将支持"
