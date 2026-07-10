# `pages/wrong-book` AI 诊断缓存与按需刷新专项优化

你是一名资深微信小程序前端工程师。请基于当前新版本代码，为：

```text
pages/wrong-book
```

增加可靠的 AI 诊断缓存机制。

最终必须实现：

```text
首次进入：没有缓存才请求 AI 诊断
再次进入：立即展示缓存，不重复请求
缓存过期：保留旧结果并在后台更新
错题数据改变：按需重新生成
手动刷新：用户可以主动重新分析
请求失败：保留旧缓存，不清空页面
```

本次优化不能只增加一个简单布尔值，必须同时处理：

- 页面实例缓存。
- 微信本地持久化缓存。
- 缓存有效期。
- 用户隔离。
- 数据变化失效。
- 并发请求去重。
- 后台刷新体验。
- 手动重新分析。
- 旧缓存兼容和异常缓存清理。

------

## 一、当前问题

当前 `pages/wrong-book/wrong-book.js` 中：

```js
onShow() {
  if (!this._ready) return
  this._loadPage()
}
```

每次页面重新显示都会调用：

```js
_loadPage() {
  this.setData({ list: [], page: 1 })
  this.loadStats()
  this.loadList(true)
  this.loadAiDiagnosis()
}
```

而 `loadAiDiagnosis()` 每次都会：

```js
this.setData({
  aiDiagnosisLoading: true,
  aiDiagnosis: null,
})
```

然后请求：

```js
api.get('/stats/ai-diagnosis')
```

造成以下问题：

1. 每次进入错题本都重新请求 AI。
2. 从 `wrong-detail` 返回也重新生成。
3. 切换底部导航后再回来也重新生成。
4. 已经显示的诊断会先被清空。
5. 页面反复出现骨架屏或加载态。
6. 请求失败时原有诊断也可能丢失。
7. 多次快速进入页面可能产生重复并发请求。
8. 用户切换筛选条件时，可能无意义地重新生成全局诊断。
9. AI 接口如果调用大模型，会产生额外时间和成本。

------

# 二、修改文件

重点修改：

```text
pages/wrong-book/wrong-book.js
pages/wrong-book/wrong-book.wxml
pages/wrong-book/wrong-book.wxss
```

复用当前项目已有工具：

```text
utils/storage.js
```

必要时可以新增：

```text
utils/ai-diagnosis-cache.js
```

优先将缓存逻辑封装为独立工具，避免所有读写、校验逻辑堆积在页面文件中。

原则上不要修改：

```text
utils/api.js
pages/wrong-detail/*
pages/practice/*
pages/review-today/*
```

除非为了在练习完成后写入明确的“AI 诊断数据已变化”标记，才允许进行极少量修改。

------

# 三、缓存总体策略

采用：

```text
内存状态
+
wx 本地持久化缓存
+
有效期
+
数据指纹
+
按需后台刷新
```

不要采用以下简单但不可靠的方案：

```text
只判断 aiDiagnosis 是否存在
只设置一个 hasLoaded 布尔值
整个应用生命周期只请求一次
每次 onShow 都后台请求
只缓存结果，不记录时间
所有用户共用同一个缓存 Key
```

------

# 四、缓存常量

建议定义：

```js
const AI_DIAGNOSIS_CACHE_VERSION = 1
const AI_DIAGNOSIS_CACHE_PREFIX = 'wrong_book_ai_diagnosis'
const AI_DIAGNOSIS_CACHE_TTL = 6 * 60 * 60 * 1000
const AI_DIAGNOSIS_MIN_REFRESH_INTERVAL = 5 * 60 * 1000
```

含义：

```text
缓存版本：1
默认有效时间：6 小时
最短重复刷新间隔：5 分钟
```

缓存时间可以配置，但必须集中定义，不要将毫秒值散落在多个方法中。

6 小时内，在错题数据没有发生明显变化的情况下，不应重复请求 AI 诊断。

------

# 五、缓存数据结构

持久化缓存建议保存：

```js
{
  version: 1,
  userKey: '当前用户唯一标识',
  data: {
    summary: '',
    weak_points: [],
    strong_points: [],
    learning_suggestions: [],
    generated: true
  },
  cachedAt: 0,
  expiresAt: 0,
  sourceSignature: '',
}
```

字段说明：

```text
version
缓存结构版本，用于将来升级后废弃旧缓存。

userKey
当前用户标识，防止退出登录后不同用户读取同一份诊断。

data
经过标准化、可以直接展示的 AI 诊断。

cachedAt
缓存写入时间。

expiresAt
缓存过期时间。

sourceSignature
生成该诊断时的错题数据指纹。
```

不得直接缓存：

- Promise。
- 页面实例。
- 未标准化的后端响应。
- loading 状态。
- Error 对象。
- 空诊断。
- 请求失败结果。

------

# 六、用户隔离

缓存必须按用户隔离。

使用现有：

```js
const storage = require('../../utils/storage')
const { KEYS } = storage
```

读取：

```js
const user = storage.get(KEYS.USER)
```

用户标识优先级建议：

```text
user.id
user.user_id
user.openid
user.username
```

缓存 Key 示例：

```js
wrong_book_ai_diagnosis_v1_12345
```

禁止：

- 把完整 Token 拼入缓存 Key。
- 把邮箱、手机号直接暴露在缓存 Key 中。
- 所有用户共享固定 Key。

当无法获取可靠用户标识时：

```text
只使用当前页面实例中的内存缓存
不写入跨用户持久化缓存
```

不能使用固定的 `anonymous` 缓存让多个登录用户共用数据。

------

# 七、缓存读取方法

新增类似：

```js
_restoreAiDiagnosisCache()
```

职责：

1. 获取当前用户对应缓存 Key。
2. 调用 `storage.get()`。
3. 校验缓存对象类型。
4. 校验版本。
5. 校验用户。
6. 校验诊断结构。
7. 判断是否过期。
8. 将有效或可继续使用的旧缓存返回。
9. 对损坏缓存执行清理。
10. 不因为缓存读取异常导致页面报错。

缓存分为三种状态：

```text
fresh：未过期，可以直接使用，不请求接口
stale：已过期，但内容有效，可以先展示并后台刷新
invalid：结构损坏或用户不匹配，删除后重新请求
```

建议返回：

```js
{
  status: 'fresh' | 'stale' | 'miss',
  data: null,
  cachedAt: 0,
  sourceSignature: '',
}
```

------

# 八、缓存写入方法

新增：

```js
_saveAiDiagnosisCache(diagnosis, sourceSignature)
```

写入前必须验证诊断至少包含以下任意一项：

```text
summary
weak_points
strong_points
learning_suggestions
```

只有存在真实有效内容时才允许写入缓存。

不得缓存：

```js
null
undefined
{}
{
  weak_points: [],
  strong_points: [],
  learning_suggestions: [],
  summary: ''
}
```

写入失败不能阻止页面展示接口结果。

------

# 九、AI 诊断标准化

将当前 `loadAiDiagnosis()` 中的数据处理抽离为纯函数：

```js
_normalizeAiDiagnosis(raw)
```

需要完成：

1. 复制原对象，不直接修改接口返回对象。
2. 保证以下字段始终是数组：

```text
weak_points
strong_points
learning_suggestions
```

1. 为薄弱点和优势领域增加：

```js
_accuracyPercent
```

1. 对准确率进行范围保护：

```text
小于 0 → 0
大于 1 → 100%
0～1 → 乘以 100
后端如果已经返回 0～100，需要兼容
```

1. 清理无效空条目。
2. 确保知识点名称和建议是字符串。
3. 返回一个适合 WXML 展示的稳定结构。

缓存和接口结果必须共用同一标准化函数。

------

# 十、数据指纹

仅使用 TTL 会导致用户刚完成大量练习后仍看到旧诊断，因此需要增加轻量数据指纹。

新增：

```js
_buildAiDiagnosisSourceSignature()
```

只使用稳定的原始字段，例如：

```js
{
  total: stats.total || 0,
  unmastered: stats.unmastered,
  masteredCount,
  latestWrongId: firstItem.id,
  latestWrongAt: firstItem.last_wrong_at
    || firstItem.last_error_at
    || firstItem.updated_at
    || '',
  firstPageWrongCount: list.reduce(...),
  firstPageReviewCount: list.reduce(...),
}
```

最后将对象稳定序列化为字符串。

不得将以下内容加入指纹：

- `_timeLabel`。
- “刚刚”“3分钟前”等相对时间。
- 当前筛选条件。
- 当前分页页码。
- 当前列表的展示样式。
- 加载状态。
- 数组随机顺序。

指纹的目的不是对全部错题做完整哈希，而是判断学习数据是否发生了明显变化。

------

# 十一、筛选条件不得触发重新生成

当前 AI 诊断接口：

```text
/stats/ai-diagnosis
```

没有携带：

```text
subject
error_type
topic
```

因此它属于全局错题诊断。

以下操作不能触发 AI 重新生成：

```text
选择学科筛选
选择错因筛选
选择知识点筛选
清除筛选
加载更多
展开或收起筛选面板
进入错题详情后原样返回
```

筛选只能刷新错题列表和页面局部分析，不能使全局 AI 缓存失效。

------

# 十二、重构页面加载流程

不要让 `_loadPage()` 无条件调用 `loadAiDiagnosis()`。

建议调整为：

```js
async _loadPage() {
  this.setData({
    list: [],
    page: 1,
  })

  await Promise.all([
    this.loadStats(),
    this.loadList(true),
  ])

  await this.ensureAiDiagnosis()
}
```

但必须注意：

- `loadStats()` 和 `loadList()` 当前都需要返回 Promise。
- 原有错误处理不能删除。
- 两个请求其中一个失败时，仍应尽可能恢复缓存。
- 不允许因为 AI 请求阻塞错题列表展示。

也可以分为：

```text
第一阶段：立即恢复 AI 缓存
第二阶段：加载错题统计和列表
第三阶段：根据缓存、TTL 和数据指纹决定是否请求 AI
```

推荐采用第二种，用户感知更快。

------

# 十三、页面生命周期

## 13.1 onLoad

在 `onLoad()` 中完成页面参数和配置初始化后，立即尝试恢复缓存：

```js
onLoad(options) {
  // 原有参数处理
  ...

  this._restoreAiDiagnosisFromCache()
}
```

这样页面首次渲染时，只要有缓存，就能直接显示 AI 诊断，而不必等待统计和列表请求完成。

------

## 13.2 onReady

保留首次核心数据加载：

```js
onReady() {
  this._ready = true
  this._loadPage()
}
```

首次没有缓存时，核心数据加载完成后再请求 AI。

------

## 13.3 onShow

当前：

```js
onShow() {
  if (!this._ready) return
  this._loadPage()
}
```

可以继续刷新统计和错题列表，但不得无条件重新请求 AI。

调整为：

```text
刷新错题统计
刷新第一页错题列表
检查 AI 缓存状态
只有满足失效条件时才更新 AI
```

从详情页返回时：

- 已有缓存立即保留。
- 不清空 `aiDiagnosis`。
- 数据指纹没有改变时不请求 AI。
- 数据指纹改变时允许后台刷新一次。

------

# 十四、核心方法 `ensureAiDiagnosis`

新增统一入口：

```js
async ensureAiDiagnosis(options = {})
```

支持参数：

```js
{
  force: false,
  background: false,
  reason: 'initial' | 'expired' | 'data-changed' | 'manual',
}
```

判断顺序必须为：

```text
1. 当前没有任何错题 → 清理旧缓存，不请求
2. 当前已有正在执行的 AI 请求 → 复用该请求
3. force === true → 请求接口
4. 存在新鲜缓存且数据指纹一致 → 直接使用，不请求
5. 存在过期缓存 → 展示缓存，后台请求
6. 缓存数据指纹变化 → 展示旧结果，后台请求
7. 完全无缓存 → 显示骨架屏并请求
```

------

# 十五、并发请求去重

页面实例增加：

```js
_aiDiagnosisPromise: null
```

请求开始时：

```js
if (this._aiDiagnosisPromise) {
  return this._aiDiagnosisPromise
}
```

请求结束后，在 `finally` 中：

```js
this._aiDiagnosisPromise = null
```

必须避免以下情况造成重复请求：

- `onReady` 与后续 `onShow` 接近触发。
- 用户连续点击“重新分析”。
- 数据请求完成时重复调用检查方法。
- 页面快速隐藏和重新显示。
- 多个异步回调同时判定缓存失效。

不能只依赖：

```js
this.data.aiDiagnosisLoading
```

因为 `setData` 是异步更新，存在短时间竞态。

------

# 十六、不要在请求前清空旧诊断

删除当前无条件行为：

```js
this.setData({
  aiDiagnosisLoading: true,
  aiDiagnosis: null,
})
```

改为区分两种情况。

## 没有旧诊断

```js
this.setData({
  aiDiagnosisLoading: true,
})
```

显示 AI 骨架屏。

## 已有旧诊断

```js
this.setData({
  aiDiagnosisRefreshing: true,
})
```

保留已有内容，只显示轻量更新状态。

请求完成前不得将：

```text
aiDiagnosis
```

设置为 `null`。

------

# 十七、页面新增状态

在 `data` 中增加：

```js
aiDiagnosisRefreshing: false,
aiDiagnosisCacheTimeLabel: '',
aiDiagnosisCacheStale: false,
aiDiagnosisError: false,
```

语义：

```text
aiDiagnosisLoading
没有任何可展示内容，正在首次加载。

aiDiagnosisRefreshing
已有诊断仍然可见，后台正在更新。

aiDiagnosisCacheTimeLabel
显示诊断更新时间，例如“更新于 14:30”或“今天 14:30”。

aiDiagnosisCacheStale
当前正在展示已过期缓存。

aiDiagnosisError
没有缓存且首次请求失败。
```

不要同时让：

```text
aiDiagnosisLoading
aiDiagnosisRefreshing
```

为 `true`。

------

# 十八、缓存状态下的 WXML

AI 卡片头部建议调整为：

```text
AI 诊断
DeepSeek / 本地分析
更新于 14:30
重新分析
```

其中：

- 更新时间为辅助文字。
- “重新分析”是轻量文字按钮。
- 已经在更新时显示“正在更新…”。
- 更新过程中禁用重复点击。
- 不要添加过重的大按钮。

示意结构：

```xml
<view class="ai-head">
  <view class="ai-head-main">
    <text class="ai-head-tag">AI 诊断</text>
    <text class="ai-head-badge" wx:if="{{aiDiagnosis.generated}}">
      DeepSeek
    </text>
    <text class="ai-head-badge local" wx:else>
      本地分析
    </text>
  </view>

  <view class="ai-head-actions">
    <text class="ai-cache-time" wx:if="{{aiDiagnosisCacheTimeLabel}}">
      {{aiDiagnosisRefreshing ? '正在更新…' : aiDiagnosisCacheTimeLabel}}
    </text>

    <text
      class="ai-refresh-action {{aiDiagnosisRefreshing ? 'disabled' : ''}}"
      bindtap="refreshAiDiagnosis"
    >
      重新分析
    </text>
  </view>
</view>
```

刷新按钮必须绑定真实方法：

```js
refreshAiDiagnosis()
```

------

# 十九、手动重新分析

新增：

```js
refreshAiDiagnosis()
```

行为：

1. 如果已有请求正在进行，直接返回。
2. 保留当前诊断。
3. 设置 `aiDiagnosisRefreshing: true`。
4. 强制请求接口。
5. 成功后覆盖缓存。
6. 更新缓存时间和数据指纹。
7. 显示：

```text
AI 诊断已更新
```

1. 失败后保留旧结果，并显示：

```text
更新失败，请稍后重试
```

手动刷新不受：

```text
TTL
最短后台刷新时间
数据指纹
```

限制，但仍必须受并发去重保护。

------

# 二十、过期缓存体验

缓存过期时不要先隐藏旧结果。

正确体验：

```text
立即展示旧缓存
→ 标记“正在更新…”
→ 后台请求新诊断
→ 成功后无闪烁替换
```

错误体验：

```text
清空旧缓存
→ 显示整张骨架屏
→ 等待接口
→ 再显示新内容
```

如果后台刷新失败：

- 保留旧诊断。
- 标记时间仍显示上次更新时间。
- 不删除缓存。
- 后台自动刷新失败可以静默处理。
- 用户手动刷新失败才显示 Toast。

------

# 二十一、完全无缓存时的体验

仅当以下条件同时满足时显示骨架屏：

```text
aiDiagnosisLoading === true
aiDiagnosis === null
```

此时使用上一轮要求的结构化 AI 骨架屏。

若首次请求失败：

- 结束骨架屏。
- 显示轻量错误状态。
- 提供“重新分析”按钮。
- 不显示大面积空白。
- 不把失败结果写入缓存。

------

# 二十二、无错题时的缓存处理

当全局错题总数为 0 时：

```text
不请求 AI 诊断接口
清除当前用户的 AI 诊断缓存
将 aiDiagnosis 设置为 null
关闭 loading 和 refreshing
```

这里必须使用全局：

```text
stats.total
```

判断，不能使用筛选后的：

```text
list.length
```

否则筛选结果为空时会错误删除全局 AI 缓存。

------

# 二十三、数据变化时的刷新节流

数据指纹变化时允许后台更新，但必须防止短时间连续生成。

例如用户连续：

```text
完成一道题
返回
再进入详情
再返回
```

可能多次产生轻微数据变化。

增加最短自动刷新间隔：

```text
5 分钟
```

规则：

```text
指纹发生变化
且距离上次成功生成超过 5 分钟
→ 后台刷新
```

若不足 5 分钟：

- 继续展示现有缓存。
- 不立即请求。
- 下次进入或缓存到期后再检查。

手动“重新分析”不受该间隔限制。

------

# 二十四、缓存失效条件

满足任一条件时缓存失效：

1. 缓存版本不一致。
2. 用户标识不一致。
3. 缓存对象结构损坏。
4. 缓存中没有有效诊断内容。
5. 缓存超过 TTL。
6. 错题数据指纹发生变化。
7. 用户主动点击重新分析。
8. 当前全局错题总数变为 0。
9. 代码显式写入 AI 数据脏标记。

但失效不等于立刻删除。

对于仍然有内容的过期缓存：

```text
先展示
再后台更新
```

只有以下情况应直接删除：

- 用户不匹配。
- 版本不匹配。
- 结构损坏。
- 当前错题总数为 0。

------

# 二十五、可选的全局脏标记

为了更准确识别练习后数据变化，可以增加：

```text
wrong_book_ai_diagnosis_dirty
```

练习、复习或错题掌握状态发生变化后写入：

```js
storage.set('wrong_book_ai_diagnosis_dirty', {
  userKey,
  at: Date.now(),
})
```

Wrong Book 读取后：

```text
标记当前缓存需要后台更新
成功更新后清除 dirty 标记
```

适合写入脏标记的场景：

- 完成一组普通练习。
- 完成今日复习。
- 在错题详情中改变掌握状态。
- 删除错题。
- 重新加入错题。
- 更正错因分类。

若当前业务没有这些明确操作，先使用：

```text
TTL + 数据指纹
```

不要为了缓存机制大范围修改其他页面。

------

# 二十六、推荐的核心流程

```text
进入 Wrong Book
↓
同步读取本地缓存
↓
存在缓存？
├─ 是：立即显示
└─ 否：准备显示骨架屏
↓
加载全局错题统计和第一页列表
↓
全局错题数是否为 0？
├─ 是：清除缓存，不调用 AI
└─ 否：继续
↓
计算数据指纹
↓
判断缓存状态
├─ 新鲜且指纹一致：结束，不请求
├─ 过期：保留内容，后台刷新
├─ 指纹改变：保留内容，后台刷新
└─ 无缓存：显示骨架并请求
↓
接口成功
↓
标准化结果
↓
更新页面
↓
写入当前用户缓存
```

------

# 二十七、错误处理

## 有缓存时请求失败

```text
保留缓存
关闭正在更新状态
不清空 AI 卡片
自动后台刷新不弹 Toast
手动刷新弹轻量 Toast
```

## 无缓存时请求失败

```text
关闭骨架屏
显示轻量错误态
提供重试入口
不写缓存
```

## 缓存读写失败

```text
退化为当前页面实例内存缓存
页面继续正常使用
记录开发日志
不向用户暴露存储错误
```

------

# 二十八、页面隐藏与异步请求

请求返回时需要确认页面仍然有效。

可以增加：

```js
_alive: false
```

生命周期：

```js
onShow() {
  this._alive = true
}

onHide() {
  this._alive = false
}

onUnload() {
  this._alive = false
}
```

即使页面已经隐藏，成功响应仍可以写入持久化缓存，但不要对已销毁页面继续执行不安全的 `setData`。

也可以通过请求序号控制：

```js
_aiDiagnosisRequestId
```

防止旧请求覆盖手动刷新后的新请求。

------

# 二十九、缓存时间显示

增加格式化方法：

```js
_formatAiDiagnosisCacheTime(timestamp)
```

建议显示：

```text
刚刚更新
10 分钟前更新
今天 14:30 更新
昨天 18:20 更新
7月10日更新
```

不得在定时器中每分钟持续刷新文案。

页面进入或缓存写入时计算一次即可。

------

# 三十、WXSS 要求

新增轻量状态样式：

```text
ai-head-actions
ai-cache-time
ai-refresh-action
ai-refresh-action.disabled
ai-card.is-refreshing
ai-inline-refresh
ai-error-state
ai-error-retry
```

刷新状态不要给整个 AI 卡片加大面积遮罩。

可以在卡片顶部加入：

- 小型旋转图标。
- 三点加载。
- “正在更新…”文字。

但：

- 旧内容保持正常可读。
- 不降低整个卡片到无法阅读。
- 不阻止页面滚动。
- 不重复显示完整 Skeleton。

------

# 三十一、必须避免的实现

禁止：

```text
每次 onShow 仍请求 AI，只是先展示缓存
缓存存在也静默重复请求
只用页面 data 缓存，不写本地缓存
所有用户使用一个固定缓存 Key
缓存永不过期
缓存失败结果
请求前清空 aiDiagnosis
筛选变化使缓存失效
loadMore 使缓存失效
使用 setTimeout 模拟后台刷新
快速点击产生多次 AI 请求
通过隐藏加载动画掩盖重复生成
```

本次目标不仅是“不看到重复加载”，而是实质上不重复调用 AI 接口。

------

# 三十二、验收场景

## 场景 1：首次进入且无缓存

预期：

```text
显示 AI 骨架屏
只请求一次 /stats/ai-diagnosis
请求成功后显示结果
写入本地缓存
```

## 场景 2：退出页面后立即返回

预期：

```text
立即显示原诊断
不显示骨架屏
不请求 AI 接口
```

## 场景 3：进入错题详情后返回

预期：

```text
错题列表可以刷新
AI 诊断保持原样
没有数据变化时不请求 AI
```

## 场景 4：切换筛选条件

预期：

```text
列表和局部分析更新
全局 AI 诊断不重新请求
```

## 场景 5：缓存过期

预期：

```text
立即展示旧诊断
显示“正在更新…”
后台只请求一次
成功后平滑更新
```

## 场景 6：错题数据变化

预期：

```text
旧诊断继续展示
超过最短刷新间隔后后台更新
不会出现整卡消失
```

## 场景 7：后台刷新失败

预期：

```text
旧诊断仍然存在
缓存不被删除
页面不切换为错误大卡
```

## 场景 8：手动重新分析

预期：

```text
立即显示“正在更新…”
旧结果保持可见
连续点击不会发起多次请求
成功后更新时间变化
```

## 场景 9：退出账号并登录另一用户

预期：

```text
新用户不会看到旧用户的 AI 诊断
使用新用户独立缓存
```

## 场景 10：没有任何错题

预期：

```text
不请求 AI
清除旧诊断缓存
AI 卡片不显示
```

------

# 三十三、接口请求检查

在微信开发者工具 Network 中验证：

```text
首次无缓存进入：1 次 /stats/ai-diagnosis
立刻再次进入：0 次
进入详情并返回：0 次
切换筛选：0 次
加载更多：0 次
手动重新分析：1 次
缓存过期：1 次后台请求
快速连续操作：最多 1 个并发请求
```

不能只通过 UI 判断缓存是否生效，必须检查真实网络请求数量。

------

# 三十四、最终输出要求

请按以下顺序输出：

```text
1. 当前重复生成的根因
2. 缓存设计说明
3. 缓存状态流转说明
4. pages/wrong-book/wrong-book.js 完整代码
5. pages/wrong-book/wrong-book.wxml 完整代码
6. pages/wrong-book/wrong-book.wxss 完整代码
7. 如新增，utils/ai-diagnosis-cache.js 完整代码
8. 如修改，utils/storage.js 变更内容
9. 缓存验收测试结果
10. Network 请求次数自检结果
```

代码必须：

- 基于当前新版本修改。
- 可直接复制覆盖。
- 不省略原有代码。
- 不改变错题筛选和分页逻辑。
- 不破坏 AI 骨架屏。
- 不清空已有诊断再刷新。
- 不重复调用 AI 接口。
- 正确隔离不同用户。
- 缓存损坏时安全降级。
- 支持手动重新分析。
- 保证 WXML 和 WXSS 语法正确。

------

本次修改后的核心行为应是：

```text
进入页面不等于重新生成 AI；
只有首次无缓存、缓存过期、错题数据明显变化或用户主动刷新时，才请求 AI 接口。
```
