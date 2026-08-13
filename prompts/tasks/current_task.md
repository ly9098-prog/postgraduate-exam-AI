请修改当前 MemoGrad 微信原生小程序项目的“分包预下载”策略。

## 背景

这是一个微信原生小程序，不是 uni-app。

当前 `app.json` 已经配置了以下分包：

- `animation`
  - root: `subpackages/animation`
- `formulas`
  - root: `subpackages/formulas`
- `productivity`
  - root: `subpackages/productivity`
- `study`
  - root: `subpackages/study`
- `export`
  - root: `subpackages/export`

当前已有：

```json
"preloadRule": {
  "pages/pomodoro/pomodoro": {
    "network": "all",
    "packages": ["productivity"]
  }
}
```

请在修改前自行检查当前代码，确认上述结构仍然成立，不要盲目覆盖其他最新改动。

------

# 目标

优化用户第一次进入核心学习页面时出现的“正在加载模块”或分包冷加载等待。

核心原则：

1. 首页进入后，预下载 `study` 分包。
2. dashboard 进入后，也确保 `study` 分包可以被预下载。
3. 保留现有 `pomodoro -> productivity` 预下载。
4. 不预下载 `formulas`。
5. 不预下载 `animation`。
6. 不预下载 `export`。
7. 不引入后端判断。
8. 不新增没有必要的 `wx.loadSubpackage` 调度代码。
9. 不改变现有分包结构。

------

# 为什么这样做

请结合当前代码确认以下页面跳转关系：

首页 `pages/home/home.js` 中：

```js
startRandom()
```

进入：

```text
/subpackages/study/practice/practice
goWrongBook()
```

进入：

```text
/subpackages/study/wrong-book/wrong-book
goReview()
```

进入：

```text
/subpackages/study/review-today/review-today
```

也就是说，首页三个核心学习行为都依赖 `study` 分包，因此 `study` 是首页之后概率最高的下一跳分包。

同时：

```js
goFormulas()
```

才会进入 `formulas`，它只是工具区的一个入口，因此不要为了它增加首页网络竞争。

`animation` 分包当前已经有专门的懒加载设计：

- `app.js`
- `utils/animation-loader.js`
- `getApp().loadRewardAnimationPackage()`
- `wx.loadSubpackage`

代码注释已经明确表达“动画分包按需加载，不在启动时主动下载”。

因此：

**不要修改 animation 的现有懒加载策略。**

------

# 需要修改的内容

主要修改：

```text
app.json
```

将 `preloadRule` 调整为：

```json
"preloadRule": {
  "pages/home/home": {
    "network": "all",
    "packages": ["study"]
  },
  "pages/dashboard/dashboard": {
    "network": "all",
    "packages": ["study"]
  },
  "pages/pomodoro/pomodoro": {
    "network": "all",
    "packages": ["productivity"]
  }
}
```

注意：

- 使用分包 `name`：`study`、`productivity`
- 不要错误填写页面路径作为 packages
- 不要删除原有 pomodoro 规则
- 保留：

```json
"lazyCodeLoading": "requiredComponents"
```

- 不修改 `subPackages` 中现有页面归属
- 不把任何分包重新移入主包

------

# 不要做的事情

不要为了“优化”而做以下改动：

### 1. 不要让首页同时预下载所有包

禁止改成类似：

```json
"packages": [
  "study",
  "formulas",
  "productivity",
  "animation",
  "export"
]
```

这样会违背拆包意义。

### 2. 不要首页预下载 formulas

`formulas` 包包含较大的 KaTeX / 公式渲染资源，属于低于核心学习流程优先级的工具功能。

保持第一次进入公式库时按需加载即可。

### 3. 不要首页预下载 animation

当前项目已经专门实现动画分包懒加载。

不要删除或绕过：

```js
loadRewardAnimationPackage()
```

也不要为了预下载 study 而重构 animation loader。

### 4. 不要预下载 export

`export` 是错题本中的深层低频功能。

现阶段维持按需加载。

### 5. 不要新增后端 API

不要增加：

```text
/preload-strategy
/prefetch
/user-package-strategy
```

等接口。

此次优化完全由微信小程序客户端的 `preloadRule` 完成。

### 6. 不要为了这个需求修改业务页面逻辑

除非发现明确 bug，否则不要修改：

```text
pages/home/home.js
pages/dashboard/dashboard.js
pages/pomodoro/pomodoro.js
```

本次应尽可能成为一个低风险的配置级优化。

------

# 验证

修改后执行以下检查。

## 1. JSON 合法性

确保：

```text
app.json
```

仍然可以正常 JSON.parse。

不要留下：

- 注释
- trailing comma
- 重复 key

------

## 2. 分包名称合法性

检查 `preloadRule.packages` 中所有名字都存在于：

```json
subPackages[].name
```

最终应该包含：

```text
study
productivity
```

------

## 3. 页面路径合法性

确认：

```text
pages/home/home
pages/dashboard/dashboard
pages/pomodoro/pomodoro
```

均属于主包 `pages`。

------

## 4. 不破坏已有行为

确认：

```text
pages/home/home
    ↓
study

pages/dashboard/dashboard
    ↓
study

pages/pomodoro/pomodoro
    ↓
productivity
```

对应的页面跳转仍然正常。

------

## 5. 检查现有测试

运行项目中与此次修改可能相关、且不依赖真实微信客户端的 Node 测试。

至少保证此次修改没有破坏 JSON 或项目静态结构。

不要为了让测试通过而修改无关业务代码。

------

# 微信开发者工具人工验证说明

代码修改完成后，请在最终报告中告诉开发者按下面步骤验证：

### 首页

1. 清理微信开发者工具缓存。
2. 重新编译。
3. 登录并进入：

```text
pages/home/home
```

1. 观察 Console / 调试信息中的分包 preload 信息。
2. 等待首页停留一小段时间。
3. 分别测试：
   - 今日练习
   - 今日复习
   - 错题本

重点观察第一次点击时是否还出现明显：

```text
正在加载模块
```

或者分包下载等待。

------

### Dashboard

重新清缓存后，如果可以直接编译进入：

```text
pages/dashboard/dashboard
```

确认 `study` 同样触发预下载。

然后点击：

- 复习
- 刷题
- 错题本

确认页面正常进入。

------

### 番茄钟

进入：

```text
pages/pomodoro/pomodoro
```

确认原来的：

```text
productivity
```

预下载仍然存在。

随后点击：

```text
学习统计
```

确认：

```text
/subpackages/productivity/pomodoro-stats/index
```

正常打开。

------

# 性能策略要求

这次不要追求“所有分包页面第一次都秒开”。

正确目标是：

```text
主包
↓
首页快速可用
↓
后台预下载高概率的 study
↓
用户点击练习 / 复习 / 错题本
↓
study 大概率已经下载完成
```

同时保持：

```text
formulas → 按需
animation → 按需
export → 按需
```

从而避免首页加载后立刻抢占过多网络资源。

------

# 可选的后续优化

此次不要直接实施，只在最终报告里作为建议列出：

如果以后有真实埋点证明：

```text
错题本用户 → 导出功能
```

的点击率很高，可以再评估：

```text
subpackages/study/wrong-book/wrong-book
    ↓
preload export
```

但现在不要添加。

同理，如果公式库成为首页非常高频的下一跳，再根据真实数据考虑 formulas，而不是现在凭感觉预加载。

------

# 最终输出

完成修改后，请输出：

1. 修改了哪些文件
2. `app.json` 最终 `preloadRule`
3. 为什么只预下载 `study` 和 `productivity`
4. 明确说明没有预下载：
   - formulas
   - animation
   - export
5. 是否修改了任何 JS 业务代码
6. 执行了哪些验证
7. 微信开发者工具中如何人工确认预下载生效
8. 如发现微信当前工具版本对 preload 大小存在构建限制，请报告实际构建结果，不要自行重构项目规避
9. 给出最终 git diff 摘要

优先采用最小改动方案，不进行无关重构。
