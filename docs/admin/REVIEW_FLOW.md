# 题目审核流程设计

> 版本：v2.5（补齐单题导入审核成功审计） | 状态：部分实现 | 更新：2026-11-01
> 修订自审计报告 C6：完善 editing/re_pending 状态机；引入 question_versions 快照；权限分级
> 2026-05-30 变更原因：同步题库 Level 1 完全重复检测；导入阶段标记疑似重复，审核发布阶段按 `subject + question_hash` 拦截。
> 2026-08-10 变更原因：题目知识点改由 `question_knowledge_points` 关联表保存（`questions.knowledge_points` 列移除）；编辑审计动作统一为 `question.update`。
> 2026-10-23 变更原因：§6 审核工作台按 `review-query-state.ts` / `page.tsx` 复核改写（过滤条件清单、答案状态筛选、re_pending 页面现状登记；该页面后续已在 v2.4 接入 `/review`）。
> 2026-10-24 变更原因：实现已入库题目 `re_pending` 写入、单题/批量重审与版本回滚；首次导入审核仍保持在 `/imports`。
> 2026-11-01 变更原因：单题导入审核通过写 `import.approve`，与审核/发布同事务提交；失败或重复审核不写成功审计。

---

## 一、完整状态机

```
                    ┌──────────────────┐
                    │  题目上传/导入     │
                    └────────┬─────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │ Level 1 重复检测              │
              │ question_hash + duplicate_*  │
              │ 只标记，不拒绝/删除             │
              └────────┬─────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │   pending（待审核）            │
              │   存在 question_imports       │
              └────────┬─────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │ question:review              │
        ▼                              ▼
┌──────────────────┐         ┌──────────────────┐
│  approved（通过）  │         │  rejected（拒绝） │
│  写入 questions   │         │  reject_reason   │
│  is_active=true  │         │  不写 questions  │
└────────┬─────────┘         └──────────────────┘
         │
         │ admin 编辑
         ├──────────────────┐
         │                  │
         │ 有 review 权限     │ 无 review 权限
         │                  │
         ▼                  ▼
┌──────────────────┐  ┌──────────────────┐
│ approved（保持）   │  │ re_pending       │
│ 写 question_     │  │ 写 question_     │
│ versions 快照     │  │ versions 快照     │
└──────────────────┘  └────────┬─────────┘
                               │
                               │ reviewer 审核
                               ├──────────┐
                               ▼          ▼
                          approved    rejected
                          (回滚 or 接受)


┌──────────────────┐
│ admin 下架        │
│ approved →       │  ─ 任意状态下：管理员可上架/下架
│ archived         │     (is_active toggle)
└──────────────────┘
```

---

## 二、状态说明

| 状态 | 存储位置 | 描述 |
|------|---------|------|
| `pending` | `question_imports.review_status` | 等待人工首次审核 |
| `approved` | 首次审核：`question_imports.review_status`；已入库重审：`questions.review_status` + `is_active=true` | 审核通过，已发布 |
| `rejected` | 首次审核：`question_imports.review_status`；已入库重审：`questions.review_status` | 审核拒绝；未入库 import 不进题库，已入库题目下架 |
| `re_pending` | `questions.review_status` | 已发布题目被编辑后，等待重新审核 |
| `archived` | `questions.is_active=false` | 已下架（保留数据，不出题） |

**重要**：
- 首次审核操作 `question_imports`，接口为 `POST /api/admin/v1/imports/questions/{importId}/approve`（审核即发布）与 `POST /api/admin/v1/imports/questions/{importId}/reject`；未人工确认的 import 不得进入正式刷题池。
- 导入阶段 Level 1 重复检测只写 `question_hash`、`duplicate_status`、`duplicate_of_question_id`、`duplicate_of_import_id`；不删除、不自动拒绝导入题。
- 审核通过 / 发布写入 `questions` 前必须按 `subject_id + question_hash` 查询正式题库；命中完全重复时不重复创建，将导入题置为 `published` 并挂到已发布题目 `question_id`。
- 已入库题目重审已实现：`POST /questions/{id}/approve`、`POST /questions/{id}/reject`、`POST /questions/batch-approve`、`POST /questions/batch-reject`；仅 `re_pending` 可通过/拒绝，`rejected` 可重审通过。
- 批量重审 `POST /questions/batch-approve`、`POST /questions/batch-reject` 支持可选 `reason` 字段（最长 256 字符）；`batch-reject` 省略 `reason` 时使用默认 `"批量重审拒绝"`。批量操作按逐题 savepoint 隔离，单题非 `ValueError` 异常不会中断整批，失败项以 `failed_items` 返回。
- `re_pending` 写入已实现：`PATCH /questions/{id}` 发生实际字段变更且操作者无 `question:review` 权限时，`review_status → re_pending`；持有 `question:review` 的编辑者保持原状态。
- `is_active=false` 时，**无论 review_status 是什么**，题目不会出现在小程序刷题池。

---

## 三、审核操作 API

> 2026-10-24 同步：**首次审核**仍走导入管理接口（`/api/admin/v1/imports`，权限 `import:write`），审核即发布。**已入库题目重审**走 `/questions`（单题权限 `question:review`，批量权限 `question:batch_review`），不创建新题目，只更新既有 `questions.review_status/is_active`、追加版本并写审计。

### 3.1 首次审核导入题目（question_imports）

```
POST /api/admin/v1/imports/questions/{importId}/approve
POST /api/admin/v1/imports/questions/{importId}/reject   # Body(可选): { "reason": "..." }
权限：import:write
```

审核通过即发布：`approve_import_question` 将 `question_imports.status` 置为 `approved`，随即调用 `publish_single_question` 写入正式 `questions`（命中完全重复时挂到已发布题目，`status=published` 且 `question_id` 指向正式题；发布失败回滚为 `pending` 留在审核队列）。reject 仅置 `status=rejected` 并记录 `reject_reason`，不写 `questions`。已发布题目（`status=published` / `question_id` 非空）不可重复审核。

2026-11-01：单题通过接口在提交前写 `import.approve` 成功审计（`important`），关联操作者、请求IP/User-Agent及导入ID，detail包含 `batch_id/question_id/status`。审计与审核/发布共用事务；审计写入失败不能保留已成功审核的更新。发布失败、重复审核不追加成功审计。本补充仅覆盖单题通过入口，批次/拒绝的现有行为不由此改变。

### 3.2 批次审核与发布

```
POST /api/admin/v1/imports/{batchId}/approve            # 通过批次内所有 pending/rejected
POST /api/admin/v1/imports/{batchId}/approve-low-risk   # 仅通过 low risk 且无高风险的题目
POST /api/admin/v1/imports/{batchId}/reject             # 批量拒绝
POST /api/admin/v1/imports/{batchId}/publish            # 批量发布（仅发布，不改变审核状态）
权限：import:write
```

`/approve` 逐题执行 Level 1 完全重复检测：`subject_id + question_hash` 命中正式题库重复题时阻止发布并挂到已发布题目；单题发布失败回滚为 `pending`，不影响批次其他题目。`/approve-low-risk` 只处理 `risk_level == "low"`、无 `ai_answer_flag`、有有效答案、无高风险标记（`math_low_confidence` / `complex_formula_requires_review`）的待审核题。

### 3.3 单题补全（AI 辅助，非审核）

```
POST /api/admin/v1/imports/questions/{importId}/complete   # 单题 AI 补全
POST /api/admin/v1/imports/questions/batch-complete        # 批量 AI 补全（ids 上限 50）
GET  /api/admin/v1/imports/questions/{importId}            # 单题详情
PUT  /api/admin/v1/imports/questions/{importId}            # 修改导入题字段（含 status / review_note / parsed_*）
权限：import:write
```

AI 补全只作为辅助任务，结果写入导入题字段（`parsed_*` / `ai_*`），**不绕过人工确认**；`/complete` 与 `/batch-complete` 分别写 `import.complete` / `import.batch_complete` 审计。

### 3.4 已入库题目重审（已实现）

- `POST /questions/{id}/approve`（重审通过，`review_status → approved`、`is_active → true`）
- `POST /questions/{id}/reject`（重审拒绝，`review_status → rejected`、`is_active → false`；body `reason` 必填）
- `POST /questions/batch-approve` / `POST /questions/batch-reject`（批量重审，ids 上限 50）

批量接口逐题执行，失败项写入 `failedItems`，整体提交后写一条 critical 审计（`success_ids / failed_items / success_count / failed_count`）。批量拒绝使用统一 reason；需要逐题理由时使用单题接口。

---

## 四、编辑操作 API（C6 关键）

### 4.1 编辑题目

```
PATCH /api/admin/v1/questions/:id
权限：question:write
Body: { content?, options?, answer?, analysis?, difficulty?, knowledgePoints?, editReason? }
```

实现策略（事务内）：
1. 读取当前 questions 记录 → 计算下一个 version 号（`MAX(question_versions.version) + 1`）
2. 将当前快照写入 question_versions（knowledge_points 快照用**操作时值**，从关联表读取）
3. 更新 questions 表；`knowledgePoints` 与 `subject_id` 不写入 ORM 列，改走 `question_knowledge_points` 关联表（`replace_question_knowledge_points`，replace 语义，source="admin"）
   - 只改知识点 → 按当前 subject replace
   - 只改 subject → 旧知识点名在新科目重建
   - 同时改 → 新 subject + 新知识点
   - `knowledgePoints: null` → 显式清空映射
4. 更新 review_status：持有 question:review → 保持原 review_status；仅持有 question:write → review_status → "re_pending"。
5. 写 audit_log（severity: important，action=`question.update`）
   detail: { question, changed_fields, before, after, editReason }

响应：
{ "data": {
    "id": 123,
    "version": 3,
    "reviewStatus": "approved"
  }
}
```

> 2026-08-10 同步：无实际字段变更时（changed_fields 为空）不写版本快照、不写审计。题目图片上传/替换/删除与快捷加选项同样复用本流程，审计 action 均为 `question.update`。

### 4.2 查看版本历史

```
GET /api/admin/v1/questions/:id/versions
权限：question:read
响应：
{ "data": {
    "items": [
      { "version": 3, "editedBy": { id, displayName }, "editReason", "createdAt", "diff": {...} },
      { "version": 2, ... },
      { "version": 1, ... }
    ]
  }
}
```

### 4.3 回滚到指定版本（已实现）

```
POST /api/admin/v1/questions/:id/rollback
权限：question:write + question:review（必须双权限）
Body: { "version": 2, "reason": "原版本更准确" }

副作用：
- 当前内容写入新 version
- 用目标版本内容覆盖 questions
- 写 audit_log（severity: critical）

权限为 `question:write + question:review`。实现为“用目标版本覆盖当前投影，再追加新版本”，不是移动 `current_version_id` 指针；回滚后 `review_status=approved`、`is_active=true`，写 critical 审计 `question.rollback`。目标版本缺少科目时拒绝回滚。
```

---

## 五、上下架 API

```
PATCH /api/admin/v1/questions/:id/toggle-active
权限：question:write
Body: { "isActive": true | false, "reason": "可选下架原因" }

副作用：
- questions.is_active → 指定值
- audit_log（severity: important）
约束：
- 仅 `review_status=approved` 的题目可激活；`rejected` 必须走重审通过（`POST /approve`），`re_pending` 必须走审核
- 软删除（`is_active=false`）后的 approved 题目可通过 toggle-active 重新激活
```

---

## 六、审核工作台设计（前端）

> 2026-10-23 按 `admin-frontend/src/app/(admin)/imports/review/review-query-state.ts`（ReviewFilters 类型与 createDefaultReviewFilters）与 `page.tsx` 复核改写。队列排序 / 分页 / 过滤语义以 `docs/architecture/REVIEW_QUEUE_COMPATIBILITY.md` §2 为准，本文不复述。

### 过滤条件（当前实现）

- 审核状态（`status`，默认 `pending`）：下拉选项 `pending` / `approved` / `rejected` / `published` / 全部；`re_pending` 属已入库题目重审域，在 `/review` 工作台处理
- 科目（`subject_id`）：subjects 下拉选择（单选，非树形）
- 来源（`source_type`）：手动上传 / AI 导入 / PDF 导入
- 风险等级（`risk_level`）：`high` / `medium` / `low`
- 答案状态（`answer_status`）：前端下拉为 `missing` / `ai_filled` / `imported` / `manual_verified` / `abnormal`；后端 `GET /imports/review-queue` 另接受 `manual_filled`（`backend/app/api/v1/admin_imports.py:464-503`）
- 关键词（`keyword`）：搜索题干 / OCR 原文，防抖后随列表请求传入
- 导入批次 ID（`batch_id`）

不存在「重复状态（duplicate_status）」与「时间范围」筛选项。注意：`risk_level` 为分页后内存过滤、`total` 口径存在偏差，属既有行为，见 `REVIEW_QUEUE_COMPATIBILITY.md` §2/§5。

### 快速审核模式
- 列表展示题目摘要（题干 + 选项 ABCD；题干摘要由 CSS 单行截断实现，无固定字数逻辑）
- `duplicate_status=possible_duplicate` 时展示疑似重复标识，并可查看命中的正式题目 ID / 暂存导入题 ID 与 hash
- 单行操作：[通过] [拒绝]
- 拒绝时弹出 reason 输入框（必填）
- 批量选中（上限 50） + 批量通过/拒绝

### re_pending 工作台（已实现）

- 管理端 `/review` 已接入导航，权限为 `question:review`；页面查询 `re_pending` / `rejected` 队列，展示当前内容与最近历史版本 diff。
- 单题通过/拒绝按权限显示；批量通过/拒绝需要 `question:batch_review`；回滚按钮需要同时具备 `question:write` 与 `question:review`。
- 首次导入审核仍在 `/imports/review`，`/review` 不承担 pending import 队列。

---

## 七、审计日志格式

> 2026-10-24 同步：首次导入审核不写 `question.*` 审计，动作记录在 `question_imports.status / reviewed_by / reviewed_at`；已入库题目重审写 `question.approved` / `question.rejected` / `question.batch_approved` / `question.batch_rejected`。题目编辑统一写 `question.update`。
>
> 2026-11-01：单题导入审核通过还会写 `import.approve`，详见§3.1；仍不复用正式题目重审的 `question.*` 动作。

### question.update（编辑，实际实现）

```json
{
  "action": "question.update",
  "severity": "important",
  "resourceType": "question",
  "resourceId": "123",
  "operatorId": 5,
  "operatorName": "editor01",
  "detail": {
    "question": { "id": 123, "content_preview": "...", "subject_name": "408 数据结构", "question_type": "single_choice" },
    "changed_fields": ["answer"],
    "before": { "answer": "A" },
    "after":  { "answer": "B" },
    "edit_reason": "原答案有误"
  }
}
```

### import.complete / import.batch_complete（AI 补全，实际实现）

```json
{
  "action": "import.batch_complete",
  "severity": "important",
  "resourceType": "question_import",
  "resourceId": "ids=[1,2,3]",
  "operatorId": 1,
  "detail": {
    "import_ids": [1, 2, 3],
    "fields": ["answer", "analysis"],
    "strategy": "fill_empty",
    "result": { "total": 3, "succeeded": 2, "failed": 1, "skipped": 0 }
  }
}
```

### question.approved（已入库重审，实际实现）

```json
{
    "action": "question.approved",
  "severity": "important",
  "resourceType": "question",
  "resourceId": "123",
  "operatorId": 1,
  "operatorName": "admin001",
  "detail": {
    "before": { "reviewStatus": "pending" },
    "after": { "reviewStatus": "approved", "isActive": true }
  }
}
```

### question.batch_approved（已入库批量重审，实际实现）

```json
{
    "action": "question.batch_approved",
  "severity": "critical",
  "resourceType": "question",
  "resourceId": "batch",
  "operatorId": 1,
  "detail": {
    "extra": {
      "successIds": [1, 2, 3, ...],
      "failedItems": [{ "id": 12, "reason": "..." }],
      "totalRequested": 50,
      "successCount": 47,
      "failedCount": 3
    }
  }
}
```

---

## 八、权限矩阵速查

| 操作 | 普通 admin（默认） | reviewer（预留） | content_editor（预留） |
|------|------------------|---------------|--------------------|
| 查看题目 | ✓ question:read | ✓ | ✓ |
| 编辑题目 | ✓ question:write | ✗ | ✓ |
| 导入题审核通过/拒绝（§3.1） | ✓ import:write | ✓ | ✗ |
| 批量审核（§3.2） | ✓ import:write | ✓ | ✗ |
| 删除题目 | ✓ question:delete | ✗ | ✗ |
| 编辑后进 re_pending | N/A | question:write（无 review 权限时） | ✓ |
| 已入库题目重审 | ✓ question:review | ✓ | ✗ |
| 批量重审 | ✓ question:batch_review | ✓ | ✗ |
| 回滚版本 | ✓ question:write + question:review | ✗ | ✗ |

---

## 九、不变式（Invariants）

实现时必须保证以下不变式恒成立：

1. **编辑必留痕**：每次 questions 写操作（有实际字段变更）必先写 question_versions 快照
2. **审核必有据**：approve/reject 必有 operatorId（非脚本场景）
3. **批量必返明细**：批量接口必须返回 successIds + failedItems
4. **状态机闭合**：`question_imports.status` 取值在 `{pending, approved, rejected, published}` 内；`questions.review_status` 取值在 `{approved, re_pending, rejected}` 内，转换仅允许 `re_pending → approved/rejected`、`rejected → approved`
5. **审计先行**：critical 操作的 audit_log 写入失败 → 整个事务回滚
6. **AppUser 不可见**：is_active=false 或 review_status ≠ approved 的题目，**绝不可**出现在小程序刷题池

---

## 相关链接

- [[docs/admin/ADMIN_ARCHITECTURE.md|ADMIN_ARCHITECTURE]] — 管理端架构
- [[docs/admin/ADMIN_API_SPEC.md|ADMIN_API_SPEC]] — 管理 API 合约
- [[docs/admin/DB_SCHEMA_ADMIN.md|DB_SCHEMA_ADMIN]] — 管理端数据模型
- [[docs/admin/RBAC_RULES.md|RBAC_RULES]] — RBAC 与身份域
- [[docs/admin/AUDIT_LOG.md|AUDIT_LOG]] — 审计记录
