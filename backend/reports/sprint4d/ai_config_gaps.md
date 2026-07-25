# AI Config Gaps — Sprint 4D 审计结果

生成日期: 2026-07-18

## admin_ai_model_configs 实际字段

| 字段 | 类型 | 用途 |
|------|------|------|
| `id` | Integer PK | 自增主键 |
| `name` | String(64) UNIQUE | 模型名称（如 deepseek-v4-flash），也作为 model_name 用于 API 调用 |
| `display_name` | String(64) | 显示名称（如 DeepSeek V4 Flash） |
| `provider` | String(32) | Provider 类型（deepseek / paddleocr_vl / openai） |
| `api_base_url` | String(256) | API Endpoint（可为空，默认 https://api.deepseek.com） |
| `api_key_encrypted` | String(512) | Fernet 加密的 API Key |
| `is_enabled` | Boolean | 启用状态（默认 true） |
| `is_default` | Boolean | 默认标志（同一 capability 下最多一个 true） |
| `sort_order` | Integer | 排序优先级（升序） |
| `feature` | String(32) | 旧版单 feature 字段（兼容） |
| `features` | JSON | 新版多 feature 支持（JSON 数组如 ["ocr","vision"]） |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

## admin_ai_configs 实际字段

| 字段 | 类型 | 用途 |
|------|------|------|
| `config_key` | String(64) PK | 配置键（如 ocr_strategy_math_formula） |
| `config_value` | Text | 配置值 |
| `updated_by` | Integer | 最后更新者 ID |
| `updated_at` | DateTime | 更新时间 |

## 两表关联方式

**无外键关联。** 两个表完全独立：
- `admin_ai_configs` 是扁平键值对存储，用于 OCR 策略开关、补全策略开关
- `admin_ai_model_configs` 是结构化模型配置，用于 AI 模型运行时配置

## 现有调用链

### admin_ai_configs（键值配置）
```
pipeline_orchestrator → get_all_configs() → DB query (TTL 10s cache) → OCR 策略开关
question_ai_complete → get_all_configs() → DB query (TTL 10s cache) → 补全策略开关
```

### admin_ai_model_configs（模型配置）
```
model_config_resolver.resolve_active_model(db, feature)
  → DB query (no cache) → decrypt_api_key → (api_key, base_url, model_name)

OCRFixRouter.configure(config)
  ← 从 pipeline_orchestrator 传入的 config dict
  ← deepseek_api_key, deepseek_base_url
  ← paddleocr_vl_api_token, paddleocr_vl_base_url, paddleocr_vl_model

OCRGateway._register_remote_adapter()
  ← PaddleOCRVLDocumentAdapter() ← 空参数 (GAP!)
```

## 现有配置解析器

`app/services/model_config_resolver.py` 已有：
- `resolve_active_model(db, feature)` — capability 匹配 + 多级回退
- `ensure_db_model_configured(db, feature)` → (api_key, base_url, model_name)

**Sprint 4D 扩展：** 新增 `AIModelConfigResolver` 类 + `ResolvedAIModelConfig` + `AIModelConfigSnapshot`。

## Gaps

1. **OCRGateway 未使用 DB 配置** — `_register_remote_adapter()` 创建空配置的 VL 适配器
2. **PipelineExecutionContext 无配置快照** — 重启任务时重新查询，可能选到不同模型
3. **模型配置无缓存** — `admin_ai_configs` 有 TTL 10s 缓存，`admin_ai_model_configs` 无缓存
4. **能力标记不一致** — admin_ai_configs 用 key 区分功能，model_configs 用 features JSON 列
5. **OCR 轻量/VL 未区分** — 当前 DB 中无专门用于远程轻量 OCR 的模型种子
6. **Secret 边界** — _decrypt_model() 返回解密后的 key，可能被传给 PipelineExecutionContext
7. **每页查询风险** — 无能力级别缓存时，每个页 OCR 调用可能重复查询数据库
