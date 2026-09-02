# API Router 架构说明

> 当前 API Router 三层结构。最后核对：2026-09-02（Codebase Memory 索引含 326 个 Route 节点）。

---

## 目标架构

```
app/main.py
  └── include_router(api_router)
        └── app/api/router.py
              ├── include_router(public_api_router)
              │     └── app/api/v1/router.py
              │           ├── auth_router
              │           ├── questions_router
              │           ├── practice_router
              │           ├── wrong_questions_router
              │           ├── ai_router
              │           ├── rag_router
              │           ├── imports_router
              │           ├── behavior_router
              │           ├── review_router
              │           ├── stats_router
              │           ├── knowledge_points_router
              │           ├── ai_import_router
              │           ├── cache_router
              │           ├── health_router
              │           ├── pomodoro_router
              │           ├── sync_router
              │           ├── knowledge_mastery_router
              │           ├── knowledge_path_router
              │           ├── study_report_router
              │           ├── adaptive_learning_router
              │           ├── exports_router
              │           └── formulas_router
              │
              ├── include_router(admin_api_router)
              │     └── app/api/admin/router.py
              │           ├── admin_auth_router
              │           ├── admin_ai_settings_router
              │           ├── admin_app_users_router
              │           ├── admin_audit_logs_router
              │           ├── admin_dashboard_router
              │           ├── admin_health_router
              │           ├── admin_imports_router
              │           ├── admin_questions_router
              │           ├── admin_rbac_router
              │           ├── admin_subjects_router
              │           ├── admin_users_router
              │           ├── admin_watermark_rules_router
              │           ├── admin_ai_config_router
              │           ├── admin_vector_config_router
              │           ├── admin_system_health_router
              │           ├── admin_knowledge_router
              │           ├── admin_recommendation_router
              │           ├── admin_formulas_router
              │           └── admin_metadata_router
              │
              └── include_router(ocr_worker_router)
                    └── app/api/internal/ocr_worker.py
```

---

## 三层边界原则

### 1. API Router 层 (app/api/)

**职责：** 鉴权、参数解析、调用 service、返回 response。

**不应做的：**
- 执行业务编排逻辑
- 直接操作数据库（除简单查询外）
- 互相 import 业务函数

**允许的 import 目标：**
- `app.services.*`
- `app.features.*`
- `app.schemas.*`
- `app.models.*`
- `app.core.*`

### 2. Service 层 (app/services/)

**职责：** 业务流程编排、公共逻辑抽离。

**不应做的：**
- 依赖 FastAPI HTTP 对象（Request, UploadFile, Depends, Response）
- 返回 HTTP Response 对象

**参数规范：**
- 接收普通 Python 类型（str, bytes, int, dict, DTO）
- 文件内容由 Router 读取后传入 bytes

### 3. Features 层 (app/features/)

**职责：** 领域逻辑、AI 管线、OCR 处理。

---

## 关键变更

### Service 抽离

`app/services/import_pipeline_service.py` 新增，包含以下函数：

| 函数 | 原先位置 | 说明 |
|------|----------|------|
| `start_import_pipeline()` | app.api.v1.imports | 统一导入核心逻辑 |
| `get_pipeline_status()` | app.api.v1.imports | 查询 pipeline 状态 |
| `_run_image_pipeline_with_db()` | app.api.v1.imports | 图片后台任务 |
| `_run_pipeline_with_db()` | app.api.v1.imports | 文件后台任务 |
| 辅助函数 | app.api.v1.imports | 常量、校验、诊断 |
| `_get_image_pipeline_status()` | app.api.v1.imports | 图片 pipeline 状态查询 |

### 交叉引用消除

- `admin_imports.py` 不再 `from app.api.v1.imports import *`
- 所有共享逻辑通过 `app.services.import_pipeline_service` 调用

### 废弃接口处理

旧接口统一返回 410 Gone，`include_in_schema=False`：
- `POST /api/v1/import/upload` → 410
- `POST /api/v1/import/image/upload` → 410
- App 侧审核接口（PUT/POST 共 8 个）→ 410（含 submit-review、review-queue）
- AI Import 丰富/补全（3 个）→ 410

### Admin 前缀统一

- `/api/v1/admin/watermark-rules` → `/api/admin/v1/watermark-rules`
- 旧路径保留为 410 Gone 过渡

---

## 路由配额

| 分类 | 数量 |
|------|------|
| Route 节点（索引快照） | 326 |
| App (public) 路由 | 以运行时 OpenAPI 为准 |
| Admin 路由 | 以运行时 OpenAPI 为准 |
| Legacy 410 路由 | ~10 |
| 健康检查/文档 | 5 |
