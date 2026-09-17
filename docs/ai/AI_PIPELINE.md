# AI Pipeline

> OpenAI-compatible 网关直连方案（Qwen / GLM 等，模型由 Admin API 配置于数据库 `admin_ai_model_configs`），无 langchain/llamaindex，一次请求一次调用。

---

## 当前实现

### 架构

```
用户请求 → Service 编排 → 构造 Prompt → OpenAI-compatible 网关（模型由 admin_ai_model_configs 决定）→ 解析 JSON → 缓存 → 返回
```

### 模块分布

| 文件 | 职责 |
|---|---|
| `app/ai/client.py` | httpx 异步客户端，单例，封装 `/v1/chat/completions` |
| `app/ai/prompts.py` | 基础错题分析 / 学习建议 / summary / 导入辅助 Prompt 模板 |
| `app/ai/prompts_learning.py` | AI 学习引擎 Prompt（讲解、错因分析、学习报告） |
| `app/ai/context.py` | 上下文构建（仅传必要信息） |
| `app/ai/fallback.py` | API 不可用时的降级静态响应 |
| `app/services/ai_service.py` | 基础编排层：analyze_error / generate_advice |
| `app/services/ai_learning_service.py` | AI 学习引擎：讲解、规则推荐、学习报告、错因分析、token 限额检查 |
| `app/features/question_pipeline.py` | 题目标准化入口（保留 `QuestionNormalizer` + 向后兼容重导出）；AI/导入逻辑已拆至 4 个子模块（P5-3） |
| `app/features/question_ai_complete.py` | ✅ P5-3 拆出：AI 补全 + 批量补全 |
| `app/features/question_ai_enrich.py` | ✅ P5-3 拆出：AI 丰富 |
| `app/features/question_draft_generator.py` | ✅ P5-3 拆出：AI 生成草稿 |
| `app/features/question_import_writer.py` | ✅ P5-3 拆出：Excel/PDF 导入 + 审核操作 |
| `app/features/pipeline_orchestrator.py` | 16 阶段管线编排（P5-2 已拆分 9 个 stage 到 pipeline_stages/） |
| `app/features/pipeline_stages/` | 7 个独立 stage 模块（match/math_detect/table_detect/normalize_schema/repair/review） |
| `app/features/ai_safety.py` | ✅ P0 新增：AI 编辑安全门禁（diff 记录 + 版本回退 + 代码/中文/选项保护） |
| `app/features/ocr_failure_analyzer.py` | ✅ P6-3 新增：16 种失败分类 + 自动归因 |
| `app/api/v1/ai.py` | 路由：基础 AI 端点 + Stage 13 AI 学习引擎端点 |

### 关键细节

**客户端** (`client.py`)
- 模型由 `admin_ai_model_configs` 数据库配置解析（历史默认 `deepseek-chat` 已移除），temperature=0.3
- 超时 60 秒（`AI_TIMEOUT`）
- `is_available()` 检查 API key 是否为非空且非占位符

**基础 AI 服务** (`ai_service.py`)
- `POST /api/v1/ai/error-analysis`：错题分析，结果缓存到 `WrongQuestion.ai_analysis`
- `POST /api/v1/ai/study-advice`：基于最近错题统计生成学习建议
- 基础服务仍是一次请求一次 LLM 调用；模型不可用时返回 fallback

**AI 学习引擎** (`ai_learning_service.py`)
- `POST /api/v1/ai/explain`：题目讲解
- `POST /api/v1/ai/recommend`：相似题推荐，当前为规则推荐，`tokens_used=0`
- `POST /api/v1/ai/report`：学习报告
- `POST /api/v1/ai/analyze-mistake`：错因分析
- 引擎内置日/月 token 限额检查（`AI_DAILY_TOKEN_LIMIT` / `AI_MONTHLY_TOKEN_LIMIT`）与 markdown code fence JSON 解析兜底

**降级策略** (`fallback.py`)
- 静态 fallback 覆盖错题分析、学习建议、讲解、学习报告等场景
- 触发条件：API key 未配置 / 请求抛 RuntimeError / token 限额用尽
- 返回结果前端可正常渲染，用户无感知

**错题分析缓存**
- 基础 `error-analysis` 结果存入 `WrongQuestion.ai_analysis`（JSON 列）
- 同一错题二次请求直接返回 `from_cache=True`，不调 API
- 缓存无过期机制

**错题分析作答事实锚定**（`app/ai/answer_grounding.py`，2026-09-17 引入）
- 服务端先确定性推导漏选/错选事实（`missing_items` / `extra_items`），作为唯一答案事实源注入 prompt（v4-grounded-answer-facts），LLM 不得重新推断
- 生成后校验模型回填的 `answer_check` 与服务端事实一致，且 `mistake_diagnosis` 不与漏选/错选事实矛盾；不一致时 fail-closed，改用确定性修复内容（`grounding_guard=repaired`）并缓存，不重复付费调用
- 错题作答版本与题目当前版本不一致时做语义漂移守卫：历史版本答案语义无法映射到当前版本则返回版本提示分析（`revision_guarded`），不误判新选项
- 展示的"作答核对"首句始终由服务端生成，模型只补充教学解释

**调用记录**
- AI 调用写入 `ai_chats` 表（session_type / messages / response / tokens / duration_ms / context_snapshot）
- 用于成本核算和调用审计

> 2026-05-31 更新原因：同步当前 Stage 13 AI 学习引擎端点、token 限额检查与 JSON 解析兜底实现。

### 已实现但边界需注意

- **token 限额只覆盖 AI 学习引擎**：`ai_learning_service.py` 已检查日/月额度；基础 `ai_service.py` 的 `error-analysis` / `study-advice` 仍未做额度检查。
- **summary Prompt 仍未接入基础路由**：`prompts.py` 中存在 `build_summary`，当前无 `/ai/summary` 路由。
- **基础 AI JSON 解析仍较弱**：`ai_service.py` 直接 `json.loads`，失败后包裹原始文本；AI 学习引擎已有 code fence / JSON 对象提取兜底。

---

## 存在问题

1. **基础 AI 服务 token 控制缺口** — `error-analysis` / `study-advice` 未接入 `_check_token_limit`
2. **summary 未接入** — Prompt 已定义但无路由和 service 使用
3. **study_advice 无记忆** — 每次调用都是独立请求，不传递历史对话，无法追问
4. **基础 AI JSON 解析脆弱** — 模型返回非标准 JSON 时仅包裹原始文本，前端可能渲染异常
5. **无重试机制** — 一次失败直接降级，没有临时故障时的重试（如 5xx 可重试 1-2 次）
6. **并发无控制** — 同一用户同时请求 AI 不做排队，可能短时间打满限额
7. **超时后无用户反馈** — 60 秒超时期间前端无进度提示，体验差

---

## 下一阶段扩展方案

### Phase 1 — 基础 AI 服务补齐（1-2 天）

- **复用 AI 学习引擎限额检查**
  - 将 `ai_service.py` 的 `error-analysis` / `study-advice` 接入日/月 token 限额
  - 超限返回降级而非报错
- **JSON 解析增强**
  - 复用 `_parse_json_response` 思路，从 markdown 代码块提取 JSON
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

### 管线中的 AI 模块（2026-06-21 更新：16 阶段管线）

| 阶段 | 模块 | AI 使用 | 触发条件 |
|------|------|---------|---------|
| [1] extract | PaddleOCR | 不使用 | —（纯 OCR） |
| [2] normalize | ImportTextNormalizer | 不使用 | —（纯规则，13 步清洗管线） |
| [3] ocr_correction | OCRFixRouter | ✅ PaddleOCR-VL → LLM（Qwen/GLM）→ Rule | 噪声/结构异常/低置信度触发 |
| [4] analyze_structure | DocumentStructureAnalyzer | 不使用 | —（纯规则） |
| [5] classify_pages | PageClassifier | 不使用 | —（纯规则） |
| [6] split | QuestionSplitter | 不使用 | —（纯规则，题号+选项提取） |
| [7] match | AnswerMatcher | 不使用 | —（纯规则） |
| [8] normalize_schema | QuestionNormalizer + BatchValidation + BatchDedup | 不使用 | —（纯规则标准化+校验+去重） |
| [9] repair | AIRepairService | ✅ LLM 修复（Qwen/GLM） | 规则无法解析的低置信度题目 |
| [10] ai_validation | AI 验证 | ✅ LLM 验证（Qwen/GLM） | repair 后补充验证 |
| [11] similarity_match | SimilarityMatcher | 不使用 | —（difflib 规则） |
| [12] math_detect | MathImportProfile | 不使用 | —（规则公式区域检测 + 截图裁剪） |
| [13] table_detect | TableRegionDetector | 不使用 | —（规则多列 Token + Markdown 转换） |
| [14] review | 审核系统 | 不使用 | —（人工处理） |
| — | pipeline_artifacts | 不使用 | checkpoint 文件存储，resume 跳过已完成 stage |
| — | quality_report | 不使用 | 每 pipeline 完成后输出风险分布/性能 Profile |
| — | ocr_failure_analyzer | 不使用 | 16 种失败分类自动归因 |

### AI 触发流程

```
规则阶段（stage1-2, 4-8, 12-14）→ 直接输出，不调用 AI
       │
       ├─ stage3 (ocr_correction): 噪声/结构异常/低置信度 → OCRFixRouter
       │    PaddleOCR-VL（链首，外部高精 OCR API）
       │      → LLM（Qwen/GLM）纯文本纠错
       │        → Rule（原样返回，不阻塞）
       │  每次编辑经过 AI Safety Gate（diff 记录 + 代码/中文/选项保护）
       │
       ├─ stage9 (repair): 规则标准化后仍有低置信度题 → AIRepairService
       │    高置信度题（>0.95）跳过 AI 修复
       │    AI 修复成功 → 标记 confidence 后进入审核
       │    AI 修复失败 → 标记 unrepaired 后进入审核（人工处理）
       │
       ├─ stage10 (ai_validation): repair 后补充 AI 验证
       │
       └─ question_pipeline (complete/enrich): 导入后 AI 补全/丰富（可选）
```

### Token 控制策略

- AI 调用集中在 stage3（ocr_correction）、stage9（repair）和 question_pipeline（complete/enrich）
- stage3 使用独立 token budget，auto 模式仅噪声时触发
- stage9 高置信度题（>0.95）跳过 AI 修复
- 可配置日/月限额，超限后静默跳过
- 修复结果计入 `ai_chats` 表审计
- `ai_safety.py` 对所有 AI 编辑记录可审计的 `AIEditTrace`（模型、变更前后、diff）

---

### 明确不做的（2026-06-21 更新）

- ❌ Streaming 输出（小程序不适合流式渲染）
- ❌ LangChain / Agent / Tool Calling
- ❌ 对话历史无限保留（只保留最近 20 条）
- ❌ 用户自定义 Prompt
- ❌ LLM 输出缓存（每次 AI 调用独立，缓存会导致陈旧结果无法更新）
- ❌ 纯 AI 自动入库（所有导入必须经过 question_imports + 人工确认）
- ❌ 完全移除旧版 `ocr_correction.py`（保留 171 行向后兼容包装，可安全删除但需验证外部调用方）
