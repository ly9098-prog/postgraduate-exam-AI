当前任务（2026-05-30）：仅维护 Admin Phase 6 文档同步，不修改业务代码。

背景：后台管理系统 Phase 6（Next.js admin-frontend）已完成主要前端实现，并已通过：

- `npm --prefix admin-frontend run lint`
- `npm --prefix admin-frontend run build`

同步范围：

- `docs/admin/README.md`
- `docs/admin/PHASE_PLAN.md`
- `docs/frontend/ADMIN_UI_RULES.md`
- `docs/project/CHANGELOG.md`
- `prompts/tasks/current-task.md`

已同步要点：

- Phase 6 前端位于 `admin-frontend`。
- 技术栈：Next.js 16、React 19、React Query、TanStack Table、Zustand、Recharts、Tailwind CSS 4。
- 页面范围：dashboard、login、app-users、admin-users、questions、review、roles、audit-logs。
- Phase 6 前端只消费 `/api/admin/v1`，不修改后端 API、DB schema 或权限语义。
- audit-log 查询参数别名已按后端同步：`pageSize`、`resourceType`、`from`、`to`。

# 待同步内容

- 需后续联调确认题目版本 diff 高亮是否达到最终验收预期；若后端版本对比字段不足，应作为后续 API/UI 联调项记录。