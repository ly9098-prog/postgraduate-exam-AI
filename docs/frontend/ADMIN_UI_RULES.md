# Admin UI Rules

> 版本：v1.1（Phase 6 前端完成同步版） | 状态：Phase 6 主要前端已完成 | 更新：2026-05-30
> 变更原因：同步 `admin-frontend` Next.js Admin Dashboard 主要实现、页面范围、仅消费 `/api/admin/v1` 的边界、audit-log 参数别名修复，以及 lint/build 验证结果。

---

## 1. 适用范围

本文件约束 `admin-frontend` 后台管理界面，仅覆盖 Phase 6 Admin Dashboard UI。后台前端只消费现有 FastAPI Admin API：`/api/admin/v1`，不得在前端阶段修改后端 API、DB schema 或权限语义。

与小程序端 `docs/frontend/UI_RULES.md`、`docs/frontend/COMPONENT_RULES.md` 分离维护；小程序 `rpx/WXML/WXSS` 规则不直接套用于 Admin Dashboard。

---

## 2. 技术与数据流约束

- Admin UI 使用 Next.js 16、React 19、TypeScript、Tailwind CSS 4；数据请求使用统一 API client + React Query；列表能力可使用 TanStack Table；图表可使用 Recharts；全局会话状态使用 Zustand。
- API base URL 默认指向 `/api/admin/v1` 对应服务，可通过 `NEXT_PUBLIC_ADMIN_API_BASE_URL` 覆盖。
- access token 只保存在内存态；refresh token 依赖 HttpOnly cookie；前端不得持久化 access token 到 localStorage/sessionStorage。
- 所有 API 请求统一走 API client 封装，自动携带 `Authorization: Bearer <access>` 与 `credentials: include`。
- API 响应以后端 `docs/admin/ADMIN_API_SPEC.md` 为准；前端不得自造字段、绕过分页或假定后端返回未定义权限。
- 401/会话失效必须清空内存态并跳转 `/login?next=<currentPath>`。
- 写操作成功后必须刷新相关 query/cache，并展示结果反馈；批量操作必须展示成功数与 failedItems 明细。

---

## 3. 登录页 `/login`

- 登录页只包含后台账号用户名、密码与提交入口，不接入微信登录。
- 登录失败统一提示“用户名或密码错误”或等价泛化错误；不得展示具体锁定维度，避免账号枚举。
- 登录成功后写入内存态：`accessToken`、`user`、`role`、`permissions`，再跳转 `next` 或 `/dashboard`。
- 登录按钮必须有 loading/disabled 态，避免重复提交。
- 登录页不得展示后台菜单；已登录访问登录页可跳转 Dashboard。

---

## 4. 后台壳子、侧边栏与顶部栏

- Admin Shell 负责会话 bootstrap；未完成 bootstrap 时展示轻量加载态，未认证时不渲染业务页面。
- 侧边栏必须基于当前 `permissions` 动态显示菜单；隐藏仅用于体验，不能替代后端 RBAC。
- 菜单最少覆盖：Dashboard、小程序用户、管理员、题库、审核工作台、角色权限、审计日志。
- 顶部栏展示当前 admin 用户、角色、登出入口；如实现改密入口，必须走 `/auth/change-password` 并触发旧 token 失效语义。
- 桌面端优先；Phase 6 不要求移动端适配，但窄屏下不得阻断核心登录与登出。

---

## 5. 权限门禁规则

- 页面级门禁：进入页面时检查目标权限；无权限应展示 403/无权限空态或隐藏入口，不应请求无权资源。
- 按钮级门禁：写操作按钮必须按权限隐藏或禁用，例如封禁、删除、审核、角色权限保存。
- 前端权限只作为 UX 控制；真实授权永远以后端 FastAPI dependencies/RBAC 为准。
- `super_admin` 保护必须前后端双层体现：前端禁用对 `super_admin` 的危险操作，后端仍必须拒绝。
- 不允许在前端硬编码“拥有全部权限”的业务绕过；应以 `/auth/me` 或登录响应的权限集合为准。

---

## 6. Dashboard

- Dashboard 展示运营总览，不承担审核或写操作。
- 统计卡片覆盖用户、题目、导入、待审核、critical audit 等核心指标。
- 趋势图消费 `/dashboard/daily`，题目分布消费 `/dashboard/questions-stats`。
- 缓存状态、接口错误只作为运维提示；Redis 降级或缓存 miss 不应在前端阻断页面渲染。
- 指标为空时显示 `--` 或空态，不用 0 掩盖接口缺失。

---

## 7. 用户管理

### 7.1 小程序用户

- 小程序用户与后台管理员必须分页面展示，不得混用模型或权限。
- 小程序用户列表支持分页、关键字、封禁状态等过滤。
- 封禁/解封属于重要操作，必须二次确认；封禁必须填写原因。
- 不应默认允许修改微信来源资料（openid、头像、昵称等）；如后端允许有限字段修改，必须按白名单展示。

### 7.2 后台管理员

- 管理员列表支持创建、编辑、删除、强制登出、重置密码等后台账号操作。
- 创建/编辑管理员时角色选择不得允许设置为 `super_admin`，除非后端提供明确受控流程。
- 禁止删除自己、禁止修改自己的 role、禁止删除或降级 `super_admin`；前端需禁用入口并展示原因。
- 重置密码、删除管理员、强制登出必须二次确认，并展示操作结果。

---

## 8. 题库审核与审核工作台

- 题库页支持多条件过滤：科目、题型、年份、审核状态、启用状态、关键字。
- 列表必须展示审核状态、启用状态、科目/题型/难度等关键信息。
- 单题详情使用抽屉或详情页展示题干、选项、答案、解析、知识点、原始导入信息（如 API 提供）。
- 审核操作包括通过、拒绝；拒绝必须填写 reason。
- 批量审核必须二次确认，并在返回后展示 `successIds` 与 `failedItems` 明细，不得只提示“全部成功”。
- 版本历史必须展示版本列表；如实现 diff，应对 `re_pending` 与历史版本进行高亮对比。
- 审核工作台 `/review` 面向快速审核，`re_pending` 必须单独 Tab 或过滤入口。

---

## 9. 角色权限

- 角色列表与权限矩阵必须按后端 permission category 分组展示。
- 创建角色不得允许 `name=super_admin`；系统角色不可删除或随意改名。
- 修改角色权限属于 critical 操作，必须二次确认，并提示会影响相关用户后续请求权限。
- 保存成功后必须刷新角色详情、权限矩阵与当前用户 `/auth/me`（如当前用户受影响）。
- 前端不得通过硬编码矩阵推断权限全集，应消费后端 `/permissions` 或 `/permissions/by-category`。

---

## 10. 审计日志

- 审计日志页支持 action/keyword、operatorId（如 UI 提供）、resourceType、resourceId（如 UI 提供）、severity、status、from、to 等过滤。
- 前端发送给后端的分页与时间/资源参数必须使用当前 `/api/admin/v1` 别名：`pageSize`、`resourceType`、`from`、`to`。
- severity 使用颜色区分：critical/danger、important/warning、normal/primary、low/neutral。
- 详情展示必须保留 JSON 结构，可格式化但不得丢弃 `detail`、`requestId`、`error_message` 等排查字段。
- 审计日志页面只读，不提供修改或删除入口。

---

## 11. 危险操作二次确认

以下操作必须二次确认：

- 封禁/解封小程序用户。
- 创建、删除、重置密码、强制登出后台管理员。
- 单题拒绝、批量通过、批量拒绝、删除/停用题目。
- 修改角色权限、删除角色。
- 任何后端标记为 `critical` 或会写 important audit 的操作。

确认弹窗必须包含：操作对象、影响说明、确认按钮 loading 态、取消入口。危险操作使用 danger 样式；拒绝/封禁类操作必须要求原因。

---

## 12. 加载、错误与空状态

- 列表页首次加载展示 skeleton 或轻量 loading；分页/筛选加载不得清空已有上下文导致闪烁。
- 空列表使用明确文案，例如“暂无题目”“暂无审计日志”。
- API 404/后端 router 未挂载时，应提示“接口待联调/后端阻塞”，不得伪造成功数据。
- API 错误展示后端 message；鉴权错误单独引导重新登录或展示无权限。
- 表单提交失败保留用户输入，避免原因、筛选条件丢失。

---

## 13. Phase 6 实现同步（2026-05-30）

- `admin-frontend` 已完成主要页面：`/dashboard`、`/login`、`/app-users`、`/admin-users`、`/questions`、`/review`、`/roles`、`/audit-logs`。
- 前端仅消费 `/api/admin/v1`，Phase 6 未修改后端 API、DB schema 或权限语义。
- audit-log 查询参数已同步为后端当前别名：`pageSize`、`resourceType`、`from`、`to`。
- 已通过 `npm --prefix admin-frontend run lint` 与 `npm --prefix admin-frontend run build`。

# 待同步内容

- 需联调确认题目版本 diff 高亮是否已达到最终验收预期；若后端版本对比字段不足，应记录为后续 API/UI 联调项，而不是在前端伪造数据。
