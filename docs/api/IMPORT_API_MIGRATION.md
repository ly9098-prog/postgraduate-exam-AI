# 导入/审核 API 迁移指南

> 本文件记录本次 API Router 重构中所有变更的接口及其替代方案。

---

## 下线接口清单

### 导入上传

| 旧接口 | HTTP | 替代接口 | 当前行为 |
|--------|------|----------|----------|
| /api/v1/import/upload | POST | /api/v1/import/pipeline/upload 或 /api/admin/v1/imports/upload | 410 Gone |
| /api/v1/import/image/upload | POST | /api/v1/import/pipeline/upload 或 /api/admin/v1/imports/batch-image/upload | 410 Gone |

### App 侧审核（全部迁移至 Admin）

| 旧接口 | HTTP | 替代接口 |
|--------|------|----------|
| /api/v1/import/questions/{question_id} | PUT | /api/admin/v1/imports/questions/{import_id} |
| /api/v1/import/batches/{batch_id}/approve | POST | /api/admin/v1/imports/{batch_id}/approve |
| /api/v1/import/batches/{batch_id}/reject | POST | /api/admin/v1/imports/{batch_id}/reject |
| /api/v1/import/questions/{question_id}/fix | PUT | /api/admin/v1/imports/questions/{import_id} |
| /api/v1/import/review/publish | POST | /api/admin/v1/imports/{batch_id}/publish |
| /api/v1/import/review/approve-and-publish | POST | /api/admin/v1/imports/{batch_id}/approve + /api/admin/v1/imports/{batch_id}/publish |
| /api/v1/import/submit-review | POST | /api/admin/v1/imports (Admin 后台统一审核) |
| /api/v1/import/review-queue | GET | /api/admin/v1/imports/review-queue |

### AI 补全

| 旧接口 | HTTP | 替代接口 |
|--------|------|----------|
| /api/v1/ai-import/enrich/{import_id} | POST | /api/admin/v1/imports/{batch_id}/enrich |
| /api/v1/ai-import/enrich-batch/{batch_id} | POST | /api/admin/v1/imports/questions/batch-complete |
| /api/v1/ai-import/complete/{import_id} | POST | /api/admin/v1/imports/questions/{import_id}/complete |

### 非标准 Admin 前缀

| 旧路径 | 新路径 |
|--------|--------|
| /api/v1/admin/watermark-rules | /api/admin/v1/watermark-rules |

---

## 保留的正式接口

### App 侧导入

| method | path | 说明 |
|--------|------|------|
| POST | /api/v1/import/pipeline/upload | 统一导入入口（Excel/PDF/TXT/图片） |
| GET | /api/v1/import/pipelines/{pipeline_id} | 查询 pipeline 进度 |
| POST | /api/v1/import/pipelines/{pipeline_id}/resume | 恢复 pipeline |
| GET | /api/v1/import/template | 下载模板 |
| GET | /api/v1/import/batches | 批次列表 |
| GET | /api/v1/import/batches/{batch_id} | 批次详情 |
| POST | /api/v1/import/submit-review | 提交审核队列 |
| GET | /api/v1/import/review-queue | 获取审核队列 |
| GET | /api/v1/import/math-preview/{import_id} | 公式预览 |
| POST | /api/v1/ai-import/generate | AI 生成草稿题目 |
| GET | /api/v1/ai-import/logs | AI 调用日志 |

### Admin 侧导入/审核

全部路径 prefix: `/api/admin/v1/imports`

| method | path | 说明 |
|--------|------|------|
| POST | /upload | 上传文件（Excel/PDF/TXT/图片） |
| GET | /pipelines/{pipeline_id} | 查询 pipeline 进度 |
| POST | /pipelines/{pipeline_id}/resume | 恢复 pipeline |
| POST | /batch-image/upload | 批量图片上传 |
| GET | /batch-image/{job_id} | 批量图片任务进度 |
| GET | /review-queue | 审核队列 |
| GET | /questions/{import_id} | 审核题目详情 |
| PUT | /questions/{import_id} | 编辑审核题目 |
| POST | /questions/{import_id}/complete | AI 补全单题 |
| POST | /questions/{import_id}/approve | 通过单题 |
| POST | /questions/{import_id}/reject | 驳回单题 |
| POST | /questions/batch-complete | 批量 AI 补全 |
| POST | /{batch_id}/approve | 通过整批 |
| POST | /{batch_id}/reject | 驳回整批 |
| POST | /{batch_id}/publish | 发布整批 |
| POST | /{batch_id}/enrich | AI 丰富整批 |

---

## 兼容期策略

- 所有兼容代码已在 2026-07-04 批次中整体删除，不再保留 410 过渡接口
- 旧路径（`/api/v1/import/upload`、`/api/v1/admin/watermark-rules` 等）已完全从路由表中移除
- 前端若仍调用旧路径将收到 404，需确保已切换到新路径

---

## 相关链接

- [[docs/backend/API_SPEC.md|API_SPEC]] — App API 合约
- [[docs/admin/ADMIN_API_SPEC.md|ADMIN_API_SPEC]] — 管理 API 合约
- [[docs/architecture/API_ROUTER_STRUCTURE.md|API_ROUTER_STRUCTURE]] — 路由结构
- [[docs/architecture/OCR_FLOW.md|OCR_FLOW]] — OCR 导入流程
- [[docs/architecture/OCR_USAGE.md|OCR_USAGE]] — OCR 使用说明
