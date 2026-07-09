# `pages/wrong-detail` 页面 AI 分析超时与 UI/逻辑问题审查报告

审查对象：

```text
miniprogram/
backend/app/
```

重点文件：

```text
miniprogram/pages/wrong-detail/wrong-detail.js
miniprogram/pages/wrong-detail/wrong-detail.wxml
miniprogram/pages/wrong-detail/wrong-detail.wxss
miniprogram/utils/api.js
app/api/v1/ai.py
app/services/ai_service.py
app/ai/client.py
app/ai/prompts.py
app/ai/fallback.py
app/api/v1/wrong_questions.py
app/schemas/wrong_question.py
```

已执行检查：

```bash
node --check pages/wrong-detail/wrong-detail.js
python -m compileall -q app
```

结果：语法检查通过，后端 Python 编译通过。

------

# 一、总体结论

`pages/wrong-detail` 页面仍然存在明显问题，主要集中在 AI 分析调用链和页面状态控制上。

当前最严重的问题是：

```text
1. AI 分析在进入错题详情页后自动调用，导致页面打开即发起耗时请求。
2. 前端 wx.request 超时时间为 30 秒，后端 AI 请求超时时间为 150 秒，前端经常先超时。
3. 滑动切换错题时，每切一题都会自动触发一次 AI 分析，容易造成多个 AI 请求堆积。
4. 后端虽然有 AI fallback，但只有等 AI 请求失败或超时后才返回；在 150 秒配置下，前端已经超时。
5. fallback 返回时，前端会同时显示“AI 结果卡片”和“AI 不可用卡片”，状态互斥关系错误。
6. 页面缺少手动触发 AI 分析按钮，不符合“AI 分析改为手动调用”的需求。
7. 页面没有单独展示原题解析、正确答案、我的答案；对非选择题或无选项题不友好。
8. 横向滑题可能与代码块横向滚动冲突。
9. 部分按钮、标签仍然依赖固定 line-height，存在文字垂直居中不稳定风险。
```

本轮建议优先修复：

```text
P0：
1. 取消 wrong-detail AI 分析自动调用。
2. 改为用户点击按钮后手动调用。
3. 修复前后端 AI 超时不一致问题。
4. 修复 AI fallback 与 AI result 同时显示的问题。

P1：
5. 增加 AI 请求防重复、超时提示、重试机制。
6. 增加正确答案、我的答案、题目解析展示。
7. 修复横滑切题与代码横向滚动冲突。

P2：
8. 修复 invalid id、stale storage、滑动加载中空白等边界问题。
9. 修复按钮和标签垂直居中问题。
```

------

# 二、AI 分析功能超时问题分析

## 2.1 当前前端调用链

文件：

```text
miniprogram/pages/wrong-detail/wrong-detail.js
```

当前 `loadData()` 中加载错题详情成功后，自动调用：

```js
this.loadAiAnalysis(wqId)
```

调用位置：

```js
async loadData(wqId) {
  this.setData({ loading: true, errorText: '' })
  try {
    const wq = await api.get(`/wrong-questions/${wqId}`)
    if (!wq) throw new Error('not found')
    const data = _processWqData(wq, this.data.safeModeActive)
    data.aiResult = null
    data.aiFallback = false
    data.errorText = ''
    this.setData(data)
    this.setData({ loading: false, currentWqId: wqId })

    ...

    this.loadAiAnalysis(wqId)
  } catch (e) {
    ...
  }
}
```

滑动切换错题 `_navigateTo()` 中也会自动调用：

```js
this.loadAiAnalysis(wqId)
```

调用位置：

```js
async _navigateTo(idx, animMs) {
  const wqId = this.data.questionIds[idx]
  try {
    const wq = await api.get(`/wrong-questions/${wqId}`)
    ...
    this.setData(Object.assign({ contentState: fromState }, data))
    ...
    this.loadAiAnalysis(wqId)
  } catch (e) {
    ...
  }
}
```

因此当前页面行为是：

```text
打开错题详情页 → 自动请求 AI 分析
左右滑动切换错题 → 每切换一题自动请求 AI 分析
```

这是超时和请求堆积的直接原因。

------

## 2.2 当前前端请求超时时间

文件：

```text
miniprogram/utils/api.js
```

底层请求统一设置：

```js
wx.request({
  url: `${config.BASE_URL}${url}`,
  method,
  data,
  header,
  timeout: 30000,
  success: resolve,
  fail: reject,
})
```

也就是说前端所有接口，包括：

```text
POST /ai/error-analysis
```

最多等待：

```text
30 秒
```

超过 30 秒后，前端会进入 fail 分支，并显示：

```js
wx.showToast({ title: '网络异常', icon: 'none' })
```

这会导致用户看到的是“网络异常”，但真实原因可能只是 AI 分析生成太慢。

------

## 2.3 当前后端 AI 超时时间

文件：

```text
app/core/config.py
```

当前配置：

```python
AI_TIMEOUT: int = 150
```

文件：

```text
app/ai/client.py
```

AI 客户端使用：

```python
self.timeout = settings.AI_TIMEOUT
self._client = httpx.AsyncClient(timeout=self.timeout)
```

也就是说后端最多等待 AI 服务：

```text
150 秒
```

但是前端只等 30 秒。

这会产生明显错位：

```text
前端 30 秒超时 → 用户看到失败
后端仍可能继续等待到 150 秒 → 资源继续占用
```

所以当前不是单纯“AI 慢”的问题，而是：

```text
前端超时阈值 < 后端超时阈值
```

导致用户体验必然不稳定。

------

## 2.4 当前后端 fallback 不能及时返回

文件：

```text
app/services/ai_service.py
```

当前逻辑：

```python
try:
    result = await deepseek.chat(messages, model=model_name, api_key=api_key, base_url=base_url)
except Exception:
    fallback = get_fallback_analysis()
    return {
        "content": fallback,
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "fallback",
        "duration_ms": 0,
    }
```

问题是：

```text
只有 deepseek.chat 抛异常后，才会返回 fallback。
```

但 `deepseek.chat()` 的超时时间是 150 秒。

所以如果 AI 服务卡住，后端不会在 25 秒内主动 fallback，前端 30 秒就已经超时了。

------

## 2.5 当前缓存机制只能解决“成功生成后的第二次访问”

文件：

```text
app/services/ai_service.py
```

当前有缓存：

```python
if wq.ai_analysis and isinstance(wq.ai_analysis, dict):
    return {
        "content": wq.ai_analysis,
        "from_cache": True,
        "from_fallback": False,
        "tokens_used": 0,
        "model": "cache",
        "duration_ms": 0,
    }
```

这个逻辑本身是好的，但只能解决：

```text
某道错题已经成功生成过 AI 分析
```

不能解决：

```text
第一次生成很慢
第一次生成超时
用户快速切换错题导致多个首次生成请求堆积
```

------

# 三、核心修复目标

本次修复要达到以下效果：

```text
1. 进入 wrong-detail 页面后，不再自动调用 AI 分析。
2. 滑动切换错题后，也不再自动调用 AI 分析。
3. 页面显示一个“生成 AI 解题技巧”按钮，由用户手动触发。
4. 手动触发时，要有 loading 状态、超时提示、失败重试。
5. 同一道题正在生成时，重复点击不应重复发请求。
6. 切换题目后，旧题目的 AI 响应不能污染新题页面。
7. 后端 AI 分析接口应在 25 秒左右主动 fallback，避免前端 30 秒超时。
8. fallback 状态和 AI 结果状态必须互斥，不能同时显示两个 AI 卡片。
```

------

# 四、详细修复任务 1：取消 AI 分析自动调用

## 修改文件

```text
miniprogram/pages/wrong-detail/wrong-detail.js
```

## 4.1 删除 `loadData()` 中的自动调用

当前代码：

```js
this.loadAiAnalysis(wqId)
```

位置：`loadData()` 成功加载错题详情后。

请删除或注释：

```js
// this.loadAiAnalysis(wqId)
```

修改后的 `loadData()` 末尾应类似：

```js
this.setData({ loading: false, currentWqId: wqId })

if (data._renderModel) {
  this._checkRenderInvariant(data._renderModel)
  this._recordRenderTrace(data._renderModel.renderTrace)
}

// 不再自动调用 AI 分析
// 用户点击按钮后再调用
```

------

## 4.2 删除 `_navigateTo()` 中的自动调用

当前代码：

```js
this.loadAiAnalysis(wqId)
```

位置：`_navigateTo()` 成功切换错题后。

请删除或注释：

```js
// this.loadAiAnalysis(wqId)
```

修改后的逻辑：

```js
this.setData(Object.assign({ contentState: fromState }, data))

setTimeout(() => {
  this.setData({ contentState: '' })
  setTimeout(() => { this._animating = false }, animMs)
}, 50)

// 不再自动调用 AI 分析
// this.loadAiAnalysis(wqId)
```

------

## 4.3 切换题目时重置 AI 状态

当前 `_navigateTo()` 已经设置：

```js
data.aiResult = null
data.aiFallback = false
```

建议补充：

```js
data.aiLoading = false
data.aiErrorText = ''
data.aiRequested = false
```

最终建议：

```js
data.aiResult = null
data.aiFallback = false
data.aiLoading = false
data.aiErrorText = ''
data.aiRequested = false
```

------

# 五、详细修复任务 2：把 AI 分析改为手动调用

## 修改文件

```text
miniprogram/pages/wrong-detail/wrong-detail.js
miniprogram/pages/wrong-detail/wrong-detail.wxml
miniprogram/pages/wrong-detail/wrong-detail.wxss
```

------

## 5.1 data 中新增 AI 状态字段

当前 data：

```js
data: {
  ...
  aiResult: null,
  aiLoading: false,
  aiFallback: false,
  ...
}
```

建议改为：

```js
data: {
  ...
  aiResult: null,
  aiLoading: false,
  aiFallback: false,
  aiErrorText: '',
  aiRequested: false,
  aiFromCache: false,
  ...
}
```

字段含义：

```text
aiResult：AI 正常结果
aiLoading：正在生成
aiFallback：AI 不可用 / 降级
aiErrorText：错误文案
aiRequested：用户是否主动点击过生成
aiFromCache：结果是否来自缓存
```

------

## 5.2 新增手动点击方法 `onTapAiAnalysis`

新增方法：

```js
onTapAiAnalysis() {
  const wqId = this.data.currentWqId || (this.data.wq && this.data.wq.id)
  if (!wqId) {
    wx.showToast({
      title: '缺少错题ID',
      icon: 'none'
    })
    return
  }

  if (this.data.aiLoading) return

  this.loadAiAnalysis(wqId, { manual: true })
},
```

------

## 5.3 改造 `loadAiAnalysis`

当前方法：

```js
async loadAiAnalysis(wqId) {
  const token = wqId + '-' + Date.now()
  this._aiToken = token
  this.setData({ aiLoading: true })
  try {
    const result = await api.post('/ai/error-analysis', { wrong_question_id: wqId })
    ...
  } catch (e) {
    ...
  }
}
```

建议改为：

```js
async loadAiAnalysis(wqId, options = {}) {
  if (!wqId) return
  if (this.data.aiLoading) return

  const token = String(wqId) + '-' + Date.now()
  this._aiToken = token

  this.setData({
    aiLoading: true,
    aiRequested: true,
    aiFallback: false,
    aiErrorText: '',
    aiResult: null,
    aiFromCache: false,
  })

  try {
    const result = await api.post('/ai/error-analysis', {
      wrong_question_id: wqId
    })

    // 旧请求返回时，不允许污染当前题目
    if (
      this._aiToken !== token ||
      !this.data.wq ||
      String(this.data.wq.id) !== String(wqId)
    ) {
      return
    }

    const content = result && result.content ? result.content : null
    const fromFallback = !!(result && result.from_fallback)
    const fromCache = !!(result && result.from_cache)

    if (fromFallback) {
      this.setData({
        aiResult: null,
        aiFallback: true,
        aiFromCache: false,
        aiErrorText: 'AI 服务暂时不可用，请稍后重试',
        aiLoading: false,
      })
      return
    }

    if (!content) {
      this.setData({
        aiResult: null,
        aiFallback: true,
        aiFromCache: false,
        aiErrorText: 'AI 分析结果为空，请稍后重试',
        aiLoading: false,
      })
      return
    }

    if (content.error_analysis) {
      content.error_analysis = String(content.error_analysis).replace(/^切入点[：:]\s*/, '')
    }

    if (content.knowledge_weakness) {
      content.knowledge_weakness = String(content.knowledge_weakness).replace(/^核心考点[：:]\s*/, '')
    }

    this.setData({
      aiResult: content,
      aiFallback: false,
      aiFromCache: fromCache,
      aiErrorText: '',
      aiLoading: false,
    })
  } catch (e) {
    console.error('加载 AI 分析失败', e)

    if (
      this._aiToken === token &&
      this.data.wq &&
      String(this.data.wq.id) === String(wqId)
    ) {
      const msg = e && e.errMsg && String(e.errMsg).includes('timeout')
        ? 'AI 分析生成超时，请稍后重试'
        : 'AI 分析生成失败，请稍后重试'

      this.setData({
        aiLoading: false,
        aiFallback: true,
        aiResult: null,
        aiFromCache: false,
        aiErrorText: msg,
      })
    }
  }
},
```

重点：

```text
1. aiLoading 为 true 时禁止重复请求。
2. from_fallback 为 true 时，不要设置 aiResult。
3. AI 失败时设置 aiFallback=true、aiResult=null。
4. stale response 不能污染当前题目。
5. 手动触发后才设置 aiRequested=true。
```

------

# 六、详细修复任务 3：修改 AI 分析区域 WXML

## 修改文件

```text
miniprogram/pages/wrong-detail/wrong-detail.wxml
```

当前 AI 区域只有：

```text
AI 成功卡片
AI 加载卡片
AI 降级卡片
```

缺少：

```text
未请求状态卡片
手动生成按钮
重试按钮
```

------

## 6.1 替换当前 AI 分析区域

请将当前从：

```xml
<!-- AI 分析 -->
```

到：

```xml
<!-- AI 降级 -->
```

整段替换为下面结构。

```xml
<!-- AI 分析：手动触发 -->
<view class="ai-card">
  <view class="section-head">
    <view>
      <text class="section-title">AI 解题技巧</text>
      <text class="section-subtitle">
        {{aiRequested ? '根据当前错题生成解题思路与核心考点' : '点击后生成，不再自动请求'}}
      </text>
    </view>
    <text class="section-chip">AI</text>
  </view>

  <!-- 未请求状态 -->
  <view wx:if="{{!aiRequested && !aiLoading && !aiResult && !aiFallback}}" class="ai-idle">
    <text class="ai-idle-title">需要 AI 帮你分析这道题吗？</text>
    <text class="ai-idle-desc">点击后将生成解题思路、核心考点和快速方法。</text>
    <button class="ai-action-btn" bindtap="onTapAiAnalysis">生成 AI 解题技巧</button>
  </view>

  <!-- 加载状态 -->
  <view wx:elif="{{aiLoading}}" class="ai-loading-state">
    <view class="section-head compact">
      <view>
        <text class="section-title small">正在生成</text>
        <text class="section-subtitle">AI 正在分析题目，请稍候</text>
      </view>
      <view class="chip-loading">
        <view class="loading-spinner mini"></view>
        <text class="chip-loading-text">生成中</text>
      </view>
    </view>

    <view class="ai-loading-skeleton">
      <view class="skeleton-block" style="width:35%;height:20rpx;margin-bottom:12rpx;"></view>
      <view class="skeleton-block" style="width:85%;height:16rpx;margin-bottom:8rpx;"></view>
      <view class="skeleton-block" style="width:70%;height:16rpx;margin-bottom:8rpx;"></view>
      <view class="skeleton-block" style="width:55%;height:16rpx;"></view>
    </view>

    <text class="ai-hint">生成时间较长时，可以稍后重试</text>
  </view>

  <!-- 成功状态 -->
  <view wx:elif="{{aiResult && !aiFallback}}" class="ai-result-state">
    <view class="ai-section" wx:if="{{aiResult.error_analysis}}">
      <text class="ai-label">解题思路</text>
      <text class="ai-text">{{aiResult.error_analysis}}</text>
    </view>

    <view class="ai-section" wx:if="{{aiResult.knowledge_weakness}}">
      <text class="ai-label">核心考点</text>
      <text class="ai-text">{{aiResult.knowledge_weakness}}</text>
    </view>

    <view class="ai-section" wx:if="{{aiResult.suggestion}}">
      <text class="ai-label">快速方法</text>
      <text class="ai-text">{{aiResult.suggestion}}</text>
    </view>

    <text class="ai-hint">
      {{aiFromCache ? '来自历史缓存，仅供参考' : '内容由 AI 生成，仅供参考'}}
    </text>

    <button class="ai-secondary-btn" bindtap="onTapAiAnalysis">重新生成</button>
  </view>

  <!-- 失败 / 降级状态 -->
  <view wx:elif="{{aiFallback}}" class="ai-fallback">
    <view class="fallback-mark">
      <view class="line-icon icon-exclamation"></view>
    </view>
    <text class="fallback-title">AI 解题技巧暂时不可用</text>
    <text class="fallback-desc">{{aiErrorText || '建议先查看题目解析，稍后再试'}}</text>
    <button class="ai-action-btn retry" bindtap="onTapAiAnalysis">重新生成</button>
  </view>
</view>
```

------

## 6.2 为什么要这样改

原来的问题是：

```xml
<view class="ai-card" wx:if="{{!aiLoading && aiResult}}">
...
</view>

<view class="ai-card" wx:if="{{!aiLoading && aiFallback}}">
...
</view>
```

当后端返回：

```json
{
  "content": {
    "error_analysis": "暂无解题技巧...",
    "knowledge_weakness": "暂无数据"
  },
  "from_fallback": true
}
```

前端会设置：

```js
aiResult = content
aiFallback = true
```

于是两个卡片会同时显示：

```text
1. AI 分析结果卡片
2. AI 不可用卡片
```

这是明显的 UI 状态互斥错误。

修复后：

```text
from_fallback=true 时，只显示 fallback 卡片，不显示 result 卡片。
```

------

# 七、详细修复任务 4：补充 AI 手动按钮样式

## 修改文件

```text
miniprogram/pages/wrong-detail/wrong-detail.wxss
```

新增样式：

```css
.ai-idle {
  padding: 26rpx 18rpx;
  border-radius: 20rpx;
  background: #F6F9FF;
  text-align: center;
}

.ai-idle-title {
  display: block;
  font-size: 29rpx;
  font-weight: 900;
  color: #18233A;
  line-height: 1.35;
}

.ai-idle-desc {
  display: block;
  margin-top: 10rpx;
  font-size: 24rpx;
  color: #617089;
  line-height: 1.5;
}

.ai-action-btn,
.ai-secondary-btn {
  margin-top: 22rpx;
  width: 100%;
  height: 82rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  padding: 0 28rpx;
  border: none;
  border-radius: 999rpx;
  font-size: 28rpx;
  font-weight: 900;
  line-height: normal;
}

.ai-action-btn {
  color: #FFFFFF;
  background: linear-gradient(135deg, #4F7FFF 0%, #6EC1FF 100%);
  box-shadow: 0 12rpx 26rpx rgba(79, 127, 255, 0.22);
}

.ai-action-btn.retry {
  margin-top: 22rpx;
}

.ai-secondary-btn {
  color: #4F7FFF;
  background: #E8F0FF;
}

.ai-action-btn::after,
.ai-secondary-btn::after {
  border: none;
}

.ai-action-btn:active,
.ai-secondary-btn:active {
  opacity: 0.9;
  transform: scale(0.98);
}

.ai-loading-state,
.ai-result-state {
  display: block;
}

.section-title.small {
  font-size: 28rpx;
}
```

------

# 八、详细修复任务 5：后端 AI 分析接口增加快速超时 fallback

## 问题

当前后端 AI 超时为 150 秒，前端 30 秒就超时。

即使改成手动触发，用户点击按钮后仍可能 30 秒超时。

所以后端必须在前端 30 秒前返回 fallback。

------

## 修改文件

```text
app/services/ai_service.py
```

## 8.1 引入 asyncio

文件顶部新增：

```python
import asyncio
```

------

## 8.2 为错题 AI 分析增加单独短超时

建议新增常量：

```python
ERROR_ANALYSIS_TIMEOUT_SECONDS = 25
```

放在文件顶部 imports 后面。

------

## 8.3 包裹 deepseek.chat

当前代码：

```python
try:
    result = await deepseek.chat(messages, model=model_name, api_key=api_key, base_url=base_url)
except Exception:
    fallback = get_fallback_analysis()
    return {
        "content": fallback,
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "fallback",
        "duration_ms": 0,
    }
```

建议改为：

```python
try:
    async with asyncio.timeout(ERROR_ANALYSIS_TIMEOUT_SECONDS):
        result = await deepseek.chat(
            messages,
            model=model_name,
            api_key=api_key,
            base_url=base_url,
        )
except Exception:
    fallback = get_fallback_analysis()
    return {
        "content": fallback,
        "from_cache": False,
        "from_fallback": True,
        "tokens_used": 0,
        "model": "fallback",
        "duration_ms": ERROR_ANALYSIS_TIMEOUT_SECONDS * 1000,
    }
```

这样后端最多 25 秒返回 fallback，不会拖到 150 秒。

------

## 8.4 限制 prompt 长度，减少 AI 响应时间

当前 prompt 使用：

```python
question.get('content', {}).get('text', '')
question.get('options', {})
```

如果题干或选项非常长，AI 响应会明显变慢。

建议在 `app/ai/prompts.py` 中新增文本截断函数：

```python
def _clip_text(value, limit=1200):
    if value is None:
        return ""
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."
```

然后修改 `build_error_analysis()`：

```python
def build_error_analysis(question: dict, user_answer: str, correct_answer: str) -> list:
    stem = _clip_text(question.get('content', {}).get('text', ''), 1200)
    options = question.get('options', {})
    options_text = _clip_text(options, 800)
    knowledge_points = question.get('knowledge_points', [])

    return [
        {"role": "system", "content": SYSTEM_PROMPTS["error_analysis"]},
        {
            "role": "user",
            "content": (
                f"【题目】{stem}\n"
                f"【选项】{options_text}\n"
                f"【正确答案】{correct_answer}\n"
                f"【我的答案】{user_answer}\n"
                f"【知识点】{knowledge_points}\n"
                "请给出该题的解题技巧，包括解题思路、核心考点和快速方法。"
            ),
        },
    ]
```

注意：不要截断正确答案和我的答案。

------

# 九、详细修复任务 6：修复 AI 请求重复点击和切题污染

## 修改文件

```text
miniprogram/pages/wrong-detail/wrong-detail.js
```

当前已经有：

```js
const token = wqId + '-' + Date.now()
this._aiToken = token
```

这是好的，但还不够。

需要补充：

```text
1. aiLoading 时不允许重复点击。
2. 切题时主动作废上一个 token。
3. 切题时关闭 loading 状态。
```

------

## 9.1 切题时作废旧 AI 请求

在 `loadData()` 开头补充：

```js
this._aiToken = ''
this.setData({
  loading: true,
  errorText: '',
  aiLoading: false,
  aiResult: null,
  aiFallback: false,
  aiErrorText: '',
  aiRequested: false,
  aiFromCache: false,
})
```

在 `_navigateTo()` 成功加载新题前，也补充：

```js
this._aiToken = ''
```

并在构造 data 时设置：

```js
data.aiLoading = false
data.aiResult = null
data.aiFallback = false
data.aiErrorText = ''
data.aiRequested = false
data.aiFromCache = false
```

------

## 9.2 避免重复点击

在 `onTapAiAnalysis()` 中：

```js
if (this.data.aiLoading) return
```

按钮 WXML 中也建议加：

```xml
<button
  class="ai-action-btn"
  bindtap="onTapAiAnalysis"
  loading="{{aiLoading}}"
  disabled="{{aiLoading}}"
>
  生成 AI 解题技巧
</button>
```

------

# 十、该页面其他 UI / 逻辑问题审查

## 问题 1：AI fallback 和 AI result 会同时显示

等级：

```text
P0
```

原因：

```js
this.setData({
  aiResult: content,
  aiFallback: result.from_fallback,
  aiLoading: false,
})
```

如果 `result.from_fallback = true`，同时有 `content`，页面两个区域都会显示。

修复：

```js
if (result.from_fallback) {
  this.setData({
    aiResult: null,
    aiFallback: true,
    aiLoading: false,
    aiErrorText: 'AI 服务暂时不可用，请稍后重试',
  })
  return
}
```

WXML 也要保证：

```xml
<view wx:elif="{{aiResult && !aiFallback}}">
```

------

## 问题 2：页面没有展示原题解析、正确答案、我的答案

等级：

```text
P1
```

当前页面主要依靠选项颜色展示：

```text
绿色 = 正确答案
蓝色 = 我的选项
```

但问题是：

```text
1. 如果是非选择题，没有 optionItems，用户看不到正确答案。
2. 如果是填空题或主观题，用户看不到“我的答案 vs 正确答案”的明确对照。
3. 后端明明返回了 answer、wrong_answer、analysis，但 WXML 没有独立展示。
4. AI 分析取消自动调用后，页面更需要先展示题目自带解析，避免空内容。
```

建议增加“答案与解析”卡片。

------

### 修复任务：新增答案解析卡片

在 `wrong-detail.wxml` 的题目信息卡片后、AI 分析卡片前新增：

```xml
<!-- 答案与解析 -->
<view class="answer-card">
  <view class="section-head compact">
    <view>
      <text class="section-title">答案与解析</text>
      <text class="section-subtitle">先查看标准答案，再决定是否生成 AI 技巧</text>
    </view>
  </view>

  <view class="answer-row">
    <text class="answer-label">我的答案</text>
    <text class="answer-value user">{{wq.wrong_answer || '未记录'}}</text>
  </view>

  <view class="answer-row">
    <text class="answer-label">正确答案</text>
    <text class="answer-value correct">{{wq.answer || '暂无答案'}}</text>
  </view>

  <view class="analysis-block" wx:if="{{wq.analysis}}">
    <text class="answer-label">题目解析</text>
    <text class="analysis-text">{{wq.analysis}}</text>
  </view>
</view>
```

WXSS 新增：

```css
.answer-card {
  margin: 18rpx 24rpx 0;
  padding: 26rpx;
  background: #FFFFFF;
  border-radius: 24rpx;
  box-shadow: 0 8rpx 24rpx rgba(42, 84, 160, 0.08);
  border: 1rpx solid rgba(226, 234, 247, 0.92);
}

.answer-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20rpx;
  padding: 16rpx 0;
  border-top: 1rpx solid #EEF2F8;
}

.answer-row:first-of-type {
  border-top: none;
}

.answer-label {
  flex-shrink: 0;
  font-size: 25rpx;
  font-weight: 900;
  color: #617089;
  line-height: 1.5;
}

.answer-value {
  flex: 1;
  min-width: 0;
  text-align: right;
  font-size: 27rpx;
  font-weight: 900;
  line-height: 1.5;
  word-break: break-word;
}

.answer-value.correct {
  color: #22C55E;
}

.answer-value.user {
  color: #4F7FFF;
}

.analysis-block {
  margin-top: 16rpx;
  padding: 18rpx;
  border-radius: 18rpx;
  background: #F6F9FF;
}

.analysis-text {
  display: block;
  margin-top: 10rpx;
  font-size: 27rpx;
  color: #18233A;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
```

------

## 问题 3：AI prompt 生成了 suggestion，但前端没有展示

等级：

```text
P2
```

后端 prompt 要求输出：

```json
{
  "error_analysis": "...",
  "knowledge_weakness": "...",
  "suggestion": "..."
}
```

但前端只展示：

```xml
{{aiResult.error_analysis}}
{{aiResult.knowledge_weakness}}
```

缺少：

```xml
{{aiResult.suggestion}}
```

修复：

```xml
<view class="ai-section" wx:if="{{aiResult.suggestion}}">
  <text class="ai-label">快速方法</text>
  <text class="ai-text">{{aiResult.suggestion}}</text>
</view>
```

------

## 问题 4：横向滑题可能和代码块横向滚动冲突

等级：

```text
P1
```

当前页面根节点绑定：

```xml
<view class="page" bindtouchstart="onTouchStart" bindtouchend="onTouchEnd">
```

代码块使用：

```xml
<scroll-view scroll-x class="code-wrapper">
```

问题：

```text
用户横向滚动代码块时，也可能触发页面左右滑题。
```

尤其是 408 代码题，代码块很长，用户横向看代码时可能误切错题。

------

### 修复任务

给代码块区域阻止页面滑题。

WXML 修改：

```xml
<scroll-view
  wx:elif="{{_renderModel.mode === 'CODE'}}"
  scroll-x
  class="code-wrapper"
  catchtouchstart="onInnerHorizontalTouch"
  catchtouchend="onInnerHorizontalTouchEnd"
>
  <text decode="false" space="preserve" class="code-text">{{_renderModel.rawText}}</text>
</scroll-view>
```

MIXED 中的 CODE 也同样加：

```xml
<scroll-view
  wx:elif="{{item.type === 'CODE'}}"
  scroll-x
  class="code-wrapper mixed-code-block"
  catchtouchstart="onInnerHorizontalTouch"
  catchtouchend="onInnerHorizontalTouchEnd"
>
  <text decode="false" space="preserve" class="code-text">{{item.rawText}}</text>
</scroll-view>
```

JS 新增：

```js
onInnerHorizontalTouch() {
  this._innerTouching = true
},

onInnerHorizontalTouchEnd() {
  setTimeout(() => {
    this._innerTouching = false
  }, 80)
},
```

在 `onTouchStart()` 和 `onTouchEnd()` 开头增加：

```js
if (this._innerTouching) return
```

------

## 问题 5：打开页面时 id 非法没有提前拦截

等级：

```text
P2
```

当前：

```js
const currentId = Number(options.id)
```

如果 `options.id` 缺失或非法，会继续执行：

```js
this.loadData(currentId)
```

可能请求：

```text
/wrong-questions/NaN
```

修复：

```js
const currentId = Number(options.id)

if (!Number.isFinite(currentId) || currentId <= 0) {
  this.setData({
    loading: false,
    errorText: '错题ID无效',
    wq: null,
  })
  return
}
```

------

## 问题 6：`wrong_detail_ids` 可能使用过期缓存

等级：

```text
P2
```

当前逻辑：

```js
const stored = wx.getStorageSync('wrong_detail_ids')
if (Array.isArray(stored) && stored.length > 0) {
  const normalized = stored.map(Number).filter(Number.isFinite)
  if (normalized.includes(currentId)) questionIds = normalized
}
```

问题：

```text
如果用户不是从 wrong-book 列表进入，而是通过直接链接进入；
同时本地 storage 里还残留旧 wrong_detail_ids；
且旧列表里恰好包含当前 id；
页面会错误启用滑动切题，并滑到旧列表里的错题。
```

建议：

```text
wrong_book 跳转时同时存储 list 的时间戳和筛选条件；
wrong-detail 读取时判断 30 分钟内有效；
或者跳转 URL 中带 source=wrong-book，只有 source=wrong-book 时才使用 storage 列表。
```

推荐最小修复：

`wrong-book.js` 跳转时改为：

```js
wx.setStorageSync('wrong_detail_nav', {
  ids,
  ts: Date.now()
})
wx.navigateTo({ url: `/pages/wrong-detail/wrong-detail?id=${id}&idx=${idx}&source=wrong-book` })
```

`wrong-detail.js` 读取时：

```js
if (options.source === 'wrong-book') {
  const nav = wx.getStorageSync('wrong_detail_nav')
  if (nav && Array.isArray(nav.ids) && Date.now() - Number(nav.ts || 0) < 30 * 60 * 1000) {
    const normalized = nav.ids.map(Number).filter(Number.isFinite)
    if (normalized.includes(currentId)) questionIds = normalized
  }
}
```

------

## 问题 7：滑动切换时加载新题没有 loading 态，慢网可能出现空白/透明停留

等级：

```text
P2
```

当前 `_navigateTo()` 先让当前内容滑出：

```js
this.setData({ contentState: isLeft ? 'slide-out-left' : 'slide-out-right' })
```

然后才请求：

```js
const wq = await api.get(`/wrong-questions/${wqId}`)
```

如果接口慢，页面可能停在透明或半透明状态，用户以为卡死。

修复建议：

```js
this.setData({
  contentState: isLeft ? 'slide-out-left' : 'slide-out-right',
  switching: true,
})
```

WXML 增加：

```xml
<view wx:if="{{switching}}" class="switch-loading">
  <loading-lottie text="正在切换错题..." size="small" />
</view>
```

请求完成后：

```js
this.setData({
  switching: false,
  contentState: ''
})
```

失败时也要恢复：

```js
this.setData({
  switching: false,
  contentState: ''
})
```

------

## 问题 8：按钮和标签垂直居中仍不稳定

等级：

```text
P2
```

当前存在：

```css
.error-btn {
  height: 80rpx;
  line-height: 80rpx;
}
```

以及：

```css
.subject-tag,
.error-type-tag,
.tag {
  display: inline-block;
  padding: 5rpx 12rpx;
  line-height: 1.35;
}
```

在部分 Android 机型上，中文文字仍可能偏上或偏下。

建议统一改成 flex 居中。

------

### 修复任务

```css
.subject-tag,
.error-type-tag,
.tag,
.section-chip,
.chip-loading {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  line-height: 1;
}

.subject-tag,
.error-type-tag,
.tag {
  min-height: 42rpx;
  padding: 0 12rpx;
}

.section-chip {
  min-height: 38rpx;
  padding: 0 14rpx;
}

.error-btn {
  width: 100%;
  height: 80rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  padding: 0 24rpx;
  border-radius: 999rpx;
  font-size: 28rpx;
  font-weight: 800;
  line-height: normal;
  border: none;
}
```

------

# 十一、建议最终代码结构

## 11.1 `wrong-detail.js` data 建议

```js
data: {
  wq: null,
  optionKeys: [],
  _renderModel: null,
  optionItems: [],

  aiResult: null,
  aiLoading: false,
  aiFallback: false,
  aiErrorText: '',
  aiRequested: false,
  aiFromCache: false,

  loading: true,
  errorText: '',
  currentWqId: null,
  questionIds: [],
  currentIdx: 0,
  totalQuestions: 0,
  swiperEnabled: false,
  contentState: '',
  switching: false,
  showSwipeHint: false,
  safeModeActive: false,
  renderTraces: [],
},
```

------

## 11.2 `onLoad()` 建议

```js
onLoad(options) {
  setRenderGuardPage('wrong-detail')

  const currentId = Number(options.id)
  if (!Number.isFinite(currentId) || currentId <= 0) {
    this.setData({
      loading: false,
      errorText: '错题ID无效',
      wq: null,
    })
    return
  }

  let questionIds = []

  try {
    if (options.source === 'wrong-book') {
      const nav = wx.getStorageSync('wrong_detail_nav')
      if (
        nav &&
        Array.isArray(nav.ids) &&
        Date.now() - Number(nav.ts || 0) < 30 * 60 * 1000
      ) {
        const normalized = nav.ids.map(Number).filter(Number.isFinite)
        if (normalized.includes(currentId)) questionIds = normalized
      }
    }
  } catch (_) {}

  const currentIdx = questionIds.indexOf(currentId)
  const swiperEnabled = questionIds.length > 1

  this.setData({
    questionIds,
    currentIdx: currentIdx >= 0 ? currentIdx : 0,
    totalQuestions: questionIds.length,
    swiperEnabled,
    showSwipeHint: swiperEnabled,
  })

  if (swiperEnabled) {
    setTimeout(() => {
      this.setData({ showSwipeHint: false })
    }, 3000)
  }

  this.loadData(currentId)
},
```

------

## 11.3 `loadData()` 建议

```js
async loadData(wqId) {
  this._aiToken = ''

  this.setData({
    loading: true,
    errorText: '',
    aiLoading: false,
    aiResult: null,
    aiFallback: false,
    aiErrorText: '',
    aiRequested: false,
    aiFromCache: false,
  })

  try {
    const wq = await api.get(`/wrong-questions/${wqId}`)
    if (!wq) throw new Error('not found')

    const data = _processWqData(wq, this.data.safeModeActive)

    data.aiResult = null
    data.aiFallback = false
    data.aiLoading = false
    data.aiErrorText = ''
    data.aiRequested = false
    data.aiFromCache = false
    data.errorText = ''

    this.setData(data)
    this.setData({
      loading: false,
      currentWqId: wqId,
    })

    if (data._renderModel) {
      this._checkRenderInvariant(data._renderModel)
      this._recordRenderTrace(data._renderModel.renderTrace)
    }

    // 注意：这里不再自动调用 AI 分析
  } catch (e) {
    console.error('加载错题详情失败', e)
    this.setData({
      loading: false,
      errorText: '错题不存在或已被移除',
      wq: null,
      optionItems: [],
      blankOptionGroups: [],
      aiResult: null,
      aiLoading: false,
      aiFallback: false,
      aiErrorText: '',
      aiRequested: false,
    })
  }
},
```

------

# 十二、验收标准

## 12.1 AI 自动调用验收

```text
1. 进入 wrong-detail 页面后，只请求 /wrong-questions/{id}。
2. 不自动请求 /ai/error-analysis。
3. 左右滑动切换错题后，只请求 /wrong-questions/{id}。
4. 不自动请求 /ai/error-analysis。
5. 页面显示“生成 AI 解题技巧”按钮。
6. 只有点击按钮后，才请求 /ai/error-analysis。
```

------

## 12.2 AI 手动调用验收

```text
1. 点击“生成 AI 解题技巧”后显示 loading。
2. loading 期间按钮不可重复点击。
3. AI 成功返回后显示：
   - 解题思路
   - 核心考点
   - 快速方法
4. AI fallback 时只显示“AI 暂时不可用”卡片。
5. AI fallback 时不能同时显示 AI 结果卡片。
6. 点击“重新生成”可以再次请求。
7. 切换题目后，上一题的 AI 分析不会残留。
8. 旧请求返回后，不会污染当前题目。
```

------

## 12.3 AI 超时验收

```text
1. 后端 /ai/error-analysis 在 AI 服务慢时，约 25 秒内返回 fallback。
2. 前端不会再等到 30 秒 wx.request timeout。
3. 前端不会把 AI 慢误报为普通“网络异常”。
4. 后端不会因为单次 AI 分析长期占用到 150 秒。
```

------

## 12.4 页面 UI/逻辑验收

```text
1. 正确答案、我的答案、题目解析清晰显示。
2. 非选择题也能看到答案和解析。
3. 代码块横向滚动时不会误触发左右切题。
4. 滑动切换错题时，慢网不会长时间空白。
5. 错题 id 非法时显示明确错误态。
6. error button、AI button、tag、chip 文字垂直居中。
7. subject 为空时不要显示空标签，建议显示“未知科目”或隐藏。
```

------

# 十三、最终修复任务 Prompt

请直接按以下任务执行修复：

```text
你需要修复 pages/wrong-detail 页面和后端 AI 分析接口的问题。请只做本次审查指出的最小必要修复，不要重构无关页面。

一、前端 wrong-detail 修复

1. 删除 pages/wrong-detail/wrong-detail.js 中 loadData() 成功后的 this.loadAiAnalysis(wqId)，禁止页面打开后自动调用 AI 分析。
2. 删除 _navigateTo() 成功切题后的 this.loadAiAnalysis(wqId)，禁止滑动切题后自动调用 AI 分析。
3. data 中新增 aiErrorText、aiRequested、aiFromCache 字段。
4. 新增 onTapAiAnalysis() 方法，用户点击按钮后才调用 loadAiAnalysis。
5. 改造 loadAiAnalysis：
   - aiLoading=true 时禁止重复请求。
   - 请求开始时设置 aiRequested=true。
   - from_fallback=true 时设置 aiResult=null、aiFallback=true。
   - 成功时设置 aiResult=content、aiFallback=false。
   - 失败或超时时设置 aiFallback=true、aiErrorText=对应提示。
   - 使用 token 防止旧请求污染当前题目。
6. 切换题目时重置 AI 状态：
   - aiLoading=false
   - aiResult=null
   - aiFallback=false
   - aiErrorText=''
   - aiRequested=false
   - aiFromCache=false
7. 修改 wrong-detail.wxml：
   - 增加“生成 AI 解题技巧”手动按钮。
   - 增加 idle/loading/success/fallback 四种互斥状态。
   - success 状态展示 error_analysis、knowledge_weakness、suggestion。
   - fallback 状态只显示错误提示和重试按钮。
8. 修改 wrong-detail.wxss：
   - 新增 ai-idle、ai-action-btn、ai-secondary-btn 等样式。
   - 所有 AI 按钮使用 flex 垂直居中。
9. 增加“答案与解析”卡片：
   - 我的答案
   - 正确答案
   - 题目解析
10. 修复横向代码块滚动误触发左右滑题：
   - code-wrapper 上增加 catchtouchstart/catchtouchend。
   - JS 增加 onInnerHorizontalTouch/onInnerHorizontalTouchEnd。
   - onTouchStart/onTouchEnd 中判断 this._innerTouching。
11. onLoad 中校验 options.id，非法 id 直接显示错误态，不请求 /wrong-questions/NaN。
12. wrong_detail_ids 改成带 source 和 ts 的 wrong_detail_nav，避免使用过期 storage 列表。
13. 滑动切换慢网时增加 switching 状态或至少保证失败后 contentState 恢复为空。

二、后端 AI 分析接口修复

1. 修改 app/services/ai_service.py：
   - import asyncio。
   - 为 analyze_error 增加 ERROR_ANALYSIS_TIMEOUT_SECONDS = 25。
   - deepseek.chat 外层使用 async with asyncio.timeout(25)。
   - 超时或异常时立即返回 get_fallback_analysis()。
   - duration_ms 设置为 25000 或实际耗时。
2. 修改 app/ai/prompts.py：
   - 增加 _clip_text。
   - build_error_analysis 中截断题干和选项，减少 prompt 过长导致的生成慢。
3. 确保 /api/v1/ai/error-analysis 在 AI 服务慢时，前端 30 秒超时前可以返回 fallback。
4. 不要缓存 fallback 到 wrong_question.ai_analysis。
5. 保留已有成功结果缓存逻辑。

三、回归检查

完成后执行：
1. node --check pages/wrong-detail/wrong-detail.js
2. python -m compileall -q app
3. 微信开发者工具验证：
   - 打开 wrong-detail 不自动请求 /ai/error-analysis。
   - 点击按钮才请求 AI。
   - fallback 不会和 result 同时显示。
   - 切换题目后 AI 状态清空。
   - 代码块横向滚动不误切题。
   - 非选择题能看到正确答案和解析。
   - 按钮和标签文字垂直居中。
```

------

# 十四、最终判断

当前 `pages/wrong-detail` 页面不建议直接上线。
必须先完成以下 4 个关键修复：

```text
1. AI 分析自动调用改为手动调用。
2. 后端 AI 分析增加 25 秒内 fallback。
3. 修复 aiFallback 与 aiResult 同时展示。
4. 增加答案与解析卡片，保证不调用 AI 时页面也有足够信息。
```

修复后，该页面的用户体验会从：

```text
打开页面就卡 AI / 超时 / 网络异常
```

变成：

```text
先稳定展示错题详情和解析，用户需要时再手动生成 AI 解题技巧
```

这才是更合理的错题详情页交互。