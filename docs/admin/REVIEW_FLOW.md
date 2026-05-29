# 题目审核流程设计

> 版本：v2.0（审计修订版） | 状态：可启动开发 | 更新：2026-05-26
> 修订自审计报告 C6：完善 editing/re_pending 状态机；引入 question_versions 快照；权限分级

---

## 一、完整状态机

```
                    ┌──────────────────┐
                    │  题目上传/导入     │
                    └────────┬─────────┘
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
- 首次审核操作 `question_imports`，建议接口为 `/imports/{importId}/approve` / `/imports/{importId}/reject`；未人工确认的 import 不得进入正式刷题池。
- 已入库题目重审操作 `questions`，接口为 `/questions/{questionId}/approve` / `/questions/{questionId}/reject`。
- 现有 questions.review_status 默认值需实施前确认是否为 "approved"（保持 FastAPI 端兼容）；字段不存在时必须列 migration。
- 新增 `re_pending` 仅在 Admin 编辑场景中产生，FastAPI 端必须过滤非 approved 题目。
- `is_active=false` 时，**无论 review_status 是什么**，题目不会出现在小程序刷题池。

---

## 三、审核操作 API

### 3.1 首次审核导入题目（question_imports）

```
POST /api/admin/v1/imports/:importId/approve
POST /api/admin/v1/imports/:importId/reject
权限：question:review
```

首次审核只操作 `question_imports` 及其确认入库流程；approve 后才允许按既有人工确认链路写入正式 `questions`。reject 不写入 `questions`。具体路径建议同步到 ADMIN_API_SPEC 后再开发。

### 3.2 已入库题目审核通过

```
POST /api/admin/v1/questions/:id/approve
权限：question:review
Body: { "comment": "可选审核备注" }

响应：
{ "data": { "id": 123, "reviewStatus": "approved", "isActive": true } }

副作用（事务内）：
- questions.review_status → "approved"
- questions.is_active → true
- audit_logs.create:
  { action: "question.approve", severity: "important",
    resourceType: "question", resourceId: "123",
    detail: { before: { reviewStatus: "pending" | "re_pending" },
              after:  { reviewStatus: "approved" } } }
```

### 3.3 已入库题目审核拒绝

```
POST /api/admin/v1/questions/:id/reject
权限：question:review
Body: { "reason": "题目选项缺失" }

副作用（事务内）：
- questions.review_status → "rejected"
- questions.is_active → false
- audit_logs.create: { ... severity: "important" ... }
```

### 3.4 批量审核

```
POST /api/admin/v1/questions/batch-approve
权限：question:batch_review
Body: { "ids": [1, 2, 3, ...] }  // 上限 50

实现策略（I3 修订）：
- 每条独立事务处理（单条失败不影响其他）
- 失败原因写入 failedItems

响应：
{ "data": {
    "successIds": [1, 2, 3, ...],
    "failedItems": [{ "id": 12, "reason": "题目不存在" }, ...]
  }
}

副作用：
- 整体写一条 audit_log（severity: critical）
  detail: { extra: { successIds, failedItems, count: 50 } }
```

```
POST /api/admin/v1/questions/batch-reject
权限：question:batch_review
Body: { "ids": [...], "reason": "批量拒绝原因" }
```

---

## 四、编辑操作 API（C6 关键）

### 4.1 编辑题目

```
PATCH /api/admin/v1/questions/:id
权限：question:write
Body: { content?, options?, answer?, analysis?, difficulty?, knowledgePoints?, editReason? }

实现策略（事务内）：
1. 读取当前 questions 记录 → 计算下一个 version 号
2. 将当前快照写入 question_versions
3. 更新 questions 表
4. 根据 operator 权限决定 review_status：
   - 持有 question:review → 保持原 review_status（通常 approved）
   - 仅持有 question:write → review_status → "re_pending"
5. 写 audit_log（severity: important）
   detail: { before: snapshot, after: newData, extra: { editReason } }

响应：
{ "data": {
    "id": 123,
    "version": 3,
    "reviewStatus": "approved" | "re_pending"
  }
}
```

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

注：当前 Phase 3 不实现，预留 API 路径以便未来扩展不影响命名。
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
- 审核状态：`pending` / `re_pending` / `rejected` / `approved`
- 科目：subjects 树形选择
- 来源：手动上传 / AI 导入 / PDF 导入
- 时间范围
- 导入批次 ID

### 快速审核模式
- 列表展示题目摘要（题干前 100 字 + 选项 ABCD）
- 单行操作：[通过] [拒绝]
- 拒绝时弹出 reason 输入框（必填）
- 批量选中（上限 50） + 批量通过/拒绝

### re_pending 工作台
- 单独 Tab 展示 re_pending 题目
- 展示版本对比（左：上次 approved 版本，右：当前编辑版本，diff 高亮）
- 审核员选择"接受变更"或"回滚"

---

## 七、审计日志格式

### question.approve

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

### question.edit（产生 re_pending）

```json
{
  "action": "question.edit",
  "severity": "important",
  "resourceType": "question",
  "resourceId": "123",
  "operatorId": 5,
  "operatorName": "editor01",
  "detail": {
    "before": { "answer": "A", "reviewStatus": "approved" },
    "after":  { "answer": "B", "reviewStatus": "re_pending" },
    "extra":  { "editReason": "原答案有误", "newVersion": 3 }
  }
}
```

### question.batch_approve

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
| 审核通过/拒绝 | ✓ question:review | ✓ | ✗ |
| 批量审核 | ✓ question:batch_review | ✓ | ✗ |
| 删除题目 | ✓ question:delete | ✗ | ✗ |
| 编辑后是否进 re_pending | ✗（同时有 review） | N/A | ✓ |
| 回滚版本 | ✓（需双权限） | ✗ | ✗ |

---

## 九、不变式（Invariants）

实现时必须保证以下不变式恒成立：

1. **编辑必留痕**：每次 questions 写操作必先写 question_versions 快照
2. **审核必有据**：approve/reject 必有 operatorId（非脚本场景）
3. **批量必返明细**：批量接口必须返回 successIds + failedItems
4. **状态机闭合**：question.review_status 取值只能在 `{pending, approved, rejected, re_pending}` 内
5. **审计先行**：critical 操作的 audit_log 写入失败 → 整个事务回滚
6. **AppUser 不可见**：is_active=false 或 review_status ≠ approved 的题目，**绝不可**出现在小程序刷题池
