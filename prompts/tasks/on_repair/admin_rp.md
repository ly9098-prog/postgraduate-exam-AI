你现在位于 MemoGrad 项目的代码仓库。请审计并修复 `admin-frontend/`，目标是让后台前端具备可重复构建、稳定认证、可靠错误处理、合理性能和可上线的 CI 门禁。

不要只输出建议。请直接阅读仓库、修改代码、补充测试、执行命令并汇报结果。

## 一、工作原则

1. 先阅读：
   - 根目录 `CLAUDE.md`
   - `README.md`
   - `admin-frontend/` 下所有构建配置
   - 后端 Admin API 的认证、刷新令牌、CORS 和相关响应结构
2. 不得凭空修改后端 API 契约。
3. 尽量保持现有 UI、业务流程、路由和中文文案不变。
4. 所有高风险批量操作必须继续保留人工确认。
5. 不允许通过关闭 TypeScript strict、忽略构建错误、批量添加 eslint-disable、使用 `any` 或删除测试来“通过检查”。
6. 每完成一个阶段都运行对应检查；发现失败应继续修复，而不是只记录问题。
7. 不提交 `.env`、密钥、token、生产地址或用户数据。
8. 不执行 `docker compose down`，不覆盖服务器环境文件。

## 二、P0：恢复可重复构建工程

检查 `admin-frontend/` 是否缺少或损坏以下文件：

- `package.json`
- 唯一且有效的依赖锁文件
- `tsconfig.json`
- `next.config.ts`
- PostCSS/Tailwind 配置
- ESLint 配置
- `.env.example`

要求：

1. 使用仓库实际技术栈：
   - Next.js 16
   - React 19
   - TypeScript
   - Tailwind CSS 4
   - TanStack Query
   - Zustand
   - ECharts/Recharts
   - KaTeX
2. 不要随意升级大版本。优先从现有锁文件、Dockerfile、部署文件或历史配置还原真实版本。
3. 增加以下 npm scripts：
   - `dev`
   - `build`
   - `start`
   - `typecheck`
   - `lint`
   - `test`
   - `check`，依次执行 typecheck、lint、test、build
4. 使用锁文件支持 `npm ci`，不要只保证 `npm install` 可用。
5. 检查 Docker 构建是否使用 `npm ci` 和多阶段构建。
6. 创建安全的 `.env.example`，至少记录：
   - `NEXT_PUBLIC_ADMIN_API_BASE_URL`
7. `NEXT_PUBLIC_ADMIN_API_BASE_URL` 的生产默认值优先使用同源 `/api/admin/v1`，不要在生产 bundle 中默认写死 `http://localhost:8000`。

## 三、P0：解决低内存服务器构建风险

当前生产服务器约 1.8 GB 内存，Next.js 默认并行构建可能 OOM。

请：

1. 检查生产部署究竟是在服务器原地构建，还是在 CI/镜像构建。
2. 优先改为：
   - CI 构建镜像；
   - 推送到镜像仓库；
   - 服务器只拉取并启动已构建镜像。
3. 若仓库现阶段必须服务器构建：
   - 合理限制 Next.js 构建 CPU/worker；
   - 设置受控的 `NODE_OPTIONS`；
   - 在部署文档中说明 swap 和可用内存前置检查；
   - 构建失败时不得影响当前在线容器；
   - 先构建成功，再原子切换。
4. 不要盲目设置过低内存上限导致构建随机失败。
5. 实际记录：
   - 构建时长；
   - 峰值 RSS；
   - 产物大小。
6. 在 `docs` 或部署说明中增加低内存部署和回滚步骤。

## 四、P1：修复确定存在的功能问题

### 4.1 公式筛选依赖

检查：

```
admin-frontend/src/app/(admin)/formulas/page.tsx
```

`queryParams` 使用了 `filters.graph_status`，但 memo 依赖可能缺失。

要求：

- 补全依赖；
- 确保修改每个筛选项都会立即产生正确 query key 和请求参数；
- 增加测试，验证 `graph_status` 修改能触发新查询。

### 4.2 登录跳转安全

检查：

```
admin-frontend/src/app/(auth)/login/page.tsx
```

不要直接信任 URL 中的 `next`。

实现一个可测试的 `safeInternalRedirect`：

- 只允许以单个 `/` 开头的站内路径；
- 拒绝 `//`；
- 拒绝带 scheme 的地址；
- 拒绝控制字符和反斜杠绕过；
- 避免重定向回 `/login` 形成循环；
- 无效时回退到 `/dashboard`。

为以下输入增加单测：

- `/questions`
- `/formulas/123?tab=graph`
- `//evil.example`
- `https://evil.example`
- `javascript:alert(1)`
- `\\evil.example`
- `/login`

### 4.3 API 客户端认证恢复

重构：

```
admin-frontend/src/lib/api/client.ts`
`admin-frontend/src/lib/auth/auth-store.ts
```

要求：

1. access token 过期并收到 401 时，最多执行一次 refresh。
2. 多个并发请求同时收到 401 时，只允许一个 refresh 请求在飞行，其他请求等待同一个 Promise。
3. refresh 成功后更新 token，并重放原始请求一次。
4. refresh 请求自身不能进入无限重试。
5. 原始请求最多重放一次。
6. refresh 失败时：
   - 清理认证状态；
   - 清理 TanStack Query 中的用户敏感缓存；
   - 跳转 `/login`；
   - 保留安全的站内 `next`。
7. 对 403、404、409、422、429、5xx 给出可区分的标准错误对象。
8. 支持调用方传入 AbortSignal。
9. 设置合理默认超时，例如普通请求 15–30 秒；上传、OCR、AI 请求允许显式覆盖。
10. FormData 不要手动设置 Content-Type。
11. 为 401 单飞刷新、重放失败、超时和 abort 编写单元测试。

避免 auth store 与 api client 形成不可维护的循环依赖。可以通过注册 callback、独立 token manager 或 auth event bus 解耦。

### 4.4 SSE 可靠性

重构：

```
admin-frontend/src/lib/api/sse.ts
```

要求：

- 显式使用正确 credentials；
- 支持 `onOpen`、`onError`、`onClose`、`onTrace`、`onDone`；
- 非 2xx 响应必须返回结构化错误；
- 单条损坏 JSON 不得导致整个读取循环静默退出；
- 支持跨 chunk 的 SSE 行和事件；
- 正确处理 `\r\n`；
- 正确处理多行 `data:`；
- 有心跳超时；
- 可配置有限次数的指数退避重连；
- 用户主动 abort 不显示错误；
- 流结束但没有 done 时，必须进入可见失败状态；
- token 失效时复用统一 refresh 机制或明确终止并要求重新认证。

补充测试覆盖：

- 正常 trace + done；
- 数据跨 chunk；
- CRLF；
- 损坏 JSON；
- 401；
- 网络中断；
- 主动 abort；
- 无 done 直接 EOF。

### 4.5 自定义选择器

检查：

```
admin-frontend/src/components/ui/custom-select.tsx
```

当前 active index 若保存在 ref 中并用于 JSX 高亮，会造成键盘操作后 UI 不重渲染。

要求：

- 将影响渲染的 active index 改为 state；
- ref 只用于 DOM；
- 支持 ArrowUp、ArrowDown、Home、End、Enter、Escape；
- 跳过 disabled option；
- 搜索结果变化后校正 active index；
- 添加正确的 combobox/listbox aria 属性；
- 点击外部、滚动和窗口 resize 后行为正确；
- 添加 React Testing Library 测试。

### 4.6 图片缓存版本

检查：

```
admin-frontend/src/components/formulas/formula-graph-spec-panel.tsx
```

禁止在 render 中使用：

```
Date.now()
```

要求：

- 仅在图片上传、生成或删除成功时更新 image version；
- 普通 state 变化不得重新下载预览图；
- URL 已有 query 参数时正确追加版本参数；
- 使用 `next/image` 前先确认远程域名和动态图像是否适合；不适合时可保留 `<img>`，但补充尺寸或 aspect ratio，减少布局偏移。

## 五、P1：React 19 和 lint 修复

配置正式 ESLint，并至少包含：

- TypeScript 推荐规则；
- React Hooks 推荐规则；
- 未使用变量检查；
- 禁止无理由的 `any`；
- 禁止生产代码随意 console.log。

重点修复：

- effect 中不必要的同步 setState；
- Hook 缺失依赖；
- render 阶段读取会影响 UI 的 ref；
- render 阶段调用不纯函数；
- 无法保留的手工 memo；
- 未使用 import 和变量。

已知重点文件包括：

- `ai-completion.tsx`
- `formulas/page.tsx`
- `imports/batch-image/page.tsx`
- `formula-category-picker.tsx`
- `formula-graph-spec-panel.tsx`
- `custom-select.tsx`
- `drawer.tsx`
- `select.tsx`

不要机械修复。对每个 effect 判断：

- 是否可以改为初始 state；
- 是否可以在事件处理函数中更新；
- 是否可以由派生值直接计算；
- 是否确实需要与外部系统同步。

## 六、P1/P2：性能重构

先测量，再改动。不要为了拆文件而拆文件。

### 6.1 拆分巨型页面

优先处理：

- `imports/review/page.tsx`
- `questions/page.tsx`
- `formulas/page.tsx`
- `formula-editor-form.tsx`
- `formula-graph-spec-panel.tsx`
- `imports/tasks/page.tsx`
- `imports/batch-image/page.tsx`

按职责拆分：

- query hooks；
- mutation hooks；
- filter state；
- table/list；
- detail drawer；
- batch action bar；
- dialogs；
- local draft；
- keyboard shortcuts；
- preview/editor panels。

目标：

- 页面文件只负责编排；
- 业务请求和 mutation 放到稳定的 hooks/service 层；
- 组件 props 清晰；
- 避免一次 state 变化重渲染整个 190 KB 页面。

### 6.2 动态加载重组件

检查并按实际 bundle 数据决定是否动态导入：

- ECharts；
- Recharts；
- 公式图像编辑器；
- 图像配置面板；
- 大型详情抽屉；
- 仅打开弹窗后才需要的组件。

要求：

- 不影响首屏关键交互；
- 提供 loading skeleton；
- 避免同一页面同时引入 ECharts 和 Recharts，除非确有必要；
- 记录优化前后各主要路由的 gzip JS 体积。

建议性能预算：

- 登录页首批 JS gzip 尽量低于 140 KiB；
- 常规列表页尽量低于 200 KiB；
- 复杂编辑页尽量低于 250 KiB；
- AI 设置页从当前量级显著下降；
- 不允许只通过关闭 source map 或压缩统计来伪造下降。

### 6.3 查询和渲染

检查：

- 搜索输入是否 debounce；
- 翻页是否保留上一页数据；
- query key 是否稳定；
- mutation 后是否精确 invalidate；
- 是否存在不必要的全局 refetch；
- 大列表是否需要虚拟化；
- `items ?? []` 是否每次 render 创建新数组并破坏 memo；
- 频繁事件是否需要 requestAnimationFrame 或节流；
- 页面卸载后异步回调是否仍 setState。

### 6.4 静态资源

将弃用的 `static/` 资源迁移到 `public/`，更新引用，并确保：

- 没有 Windows 快捷方式；
- 没有 `Zone.Identifier`；
- 没有临时文件；
- 没有备份副本；
- 大图片经过压缩；
- 缓存策略正确。

## 七、错误边界和可观测性

增加适合 App Router 的：

- `error.tsx`
- `loading.tsx`
- 必要的 `not-found.tsx`

要求：

- 错误页支持重试；
- 不向用户泄露 token、请求头或敏感响应；
- 401 与一般错误区分；
- TanStack Query 错误状态不能只渲染空白；
- 批量任务错误应显示失败项和重试入口；
- 若项目已接入 Sentry，使用现有配置，不重复初始化；
- 若未接入，只预留清晰接口，不擅自加入收费依赖。

## 八、测试和 CI

至少建立以下门禁：

```bash
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

增加关键 E2E 测试，优先使用仓库已有测试框架；若没有，可加入 Playwright：

1. 未登录访问 `/dashboard` 跳转登录；
2. 登录成功回到安全的 next 页面；
3. 恶意 next 被拒绝；
4. token 过期后只 refresh 一次；
5. 无权限用户看不到对应导航和操作；
6. 公式 `graph_status` 筛选请求正确；
7. 批量图片导入 SSE 成功、失败、中断；
8. 自定义 select 键盘操作；
9. 公式图片预览不会因无关 render 重载。

CI 中缓存 npm 和 Next build cache，但锁文件变化必须正确失效。

## 九、安全和配置检查

检查并合理配置：

- CSP；
- `X-Content-Type-Options`;
- `Referrer-Policy`;
- `Permissions-Policy`;
- frame-ancestors 或 X-Frame-Options；
- source map 是否公开；
- 生产环境是否泄露 localhost 地址；
- remote image host；
- CORS 与 cookie 的 SameSite/Secure 策略；
- refresh cookie 是否 HttpOnly；
- 管理端 API 是否由后端强制 RBAC，而非只靠前端隐藏按钮。

不要在不理解现有 Nginx 配置时重复或冲突地添加 Header。先检查 Nginx 和 Next 的职责边界。

## 十、最终验收标准

完成后必须满足：

1. 从干净目录执行 `npm ci` 成功。
2. `npm run typecheck` 零错误。
3. `npm run lint` 零错误；warning 必须解释，原则上也应清零。
4. 所有单元测试通过。
5. 所有新增 E2E 通过。
6. `npm run build` 稳定通过。
7. 构建不会在 1.8 GB 生产服务器流程中直接 OOM，或者生产流程已改为服务器外构建。
8. 登录跳转不存在开放重定向。
9. 并发 401 只产生一次 refresh。
10. SSE 中断不会让 UI 永久停留在处理中。
11. `graph_status` 筛选能正确请求。
12. 键盘选择器高亮和选择行为正确。
13. 预览图片不会在无关重渲染时重新请求。
14. 不再使用弃用的 `static/` 目录。
15. 主要路由 bundle 大小有优化前后对比。
16. 不改变现有 Admin API 契约。
17. 不提交密钥或生产环境值。

## 十一、最终输出格式

完成修改后，请输出：

1. 上线结论：Go / Conditional Go / No-Go。
2. 修改文件列表。
3. 按 P0、P1、P2 分类的修复摘要。
4. 执行过的命令及其结果。
5. 测试数量和结果。
6. 构建时间、峰值内存和主要页面 bundle 对比。
7. 尚未解决的问题及原因。
8. 部署和回滚步骤。
9. 需要人工验证的清单。
10. 不要只说“已修复”，必须提供可复核的命令输出摘要和关键实现说明。