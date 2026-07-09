你现在接手一个微信小程序 + FastAPI 后端 + Admin 前端项目。请基于当前项目代码完成以下需求修改，不要只给方案，需要直接落地代码修改，并在完成后输出修改文件清单、关键变更说明、验证方法。

## 一、项目范围

当前涉及三个代码包：

1. 小程序端：`miniprogram`
2. 后端接口：`app`
3. Admin 前端：`admin-frontend`

重点页面和接口路径：

- 小程序错题详情页：
  - `miniprogram/pages/wrong-detail/wrong-detail.wxml`
  - `miniprogram/pages/wrong-detail/wrong-detail.wxss`
  - `miniprogram/pages/wrong-detail/wrong-detail.js`
- 小程序当前 AI 解析调用：
  - `wrong-detail.js` 中 `loadAiAnalysis`
  - 请求接口：`POST /api/v1/ai/error-analysis`
- 后端 AI 解析入口：
  - `app/api/v1/ai.py`
  - `app/services/ai_service.py`
  - `app/services/model_config_resolver.py`
  - `app/models/admin_ai_config.py`
- Admin 模型配置页面：
  - `admin-frontend/src/app/(admin)/ai-settings/page.tsx`
  - `admin-frontend/src/app/(admin)/ai-settings/components/model-cards.tsx`
  - `admin-frontend/src/lib/api/types.ts`

------

## 二、需求 1：去掉 `pages/wrong-detail` 页面中的“答案与解析区域”

### 背景

当前 `pages/wrong-detail/wrong-detail.wxml` 中在题目卡片之后存在一个独立的“答案与解析”卡片：

```xml
<!-- 答案与解析 -->
<view class="answer-card">
  ...
</view>
```

该区域展示了：

- 我的答案
- 正确答案
- 题目解析

但是题目区域本身已经包含这些内容，导致页面重复展示，视觉冗余。

### 修改要求

1. 删除或隐藏 `wrong-detail.wxml` 中独立的“答案与解析”卡片区域。
2. 页面中不要再出现标题为“答案与解析”的独立模块。
3. 保留题目区域中已有的答案、正确答案、解析内容。
4. 不要影响下面的 `AI 解题技巧` 卡片。
5. 删除后页面结构应为：
   - 题目信息卡片
   - AI 解题技巧卡片
6. 检查 `wrong-detail.wxss` 中与 `.answer-card`、`.answer-row`、`.answer-label`、`.answer-value`、`.analysis-block` 等仅服务于已删除区域的样式：
   - 如果完全不再使用，可以清理；
   - 如果题目区域仍复用这些 class，则不要盲目删除，避免影响题目区域展示。

### 验收标准

- 进入错题详情页后，不再看到单独的“答案与解析”卡片。
- 页面中不再重复展示“我的答案 / 正确答案 / 题目解析”两遍。
- AI 解题技巧区域仍然正常显示，并可点击生成。
- 左右滑动切换错题时页面结构正常，不出现空白卡片或样式塌陷。

------

## 三、需求 2：修复题目区域中“我的答案”和“正确答案”缩进与其他答案不一致的问题

### 背景

当前 `pages/wrong-detail` 页面中，题目区域里的“我的答案”和“正确答案”与其他答案、选项内容的左侧缩进不一致，视觉上不对齐。

需要统一题目区域内答案信息的排版，使它们与普通选项、解析、题干内容保持一致的内容起点和层级。

### 修改要求

请检查 `wrong-detail.wxml`、`wrong-detail.wxss` 以及题目渲染组件相关输出，重点排查以下情况：

1. “我的答案”和“正确答案”是否来自题目富文本内容。
2. 是否由 `math-question`、`mp-html`、`rich-text` 或后端返回的题目内容直接渲染出来。
3. 是否因为外层 `flex`、`text-align:right`、额外 `padding-left`、`margin-left`、`display:inline-block` 等导致缩进不一致。
4. 是否因为普通选项 `.option-line` 有统一 padding，而答案区域没有同步 padding。

### 样式修复目标

1. “我的答案”和“正确答案”的左边界应与其他答案/选项内容保持一致。
2. 标签和值之间间距自然，不要出现标签靠左、答案值被挤到最右侧的问题。
3. 小屏设备下不能溢出，长答案需要自动换行。
4. 多选答案、填空答案、较长文本答案均要显示正常。
5. 颜色可以保留：
   - 我的答案：蓝色或用户答案色
   - 正确答案：绿色或正确答案色
6. 不要为了对齐破坏选项高亮、空格题、多空选择题的样式。

### 推荐实现方向

可以根据实际结构选择其中一种方式：

#### 方案 A：统一为块级纵向结构

将题目区域内答案行统一渲染为：

```xml
<view class="question-answer-line">
  <text class="question-answer-label">我的答案</text>
  <text class="question-answer-value user">...</text>
</view>
```

对应样式：

```css
.question-answer-line {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
  padding: 12rpx 0;
  line-height: 1.6;
}

.question-answer-label {
  flex-shrink: 0;
  font-size: 26rpx;
  font-weight: 800;
}

.question-answer-value {
  flex: 1;
  min-width: 0;
  word-break: break-word;
  white-space: pre-wrap;
}
```

#### 方案 B：如果答案内容来自富文本

如果“我的答案 / 正确答案”是作为题干富文本中的普通文本渲染出来，需要在富文本预处理或样式层处理缩进：

- 不要让其继承选项以外的额外缩进；
- 不要使用 `text-align: right`；
- 不要让答案值 `float` 或被推到右侧；
- 保证其与 `.option-line` 或题干正文的内容区域左边界一致。

### 验收标准

- “我的答案”和“正确答案”与其他答案/选项的左侧缩进一致。
- 普通单选、多选、判断、填空、多空选择题页面均显示正常。
- 长答案不会超出屏幕。
- 不再出现“我的答案/正确答案”比其他答案多缩进或少缩进的问题。
- 删除独立“答案与解析”区域后，题目区域内的信息仍然完整可读。

------

## 四、需求 3：检查 `pages/wrong-detail` 页面配置的 LLM 模型是否写死，如写死则改为从 `admin_ai_model_configs` 表获取

### 背景

`pages/wrong-detail` 页面点击“生成 AI 解题技巧”时，会请求：

```js
api.post('/ai/error-analysis', { wrong_question_id: wqId })
```

后端入口是：

```python
app/api/v1/ai.py
@router.post("/error-analysis")
```

进一步调用：

```python
app/services/ai_service.py
analyze_error(...)
```

需要确保这个 AI 解析使用的 LLM 模型不是写死的，而是从数据库表：

```text
admin_ai_model_configs
```

读取，并且该模型可以在 Admin 前端：

```text
/admin/ai-settings
```

页面中进行配置。

### 当前需要重点检查的位置

请重点检查以下文件中是否存在写死模型的问题：

```text
app/services/ai_service.py
app/ai/client.py
app/core/config.py
app/services/model_config_resolver.py
app/services/admin_ai_config_service.py
admin-frontend/src/app/(admin)/ai-settings/components/model-cards.tsx
admin-frontend/src/app/(admin)/ai-settings/page.tsx
```

重点搜索关键词：

```text
deepseek-v4-flash
DEEPSEEK_MODEL
TEXT_IMPORT_LLM_MODEL
model=
model_name
ensure_db_model_configured
resolve_active_model
admin_ai_model_configs
```

### 后端修改要求

1. `wrong-detail` 的 AI 解题技巧接口，也就是 `/api/v1/ai/error-analysis`，必须使用 `admin_ai_model_configs` 表中的模型配置。
2. 对应后端调用链应使用：

```python
ensure_db_model_configured(db, feature="analysis")
```

或等价逻辑。

1. `feature="analysis"` 应明确对应“AI 解析 / 错题解析 / 解题技巧”功能。
2. 运行时不要把 `deepseek-v4-flash`、`DEEPSEEK_MODEL` 作为错题详情 AI 解析的最终固定模型。
3. 如果数据库中没有可用的 `analysis` 模型，应按项目现有降级逻辑处理，例如：
   - 返回 fallback；
   - 或返回明确的配置缺失提示；
   - 但不要静默使用写死模型继续请求。
4. `DeepSeekClient.chat()` 可以保留通用兜底能力，但 `/ai/error-analysis` 这条链路必须显式传入从数据库解析出来的 `model_name`、`api_key`、`base_url`。
5. 如果当前代码中 `ensure_db_model_configured(db, feature="analysis")` 已存在，也要继续检查：
   - 当返回 `None` 时是否又回退到 `settings.DEEPSEEK_MODEL`；
   - 是否最终仍然调用了硬编码模型；
   - 日志中的 model 是否真实来自 DB。
6. AI 调用日志 `AiChat.model` 应记录实际返回/调用的模型名，不能固定写死。
7. 保持已有缓存逻辑不变：
   - 如果 `wq.ai_analysis` 已存在，可以继续返回缓存；
   - 缓存返回时 `model` 可以是 `"cache"`。

### 模型选择规则

请使用当前项目已有的模型解析规则，或者按以下规则实现：

1. 优先选择：
   - `is_enabled = true`
   - `features` 包含 `"analysis"` 的模型
2. 如果没有专用 `analysis` 模型：
   - 可以使用未绑定 feature 的通用模型；
   - 但这个通用模型也必须来自 `admin_ai_model_configs` 表
3. 最后才可以使用任意启用模型作为兜底；
4. 不允许在错题详情 AI 解析链路里直接写死具体模型名。

### Admin 前端修改要求

确保 `/admin/ai-settings` 页面可以配置错题详情 AI 解析使用的模型。

重点检查：

```text
admin-frontend/src/app/(admin)/ai-settings/components/model-cards.tsx
```

需要满足：

1. 模型新增弹窗支持选择用途：
   - OCR 纠错
   - AI 补全
   - AI 解析
   - 视觉层
2. “AI 解析”对应的 feature 值必须是：

```ts
analysis
```

1. 模型编辑区域也必须支持修改 `features`，并能保存到后端。
2. 模型列表中应展示该模型用途，比如“AI 解析”。
3. `/admin/ai-settings/page.tsx` 中的模型解析展示也要能显示当前 `analysis` 模型。
4. 如果当前页面已有 `analysis` 选项，不要重复添加，但要确认：
   - 新增模型时能选；
   - 编辑模型时能选；
   - 保存后能回显；
   - 后端接口能正确保存到 `admin_ai_model_configs.features`。
5. 类型定义中需要确认以下字段存在且一致：

```ts
feature?: string | null
features?: string[] | null
```

### 后端 Admin 模型接口要求

检查并确保以下接口正常支持 `analysis` feature：

```text
GET    /api/v1/ai-models
POST   /api/v1/ai-models
PATCH  /api/v1/ai-models/{model_id}
DELETE /api/v1/ai-models/{model_id}
POST   /api/v1/ai-models/test-connection
```

要求：

1. `POST /ai-models` 支持传入：

```json
{
  "name": "xxx",
  "display_name": "xxx",
  "provider": "xxx",
  "api_base_url": "xxx",
  "api_key": "xxx",
  "features": ["analysis"]
}
```

1. `PATCH /ai-models/{id}` 支持修改：

```json
{
  "features": ["analysis"]
}
```

1. 返回值中包含：

```json
{
  "feature": "analysis",
  "features": ["analysis"]
}
```

1. 如果项目已有“同一 feature 只允许一个启用模型”的限制，需要保持这个限制。
2. 如果 `features` 为空或 `null`，表示通用模型。

------

## 五、数据库要求

表名：

```text
admin_ai_model_configs
```

请确认模型表至少支持以下字段：

```text
id
name
display_name
provider
api_base_url
api_key_encrypted
is_enabled
is_default
sort_order
feature
features
created_at
updated_at
```

其中：

- `feature` 是旧字段，单功能兼容；
- `features` 是新字段，JSON 数组，支持多功能绑定；
- `analysis` 应作为错题详情 AI 解析功能标识。

如果数据库迁移或初始化逻辑缺少字段，需要补充迁移或初始化逻辑，避免线上启动时报字段不存在。

------

## 六、完整验收流程

### 1. 小程序错题详情页面

打开一个错题详情页，验证：

- 不再出现独立“答案与解析”卡片；
- 题目区域仍有题干、选项、我的答案、正确答案、解析；
- “我的答案”和“正确答案”缩进与其他答案/选项一致；
- AI 解题技巧按钮存在；
- 点击“生成 AI 解题技巧”可正常请求；
- 请求失败时 fallback UI 正常；
- 左右切换错题后不出现旧 AI 结果串题。

### 2. Admin 前端模型配置

进入：

```text
/admin/ai-settings
```

验证：

- 可以新增模型；
- 可以选择用途“AI 解析”；
- 保存后模型列表展示“AI 解析”标签；
- 编辑模型时可以修改用途；
- 刷新页面后配置仍能回显；
- 模型连接测试可正常使用。

### 3. 后端模型读取

通过数据库创建或 Admin 页面创建一个 `features=["analysis"]` 的模型。

然后调用：

```text
POST /api/v1/ai/error-analysis
```

验证：

- 后端实际使用该 `analysis` 模型；
- 日志中记录的模型名不是写死值；
- 修改 Admin 页面中的 analysis 模型后，错题详情 AI 解析会使用新模型；
- 禁用 analysis 模型后，按规则使用通用模型或 fallback；
- 没有任何启用模型时，不应静默使用写死模型。

### 4. 回归测试

检查以下功能不受影响：

- OCR 纠错模型配置；
- AI 补全模型配置；
- 视觉层模型配置；
- 题目导入；
- 错题详情加载；
- 错题详情 AI 解析缓存；
- 多题左右滑动切换；
- 小程序端普通题目渲染、公式渲染、代码块渲染。

------

## 七、输出要求

完成后请输出以下内容：

1. 修改文件清单。
2. 每个文件的关键改动说明。
3. 是否发现错题详情 AI 模型写死。
4. 如果发现写死，说明已如何改为从 `admin_ai_model_configs` 获取。
5. Admin 前端 `/ai-settings` 是否已支持配置 `analysis` 模型。
6. 小程序错题详情页面的 UI 验收截图或说明。
7. 后端接口验证方法。
8. 仍需注意的风险点。

------

## 八、重要注意事项

1. 不要只删除数据字段，优先解决页面冗余和缩进问题。
2. 不要破坏现有题目渲染逻辑，尤其是数学公式、代码块、富文本、填空题、多空选择题。
3. 不要把模型名继续写死在错题详情 AI 解析链路中。
4. 不要为了满足需求删除 Admin 已有 OCR、补全、视觉模型配置能力。
5. 不要暴露完整 API Key，Admin 前端只能显示掩码。
6. 不要把 `analysis` 和 `completion` 混用，错题详情 AI 解题技巧必须使用 `analysis` 功能模型。
7. 兼容旧数据：如果旧数据只有 `feature` 字段，也要能同步或兼容到 `features`。
8. 修改后请确保项目能正常启动，前后端 TypeScript / Python 不出现语法错误。