# Admin 导入与审核流迁移方案

## 任务背景

当前题目导入的重流程已从小程序 `/api/v1/import` 迁移到 Admin 后台主链路，小程序仅保留拍照录题、单张图片导入和少量题目导入。所有导入结果必须先进入 `question_imports` 待审核，由后台管理员审核后发布到正式题库。

## 当前状态

- 迁移主体已完成。
- Admin 后台导入 / 进度 / 待审核 / 发布相关 API 已补齐。
- Admin 前端导入任务页、导入记录页、待审核页 / 题目列表页已接入。
- 小程序导入流已简化为轻量读入链路。
- App / 小程序管理型写入接口已收紧或禁止，模板下载仍保留给已认证 App 用户。
- 已补充导入边界与写入边界测试。
- 当前剩余事项：
  - Admin 浏览器端上传、进度轮询、待审核、发布全流程手工 UI 走查验证。
  - Admin 审核阶段补齐单题 AI 补全能力，复用现有 `question_pipeline.complete_import`，补全后仍需管理员人工复核、保存或通过。

## 核心原则

1. 不新增 OCR 引擎。
2. 不复制 PDF/OCR/拆题/发布业务逻辑。
3. 不做书籍类 PDF 优化。
4. 不增加复杂 AI 功能。
5. 尽量不改数据库结构。
6. 复用现有导入、OCR、审核、发布服务。

需要复用的核心模块：

- `backend/app/features/pipeline_orchestrator.py`
- `backend/app/features/review_service.py`
- `backend/app/features/question_publish_service.py`
- `backend/app/services/ocr_service.py`
- `backend/app/services/import_service.py`
- `backend/app/services/admin_import_service.py`

## 一、后端方案

### 1. Admin 成为导入/审核/发布主入口

关键文件：

- `backend/app/api/v1/admin_imports.py`
- `backend/app/api/v1/imports.py`
- `backend/app/services/admin_import_service.py`
- `backend/app/schemas/admin_imports.py`

### 2. 共享上传启动逻辑

从现有小程序端 `/api/v1/import/pipeline/upload` 中抽取可复用逻辑，供 Admin 与小程序共同调用。

共享逻辑负责：

- 校验文件名、文件类型、文件大小。
- 校验 PDF 页码范围。
- 判断来源类型：PDF、TXT、Excel、图片。
- 创建 pipeline id。
- 初始化 pipeline 状态。
- 调用已有后台任务：
  - `run_pipeline_background`
  - `run_excel_pipeline_background`
  - 图片 OCR 分支
- 返回 `PipelineUploadResponse`。

共享逻辑不得重新实现 OCR、拆题、标准化或发布。

`created_by` 建议区分来源：

```text
admin:{admin_id}
user:{user_id}
```

### 3. 新增 Admin import API

在 `backend/app/api/v1/admin_imports.py` 增加：

| 方法 | 路径 | 作用 |
|---|---|---|
| `POST` | `/api/admin/v1/imports/upload` | Admin 上传 PDF/图片/TXT/Excel |
| `GET` | `/api/admin/v1/imports/pipelines/{pipeline_id}` | 查看导入任务进度 |
| `GET` | `/api/admin/v1/imports/review-queue` | 查看待审核导入题目 |
| `PUT` | `/api/admin/v1/imports/questions/{import_id}` | 编辑待审核题目 |
| `POST` | `/api/admin/v1/imports/questions/{import_id}/complete` | Admin 单题 AI 补全暂存题目 |
| `POST` | `/api/admin/v1/imports/questions/{import_id}/approve` | 单题通过 |
| `POST` | `/api/admin/v1/imports/questions/{import_id}/reject` | 单题驳回 |
| `POST` | `/api/admin/v1/imports/{batch_id}/approve` | 批量通过 |
| `POST` | `/api/admin/v1/imports/{batch_id}/reject` | 批量驳回 |
| `POST` | `/api/admin/v1/imports/{batch_id}/publish` | 发布已通过题目 |
| `DELETE` | `/api/admin/v1/imports/{batch_id}` | 删除未发布导入批次 |
| `DELETE` | `/api/admin/v1/imports/questions/{import_id}` | 删除未发布导入题目 |

权限建议：

- 读取类接口：`import:read`
- 上传、编辑、删除类接口：`import:write`
- 审核类接口：`question:review` 或 `import:write`
- 发布类接口：优先沿用现有后台权限体系，至少不能对小程序用户开放。

### 4. 保留已有 Admin import 能力

继续保留：

- `GET /api/admin/v1/imports`
- `GET /api/admin/v1/imports/{batch_id}`
- `POST /api/admin/v1/imports/{batch_id}/enrich`
- `GET /api/admin/v1/imports/{batch_id}/status`

### 5. 小程序端接口降权

保留轻量上传与状态查询：

- `POST /api/v1/import/pipeline/upload`
- `GET /api/v1/import/pipelines/{pipeline_id}`

小程序端不再开放审核和发布能力，以下接口需要停止前端调用，并在后端返回 403 或迁移到 Admin：

- `POST /api/v1/import/batches/{batch_id}/approve`
- `POST /api/v1/import/batches/{batch_id}/reject`
- `POST /api/v1/import/review/publish`
- `POST /api/v1/import/review/approve-and-publish`

批次详情如需兼容旧页面，可暂时只读，但不能允许小程序用户通过、驳回或发布。

## 二、Admin 前端方案

关键文件：

- `admin-frontend/src/lib/routes.ts`
- `admin-frontend/src/components/layout/sidebar.tsx`
- `admin-frontend/src/lib/permissions/permissions.ts`
- `admin-frontend/src/lib/api/client.ts`
- `admin-frontend/src/lib/api/types.ts`
- `admin-frontend/src/app/(admin)/imports/...`

### 1. 权限与 API Client

补齐前端权限类型：

```text
import:read
import:write
```

修改 Admin API client：

- 当 `body instanceof FormData` 时，不设置 `Content-Type: application/json`。
- 文件上传由浏览器自动设置 multipart boundary。

新增前端类型：

- Admin import batch item。
- Admin import question item。
- Pipeline upload response。
- Pipeline status response。
- Review action response。
- Publish response。
- Delete response。

### 2. 菜单结构

新增 Admin 菜单：

```text
题目导入管理
├── 题目列表
├── 导入任务
├── 待审核题目
└── 导入记录
```

MVP 可先用平铺路由：

| 菜单 | 路由 |
|---|---|
| 题目列表 | `/imports/questions` |
| 导入任务 | `/imports/tasks` |
| 待审核题目 | `/imports/review` |
| 导入记录 | `/imports/history` |

### 3. 导入任务页面

新增：

- `admin-frontend/src/app/(admin)/imports/tasks/page.tsx`

功能：

- 上传 PDF、普通图片、文本 PDF/TXT，Excel 如现有后端支持可保留。
- 设置科目、导入模式、页码范围、是否 AI 修复。
- 调用 `POST /api/admin/v1/imports/upload`。
- 轮询 `GET /api/admin/v1/imports/pipelines/{pipeline_id}`。
- 显示导入进度、识别进度、成功题数、失败题数、错误日志、当前阶段。
- 完成后跳转导入记录或待审核题目。
- “重新导入” MVP 为重新选择文件上传，不做服务端无源文件 reimport。

### 4. 导入记录页面

新增：

- `admin-frontend/src/app/(admin)/imports/history/page.tsx`

功能：

- 调用 `GET /api/admin/v1/imports`。
- 显示 batch_id、source_file、source_type、total/pending/approved/rejected/published、创建/更新时间。
- 支持查看结果、发布已通过题目、删除未发布批次。

### 5. 待审核题目与题目列表

新增或包装：

- `admin-frontend/src/app/(admin)/imports/review/page.tsx`
- `admin-frontend/src/app/(admin)/imports/questions/page.tsx`

功能：

- 查看题干、选项、答案、解析、OCR 原文/原始数据。
- 查看重复状态、AI/OCR metadata。
- 支持单题通过、驳回、编辑后通过。
- 支持单题 AI 补全：复用后端暂存题目补全能力，只补齐 `question_imports`，不直接发布正式题库。
- 展示 `ai_metadata.complete_suggestion` 等 AI 建议；AI 建议答案不得自动入库，需管理员应用建议、保存并通过后才可发布。
- 支持批量通过、批量驳回。
- 仅允许发布 `approved` 题目。

## 三、小程序方案

关键文件：

- `miniprogram/pages/import/import.js`
- `miniprogram/pages/import/import.wxml`
- `miniprogram/pages/import/import.wxss`
- `miniprogram/pages/import-batch/import-batch.js`
- `miniprogram/pages/import-batch/import-batch.wxml`

### 保留

- 拍照录题。
- 单张图片导入。
- 少量题目导入。
- 基础 OCR 上传和状态展示。

### 删除或禁用

- 复杂导入配置。
- 批量审核。
- 批量通过/驳回。
- 题目发布。
- 管理员审核相关入口。
- AI enrich/complete 等管理型操作。

### 新小程序流程

```text
上传
↓
OCR/解析
↓
进入 question_imports 待审核
↓
提示：已提交审核，管理员审核后会加入题库
```

小程序用户不可直接发布题目。

## 四、数据库策略

MVP 不新增表、不改 schema。

复用现有表：

- `question_imports`
  - 存储导入 staging 数据。
  - 支持 `pending`、`approved`、`rejected`、`published` 状态。
  - 存储 parsed content/options/answer/analysis、OCR/AI metadata、duplicate 信息。
- `import_pipelines`
  - 存储导入任务。
- `import_pipeline_chunks`
  - 存储大 PDF 分块进度。

暂缓：

- `question_imports.pipeline_id` 字段。
- 原始上传文件持久化。
- 独立 import task 表。
- 服务端无文件重新导入。

## 五、本轮暂缓范围

- 当前不做：
  - ZIP 图片包导入。
  - 新 OCR 引擎。
  - 书籍类 PDF 优化。
  - 复杂 AI 增强。
  - 原文件持久化。
  - 真正服务端 reimport。
  - 大规模 sidebar 架构重构。
- 当前新增待办：Admin 审核阶段单题 AI 补全，仅作为人工审核辅助，不改变“无纯 AI 自动入库”约束。

ZIP 导入涉及解压安全、路径穿越防护、文件数/大小限制和多任务编排，建议等 Admin PDF/普通图片/文本 PDF 跑通后单独处理。

## 六、验证计划

### 后端验证

- Admin 有 `import:write` 时可上传小 PDF/图片/TXT。
- 无权限 Admin 上传返回 403。
- Admin 可查询 pipeline status。
- pipeline 完成后写入 `question_imports`，默认 `status = pending`。
- Admin 单题 approve/reject/edit 正确更新 staging 字段。
- Admin 单题 AI 补全只更新 `question_imports` 暂存字段和 AI metadata，不直接发布正式题库。
- Admin AI 补全需受 `import:write` 和后台 AI 设置约束。
- Admin batch approve/reject 正确计数。
- Admin publish 只发布 approved rows。
- 删除未发布 batch 成功。
- 删除已发布或已关联正式题目的 batch 失败。
- 小程序 publish/approve/reject 接口不可用。

### 已完成验证

- 后端边界测试已通过，覆盖 app 导入边界、Admin 导入服务/API 边界，以及模板下载 / 写入边界。
- 关键写入边界已收紧，确认管理型写接口不会向普通 App / 小程序开放。

### 待完成手工验证

1. Admin 浏览器端上传、进度轮询、待审核、发布全流程走查。
2. Admin 待审核页单题 AI 补全走查：确认补全结果刷新到暂存题目，AI 建议可复核，答案建议不会自动保存或通过。
3. 小程序真机 / 开发者工具轻量导入只读流程走查。
4. 确认模板下载仍可供已认证 App 用户使用。

## 七、当前结论

- 迁移实现已进入收尾阶段。
- 当前不再补充新能力，优先完成手工 UI 验证。
- 如手工验证未通过，再单独补齐缺口或回写待同步内容。
