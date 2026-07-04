# API Router 审计报告

> 生成时间：2026-07-04
> 范围：导入、审核、AI 补全相关路由

---

## 审计方法

使用 `python3 -c "from app.main import app; ..."` 扫描 FastAPI 路由表，结合源代码逐条核查。

---

## 重点路由清单

### 导入上传入口（旧状态）

| method | path | 来源文件 | 状态 | 处理方案 |
|--------|------|----------|------|----------|
| POST | /api/v1/import/upload | imports.py | 废弃（曾执行真实逻辑） | → 410 Gone |
| POST | /api/v1/import/image/upload | imports.py | 废弃（曾执行真实逻辑） | → 410 Gone |
| POST | /api/v1/import/pipeline/upload | imports.py | **正式（App 侧唯一入口）** | 保留 |
| POST | /api/admin/v1/imports/upload | admin_imports.py | **正式（Admin 侧入口）** | 保留 |
| POST | /api/admin/v1/imports/batch-image/upload | admin_imports.py | **正式（批量图片）** | 保留 |

### Pipeline 状态/恢复

| method | path | 来源文件 | 状态 |
|--------|------|----------|------|
| GET | /api/v1/import/pipelines/{pipeline_id} | imports.py | 保留（App） |
| POST | /api/v1/import/pipelines/{pipeline_id}/resume | imports.py | 保留（App） |
| GET | /api/admin/v1/imports/pipelines/{pipeline_id} | admin_imports.py | 保留（Admin） |
| POST | /api/admin/v1/imports/pipelines/{pipeline_id}/resume | admin_imports.py | 保留（Admin） |

### 审核接口

| method | path | 来源文件 | 旧状态 | 处理方案 |
|--------|------|----------|--------|----------|
| GET | /api/v1/import/review-queue | imports.py | 正常执行 | → 410 Gone（审核已归 Admin） |
| POST | /api/v1/import/submit-review | imports.py | 正常执行 | → 410 Gone（审核已归 Admin） |
| PUT | /api/v1/import/questions/{question_id} | imports.py | 403 占位 | → 410 Gone |
| POST | /api/v1/import/batches/{batch_id}/approve | imports.py | 403 占位 | → 410 Gone |
| POST | /api/v1/import/batches/{batch_id}/reject | imports.py | 403 占位 | → 410 Gone |
| PUT | /api/v1/import/questions/{question_id}/fix | imports.py | 403 占位 | → 410 Gone |
| POST | /api/v1/import/review/publish | imports.py | 403 占位 | → 410 Gone |
| POST | /api/v1/import/review/approve-and-publish | imports.py | 403 占位 | → 410 Gone |

### Admin 审核接口（全部保留）

| method | path | 来源文件 |
|--------|------|----------|
| GET | /api/admin/v1/imports/review-queue | admin_imports.py |
| GET | /api/admin/v1/imports/questions/{import_id} | admin_imports.py |
| PUT | /api/admin/v1/imports/questions/{import_id} | admin_imports.py |
| POST | /api/admin/v1/imports/questions/{import_id}/complete | admin_imports.py |
| POST | /api/admin/v1/imports/questions/{import_id}/approve | admin_imports.py |
| POST | /api/admin/v1/imports/questions/{import_id}/reject | admin_imports.py |
| POST | /api/admin/v1/imports/questions/batch-complete | admin_imports.py |
| POST | /api/admin/v1/imports/{batch_id}/approve | admin_imports.py |
| POST | /api/admin/v1/imports/{batch_id}/reject | admin_imports.py |
| POST | /api/admin/v1/imports/{batch_id}/publish | admin_imports.py |
| POST | /api/admin/v1/imports/{batch_id}/enrich | admin_imports.py |
| POST | /api/admin/v1/imports/{batch_id}/approve-low-risk | admin_imports.py |

### AI Import 接口

| method | path | 来源文件 | 旧状态 | 处理方案 |
|--------|------|----------|--------|----------|
| POST | /api/v1/ai-import/enrich/{import_id} | ai_import.py | 403 占位 | → 410 Gone |
| POST | /api/v1/ai-import/enrich-batch/{batch_id} | ai_import.py | 403 占位 | → 410 Gone |
| POST | /api/v1/ai-import/complete/{import_id} | ai_import.py | 403 占位 | → 410 Gone |
| POST | /api/v1/ai-import/generate | ai_import.py | 正常执行 | 保留 |
| GET | /api/v1/ai-import/logs | ai_import.py | 正常执行 | 保留 |

### 非标准 Admin 前缀

| method | path | 旧前缀 | 处理方案 |
|--------|------|--------|----------|
| GET | /api/v1/admin/watermark-rules | /api/v1/admin/ | → `/api/admin/v1/watermark-rules` |
| POST | /api/v1/admin/watermark-rules | /api/v1/admin/ | → `/api/admin/v1/watermark-rules` |
| PUT | /api/v1/admin/watermark-rules/{rule_id} | /api/v1/admin/ | → `/api/admin/v1/watermark-rules/{rule_id}` |
| DELETE | /api/v1/admin/watermark-rules/{rule_id} | /api/v1/admin/ | → `/api/admin/v1/watermark-rules/{rule_id}` |

### 结构性问题

| 问题 | 严重程度 | 是否修复 |
|------|----------|----------|
| admin_imports.py import app.api.v1.imports 业务函数 | 高（跨层引用） | **已修复** |
| 多条等价上传入口并行 | 高（入口不唯一） | **已修复**（旧入口已删除） |
| 废弃审核接口在 OpenAPI 中暴露 | 中 | **已修复** |
| main.py 直接 include 30+ Router | 中（维护负担） | **已修复**（聚合 Router） |
| /api/v1/admin/ 非标准前缀 | 低 | **已修复** |
