# 题目审核流程设计

> 版本：v2.2（知识点关联表与编辑审计同步版） | 状态：可启动开发 | 更新：2026-08-10
> 修订自审计报告 C6：完善 editing/re_pending 状态机；引入 question_versions 快照；权限分级
> 2026-05-30 变更原因：同步题库 Level 1 完全重复检测；导入阶段标记疑似重复，审核发布阶段按 `subject + question_hash` 拦截。
> 2026-08-10 变更原因：题目知识点改由 `question_knowledge_points` 关联表保存（`questions.knowledge_points` 列移除）；编辑审计动作统一为 `question.update`。

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
- 已入库题目重审（approve/reject）当前**未实现**——无 `/questions/{id}/approve` 等接口；重审设计见 §3.4（设计预留）。
- `re_pending` 状态为**设计预留**：当前 `PATCH /questions/{id}` 编辑不改变 review_status（`_EDIT_FIELDS` 不含 review_status），FastAPI 端无需过滤；未来实现时须过滤非 approved 题目。
- `is_active=false` 时，**无论 review_status 是什么**，题目不会出现在小程序刷题池。

---

## 三、审核操作 API

> 2026-08-10 同步：审核全部走**导入管理**接口（`/api/admin/v1/imports`，权限 `import:write`），审核即发布——approve 直接写入正式 `questions`。**不存在** `POST /questions/{id}/approve`、`/reject`、`/batch-approve`、`/batch-reject` 等接口（§3.2/3.3/3.4 原设计未实现，归入 §3.4 预留说明）。

### 3.1 首次审核导入题目（question_imports）

```
POST /api/admin/v1/imports/questions/{importId}/approve
POST /api/admin/v1/imports/questions/{importId}/reject   # Body(可选): { "reason": "..." }
权限：import:write
```

审核通过即发布：`approve_import_question` 将 `question_imports.status` 置为 `approved`，随即调用 `publish_single_question` 写入正式 `questions`（命中完全重复时挂到已发布题目，`status=published` 且 `question_id` 指向正式题；发布失败回滚为 `pending` 留在审核队列）。reject 仅置 `status=rejected` 并记录 `reject_reason`，不写 `questions`。已发布题目（`status=published` / `question_id` 非空）不可重复审核。

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

### 3.4 已入库题目重审（设计预留，未实现）

以下原设计端点当前**未实现**，仅保留路径命名以便未来扩展：
- `POST /questions/{id}/approve`（重审通过，`review_status → approved`、`is_active → true`）
- `POST /questions/{id}/reject`（重审拒绝，`review_status → rejected`、`is_active → false`）
- `POST /questions/batch-approve` / `POST /questions/batch-reject`（批量重审，ids 上限 50）

实现时须遵循：每条独立事务、失败写 `failedItems`、整体写一条 critical 审计（`detail.extra.successIds / failedItems / count`）；已入库题目的 `review_status` 目前只会是 `approved`（无其他写入口）。

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
4. 更新 review_status（**当前未实现**——设计预留）：原设计根据 operator 权限决定——持有 question:review → 保持原 review_status；仅持有 question:write → review_status → "re_pending"。当前实现 `_EDIT_FIELDS` 不含 `review_status`，编辑不改变审核状态，响应 `reviewStatus` 恒为当前值（通常 approved）。
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

### 4.3 回滚到指定版本（保留预留位）

```
POST /api/admin/v1/questions/:id/rollback
权限：question:write + question:review（必须双权限）
Body: { "version": 2, "reason": "原版本更准确" }

副作用：
- 当前内容写入新 version
- 用目标版本内容覆盖 questions
- 写 audit_log（severity: critical）

注：**未实现**（设计预留，保留 API 路径以便未来扩展不影响命名）。
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
```

---

## 六、审核工作台设计（前端）

### 过滤条件
- 审核状态：`pending` / `rejected` / `approved`（`re_pending` 为设计预留，当前无此状态数据）
- 重复状态：`normal` / `possible_duplicate`
- 科目：subjects 树形选择
- 来源：手动上传 / AI 导入 / PDF 导入
- 时间范围
- 导入批次 ID

### 快速审核模式
- 列表展示题目摘要（题干前 100 字 + 选项 ABCD）
- `duplicate_status=possible_duplicate` 时展示疑似重复标识，并可查看命中的正式题目 ID / 暂存导入题 ID 与 hash
- 单行操作：[通过] [拒绝]
- 拒绝时弹出 reason 输入框（必填）
- 批量选中（上限 50） + 批量通过/拒绝

### re_pending 工作台（设计预留，未实现）
- 单独 Tab 展示 re_pending 题目
- 展示版本对比（左：上次 approved 版本，右：当前编辑版本，diff 高亮）
- 审核员选择"接受变更"或"回滚"

---

## 七、审计日志格式

> 2026-08-10 同步：审核（通过/拒绝）本身**不写** `question.*` 审计，动作记录在 `question_imports.status / reviewed_by / reviewed_at`；题目编辑统一写 `question.update`。以下 `question.approve` / `question.batch_approve` 为设计参考（未实现），`import.batch_complete` 为实际批量动作样例。

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

### question.approve（设计参考，未实现）

```json
{
  "action": "question.approve",
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

### question.batch_approve（设计参考，未实现）

```json
{
  "action": "question.batch_approve",
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
| 编辑后是否进 re_pending（未实现） | N/A | N/A | N/A |
| 回滚版本（未实现） | N/A | ✗ | ✗ |

---

## 九、不变式（Invariants）

实现时必须保证以下不变式恒成立：

1. **编辑必留痕**：每次 questions 写操作（有实际字段变更）必先写 question_versions 快照
2. **审核必有据**：approve/reject 必有 operatorId（非脚本场景）
3. **批量必返明细**：批量接口必须返回 successIds + failedItems
4. **状态机闭合**：`question_imports.status` 取值在 `{pending, approved, rejected, published}` 内；`questions.review_status` 目前仅 `approved`（`re_pending` 为设计预留，未实现时无写入路径）
5. **审计先行**：critical 操作的 audit_log 写入失败 → 整个事务回滚
6. **AppUser 不可见**：is_active=false 或 review_status ≠ approved 的题目，**绝不可**出现在小程序刷题池
