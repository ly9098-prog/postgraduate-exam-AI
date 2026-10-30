# Admin 身份、用户、权限与审计兼容说明

> 2026-10-30；§328，ADM-04，L3 身份边界评估。范围为 `/admin-users`、`/app-users`、`/audit-logs`、`/roles`、`/login`、`/` 六入口，以及共享身份客户端的 18 类消费契约。保留现有职责，补契约与修正旧测试，不修改业务运行时。一次独立审查已完成，结论为 `RETAIN`；真实环境仍另行验收。

## 1. 保留的职责与边界

| 消费者 | 原有 owner | 兼容边界 |
| --- | --- | --- |
| 根入口、登录、AdminShell | Next 根重定向、LoginForm、safeInternalRedirect、AdminShell/useAuthBootstrap | 根入口重定向 `/dashboard`。登录等待 store action 完成后才跳转，外部 next 回退到 `/dashboard`，错误展示保持通用文案并在 finally 恢复 loading。壳在 bootstrap 完成且未认证时跳转登录，并把当前 pathname 编码进 next；不声明浏览器真实调度已验证。 |
| 共享身份客户端 | auth-store、API client | auth store 持有登录状态、用户/角色/权限及 token 同步；client 持有请求头、cookie、401 刷新单飞和一次重放。监听器和 token provider 保持一致；bootstrap 先尝试现有 token 的 `/auth/me`，失败后清理并走 cookie refresh；logout 无论结果如何在 finally 清理本地身份，非401错误仍可向调用方传播。 |
| 服务端登录、刷新与登出 | admin_auth、admin_auth_service、admin_security | Admin JWT 与小程序 user JWT 隔离 audience 和签名域；Admin access 与 refresh 共用 Admin audience/签名域，通过 type 区分。保留 cookie 属性、可信浏览器 origin、登录失败计数/锁、JWT nbf/黑名单和 refresh jti 单次消费。认证安全缓存不可用不放行；线上观测和角色缓存有各自降级策略，不混成统一“可用时才鉴权”。 |
| `/admin-users` | 页面请求/表单/确认动作、admin-user-utils、admin_users、admin_user_service | 列表筛选与全局摘要查询分开；新建包含初始凭据，PATCH 只提交可编辑资料/role/is_active，不顺带提交 username/凭据。强制登出、重置凭据与 DELETE 各走既有端点；DELETE 是停用。服务端禁止操作 super_admin 目标或分配该角色，并分别保护删除自己、强制登出自己、重置自己凭据和修改自己角色；不扩大成“禁止一切自身资料修改”。nbf、审计和数据库提交保持原先顺序，不声称跨Redis/数据库原子性。 |
| `/app-users` | 页面过滤/分批操作/导出、app-user-utils、admin_app_users、admin_app_user_service | openid 用户与 Admin 账号仍是两个身份域。批量封禁/解封按5项一组并等待整组完成；失败阻止后续组，不能说先前请求回滚。封禁 reason 去空白/空值，解封不传 body；成功清理选择并失效列表与摘要。绑定/解绑在路由与service均要求 super_admin，仍保留唯一绑定检查。 |
| `/roles` | 页面角色编辑覆盖层、role-permission-utils、admin_rbac、admin_auth_service、admin_security角色版本缓存 | 非 super_admin 的两个查询关闭，bootstrap 后重定向。保存等待 roles 缓存失效完成后，仅清理刚保存角色的覆盖层。服务拒绝修改 super_admin 和不存在权限；路由先完成数据库 commit，再 bump_role_version、refresh；错误映射保留403/422并 rollback，不在失败分支更新版本。缓存版本更新是尽力而为，不能写成跨库强一致事务。 |
| `/audit-logs` 与详情抽屉 | 页面列表/过滤状态、审计组件、admin_audit_logs、admin_audit_service、审计题目解析器 | 列表使用 pageSize/resourceType/from/to 别名和已提交关键词，保留 UTC 日期转换与审计半开时间范围。详情按ID分缓存、null关闭请求。读取权限、关键词长度/LIKE转义、敏感字段净化、列表安全摘要和详情题目解析保持；不把页面端口测试当作真实审计落库证明。 |

18 类契约按领域去重；共享 login/logout/me/refresh 的模块可达不表示每个页面都运行这些动作。7 个当前无有界静态浏览器消费形状的注册端点仍保留：Admin 详情，App 详情/PATCH/绑定/解绑，Admin 自身改密，平铺权限列表。没有删除端点或合并用户身份域。

## 2. 保留结论

认证协议、令牌安全、store 状态、HTTP传输、两类用户管理、RBAC提交和审计读取已有明确 owner。角色缓存更新与数据库提交、nbf与账号修改各有原有时序，兼容性重构不能把这些副作用挪进通用CRUD或统一用户门面。

现有 admin-user/app-user/role-permission 纯工具和审计展示组件可以独立测试；剩余页面较长主要是既有界面与表单编排。未发现必须靠进一步切分解决的具体结构问题。因此保留职责，停止按长度扩展；真实 cookie、JWT、PostgreSQL/Redis并发和浏览器验收仍留最终环境阶段。

## 3. 本轮测试

新增 `admin-frontend/src/app/(admin)/admin-users/identity-page-contracts.test.ts`：18 项直接调用六个真实页面及壳/详情抽屉。LoginForm 通过真实 LoginPage 元素的 component type 取得，未增加业务导出。覆盖登录等待/安全跳转/通用错误、bootstrap门禁与返回路径、Admin查询和新建/PATCH/强退/重置/停用请求、App批量5并发屏障及部分失败、角色保存等待失效、审计别名与详情查询。

hook/query/mutation/request端口为隔离替身；只显式执行适用的壳/角色守卫effect。未挂载DOM、未运行React或TanStack完整调度、未验证原生fetch/cookie/CSV下载。重置动作只核对端点和body字段，不复制现有UI的固定重置值。

现有RBAC测试中，原名“按分类权限”实际请求了 `/permissions`。本轮修正为真实 `/permissions/by-category` 并断言分组/统计；补非super_admin拒绝，以及真实 `replace_role_permissions` 的延期commit屏障、成功响应去重排序、403/422回滚且不bump。数据库/service/cache版本端口为替身，不是PostgreSQL/Redis事务验收。

## 4. 验证与复用

- 管理端146文件1821项通过，本身份域7文件158项；新增文件18项全部包含在该次全套运行中。TypeScript通过，lint0错误、138条既有警告。运行时/构建配置未变，未跑build。
- 后端初始10文件99项通过（21.32秒），随后补强RBAC文件并窄复验7项通过（5.78秒），不能写成一次组合103项运行。身份矩阵/路由完整性/开发权限另3文件11项通过，不与前两组相加冒充一次运行。
- 改动Python严格Ruff、app项目CI忽略集Ruff、compileall和diff检查通过。
- 1116运行时路径逐字保持。固定473文件8155项复用§323；2246原冻结输入为2243不变+3项测试例外，其中本轮RBAC文件不在固定命令中且已窄复验，先前两个例外保持。固定命令实际输入未变，不能把复用写成本轮完整CI。OpenAPI334路径复用§321，后端运行时未变。
- 一次独立只读审查完成：两项P3（冻结输入摘要计数、Admin access/refresh与user签名域表述）已修正并窄复核，无剩余P0–P3；独立前端18项、RBAC7项通过。
- 结果：[admin-identity-retention-2026-10-30.json](refactor-results/admin-identity-retention-2026-10-30.json)。

## 5. 最终环境验收

真实浏览器的cookie/跨域/返回路径、真实Admin JWT登录/续签/退出、RBAC与审计持久化、PostgreSQL/Redis多进程refresh消费/nbf/角色版本传播均未在本轮验收。它们继续归ENV-02/03/05；单次测试进程的替身不能证明跨进程原子性。

下一ADM-05：模型配置、推荐实验/策略/指标/报告与系统任务六页。全部结构条目进入终态后才开始真实环境验收，生产最后且操作另行授权。
