# AI 补全功能审计报告

> 审计日期: 2026-06-19
> 审计范围: AI 补全（AI Completion）功能全链路

---

## 1. AI 补全整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│ Admin Frontend (Next.js)                                        │
│  ├─ AI 设置页面 (ai-settings/page.tsx)                          │
│  │   ├─ AiCompletionPreview (completion_auto_* 开关)            │
│  │   └─ OcrAccordion (题目结构修复展示)                          │
│  └─ 导入审核页面 (imports/review/page.tsx)                      │
│       ├─ "AI 补全" 按钮 (单题)                                   │
│       └─ "AI 批量补全" 按钮                                      │
├─────────────────────────────────────────────────────────────────┤
│ Backend API (FastAPI)                                           │
│  ├─ POST /api/admin/v1/imports/questions/{id}/complete (单题)   │
│  └─ POST /api/admin/v1/imports/questions/batch-complete (批量)  │
├─────────────────────────────────────────────────────────────────┤
│ Service Layer                                                   │
│  ├─ admin_import_service.py                                     │
│  │   ├─ complete_import_question()    — 单题补全                │
│  │   └─ batch_complete_import_questions() — 批量补全            │
│  └─ admin_ai_config_service.py — 配置读取                        │
├─────────────────────────────────────────────────────────────────┤
│ Pipeline Layer                                                  │
│  └─ question_pipeline.py                                        │
│      ├─ complete_import()               — 单题补全核心          │
│      ├─ complete_import_with_strategy() — 批量单题补全核心      │
│      ├─ batch_complete_questions()      — 批量调度              │
│      ├─ _detect_missing()              — 检测缺失字段           │
│      └─ _detect_fields_to_complete()   — 字段选择(含配置)      │
├─────────────────────────────────────────────────────────────────┤
│ AI Layer                                                        │
│  ├─ prompts.py — Prompt 模板                                    │
│  │   ├─ SYSTEM_PROMPTS["complete_question"]  → 补全助手         │
│  │   └─ SYSTEM_PROMPTS["question_repair"]    → 修复助手(未启用) │
│  └─ client.py — DeepSeek API 调用                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 实际调用链路

### 单题补全链路

```
用户点击 "AI 补全"
  → review/page.tsx completeMutation
    → POST /imports/questions/{id}/complete
      → admin_import_service.complete_import_question()
        → ensure_ai_parse_allowed()    [DB查询权限]
        → question_pipeline.complete_import()
          → _detect_missing(qi)        [检测缺失字段]
          → 读取 admin_ai_configs      [DB查询自定义completion_prompt]
          → build_complete_question()  [构建Prompt]
          → _call_or_fallback()
            → deepseek.chat()          [HTTP请求DeepSeek API]
            → 解析响应
          → _apply_complete_suggestion() [写入DB]
          → db.commit()                [提交事务]
          → 写 AiGenerationLog         [记录日志]
          → db.commit()                [二次提交!]
```

### 批量补全链路

```
用户点击 "AI 批量补全"
  → POST /imports/questions/batch-complete
    → admin_import_service.batch_complete_import_questions()
      → ensure_ai_parse_allowed()      [DB查询权限]
      → question_pipeline.batch_complete_questions()
        → 读取 admin_ai_configs (一次性)
        → _get_disabled_completion_fields()
        → FOR each import_id (串行!!!):
            → complete_import_with_strategy()
              → _detect_fields_to_complete()
              → build_batch_complete_question()
              → _call_or_fallback()
                → deepseek.chat()       [每道题一次API调用]
              → _apply_batch_complete_result()
              → 写 AiGenerationLog
        → 返回结果
      → db.commit()
```

---

## 3. 性能瓶颈分析

### 瓶颈1：批量补全严格串行（严重）

**位置**: `backend/app/features/question_pipeline.py:2275`

```python
for import_id in import_ids:                          # 串行！
    r = await complete_import_with_strategy(...)       # await等待API返回
```

**问题**: 50 道题 → 50 次串行 DeepSeek API 调用。每道题约 5-15s → 总计约 4-12 分钟。

**当前耗时**: 50题 × 平均10s = ~500s
**优化后耗时**: 50题 / 5并发 × 10s = ~100s
**预计提升比例**: ~5x

### 瓶颈2：单题补全忽略 auto_* 开关配置

**位置**: `backend/app/features/question_pipeline.py:1937`

```python
# complete_import() 中：
missing = _detect_missing(qi)   # 只检查空字段，不读取completion_auto_*配置
```

而 `_get_disabled_completion_fields()` 只在批量补全中被调用。

**问题**: 用户在 AI 设置页面关闭"自动补全题干"等开关，单题补全不生效。这导致：
1. 用户困惑为什么开关没效果
2. 本可以通过关闭开关减少的 API 调用工作量，仍然全量执行

**影响**: 单题补全总是补全所有缺失字段，即使用户配置了排除某些字段。

### 瓶颈3：双次 db.commit()

**位置**: `backend/app/services/admin_import_service.py:190-199`

```python
result = await question_pipeline.batch_complete_questions(db, ...)
await db.commit()  # 第1次
await write_admin_audit(db, ...)  # 在同一个db session中再次写
```

单题补全也有类似问题：`question_pipeline.py:1993` 提交一次，`admin_import_service.py` 外层又提交一次。

### 瓶颈4：每次单题补全都读取 admin_ai_configs

**位置**: `backend/app/features/question_pipeline.py:1942-1947`

每次单题补全都重新查询整个配置表。批量补全只读一次，但单题每次都读。

**当前耗时**: 每次 ~50ms（可忽略）
**优化建议**: 添加本地缓存，5-10s 过期

### 瓶颈5：Prompt 体积大

`SYSTEM_PROMPTS["complete_question"]` 约 800 字 + 用户消息中包含所有已有字段。
对于只需要补全"难度"等简单字段的场景，仍然发送完整的题目上下文。

### 瓶颈6：无流式响应

前端等待完整的 API 调用结束后才显示结果，无法渐进式展示。

---

## 4. 结构修复功能状态分析

### 状态：部分失效

**评估: 功能设计上存在概念混淆，实际"修复题目结构"开关不存在**

### 详细分析

#### 4.1 现有的相关功能

| 功能 | 位置 | 类型 | 状态 |
|------|------|------|------|
| OCR 题目结构修复面板 | ocr-accordion.tsx:43 | **展示型**（无开关） | 仅显示"已启用/已关闭"标签 |
| `ocr_structure_*` 配置 | admin_ai_config_service.py:51-54 | K/V 存储 | 存储了值，影响 OCR 阶段 |
| `completion_auto_*` 开关 | ai-completion.tsx:87-91 | 开关型 | 功能正常但仅影响批量补全 |
| `question_repair` prompt | prompts.py:77 | Prompt | **完整但 AI 补全流程中未使用** |
| `enable_ai_repair` 参数 | pipeline orchestrator | 导入管线参数 | 仅导入管线 stage6 使用 |

#### 4.2 关键发现

1. **OCR 配置面板中"题目结构修复"无开关可操作**
   - 文件: `admin-frontend/.../ocr-accordion.tsx:43-78`
   - 该面板仅显示 4 个状态项（题型识别、选项提取、答案匹配、解析分离），均为纯文本展示
   - 用户看到"已启用"标签但无法开关 → 认为功能失效

2. **`question_repair` prompt 在 AI 补全流程中未被使用**
   - 单题补全 `complete_import()` 使用 `build_complete_question()` → `SYSTEM_PROMPTS["complete_question"]`
   - 批量补全 `batch_complete_questions()` 使用 `build_batch_complete_question()` → `SYSTEM_PROMPTS["complete_question"]`
   - `SYSTEM_PROMPTS["question_repair"]` 仅在导入管线 stage6 的 `ai_repair.repair_questions()` 中使用
   - **AI 补全流程始终使用"补全"策略，从未使用"修复"策略**

3. **`structure_fix_*` 字段从未被实现**
   - 根据计划文档 `done-ai-settings-config-api.md` R5，"结构修复面板缺失"被标记为 🟡
   - 计划补全 `structure_fix_*` 字段但从未落地
   - 数据库中不存在任何 `structure_fix_*` 配置键

4. **`completion_auto_*` 开关在单题补全中不生效**
   - 文件: `backend/app/features/question_pipeline.py:2042-2056`
   - `_get_disabled_completion_fields()` 仅在批量补全中被调用（line 2265）
   - 单题补全 `complete_import()` 直接调用 `_detect_missing()`，无视配置开关

#### 4.3 "开启和关闭效果没有区别"的根因

用户最可能遇到的情况是：

**场景A**: 在 AI 设置页面看到"题目结构修复"面板（OCR 配置中），但该面板仅展示状态，无开关可操作 → "关不掉"

**场景B**: 在 AI 设置页面开关 `completion_auto_*` 选项，然后在导入审核页面对单题点击"AI 补全" → 开关不生效，因为单题补全不读取这些配置

**场景C**: 期望 AI 补全使用"修复"策略而非"补全"策略 → 「修复题目结构」概念在前端不存在，后端有 `question_repair` prompt 但未被接入

---

## 5. 修复方案

### 5.1 性能优化

| # | 修改 | 文件 | 原因 | 风险 | 预估收益 |
|---|------|------|------|------|----------|
| P1 | 批量补全改为并发执行（asyncio.gather + 信号量限流） | `question_pipeline.py` batch_complete_questions | 串行 API 调用是最大瓶颈 | 低（需控制并发数） | 5x |
| P2 | 单题补全读取 `completion_auto_*` 配置 | `question_pipeline.py` complete_import | 让用户配置生效，减少不必要的字段补全 | 低 | 1.5x (减少token) |
| P3 | 减少冗余 db.commit() | `admin_import_service.py` + `question_pipeline.py` | 双次提交浪费 DB 往返 | 低 | 5% |
| P4 | 配置读取添加进程内缓存 | `question_pipeline.py` | 减少重复 DB 查询 | 低 | ~1% |

### 5.2 结构修复功能优化

| # | 修改 | 文件 | 原因 | 风险 |
|---|------|------|------|------|
| S1 | OCR 结构面板添加真实开关 | `ocr-accordion.tsx` | 让用户可以开关结构修复项 | 低（仅前端UI） |
| S2 | 单题补全接入 `completion_auto_*` 配置 | `question_pipeline.py` complete_import | 让用户配置在单题补全中也生效 | 低 |
| S3 | AI 补全增加"题目结构修复"模式选项 | 新增：前端 toggle + 后端参数 | 提供真正的结构修复能力 | 中 |
| S4 | `question_repair` prompt 接入 AI 补全流程 | `question_pipeline.py` | 复用已有 prompt，提供差异化的修复策略 | 中 |

---

## 性能对比估算

```
                   当前耗时(50题)    优化后(50题)    提升比例
单题补全             10-15s          10-15s          不变(单次快不了)
批量补全 50题        ~500s           ~100s           5x
Token用量(50题)      ~200K           ~120K           1.7x (排除不需要的字段后)
DB 往返(50题)        ~100次          ~50次           2x
```
