# BUGS

> 审计日期: 2026-06-17
> 修复日期: 2026-06-17
> 优先级: CRITICAL > HIGH > MEDIUM > LOW

---

## CRITICAL

### C1. `deepseek.chat()` URL 双写 `/v1` 风险 ✅

**位置**: `backend/app/ai/client.py:60`

`f"{_base_url}/v1/chat/completions"` 在 `_base_url` 已含 `/v1` 时构造出 `/v1/v1/chat/completions`。

- 触发条件: legacy 路径 + DB 中 `feature="ocr"` 配置为 Qwen-VL（`base_url=https://dashscope.aliyuncs.com/compatible-mode/v1`）
- 影响: 请求失败 → `return None` → 纠错静默跳过，无日志告警
- 当前实际影响有限（`ocr_fix_feature_flag` 默认 true 走 router，不走 legacy）

**修复**: 构造 URL 前检查并 strip 末尾 `/v1`，再统一拼接 `/v1/chat/completions`。

### C2. 两套独立 token 计数器，无共享预算 ✅

**位置**: `ocr_correction.py:57-59` / `ai_repair.py:22`

OCR 纠错和 AI Repair 各自维护模块级 `_token_usage` dict，进程重启归零，日/月总额限制形同虚设。

- 影响: 无法实施真实预算控制，成本不可控
- 并发: `_token_usage` 操作无锁保护（见 M5）

**修复**: 抽取共享模块 `backend/app/features/token_budget.py`，两处统一导入，加 `asyncio.Lock` 保护并发。

---

## HIGH

### H1. Router 模式逐块串行调用 ✅

**位置**: `pipeline_orchestrator.py:1381`

`_run_ocr_correction_router` 用 `for idx, block in enumerate(...)` 逐块串行调用 `router.fix()`。Legacy 路径 `ocr_correction.py:463-472` 使用 `asyncio.gather` + `Semaphore(3)` 并发 3 路。

- 影响: Router 模式多 block 导入显著更慢
- 额外问题: `qwen_adapter.py:279` 每次新建 `httpx.AsyncClient`，无连接复用

**修复**: Router 模式改为两阶段（分类 + `asyncio.gather` 并发调用），QwenFixer 增加实例级 `httpx.AsyncClient` 复用。

### H2. 长度安全阈值不一致 ✅

**位置**: `ocr_correction.py:318` vs `deepseek_adapter.py:86`

同一 OCR 纠错功能，legacy 使用 `0.3` 倍下限，DeepSeekFixer 使用 `0.5` 倍下限。

- 影响: `0.3` 过于宽松，可能接受 AI 输出严重截断的文本

**修复**: legacy 路径统一切换为 `0.5`。

### H3. Legacy 路径无法利用 VL 模型的图片能力 ✅

**位置**: `ocr_correction.py:276-321`

`_call_ai_correction` 仅传入文本 `block_text`，调用 `deepseek.chat()`（纯文本 API）。即使 `feature="ocr"` 配置为 Qwen-VL 视觉模型，图片数据完全不传递，Qwen-VL 退化为纯文本纠错。

**修复**: `correct_ocr_blocks` 新增 `page_images` 参数，透传到 `_call_ai_correction`；当 base_url 含 dashscope 且提供了页面图片时，构造多模态 vision 请求。

---

## MEDIUM

### M1. 批次 token 计数截断 ✅

**位置**: `ai_repair.py:349`

`token_used: result["tokens_used"] // len(batch)` 整数除法丢弃余数，逐批累加后总 token 计数偏小。

**修复**: 改为 `base + (1 if pos < rem else 0)` 公平分配余数。

### M2. `corrected_blocks` None 穿透风险 ✅

**位置**: `ocr_correction.py:426-428` / `ocr_correction.py:520`

初始化为 `[None] * len(...)`，末尾 list comprehension 过滤 None。若循环遗漏任何 block（当前逻辑不会，但代码脆弱），None 被静默丢弃，最终 blocks 数量 < 输入数量，下游 splitter 可能收到不完整数据。

**修复**: 过滤前增加防御性检查，对残留 None 打印 error 日志并回退为原始 block。Router 路径同步加固。

### M3. 白板 marker 恢复丢失 AI 修复结果 ✅

**位置**: `ai_repair.py:491-493`

AI 修复的 stem 若不含原始 blank_option_groups 的全部 markers，整个修复的 stem 被丢弃、回退为原始 stem。该保护正确但未记录 warning 日志，排查时无法知道 AI 修复因 marker 丢失被弃用。

**修复**: 添加 `logger.warning(...)` 记录丢弃原因和涉及的 markers。

### M4. Token 估算重复计算 ✅

**位置**: `ocr_correction.py:288-297`

先做 `_estimate_tokens(block_text) * 3` 与 `max_tokens` 比较，line 300 又重复计算一次 `_estimate_tokens(block_text) * 3` 用于预算检查。

**修复**: 合并为一次计算，统一复用。

### M5. `_token_usage` 并发非安全 ✅

**位置**: `ocr_correction.py` / `ai_repair.py`

两个模块的 `_token_usage` dict 操作（`_reset_counters_if_needed` / `_record_token_usage`）无锁保护。多并发导入时存在竞态条件。

**修复**: 共享模块 `token_budget.py` 所有 dict 操作由 `asyncio.Lock` 保护。

---

## LOW

### L1. `ocr_correction.py` 和 `ai_repair.py` 代码重复 ✅

`_reset_counters_if_needed`、`_check_token_limit`、`_record_token_usage`、`_estimate_tokens` 在两处完全重复。任何 budget 逻辑修改需改两处。

**修复**: 抽取共享模块 `backend/app/features/token_budget.py`，两处统一导入。

### L2. AI 修复降级时无区分日志 ✅

**位置**: `ai_repair.py:352-358`

batch parse 失败时逐题降级调用 `_call_ai_for_repair`，降级原因只记录了一条 warning，未在最终结果中标记"此题为 batch-fallback 修复"，排查困难。

**修复**: 降级结果添加 `_batch_fallback=True` 标记，最终 repaired 条目携带 `repair_method: "batch_fallback"` 和 `batch_fallback_repair` risk flag。

---

## 总结

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 总问题数 | 10 | 0 |
| CRITICAL | 2 | 0 |
| HIGH | 3 | 0 |
| MEDIUM | 5 | 0 |
| LOW | 2 | 0 |

所有问题均已修复，涉及文件:

| 文件 | 涉及问题 |
|------|----------|
| `backend/app/ai/client.py` | C1 |
| `backend/app/features/token_budget.py` | C2, M5, L1 (新增) |
| `backend/app/features/ocr_correction.py` | C2, H2, H3, M2, M4, M5, L1 |
| `backend/app/features/ai_repair.py` | C2, M1, M3, M5, L1, L2 |
| `backend/app/features/pipeline_orchestrator.py` | H1, H3 |
| `backend/app/features/ocr_fix/qwen_adapter.py` | H1 |
