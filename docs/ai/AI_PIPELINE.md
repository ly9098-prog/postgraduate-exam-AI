# AI Pipeline

> DeepSeek 直连方案，无 langchain/llamaindex，一次请求一次调用。

---

## 当前实现

### 架构

```
用户请求 → Service 编排 → 构造 Prompt → DeepSeek API → 解析 JSON → 缓存 → 返回
```

### 模块分布

| 文件 | 职责 |
|---|---|
| `app/ai/client.py` | httpx 异步客户端，单例，封装 `/v1/chat/completions` |
| `app/ai/prompts.py` | 三个 Prompt 模板（error_analysis / study_advice / summary） |
| `app/ai/context.py` | 上下文构建（仅传必要信息） |
| `app/ai/fallback.py` | API 不可用时的降级静态响应 |
| `app/services/ai_service.py` | 编排层：analyze_error / generate_advice |
| `app/api/v1/ai.py` | 两个路由：POST error-analysis / POST study-advice |

### 关键细节

**客户端** (`client.py`)
- 模型硬编码 `deepseek-chat`，temperature=0.3
- 超时 60 秒（`AI_TIMEOUT`）
- `is_available()` 检查 API key 是否为非空且非占位符

**降级策略** (`fallback.py`)
- 三个静态字典：FALLBACK_ANALYSIS / FALLBACK_ADVICE / FALLBACK_SUMMARY
- 触发条件：API key 未配置 / 请求抛 RuntimeError（网络超时、HTTP 错误）
- 返回结果前端可正常渲染，用户无感知

**错题分析缓存**
- 结果存入 `WrongQuestion.ai_analysis`（JSON 列）
- 同一错题二次请求直接返回 `from_cache=True`，不调 API
- 缓存无过期机制

**调用记录**
- 每次 AI 调用写入 `ai_chats` 表（session_type / messages / response / tokens / duration_ms / context_snapshot）
- 用于成本核算和调用审计

### 数据库中已存在但未使用的

- **`AI_DAILY_TOKEN_LIMIT`**：`config.py` 中定义值为 50000，`ai_service.py` 从未检查
- **`token_counter.py`**：文件不存在，无 token 估算逻辑
- **`summary` prompt**：`prompts.py` 中存在 `build_summary` 函数，无 service 调用

---

## 存在问题

1. **零 token 控制** — 无请求前估算，无日/月限额检查，API 费用不可控
2. **summary 未接入** — Prompt 已定义但无路由和 service 使用
3. **study_advice 无记忆** — 每次调用都是独立请求，不传递历史对话，无法追问
4. **JSON 解析脆弱** — 如果 DeepSeek 返回非标准 JSON，`json.loads` 失败后原始文本直接当 key 包裹，前端可能渲染异常
5. **无重试机制** — 一次失败直接降级，没有临时故障时的重试（如 5xx 可重试 1-2 次）
6. **并发无控制** — 同一用户同时请求 AI 不做排队，可能短时间打满限额
7. **超时后无用户反馈** — 60 秒超时期间前端无进度提示，体验差

---

## 下一阶段扩展方案

### Phase 1 — 基础设施补齐（1-2 天）

```
├── app/ai/
│   ├── token_counter.py     ← 新增
│   ├── rate_limiter.py      ← 新增（可选）
```

- **token_counter.py**
  - 基于字符粗略估算（中文 ~1.5 token/字，英文 ~0.3 token/字符）
  - `check_token_limit(user_id, estimated)` 查询当日 `ai_chats` 累计用量
  - 超限返回降级而非报错
- **service 层集成 token 检查**
  - `ai_service.py` 中每个接口入口调用 `check_token_limit`
- **JSON 解析增强**
  - 尝试从 markdown 代码块提取 JSON（````json ... ````）
  - 兜底用正则提取 `{...}` 结构

### Phase 2 — 功能完善（1-2 天）

- **summary 接口上线**
  - 新增 `POST /api/v1/ai/summary` 路由
  - 输出：按科目/时间段汇总薄弱知识点、推荐复习重点
- **study_advice 增加简单上下文**
  - 携带最近 3 次建议记录摘要，不传完整历史
  - 避免重复建议同一知识点

### Phase 3 — 体验优化（持续）

- **重试 1 次**：遇到 5xx 或网络错误时重试 1 次后再降级
- **取消缓存过期**：`WrongQuestion.ai_analysis` 缓存增加 `cached_at` 时间戳，超过 30 天允许重新分析
- **前端反馈**：接口返回 `{..., estimated_wait_ms: int}`，小程序显示进度提示

---

## 导入管线 AI 架构

### 设计原则（from new_task.md）

1. **OCR 与 AI 解耦** — OCR 只负责文本提取，AI 只负责修复/补全
2. **AI 仅用于修复/补全/结构化增强** — 禁止将所有内容直接丢给 LLM
3. **优先规则解析** — 规则能解决的问题不用 AI
4. **Prompt 外置** — 所有 prompt 统一放入 `/prompts/development/`
5. **AI 能力必须可关闭** — 关闭后不影响核心导入流程

### 管线中的 AI 模块

| 阶段 | 模块 | AI 使用 | 触发条件 |
|------|------|---------|---------|
| stage1 | ImportTextNormalizer | 不使用 | —（纯规则） |
| stage2 | DocumentStructureAnalyzer | 不使用 | —（纯规则） |
| stage3 | QuestionSplitter | 不使用 | —（纯规则） |
| stage4 | AnswerMatcher | 不使用 | —（纯规则） |
| stage5 | QuestionNormalizer | 不使用 | —（纯规则） |
| stage6 | AIRepairService | DeepSeek 修复 | 规则无法解析的低置信度题目 |
| stage7 | 审核系统 | 不使用 | —（人工处理） |
| stage8 | ImportPipelineService | 编排（不直接调用） | — |
| stage9 | OCR 增强 | DeepSeek VL（可选） | 扫描版 PDF 检测 |

### AI 触发流程

```
规则解析成功 → 直接输出（stage1-5 主线）
       ↓（失败）
    AIRepairService（stage6）
       ↓
    AI 修复成功 → 标记 confidence 后进入审核
       ↓
    AI 修复失败 → 标记 unrepaired 后进入审核（人工处理）
```

### Token 控制策略

- 仅在 stage6 和 stage9 消耗 token
- 低频触发：只处理规则无法解析的数据
- 可配置日/月限额，超限后静默跳过
- 修复结果计入 `ai_chats` 表审计

---

### 明确不做的

- ❌ Streaming 输出（小程序不适合流式渲染）
- ❌ LangChain / Agent / Tool Calling
- ❌ 多模型切换（deepseek-chat 够用）
- ❌ 对话历史无限保留（只保留最近 20 条）
- ❌ 用户自定义 Prompt
