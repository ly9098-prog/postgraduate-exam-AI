请修复 admin-frontend 项目中“刷新页面 / 初次加载页面 / 数据重新拉取时页面跳动”的问题，确保后台管理系统在刷新、鉴权初始化、接口加载、筛选刷新、分页切换时布局稳定，不出现明显的上下跳动、左右宽度变化或内容突然位移。

## 问题背景

当前项目为 Next.js App Router + React Query + Zustand 的后台管理系统。用户在刷新后台页面或进入部分页面时，会看到页面发生跳动，主要表现为：

1. 刷新页面时，先出现一个居中的 `Session drafting...` 加载页，然后突然切换成完整后台布局，导致页面大幅跳动。
2. 首次加载数据时，页面骨架屏高度和真实内容高度不一致，数据返回后内容上移或下移。
3. React Query 重新拉取数据时，例如点击刷新、筛选、翻页，部分页面会插入“刷新中...”提示，导致列表整体下移。
4. 浏览器滚动条出现 / 消失时，页面宽度发生轻微变化，造成横向抖动。
5. 移动端或窄屏下，`h-screen` 可能受浏览器地址栏影响，刷新或加载时视口高度变化导致页面跳动。
6. 某些 `animate-rise-in`、`animate-drop-in` 动画在首屏加载时可能带来视觉上的“跳一下”。

## 重点排查文件

请重点检查并修改以下文件：

- `src/components/layout/admin-shell.tsx`
- `src/components/layout/sidebar.tsx`
- `src/components/layout/topbar.tsx`
- `src/app/globals.css`
- `src/app/(admin)/layout.tsx`
- `src/app/(admin)/audit-logs/page.tsx`
- `src/components/audit-logs/audit-log-list.tsx`

同时建议全局排查其他页面的 loading / skeleton / isFetching 状态：

- `src/app/(admin)/dashboard/page.tsx`
- `src/app/(admin)/questions/page.tsx`
- `src/app/(admin)/ai-settings/page.tsx`
- `src/app/(admin)/imports/**/page.tsx`

## 当前关键问题点

### 1. AdminShell 鉴权初始化导致整页结构切换

当前 `AdminShell` 在 `isBootstrapping` 时直接返回：

```tsx
<div className="grid min-h-screen place-items-center ...">
  Session drafting...
</div>
```

鉴权完成后才渲染：

```tsx
<div className="flex h-screen overflow-hidden">
  <Sidebar />
  <div className="flex min-w-0 flex-1 flex-col">
    <Topbar />
    <main className="flex-1 overflow-y-auto px-4 py-6 lg:px-8">
      {children}
    </main>
  </div>
</div>
```

这会导致刷新时 DOM 结构、宽度、高度、滚动容器、侧边栏、顶部栏全部重新出现，从而产生明显页面跳动。

## 修复目标

### 目标 1：刷新页面时后台布局不大幅跳动

刷新任意后台页面时，应尽量保持完整后台骨架布局：

- 左侧 sidebar 区域宽度稳定
- 顶部 topbar 高度稳定
- main 内容区 padding 稳定
- 页面滚动容器稳定
- 不要从一个居中 loading 页面突然切换到后台 layout

推荐将 `isBootstrapping` 状态改为“后台骨架屏”，而不是整页居中 loading。

建议新增或内联实现：

- `AdminShellSkeleton`
- `SidebarSkeleton`
- `TopbarSkeleton`
- `MainContentSkeleton`

结构应与真实后台布局一致：

```tsx
<div className="flex min-h-dvh overflow-hidden">
  <SidebarSkeleton />
  <div className="flex min-w-0 flex-1 flex-col">
    <TopbarSkeleton />
    <main className="flex-1 overflow-y-auto px-4 py-6 lg:px-8">
      <MainContentSkeleton />
    </main>
  </div>
</div>
```

不要再让 `isBootstrapping` 返回完全不同的居中页面结构。

### 目标 2：统一使用稳定视口高度

当前后台布局使用：

```tsx
<div className="flex h-screen overflow-hidden">
```

建议替换为更稳定的动态视口高度：

```tsx
<div className="flex h-dvh min-h-dvh overflow-hidden">
```

或：

```tsx
<div className="flex min-h-dvh overflow-hidden">
```

具体选择需要结合 main 内部滚动行为验证。

侧边栏也建议从：

```tsx
h-screen
```

调整为：

```tsx
h-dvh
```

或在父容器控制高度后使用：

```tsx
h-full
```

确保桌面端和移动端刷新时不会因为浏览器地址栏、系统 UI、高度计算变化导致页面跳动。

### 目标 3：稳定滚动条占位，避免横向抖动

请在 `src/app/globals.css` 中加入全局滚动条稳定策略：

```css
html {
  scrollbar-gutter: stable;
}
```

同时建议增加：

```css
html,
body {
  min-height: 100%;
}

body {
  min-height: 100dvh;
  overflow-x: hidden;
}
```

如果项目主要使用内部 main 容器滚动，而不是 body 滚动，也要确保：

- 外层 layout 不产生 body 横向滚动
- main 内部滚动条出现 / 消失不影响整体宽度
- 不同页面内容高度变化时不会导致 body 与 main 之间切换滚动容器

### 目标 4：修复数据刷新时列表整体下移

以 `/audit-logs` 为例，当前 `AuditLogList` 中存在：

```tsx
{isFetching && (
  <div className="mb-3 flex items-center gap-2 text-xs ...">
    <RefreshCw className="h-3 w-3 animate-spin" />
    刷新中...
  </div>
)}
```

这个元素只在 `isFetching` 时出现，会把下面的日志列表整体向下推，造成刷新时跳动。

请改成以下任一稳定方案。

方案 A：始终预留刷新提示高度：

```tsx
<div className="mb-3 h-4">
  {isFetching && !isLoading ? (
    <div className="flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
      <RefreshCw className="h-3 w-3 animate-spin" />
      刷新中...
    </div>
  ) : null}
</div>
```

方案 B：将刷新提示改为绝对定位，不参与文档流：

```tsx
<div className="relative">
  {isFetching && !isLoading ? (
    <div className="absolute -top-6 left-0 flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
      <RefreshCw className="h-3 w-3 animate-spin" />
      刷新中...
    </div>
  ) : null}

  <div className="space-y-2.5">
    ...
  </div>
</div>
```

推荐优先使用方案 A，更稳定、更简单。

### 目标 5：React Query 加载状态不要反复清空页面

对于分页、筛选、刷新类页面，请尽量保留上一份数据，避免每次参数变化时列表消失、骨架屏出现、真实内容再出现。

建议在相关 `useQuery` 中使用 React Query 的 `placeholderData` 或 `keepPreviousData` 思路。

例如 `/audit-logs` 页面可考虑：

```tsx
import { keepPreviousData, useQuery } from "@tanstack/react-query";

const logs = useQuery({
  queryKey: ["audit-logs", "list", queryParams],
  queryFn: () =>
    apiRequest<PaginatedResponse<AuditLogListItem>>(
      `/audit-logs${toQuery(queryParams)}`,
    ),
  retry: 1,
  staleTime: 10_000,
  refetchOnMount: "always",
  placeholderData: keepPreviousData,
});
```

要求：

- 首次进入页面时可以显示 skeleton
- 已经有旧数据时，筛选、分页、刷新不应清空列表
- `isFetching` 只展示轻量刷新状态
- 不要因为 `isLoading` / `isFetching` 判断错误导致列表闪烁

注意：

- 如果使用的是 React Query v5，优先使用 `placeholderData: keepPreviousData`
- 如果项目版本不支持，请按当前版本采用等价实现
- 不要引入新的第三方库

### 目标 6：骨架屏高度接近真实内容高度

检查各页面 skeleton，确保 skeleton 高度尽量接近真实内容。

以 `/audit-logs` 为例，当前 loading skeleton 为 5 条：

```tsx
Array.from({ length: 5 })
```

真实列表 pageSize 是 20，这会导致首屏加载完成后列表高度明显变长，页面可能跳动。

建议：

- skeleton 数量与首屏真实内容接近，例如 8 到 10 条
- 单条 skeleton 高度尽量接近 `AuditLogItem`
- 列表、分页、筛选区域都应有稳定占位
- 不要 loading 时整个列表容器高度过小

可以将 loading 区域改成：

```tsx
<div className="space-y-2.5">
  {Array.from({ length: 8 }).map(...)}
</div>
```

如果真实 `AuditLogItem` 高度较高，则 skeleton 也应使用接近的 padding、圆角、metadata 行高度。

### 目标 7：分页区域高度稳定

当前分页只在：

```tsx
{data.total > 20 && (...)}
```

时渲染。

如果加载前、加载后、筛选后 total 变化，分页区域出现 / 消失会导致页面底部跳动。

建议：

- 如果当前页面布局对跳动敏感，可以为分页区域预留最小高度
- 或者让分页容器始终存在，只在没有分页时隐藏内容但保留高度

例如：

```tsx
<div className="mt-4 min-h-9">
  {data.total > 20 ? (
    ...
  ) : null}
</div>
```

不要因为分页按钮出现 / 消失导致列表末尾明显跳动。

### 目标 8：减少首屏动画导致的视觉跳动

全局存在：

```css
.animate-rise-in {
  animation: rise-in 520ms ...
}
```

该动画会使用：

```css
transform: translateY(14px) scale(0.98);
```

在页面初次加载、数据加载完成、卡片出现时可能造成视觉上的“跳一下”。

请检查首屏核心布局，尤其是：

- 页面最外层容器
- 大卡片容器
- 列表容器
- dashboard 卡片
- ai-settings 区块

要求：

- 不要在核心页面布局容器上滥用 `animate-rise-in`
- 可以保留在非首屏、局部提示、弹层或轻量模块上
- 对骨架屏到真实内容切换时，不建议真实内容整体使用 translateY 动画
- 增加 motion reduce 支持

建议在 CSS 中补充：

```css
@media (prefers-reduced-motion: reduce) {
  .animate-rise-in,
  .animate-drop-in,
  .trace-enter,
  .stage-circle-done,
  .stage-circle-active::before {
    animation: none !important;
  }
}
```

如果某些页面加载完成后仍明显跳动，请优先移除首屏容器上的 `animate-rise-in`。

## 推荐实现步骤

### Step 1：重构 AdminShell bootstrapping 状态

修改 `src/components/layout/admin-shell.tsx`。

将当前：

```tsx
if (isBootstrapping) {
  return <div className="grid min-h-screen place-items-center ...">Session drafting...</div>;
}
```

改为渲染和真实后台布局一致的 skeleton shell。

要求：

- 桌面端 sidebar 宽度与真实 sidebar 一致：`lg:w-72`
- 移动端 sidebar 行为与真实布局一致：`lg:block`，小屏隐藏
- topbar 高度、padding 与真实 topbar 接近
- main 区域 padding 与真实 main 一致
- skeleton 不需要真实文字，但需要保留布局高度
- 不能导致未登录页面闪现后台真实内容
- 如果未认证，仍然允许跳转 `/login?next=...`

### Step 2：统一 AdminShell 高度和滚动容器

将后台布局容器从 `h-screen` 优化为 `h-dvh min-h-dvh` 或等价稳定写法。

示例：

```tsx
return (
  <div className="flex h-dvh min-h-dvh overflow-hidden">
    <Sidebar />
    <div className="flex min-w-0 flex-1 flex-col">
      <Topbar />
      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-6 lg:px-8">
        {children}
      </main>
    </div>
  </div>
);
```

注意 main 建议加：

```tsx
min-h-0
```

避免 flex 子项内部滚动异常。

### Step 3：同步修复 Sidebar 高度

修改 `src/components/layout/sidebar.tsx`。

将：

```tsx
h-screen
```

改为：

```tsx
h-dvh
```

或：

```tsx
h-full
```

取决于父容器实现。

推荐：

```tsx
<aside className="hidden h-dvh w-72 shrink-0 overflow-y-auto ... lg:block">
```

如果父容器已经 `h-dvh`，也可以使用：

```tsx
<aside className="hidden h-full w-72 shrink-0 overflow-y-auto ... lg:block">
```

### Step 4：修复全局滚动条和 overflow

修改 `src/app/globals.css`。

建议加入：

```css
html {
  min-height: 100%;
  background: var(--color-bg);
  scrollbar-gutter: stable;
}

body {
  min-height: 100dvh;
  margin: 0;
  overflow-x: hidden;
  ...
}
```

保留现有背景、字体、颜色设置。

### Step 5：修复 `/audit-logs` 刷新跳动

修改 `src/app/(admin)/audit-logs/page.tsx`。

建议引入：

```tsx
import { keepPreviousData, useQuery } from "@tanstack/react-query";
```

并在 `useQuery` 中加入：

```tsx
placeholderData: keepPreviousData,
```

确保筛选、分页、刷新时不会把已有列表清空。

修改 `src/components/audit-logs/audit-log-list.tsx`。

重点：

1. `isLoading` 只表示首次无数据加载。
2. `isFetching` 不要插入会改变布局高度的新元素。
3. “刷新中...”提示应固定占位或绝对定位。
4. skeleton 数量和真实列表高度更接近。
5. 分页区域可预留最小高度。

示例方向：

```tsx
const showInitialLoading = isLoading && !data;

if (showInitialLoading) {
  return (
    <div className="space-y-2.5">
      {Array.from({ length: 8 }).map(...)}
    </div>
  );
}
```

刷新提示区域：

```tsx
<div className="mb-3 h-4">
  {isFetching && !isLoading ? (
    <div className="flex items-center gap-2 text-xs text-[var(--color-text-hint)]">
      <RefreshCw className="h-3 w-3 animate-spin" />
      刷新中...
    </div>
  ) : null}
</div>
```

分页区域：

```tsx
<div className="mt-4 min-h-9">
  {data.total > 20 ? (
    ...
  ) : null}
</div>
```

### Step 6：排查其他页面同类问题

请全局搜索以下关键词：

- `isLoading ?`
- `isFetching &&`
- `animate-rise-in`
- `h-screen`
- `min-h-screen`
- `Array.from({ length`
- `loading`
- `Session drafting`

重点检查是否存在以下问题：

- 加载时整个页面被替换成高度很小的 loading
- 加载完成后真实内容高度远大于 skeleton
- refetch 时插入提示条导致内容下移
- 分页、统计卡片、筛选栏在加载前后高度不一致
- 使用 `h-screen` 导致移动端高度变化
- 页面最外层容器使用 `animate-rise-in`

## 验收标准

### 刷新后台页面

请在以下页面直接浏览器刷新验证：

- `/dashboard`
- `/questions`
- `/audit-logs`
- `/ai-settings`
- `/imports/tasks`
- `/imports/review`

要求：

- 不再出现从居中 loading 页突然切换到后台布局的大幅跳动
- sidebar、topbar、main 区域尺寸稳定
- 页面不会左右抖动
- body 不出现横向滚动条
- main 滚动容器正常

### `/audit-logs` 页面

请验证：

- 首次进入页面 skeleton 高度合理
- 数据加载完成后列表不明显跳动
- 点击刷新时，日志列表不整体下移
- 筛选条件变化时，旧数据不会瞬间清空再重建
- 翻页时页面不大幅跳动
- 分页区域出现 / 消失不会造成明显跳动
- 空状态、错误状态仍正常显示

### 响应式验证

请至少验证以下宽度：

- 1440px
- 1024px
- 768px
- 390px

要求：

- 页面刷新时布局稳定
- 移动端地址栏变化不导致明显高度跳动
- 无页面级横向滚动
- sidebar 在桌面端宽度稳定，在移动端按当前设计隐藏

### 动画验证

请验证：

- 首屏核心布局不因 `animate-rise-in` 出现明显下落动画
- `prefers-reduced-motion: reduce` 下动画被禁用
- 弹层、局部提示、按钮 loading 动画不受破坏

## 非目标

本次任务不要修改：

- 登录接口
- 鉴权业务逻辑
- 权限判断逻辑
- API 参数结构
- 后端接口
- 页面业务功能
- 表格 / 列表数据字段
- 路由结构

除非确有必要，不要引入新的第三方依赖。

## 交付要求

完成后请提供：

1. 修改过的文件列表
2. 每个文件的核心改动说明
3. 页面跳动的根因说明
4. 本地验证步骤
5. 是否影响其他后台页面
6. 如果保留了某些轻微动画，请说明原因
7. 如果某些页面仍可能因为接口数据量变化产生高度变化，请说明剩余风险

## 预期结果

修复后，后台管理系统在刷新页面、初始化鉴权、接口加载、数据刷新、筛选、分页时应表现稳定：

- 不再从完全不同的 loading 页面跳到后台布局
- sidebar/topbar/main 尺寸稳定
- 列表刷新不整体下移
- 骨架屏和真实内容高度接近
- 滚动条出现 / 消失不引发横向抖动
- 移动端视口高度变化影响降低
- 不破坏现有鉴权、跳转、权限和数据加载逻辑
