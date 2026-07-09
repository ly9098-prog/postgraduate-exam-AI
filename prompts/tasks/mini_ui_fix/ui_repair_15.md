你现在接手一个微信小程序 + FastAPI 后端项目。请基于当前项目代码，优化 `pages/wrong-detail` 页面 AI 分析体验，目标是减少用户等待时间，并确保 AI 分析结果能够持久化复用。

## 一、当前问题

当前小程序错题详情页 `pages/wrong-detail` 的 AI 分析存在两个体验问题：

1. 用户每次进入错题详情页后，如果想看 AI 分析，需要点击“生成 AI 解题技巧”，然后等待一段时间。
2. 虽然后端 `wrong_questions.ai_analysis` 字段已经存在，`app/services/ai_service.py` 中也有一定缓存逻辑，但错题详情接口没有把已生成的 `ai_analysis` 返回给小程序，导致前端无法在页面加载时直接展示已有 AI 分析。

请直接修改代码，完成以下优化。

------

## 二、涉及文件

重点检查和修改以下文件：

### 后端

```text
app/models/wrong_question.py
app/schemas/wrong_question.py
app/api/v1/wrong_questions.py
app/api/v1/ai.py
app/services/ai_service.py
app/services/wrong_question_service.py
```

### 小程序端

```text
miniprogram/pages/wrong-detail/wrong-detail.js
miniprogram/pages/wrong-detail/wrong-detail.wxml
miniprogram/pages/wrong-detail/wrong-detail.wxss
```

------

## 三、需求 1：错题详情接口返回已持久化的 AI 分析结果

### 当前情况

后端模型中已经有：

```python
ai_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

并且 `app/services/ai_service.py` 中已有逻辑：

```python
if wq.ai_analysis and isinstance(wq.ai_analysis, dict):
    return {
        "content": wq.ai_analysis,
        "from_cache": True,
        ...
    }
```

但是 `WrongQuestionResponse` 当前没有返回 `ai_analysis` 字段，`wrong_questions.py` 的 `enrich_wq()` 也没有把 `wq.ai_analysis` 塞进响应里。

### 修改要求

1. 修改 `app/schemas/wrong_question.py`，在 `WrongQuestionResponse` 中新增字段：

```python
ai_analysis: dict | None = None
ai_analysis_status: str | None = None
```

其中：

- `ai_analysis`：已生成的 AI 分析结果；
- `ai_analysis_status`：用于前端判断状态，可选值：
  - `"ready"`：已有可用 AI 分析；
  - `"empty"`：尚未生成；
  - `"fallback"`：如果后续支持 fallback 持久化，可标记为 fallback；
  - `"generating"`：如果后续增加异步生成队列，可使用。

1. 修改 `app/api/v1/wrong_questions.py` 中的 `enrich_wq()`，返回：

```python
ai_analysis=wq.ai_analysis,
ai_analysis_status="ready" if isinstance(wq.ai_analysis, dict) and wq.ai_analysis else "empty"
```

1. 保证以下接口都能返回该字段：

```text
GET /api/v1/wrong-questions
GET /api/v1/wrong-questions/{wq_id}
PUT /api/v1/wrong-questions/{wq_id}
PUT /api/v1/wrong-questions/{wq_id}/quality
```

1. 列表接口 `GET /wrong-questions` 是否返回 `ai_analysis` 可以根据性能决定：
   - 如果每页最多 20 条，可以返回；
   - 如果担心响应变大，可以只返回 `ai_analysis_status`；
   - 但详情接口 `GET /wrong-questions/{wq_id}` 必须返回完整 `ai_analysis`。

### 验收标准

- 数据库中某条错题已有 `ai_analysis` 时，调用 `GET /api/v1/wrong-questions/{wq_id}` 能直接看到该字段。
- `ai_analysis_status` 正确返回 `"ready"`。
- 没有生成过 AI 分析的错题返回 `ai_analysis: null`，`ai_analysis_status: "empty"`。
- 不影响现有题干、选项、答案、解析字段。

------

## 四、需求 2：小程序进入错题详情页时优先展示已持久化 AI 分析，不再强制等待

### 当前情况

`wrong-detail.js` 中目前是：

```js
// 不再自动调用 AI 分析，用户点击按钮后手动触发
```

用户点击按钮后调用：

```js
api.post('/ai/error-analysis', { wrong_question_id: wqId })
```

这样即使后端已经有缓存，用户仍然需要点击并等待一次接口返回。

### 修改要求

1. 在 `loadDetail` 或处理错题详情数据的逻辑中，读取后端返回的：

```js
wq.ai_analysis
wq.ai_analysis_status
```

1. 如果 `wq.ai_analysis` 存在，直接设置：

```js
this.setData({
  aiResult: wq.ai_analysis,
  aiRequested: true,
  aiLoading: false,
  aiFallback: false,
  aiErrorText: '',
  aiFromCache: true
})
```

1. 此时页面应直接展示 AI 解题技巧内容，不需要用户再次点击“生成 AI 解题技巧”。
2. 如果 `wq.ai_analysis` 不存在，则保持当前逻辑：
   - 显示“生成 AI 解题技巧”按钮；
   - 用户点击后再生成。
3. 用户点击“生成 AI 解题技巧”时，如果前端已经有 `aiResult`，不要重复请求，可以提示：

```js
wx.showToast({ title: '已加载 AI 分析', icon: 'none' })
```

或者直接展开展示，不再重复调用接口。

1. 如果用户确实需要重新生成，可以新增一个“重新生成”入口，但默认不要每次重复生成。

### 推荐前端逻辑

在 `loadDetail` 成功拿到 `wq` 后增加类似逻辑：

```js
const cachedAi = wq && wq.ai_analysis && typeof wq.ai_analysis === 'object'
if (cachedAi) {
  this.setData({
    aiResult: wq.ai_analysis,
    aiRequested: true,
    aiLoading: false,
    aiFallback: false,
    aiErrorText: '',
    aiFromCache: true,
  })
} else {
  this.setData({
    aiResult: null,
    aiRequested: false,
    aiLoading: false,
    aiFallback: false,
    aiErrorText: '',
    aiFromCache: false,
  })
}
```

### 验收标准

- 已生成 AI 分析的错题，进入详情页后直接展示结果。
- 不需要点击按钮，不需要等待 AI 重新生成。
- 未生成 AI 分析的错题，仍然显示生成按钮。
- 用户点击已生成错题的按钮，不会重复请求 AI。
- 左右切换错题时，不会串题显示上一个错题的 AI 结果。
- `aiFromCache` 状态正确。

------

## 五、需求 3：确保 AI 分析结果真正持久化，避免重复调用大模型

### 当前情况

`app/services/ai_service.py` 中已有：

```python
wq.ai_analysis = parsed
await db.commit()
```

这说明成功生成后理论上已经会持久化。

但仍需要检查以下问题：

1. 是否只有成功 JSON 解析后才保存。
2. 如果模型返回纯文本，是否也能保存。
3. 如果接口 fallback，是否保存 fallback。
4. 如果并发点击，是否会产生重复 AI 调用。
5. 如果用户重复进入页面，是否总能从数据库返回缓存。

### 修改要求

1. 保持成功结果持久化到：

```text
wrong_questions.ai_analysis
```

1. 如果模型返回不是合法 JSON，目前会转成：

```python
parsed = {"error_analysis": result["content"]}
```

该结果也必须保存。

1. 建议新增持久化元信息字段，便于后续维护：

如果允许改表，可新增字段：

```text
ai_analysis_status
ai_analysis_model
ai_analysis_generated_at
ai_analysis_version
```

如果暂时不改表，可把元信息放入 `ai_analysis` 内部：

```json
{
  "error_analysis": "...",
  "knowledge_weakness": "...",
  "solution_strategy": "...",
  "_meta": {
    "model": "xxx",
    "generated_at": "2026-07-03T...",
    "version": "v1",
    "from_fallback": false
  }
}
```

1. 当前不建议持久化 fallback 结果，除非产品明确接受。因为 fallback 通常是通用兜底内容，质量较低。推荐逻辑：

```python
if not from_fallback:
    wq.ai_analysis = parsed
    await db.commit()
```

1. 如果确实要持久化 fallback，需要在 `_meta.from_fallback = true` 标记，前端展示时要提示“AI 服务暂不可用，当前为基础建议”。

### 验收标准

- 第一次点击生成时调用大模型。
- 生成成功后，数据库 `wrong_questions.ai_analysis` 有内容。
- 第二次点击同一题时，后端直接返回 `from_cache: true`。
- 第二次进入同一题详情页时，前端直接展示 `ai_analysis`，不再调用 `/ai/error-analysis`。
- 如果模型返回非 JSON 文本，也能持久化为结构化对象。
- fallback 默认不污染正式 AI 分析缓存。

------

## 六、需求 4：减少首次生成等待时间

仅靠持久化只能解决“第二次以后快”，首次生成仍然需要等待。请增加以下优化策略，至少实现前两项。

### 方案 A：页面加载后自动预取缓存，不自动生成

这是最低风险方案。

1. 错题详情接口直接返回 `ai_analysis`。
2. 如果有缓存，页面直接展示。
3. 如果无缓存，不自动调用 AI，避免浪费 token。
4. 用户点击后再生成。

这个方案必须实现。

------

### 方案 B：用户进入页面后延迟预生成，但不阻塞页面

适合提升体验。

1. 用户进入错题详情页后，页面先正常展示题目。
2. 如果该题没有 `ai_analysis`，可以在页面空闲后自动发起生成。
3. 前端 UI 显示：

```text
AI 解题技巧生成中...
```

1. 用户不需要点按钮，过一会自动出现结果。
2. 要设置防抖和取消逻辑：
   - 用户快速切换题目时，不要把 A 题结果显示到 B 题；
   - 页面卸载或切题时应忽略旧请求结果；
   - 不要多个请求同时生成同一题。

可在小程序端使用现有 `_aiToken` 机制继续防串题。

------

### 方案 C：创建错题时后台预生成 AI 分析

这是体验最好的方案，但实现复杂度更高。

在错题创建成功后，后台异步生成 AI 分析，用户进入详情页时大概率已经有结果。

推荐实现方式：

1. 在创建错题后，不要阻塞用户主流程。
2. 使用后端异步任务或任务队列生成 AI 分析。
3. 优先推荐：
   - Celery + Redis；
   - RQ + Redis；
   - FastAPI BackgroundTasks；
   - 项目已有任务系统。
4. 如果项目当前没有任务队列，可以先用 FastAPI `BackgroundTasks` 做轻量版本。
5. 后台任务需要重新创建数据库 session，不能直接复用请求里的 `db`。
6. 任务执行前再次检查 `wq.ai_analysis` 是否已经存在，避免重复生成。
7. 失败时只记录日志，不影响用户添加错题。

### 推荐接口设计

新增一个轻量接口用于触发预生成：

```text
POST /api/v1/ai/error-analysis/prewarm
```

请求：

```json
{
  "wrong_question_ids": [1, 2, 3]
}
```

返回：

```json
{
  "queued": [1, 2, 3],
  "skipped": [],
  "reason": "already_cached"
}
```

用途：

- 错题列表页可以批量预热当前页错题；
- 错题详情页可以预热当前题和相邻题；
- 复习模式可以提前预热下一题。

------

## 七、需求 5：避免并发重复生成同一道题

### 背景

如果用户连续点击按钮，或者多个端同时请求同一错题，可能会同时触发多次大模型调用，浪费 token。

### 修改要求

后端 `analyze_error()` 中增加并发保护。

可选实现：

#### 方案 A：数据库状态字段

新增字段：

```text
ai_analysis_status
```

取值：

```text
empty
generating
ready
failed
```

流程：

1. 请求进入后先查 `ai_analysis`；
2. 如果已有，直接返回 cache；
3. 如果状态是 `generating`，返回：

```json
{
  "status": "generating",
  "content": null,
  "from_cache": false
}
```

1. 前端轮询或稍后重试；
2. 当前请求设置状态为 `generating`；
3. 生成成功后写入 `ai_analysis` 并设置 `ready`；
4. 失败后设置 `failed`。

#### 方案 B：Redis 分布式锁

key：

```text
ai:error_analysis:{wrong_question_id}
```

有效期：

```text
60s
```

如果拿不到锁：

- 先重新查数据库；
- 如果还没有结果，返回 `generating`；
- 前端提示“AI 分析生成中”。

### 验收标准

- 连续点击同一题生成按钮，不会产生多次模型调用。
- 多端同时请求同一题，不会重复消耗大模型。
- 已生成结果始终优先返回缓存。
- 生成失败不会导致状态永久卡在 `generating`。

------

## 八、前端交互优化要求

请优化 `wrong-detail.wxml` 的 AI 区域展示状态。

### 状态 1：已有缓存

展示：

```text
AI 解题技巧
已为你生成
[展示分析内容]
```

可以弱化或隐藏“生成 AI 解题技巧”按钮。

### 状态 2：未生成

展示：

```text
AI 解题技巧
根据你的错因生成解题切入点、知识薄弱点和快速突破建议
[生成 AI 解题技巧]
```

### 状态 3：生成中

展示：

```text
AI 解题技巧生成中...
```

按钮置灰，不能重复点击。

### 状态 4：生成失败

展示：

```text
AI 分析生成失败，请稍后重试
[重新生成]
```

### 状态 5：来自缓存

可以显示轻提示：

```text
已加载历史 AI 分析
```

不要让用户误以为又重新调用了 AI。

------

## 九、推荐最终实现优先级

请按以下优先级落地：

### P0：必须完成

1. `WrongQuestionResponse` 增加 `ai_analysis` 和 `ai_analysis_status`。
2. `GET /wrong-questions/{wq_id}` 返回已持久化 AI 分析。
3. 小程序详情页加载时，如果有 `ai_analysis`，直接展示。
4. 点击按钮前检查本地是否已有 `aiResult`，避免重复请求。
5. 保持后端 `wq.ai_analysis` 成功生成后持久化。

### P1：强烈建议完成

1. 新增 `ai_analysis_generated_at`、`ai_analysis_model` 或 `_meta` 元信息。
2. 增加并发防重复生成保护。
3. 增加“重新生成”按钮，但默认不重复生成。
4. 预热当前题相邻题的 AI 分析。

### P2：后续优化

1. 错题创建后后台自动预生成。
2. 错题列表页批量预热。
3. 使用 Redis/Celery 做可靠任务队列。
4. 增加 AI 分析版本号，Prompt 更新后可按版本重新生成。

------

## 十、接口返回建议

### `/api/v1/wrong-questions/{wq_id}` 返回示例

```json
{
  "id": 123,
  "question_id": 456,
  "wrong_answer": "B",
  "answer": "C",
  "analysis": "...",
  "ai_analysis": {
    "error_analysis": "...",
    "knowledge_weakness": "...",
    "solution_strategy": "...",
    "_meta": {
      "model": "deepseek-v4-flash",
      "generated_at": "2026-07-03T10:30:00",
      "version": "v1",
      "from_fallback": false
    }
  },
  "ai_analysis_status": "ready"
}
```

### `/api/v1/ai/error-analysis` 返回缓存示例

```json
{
  "session_type": "error_analysis",
  "content": {
    "error_analysis": "...",
    "knowledge_weakness": "...",
    "solution_strategy": "..."
  },
  "tokens_used": 0,
  "model": "cache",
  "duration_ms": 0,
  "from_cache": true,
  "from_fallback": false
}
```

------

## 十一、测试用例

请至少验证以下场景：

1. 新错题，数据库没有 `ai_analysis`：
   - 进入详情页不展示 AI 结果；
   - 点击按钮后生成；
   - 生成成功后写入数据库。
2. 老错题，数据库已有 `ai_analysis`：
   - 进入详情页直接展示；
   - 不调用 `/ai/error-analysis`；
   - `aiFromCache = true`。
3. 同一题重复点击：
   - 不重复调用 AI；
   - 按钮有 loading 或禁用状态。
4. 快速切换题目：
   - A 题 AI 结果不会显示到 B 题；
   - 旧请求返回后会被 `_aiToken` 拦截。
5. 模型接口异常：
   - 不写入错误缓存；
   - 前端显示失败提示；
   - 用户可以重新生成。
6. 模型返回非 JSON：
   - 后端包装成 `{ "error_analysis": "..." }`；
   - 正常保存；
   - 前端能展示。

------

## 十二、输出要求

完成后请输出：

1. 修改文件清单。
2. 后端具体改了哪些字段和接口。
3. 前端具体改了哪些加载逻辑。
4. AI 分析结果是否已经持久化。
5. 首次生成和二次查看的体验差异。
6. 是否增加了并发防重复生成。
7. 验证步骤和测试结果。
8. 仍需后续优化的点。