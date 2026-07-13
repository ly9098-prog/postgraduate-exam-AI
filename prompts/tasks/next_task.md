# MemoGrad 公式模块精准修复任务 Prompt

你正在维护 MemoGrad 完整项目仓库，项目包含：

```text
backend/
admin-frontend/
miniprogram/
```

请直接修复当前公式模块问题，不要只输出分析或改造建议。先阅读根目录 `CLAUDE.md`、相关架构文档、现有测试配置和实际源码，再按下列任务修改、测试并给出验收结果。

---

## 一、已通过源码确认的根因

### 1. 侧边栏重复高亮

文件：

```text
admin-frontend/src/components/layout/sidebar.tsx
admin-frontend/src/lib/routes.ts
```

当前逻辑：

```ts
pathname === route.href || pathname.startsWith(`${route.href}/`)
```

因此 `/formulas/categories` 和 `/formulas/review` 同时命中 `/formulas`，造成截图中“公式库”和“公式分类”同时高亮。

### 2. 管理端公式详情没有真实 LaTeX 渲染

文件：

```text
admin-frontend/src/app/(admin)/formulas/page.tsx
admin-frontend/src/app/(admin)/formulas/[id]/page.tsx
```

当前公式块使用：

```tsx
<pre>{block.latex}</pre>
```

项目现有：

```text
admin-frontend/src/components/ui/math-formula.tsx
```

只是字符替换和上下标近似显示，不是真实 KaTeX 渲染，不能用于公式库详情。

### 3. 公式列表页使用了页面内局部下拉框

文件：

```text
admin-frontend/src/app/(admin)/formulas/page.tsx
```

该页面在本文件内重复定义 `CustomSelect`，没有外部点击关闭能力。

共享组件：

```text
admin-frontend/src/components/ui/custom-select.tsx
```

虽然使用 Portal，但当前外部点击监听只判断触发器 `ref`，没有判断 Portal 面板节点，所以共享组件也需要一起修复。

### 4. 分类筛选被展平为超长普通下拉

`formulas/page.tsx` 当前通过 `flattenCategories()` 把三级分类全部展开为字符串选项，产生截图中长文本、难查找、难浏览的问题。

### 5. 新建和编辑页面仍使用原生 select

文件：

```text
admin-frontend/src/app/(admin)/formulas/new/page.tsx
admin-frontend/src/app/(admin)/formulas/[id]/page.tsx
```

均存在原生 `<select>`，且只通过 `depth === 2` 判断可选分类。

### 6. 新建公式页面为单列长表单

`/formulas/new` 当前依次纵向排列分类、标题、别名、摘要、标签、公式块、适用条件、符号说明、易错提醒、例题和保存按钮，导致频繁滚动。

### 7. 小程序“无公式数据”的前端根因已确认

文件：

```text
miniprogram/utils/api.js
miniprogram/subpackages/formulas/library/index.js
miniprogram/subpackages/formulas/reader/index.js
```

`utils/api.js` 的 `request()` 最终已经直接返回：

```js
return res.data
```

但公式页面仍然二次读取：

```js
res.data?.items
res.data || {}
```

因此目录、标签、公式列表、详情和收藏列表都被错误解析为空。

当前错误位置包括但不限于：

```js
// library/index.js
const catalog = res.data?.items || []
this.setData({ tags: res.data?.items || [] })
const data = res.data || {}

// reader/index.js
const card = this.enrichCard(res.data || {})
const favIds = (res.data?.items || []).map(...)
```

此外 `enrichCard()` 是 `async`，但调用方没有 `await`，会把 Promise 写入 `displayCards`。

### 8. 小程序 WXSS 警告根因已确认

警告指向：

```text
components/mp-html/index.wxss:41:8
```

实际来自其导入文件：

```text
miniprogram/components/mp-html/latex/katex.wxss
```

第 41～42 行使用了组件 WXSS 不允许的标签选择器：

```css
.katex view,
.katex text {
  ...
}
```

不要误删整个 KaTeX 样式，也不要关闭微信警告。应把该规则改为合法类选择器，并同步确保 KaTeX 生成节点带有对应 class；若现有节点本身已有可复用 class，则优先改为已有 class 组合，不要无意义修改渲染树。

### 9. `noop` 缺失根因已确认

文件：

```text
miniprogram/subpackages/formulas/library/index.wxml
```

存在：

```xml
catchtap="noop"
```

但：

```text
miniprogram/subpackages/formulas/library/index.js
```

没有 `noop()` 方法。

### 10. 分类管理页间距和新建位置问题已确认

文件：

```text
admin-frontend/src/app/(admin)/formulas/categories/page.tsx
```

当前树容器使用：

```tsx
<div className="space-y-1">
```

新建表单位于分类树底部；并且当前创建请求把 `node_type` 固定写成 `group`，行内加号仅出现在 `group` 节点，却把 `parent_id` 设置为 `cat.parent_id`，实际语义是创建同级分组，和“添加子分类”图标不一致。

---

## 二、总体开发要求

1. 基于现有架构做最小、可维护的修复，不重写整个公式领域。
2. 管理端继续使用 Next.js App Router、React、TanStack Query、现有 RBAC 和设计变量。
3. 小程序继续使用原生微信小程序和现有 `mp-html + KaTeX`。
4. 不改变现有后端字段、状态机和接口路径，除非扫描后端确认前后端确实不一致。
5. 不在前端硬编码公式数据。
6. 不通过屏蔽警告、关闭校验、延时 hack 或整页刷新掩盖问题。
7. 所有管理端写操作继续接入现有审计日志和权限控制。
8. 完成后必须实际运行管理端 lint/typecheck/build、小程序静态检查及后端公式相关测试。

---

# 三、具体修复任务

## 任务 1：修复侧边栏唯一高亮

重构路由激活逻辑，确保任意路径最多只有一个菜单项激活。

建议在 `src/lib/routes.ts` 中增加明确匹配策略，或实现纯函数：

```ts
getActiveAdminRoute(pathname: string, routes: AdminRoute[]): AdminRoute | null
```

推荐规则：

1. 路径必须满足完整段边界匹配；
2. 多个候选命中时，选择 `href` 最长、最具体的一项；
3. `/formulas/new` 和 `/formulas/{id}` 归属“公式库”；
4. `/formulas/categories` 只归属“公式分类”；
5. `/formulas/review` 及其子路径只归属“公式审核”。

验收矩阵：

| 当前路径               | 唯一高亮 |
| ---------------------- | -------- |
| `/formulas`            | 公式库   |
| `/formulas/new`        | 公式库   |
| `/formulas/57`         | 公式库   |
| `/formulas/categories` | 公式分类 |
| `/formulas/review`     | 公式审核 |
| `/formulas/review/57`  | 公式审核 |

不得通过在 JSX 中不断追加特殊判断完成。

---

## 任务 2：实现真实、安全的 LaTeX 渲染

新增统一组件，例如：

```text
admin-frontend/src/components/ui/latex-renderer.tsx
```

先检查完整仓库 `package.json`：

- 已安装 `katex` 时直接复用；
- 未安装时添加 `katex` 及必要类型；
- 在合适的全局入口引入 `katex/dist/katex.min.css`。

组件要求：

```ts
type LatexRendererProps = {
  latex: string;
  displayMode?: boolean;
  className?: string;
  showSourceOnError?: boolean;
};
```

KaTeX 配置至少为：

```ts
{
  displayMode,
  throwOnError: false,
  strict: "warn",
  trust: false,
  output: "htmlAndMathml"
}
```

必须处理：

- `$...$`
- `$$...$$`
- `\(...\)`
- `\[...\]`
- 无分隔符纯 LaTeX
- 空字符串
- 无效 LaTeX
- 长公式横向滚动

不得开启 `trust: true`，不得直接信任用户 HTML。

替换：

```text
/formulas 列表页详情抽屉中的公式块
/formulas/[id] 只读详情中的公式块
/formulas/new 公式块实时预览
/formulas/[id] 编辑状态实时预览
```

验收公式：

```latex
\lim_{x\to 0}\frac{\sin x}{x}=1
```

必须显示为真实极限和分式排版。

---

## 任务 3：统一并修复 CustomSelect

删除 `formulas/page.tsx` 内部局部 `CustomSelect`，统一使用：

```text
admin-frontend/src/components/ui/custom-select.tsx
```

修复 Portal 外部点击：

```ts
const triggerRef = useRef<HTMLDivElement>(null)
const dropdownRef = useRef<HTMLDivElement>(null)
```

外部点击必须同时排除触发器和 Portal 面板：

```ts
if (
  !triggerRef.current?.contains(target) &&
  !dropdownRef.current?.contains(target)
) {
  close()
}
```

推荐使用 `pointerdown` capture 监听，避免选项点击和关闭顺序错误。

同时实现：

- 点击页面其他区域关闭；
- `Escape` 关闭并把焦点还给触发器；
- 选择后关闭；
- 点击搜索输入框不关闭；
- 清除按钮不触发打开；
- 禁用选项不可选；
- 窗口 resize/滚动时重新定位或关闭；
- 卸载时清理监听；
- 正确的 combobox/listbox/option ARIA；
- 同一页面打开新下拉时，旧下拉关闭。

验收：截图中的“全部状态”打开后，点击表格、标题、搜索框外部、页面空白区均能关闭。

---

## 任务 4：把“全部分类”改为树形分类选择器

新增可复用组件：

```text
admin-frontend/src/components/formulas/formula-category-picker.tsx
```

支持：

```ts
mode: "filter" | "form"
```

### filter 模式

用于 `/formulas`：

- 显示科目 → 章节 → 分组树；
- 可展开/收起；
- 可按名称和编码搜索；
- 顶部提供“全部分类”；
- 当前选中节点有明确状态；
- 触发器显示完整路径；
- 最大高度 360～420px，内部滚动；
- 选择后关闭；
- 点击外部关闭；
- 支持清除。

根据后端真实筛选语义决定：

- 若 `category_id` 支持父节点递归筛选，可选择任意层级；
- 若只支持叶子分类，则科目和章节仅作为导航，只允许选择 `group`。

不得为了 UI 擅自修改 API 语义。

### form 模式

用于 `/formulas/new` 和 `/formulas/[id]`：

- 只允许选择可承载公式的叶子分类；
- 不能再用 `depth === 2` 作为唯一判断，应使用 `node_type === "group"`；
- 显示完整路径，例如：

```text
高等数学 / 函数、极限与连续 / 极限基础公式
```

---

## 任务 5：替换新建和编辑页原生 select

替换：

```text
admin-frontend/src/app/(admin)/formulas/new/page.tsx
admin-frontend/src/app/(admin)/formulas/[id]/page.tsx
```

中的公式分类 `<select>`，统一使用 `FormulaCategoryPicker`。

必须满足：

- 保持请求字段 `category_id` 不变；
- 编辑页正确回显；
- 加载中禁用；
- 加载失败显示错误及重试；
- 未选分类显示字段级错误；
- 非 `group` 节点不能提交。

---

## 任务 6：重构 `/formulas/new` 为紧凑编辑工作台

优先抽取复用组件：

```text
FormulaEditorForm
FormulaBlockEditor
FormulaCategoryPicker
LatexRenderer
```

桌面端改为两栏：

```text
┌──────────────────────────────────────────────┐
│ 返回  新建公式             取消  保存草稿    │ sticky
├────────────────────────────┬─────────────────┤
│ 公式内容主区                │ 基础信息 sticky │
│ - 公式块编辑                │ - 分类          │
│ - LaTeX 实时预览            │ - 标题          │
│ - 补充说明折叠区            │ - 别名          │
│ - 典型例题折叠区            │ - 标签          │
│                            │ - 摘要          │
└────────────────────────────┴─────────────────┘
```

要求：

- 1440×900 下，分类、标题、标签、第一个公式块和保存按钮均可在首屏操作；
- 顶部操作栏 sticky；
- 右侧基础信息区 sticky；
- 移动端自动回落单列；
- 每个公式块采用“编辑 + 实时预览”布局；
- 添加公式块按钮在公式块区域顶部可见；
- 适用条件、符号说明、易错提醒放入折叠区；
- 例题默认折叠，标题显示数量，例如 `典型例题（1/3）`；
- 保存失败保留输入；
- 必填错误聚焦或滚动到对应字段；
- 不改变当前创建 payload 和 1～8 个公式块、最多 3 个例题限制。

`/formulas/[id]` 编辑状态尽量复用同一表单组件，避免继续维护两套表单。

---

## 任务 7：修复小程序公式模块

### 7.1 修复 API 响应解包

统一公式模块使用 `api.request()` 的真实返回值。

因为 `api.request()` 已直接返回响应 body，公式页面应写成：

```js
const data = await api.request(...)
const items = data.items || []
```

而不是：

```js
res.data.items
```

至少修复：

```text
miniprogram/subpackages/formulas/library/index.js
miniprogram/subpackages/formulas/reader/index.js
```

包括：

- catalog；
- tags；
- formula list；
- formula detail；
- random formula；
- favorites list。

### 7.2 修复 async enrichCard

当前：

```js
const card = this.enrichCard(...)
```

必须改为：

```js
const card = await this.enrichCard(...)
```

否则 `displayCards` 中会放入 Promise。

### 7.3 校验接口路径

扫描后端真实公共 API 路由，核对当前小程序使用的：

```text
/formulas/favorites/list
/formulas/random/next
/formulas/tags
```

如果后端真实路径不同，只在统一 API 调用层和页面中改为真实路径，并补测试；不要同时保留多套猜测路径。

### 7.4 修复随机排重

当前 `_excludeIds` 仅收集但没有随请求发送。若后端支持 `exclude_ids`，应按真实 Schema 传递，最多保留合理数量；若不支持，不要伪造参数，应按后端实际实现修正。

### 7.5 修复 WXSS 标签选择器警告

处理：

```text
miniprogram/components/mp-html/latex/katex.wxss
```

中的：

```css
.katex view,
.katex text
```

改为合法类选择器，并确保渲染节点拥有相应 class。修改后扫描 `components/mp-html/**/*.wxss`，确认没有其他标签、ID、属性选择器警告。

不得破坏现有题目、错题和公式渲染。

### 7.6 修复 noop

在 `library/index.js` 增加实际存在的：

```js
noop() {}
```

或在确认不需要阻止冒泡后移除无意义绑定。

若保留弹层阻止穿透，继续使用：

```xml
catchtap="noop"
```

并确保方法存在。

### 7.7 改善加载状态

`library` 页面增加明确状态：

```text
initialLoading
loadingMore
loadError
empty
hasMore
```

要求：

- 接口错误不能显示成“暂无公式数据”；
- 错误状态提供“重新加载”；
- 切换科目、章节、标签、收藏和搜索时避免竞态覆盖；
- 搜索 timer 在页面卸载时清理；
- `onPullDownRefresh` 无论成功失败都必须停止；
- 有已发布数据时列表必须正常出现。

### 7.8 列表公式预览

当前列表页直接用 `<text>` 显示 `b.latex`，可继续作为轻量摘要，但至少要：

- 限制最多展示 1～2 个公式块；
- 长文本截断；
- 不撑破卡片；
- 详情阅读页继续使用 `formula-card + mp-html/KaTeX` 真实渲染。

---

## 任务 8：优化公式分类树可读性

修改：

```text
admin-frontend/src/app/(admin)/formulas/categories/page.tsx
```

要求：

- 根列表从 `space-y-1` 调整为更合理的视觉间隔；
- 展开子树增加 `mt-2` 和 `space-y-2`；
- 使用左侧层级引导线或淡色子树容器；
- 行最小高度和上下内边距一致；
- 科目、章节、分组标签区分清楚；
- 停用状态、hover、编辑状态清晰；
- 操作图标增加 `aria-label` 和 `title`；
- 小屏下名称、编码可换行；
- 保持树紧凑，不要变成松散的大卡片列表。

建议结构：

```tsx
<div className="space-y-2">
  <CategoryRow />
  {expanded && (
    <div className="mt-2 space-y-2 border-l pl-4">
      ...
    </div>
  )}
</div>
```

---

## 任务 9：把新建分类改为顶部弹窗或抽屉

新增：

```text
FormulaCategoryDialog
```

页面标题右上角固定显示“新建分类”，点击打开自定义 Dialog/Drawer，不再把表单放在页面底部。

层级规则必须严格为：

```text
subject → chapter → group
```

修复当前创建逻辑：

- 不再把 `node_type` 永久固定为 `group`；
- 不选父级时创建 `subject`；
- 父级为 `subject` 时创建 `chapter`；
- 父级为 `chapter` 时创建 `group`；
- `group` 不允许再创建子级。

行内加号规则：

- 科目行：添加子章节；
- 章节行：添加子分组；
- 分组行：不显示“添加子分类”；
- 若要提供添加同级，必须使用明确文字或 tooltip，不得继续用含义不明的加号。

创建成功后：

- 关闭弹窗；
- 清空表单；
- 刷新分类树；
- 自动展开父节点；
- 显示成功提示。

创建失败后：

- 弹窗保持打开；
- 保留输入；
- 显示字段级/API 错误。

---

# 四、测试与验收

## 管理端

先读取完整仓库 `package.json`，执行实际存在的命令，至少覆盖：

```bash
npm run lint
npm run typecheck
npm run build
```

测试重点：

1. 侧边栏唯一高亮；
2. `/formulas/categories` 不再高亮“公式库”；
3. 下拉点击外部关闭；
4. Portal 内部点击不误关闭；
5. Escape 关闭；
6. 分类树搜索、选择、清除；
7. 表单只能选择 group；
8. 编辑页正确回显；
9. KaTeX 正常渲染；
10. 无效 LaTeX 不导致页面崩溃；
11. 新建分类层级推断正确；
12. 新建/编辑 payload 与后端兼容。

## 小程序

至少确认：

- 不再出现 `Some selectors are not allowed in component wxss`；
- 不再出现 `does not have a method "noop"`；
- catalog、tags、list、detail 能正确读取响应；
- `displayCards` 中不是 Promise；
- 有已发布公式时正常展示；
- 网络错误显示错误状态；
- 切换筛选、搜索、分页、收藏无明显回归；
- 控制台无未处理 Promise。

## 后端

扫描并运行公式相关测试，核对：

- 公共公式路由真实路径；
- 只返回 `published`、未软删除、分类有效的数据；
- 开发数据库是否存在已发布公式；
- 若没有，使用现有幂等 seed 插入开发测试数据；
- 禁止生产环境自动发布 AI 内容。

---

# 五、禁止事项

1. 不在小程序硬编码公式列表。
2. 不关闭微信警告来掩盖非法选择器。
3. 不把所有分类继续塞入普通下拉框。
4. 不保留公式页面局部重复 `CustomSelect`。
5. 不继续使用原生 `<select>`。
6. 不用字符替换模拟 LaTeX。
7. 不开启 KaTeX `trust: true`。
8. 不用 `pathname.startsWith('/formulas')` 直接判断所有公式菜单。
9. 不用整页刷新更新分类树。
10. 不修改无关模块的大量样式。

---

# 六、最终输出

完成后输出：

1. 1～9 项根因与修复结果；
2. 修改文件清单；
3. 新增组件清单；
4. 管理端测试命令与结果；
5. 小程序编译与接口验证结果；
6. 后端测试结果；
7. 真实公共公式 API 路径清单；
8. 数据库中 `published` 公式数量；
9. 若执行 seed，给出命令和插入数量；
10. 每项验收标准通过/不通过及证据；
11. 尚需人工处理的事项。

必须实际修改和验证代码，不要只输出计划。
