# AI 解析设置页面 — 配置接口实施

## 目标

为 AI 解析设置页面（`/ai-settings`）的 3 个配置 UI（ModelCards / OcrAccordion / AiCompletionPreview）补全后端 API、数据库表和持久化逻辑，使配置可保存、可读取、可编辑。默认值沿用当前代码中硬编码的 prompt 和配置项。

---

## 总览

| Phase | 内容 | 涉及新文件 |
|-------|------|-----------|
| A | 提取现有 prompt 保存到 `/docs/` | `docs/backend/ai-prompts.md` |
| B | 数据库表 + Alembic migration | `models/admin_ai_config.py` |
| C | Pydantic schema + Service + Route | `schemas/admin_ai_config.py`, `services/admin_ai_config_service.py`, `api/v1/admin_ai_config.py` |
| D | 前端对接（TypeScript 类型 + 组件重写） | 修改现有 3 个组件 |

---

## 审计风险处置对照

| 风险 | 级别 | 处置方式 |
|------|------|---------|
| R1 api_key 明文存储 | 🔴 | 加密存储，API 响应不返回明文 |
| R2 单行表兼容性 | 🔴 | 改用键值对表 `admin_ai_configs` |
| R3 PATCH/PUT 不统一 | 🟡 | 全部统一为 PATCH |
| R4 权限颗粒度 | 🟡 | 沿用现有 `ai_setting:read/write`，关键操作写审计日志 |
| R5 结构修复面板缺失 | 🟡 | 补全 `structure_fix_*` 字段 |
| R6 前后端字段错位 | 🟡 | 重新对齐字段命名 |
| R7 命名规范 / migration | 🟡 | 使用 `admin_` 前缀 + Alembic |
| R8 假配置 | 🟡 | UI 标注提示，预留抽象层 |
| R9 不热更新 | 🟢 | 现阶段只存不用 |
| R10 统计数据缺失 | 🟢 | 保留前端静态展示 |
| R11 API Key 验证 | 🟢 | 保存时测试调用 |
| R12 Prompt 长度校验 | 🟢 | Schema 加 `max_length` |

---

## Phase A — 保存 prompt 到 /docs/

**文件**: `docs/backend/ai-prompts.md`

从以下文件提取所有系统 prompt：
- `app/ai/prompts.py` — OCR 纠错 / 题目修复 / 题目富化 / 题目生成 / 题目补全
- `app/ai/prompts_learning.py` — 题目讲解 / 错因分析 / 学习报告
- `app/features/ocr_service.py` — 视觉 OCR 提示词

每个 prompt 标注：来源文件、用途、对应函数名。

---

## Phase B — 数据库表

### B1. `admin_ai_model_configs`

```python
class AdminAiModelConfig(Base):
    __tablename__ = "admin_ai_model_configs"
    
    id: int (PK, autoincrement)
    name: str(64)         # "deepseek-v4-flash"
    display_name: str(64) # "DeepSeek V4 Flash"
    provider: str(32)     # "deepseek" / "openai" / "anthropic"
    api_base_url: str | None
    api_key_encrypted: str | None  # AES-256 加密存储
    is_enabled: bool (default=True)
    is_default: bool (default=False)
    sort_order: int (default=0)
    created_at: datetime
    updated_at: datetime
```

- `api_key_encrypted` 在 API 响应中替换为 `api_configured: bool`
- 加密密钥从环境变量 `AI_CONFIG_ENCRYPT_KEY` 读取
- 加密使用 `cryptography.fernet`

### B2. `admin_ai_configs`（键值对表，避免单行表兼容性问题）

```python
class AdminAiConfig(Base):
    __tablename__ = "admin_ai_configs"
    
    config_key: str(64) (PK)
    config_value: Text  # JSON 序列化存储
    updated_by: int | None
    updated_at: datetime
```

支持的 config_key 及值类型：

| Key | 类型 | 默认值 | 对应 UI |
|-----|------|--------|---------|
| `ocr_correction_prompt` | str | `SYSTEM_PROMPTS["ocr_correction"]` 全文 | OCR 纠错 Prompt 文本框 |
| `ocr_strategy_math_formula` | bool | true | OCR 纠错策略 - 数学公式修复 |
| `ocr_strategy_punctuation` | bool | true | OCR 纠错策略 - 标点符号校正 |
| `ocr_strategy_digit_letter` | bool | true | OCR 纠错策略 - 数字与字母混淆修复 |
| `ocr_strategy_space_newline` | bool | false | OCR 纠错策略 - 空格与换行处理 |
| `ocr_structure_question_type` | bool | true | 题目结构修复 - 题型识别 |
| `ocr_structure_options` | bool | true | 题目结构修复 - 选项提取 |
| `ocr_structure_answer` | bool | true | 题目结构修复 - 答案匹配 |
| `ocr_structure_analysis` | bool | true | 题目结构修复 - 解析分离 |
| `ocr_filter_max_chars` | int | 2000 | 长文本过滤 - 单题最大字符数 |
| `ocr_filter_max_tokens` | int | 4096 | 长文本过滤 - 单次最大 Token 数 |
| `ocr_filter_sensitive` | bool | true | 长文本过滤 - 敏感内容过滤 |
| `completion_prompt` | str | `SYSTEM_PROMPTS["complete_question"]` 全文 | AI 补全 Prompt 文本框 |
| `completion_auto_stem` | bool | true | 自动补全题干 |
| `completion_auto_options` | bool | true | 智能选项生成 |
| `completion_auto_answer_reasoning` | bool | false | 答案推理链 |
| `completion_auto_knowledge_tags` | bool | true | 知识点标签 |

---

## Phase C — 后端 API

### 路由前缀: `/api/admin/v1`

统一文件 `api/v1/admin_ai_config.py`、`services/admin_ai_config_service.py`、`schemas/admin_ai_config.py`

#### C1 模型配置

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ai-models` | GET | 返回模型列表（不含 api_key，含 `api_configured: bool`） |
| `/ai-models/{id}` | PATCH | 更新单个模型字段（is_enabled / is_default / api_key / api_base_url） |

- PATCH 时若 `api_key` 为 `"****"` 表示不修改
- PATCH 时若 `api_key` 为真实值 → 加密存储 → 并做一次测试调用验证有效性
- 设置 `is_default=true` 时，自动清除其他模型的 default 标志

#### C2 配置项

| 端点 | 方法 | 说明 |
|------|------|------|
| `/ai-configs` | GET | 返回所有配置键值对（扁平 JSON 对象） |
| `/ai-configs` | PATCH | 部分更新提交的配置项（只提交有变化的字段） |

- PATCH body: `{"key": value, ...}` — 只包含要修改的项
- 不存在的 key 自动忽略
- prompt 字段 `max_length=5000`

#### 权限控制

- 均沿用 `ai_setting:read`（GET）和 `ai_setting:write`（PATCH）
- PATCH 操作记录 `severity=normal` 审计日志（action: `ai_config.update`）

---

## Phase D — 前端对接

### D1 TypeScript 类型 (`types.ts`)

```typescript
export type AdminAiModelConfig = {
  id: number;
  name: string;
  display_name: string;
  provider: string;
  api_base_url: string | null;
  api_configured: boolean;
  is_enabled: boolean;
  is_default: boolean;
  sort_order: number;
  call_count?: number;      // 前端本地从 stats 拼接
  avg_latency_ms?: number;  // 前端本地从 stats 拼接
};

export type AdminAiModelPatchRequest = {
  is_enabled?: boolean;
  is_default?: boolean;
  api_key?: string;
  api_base_url?: string;
};

export type AdminAiConfigs = Record<string, string | number | boolean>;
```

### D2 ModelCards 组件重写

- 从 `GET /api/admin/v1/ai-models` 获取模型列表
- 开关/默认按钮 → `PATCH /api/admin/v1/ai-models/{id}`
- 统计数据（callCount/avgLatency）保留静态展示，阶段目标暂不接真实数据
- 加载态：卡片骨架屏
- 错误态：保留上次成功数据 + toast 提示

### D3 OcrAccordion 组件重写

- 从 `GET /api/admin/v1/ai-configs` 读取所有 OCR 相关 key
- 保存时 `PATCH /api/admin/v1/ai-configs` 只发送修改的 key
- 加载态：各 panel 内容显示骨架屏
- 错误态：保留上次成功值，操作栏显示错误提示
- 第 3 面板数据补齐：后端 `structure_fix_*` 4 字段

### D4 AiCompletionPreview 组件重写

- 从 `GET /api/admin/v1/ai-configs` 读取 `completion_*` 相关 key
- Prompt 默认值从 API 返回的 `completion_prompt` 中读取
- 补全维度按钮重新对齐为：补全内容类型（题干/答案/解析/知识点），toggle 为"补全时包含该字段"

### D5 页面集成（page.tsx）

- 新增 `useQuery(["ai-models"])` 和 `useQuery(["ai-configs"])`
- 数据传给各子组件
- 统一 loading / error 状态管理

---

## 不变的部分

- `app/ai/client.py` — 模型调用仍硬编码，新表仅存储不生效
- `app/ai/prompts.py` — prompt 仍从常量读取，新表初始值为这些常量副本
- `app/core/config.py` / `app/features/ocr_service.py` — 不受影响
- 扫描版 OCR（视觉识别）不动

## UI 标注文案

- 模型卡片底部提示：*"当前版本实际使用模型为 DeepSeek V4 Flash，此处配置仅作为记录"*
- 配置区域提示：*"配置已保存，将在后续版本中生效"*

---

## 执行顺序

```
Phase A (docs)
  ↓
Phase B (model + migration) ─→ Phase C (API) ─→ Phase D (frontend)
  └── B1 model_configs ─────→ C1 ai-models API ──→ D2 ModelCards
  └── B2 ai_configs (kv) ───→ C2 ai-configs API ──→ D3 OcrAccordion
                                                    └── D4 AiCompletionPreview
                                                    └── D5 page integration
```
