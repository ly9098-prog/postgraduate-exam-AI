# OCR 导入使用说明

> 面向管理员和操作者，说明如何通过图片/PDF OCR 导入题目，以及系统如何自动纠错。
>
> 更新于 2026-06-21（P8 功能冻结）。OCR 导入管线已进入功能冻结，后续仅进行 bugfix。

---

## 1. 概述

系统支持通过图片（PNG/JPG）和 PDF（文本型/扫描型）导入题目，完整流程：

```
上传图片/PDF → PaddleOCR 识别 → 规则清洗 → AI 纠错 → 结构分析
  → 题目切分 → 答案匹配 → 标准化 → AI 修复（可选）→ 公式截图 → 表格检测
  → 审核暂存区 → 人工审核 → 入库
```

总共 16 个阶段（extract → review），支持 checkpoint + artifact resume（中断后从已完成阶段恢复，不重跑 OCR）。

所有导入的题目**必须经过人工确认**才能进入正式题库。

---

## 2. 导入方式

### 2.1 批量图片导入（推荐）

> 路径：Admin 后台 → 导入 → 批量图片上传

支持同时上传多张图片，系统并行处理后统一进入待审核队列。

**请求示例：**

```
POST /api/admin/v1/imports/batch-image/upload?concurrency=2&enable_ai_repair=true
```

参数说明：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `concurrency` | 2 | 并发数，范围 1-4，过高可能触发 AI 限流 |
| `enable_ai_repair` | true | 是否启用 AI 修复（标准化阶段） |
| `confidence_threshold` | 0.6 | AI 标准化置信度阈值 |

**状态查询：**

```
GET /api/admin/v1/imports/batch-image/{job_id}
```

返回每张图片的处理状态（pending / processing / succeeded / failed）和识别文本。

### 2.2 单张图片导入

> 路径：Admin 后台 → 导入 → 试题上传 → 选择图片

单张上传后同步等待 OCR + 管线处理完成，返回待审核题目。

---

## 3. AI OCR 纠错机制

系统在 OCR 识别后、题目切分前，会自动判断是否需要 AI 纠错。纠错由**触发引擎** + **纠错路由器（OCRFixRouter）**两级控制。

### 3.1 触发引擎（Trigger Engine）

纠错不是无脑触发的。系统从多个维度评估 OCR 质量，满足任一条件即触发纠错：

| 维度 | 检测内容 | 典型触发场景 |
|------|----------|-------------|
| **噪声检测** | 乱码字符（�□█）、控制字符、短行比例 | 扫描件、低质量图片 |
| **结构异常** | 中文占比异常、符号密度过高、无意义 ASCII 串、选项结构失效、选项缺失 | OCR 严重错乱、选项被吞 |
| **低置信度** | PaddleOCR 平均置信度 < 0.85 | 模糊图片、不规则字体 |

**图片场景**自动降低触发阈值（标准阈值的 70%），更容易触发纠错，但不会无条件强制调用 AI。

### 3.2 纠错路由器（OCRFixRouter）

触发纠错后，按以下链顺序尝试，成功后立即返回：

```
PaddleOCR-VL（外部高精 OCR API：看图纠错） → LLM 纠错（Qwen/GLM，OpenAI-compatible 网关：文本修复） → 规则降级（原样返回）
```

- **PaddleOCR-VL**（链首）：外部高精 OCR API，接收原图做视觉识别，凭证由 DB 动态管理（`resolve_active_model(feature="vision")`），admin UI 可配置
- **LLM 纠错（Qwen/GLM）**（回退）：纯文本纠错，修复 OCR 常见错字、错位等，含 length 越界检查（0.5x~2x）和题干丢失保护
- **规则降级**（最终 fallback）：所有 AI 不可用时原样返回，不阻塞流程
- **AI Safety Gate**（`ai_safety.py`）：每次 AI 编辑记录变更前后 diff，保护代码符号/中文比例/选项数，所有编辑可审计追溯

> ⚠️ Qwen-VL 已从路由链中移除（2026-06-21）。旧版 `qwen_adapter.py`（309 行）已删除；路由链现为 PaddleOCR-VL → LLM 纠错（Qwen/GLM，OpenAI-compatible 网关）→ Rule。

### 3.3 典型触发示例

**案例：OCR 识别正常但选项 D 缺失**

OCR 结果看起来正常（无乱码），但只有 A/B/C 三个选项。传统噪声检测不会触发，但**结构异常检测**发现「有 A/B/C 但缺 D」，自动触发 PaddleOCR-VL 根据图片补全选项。

**案例：OCR 严重乱码**

```
! (d) aaxy !axau<-d=axau<-Aaxd<-d
```

符号密度维度和无意义 ASCII 串维度同时触发，PaddleOCR-VL 用图片恢复原始内容。

---

## 4. 理解导入结果

### 4.1 状态说明

| 状态 | 含义 |
|------|------|
| `pending` | 待处理 |
| `processing` | OCR / 管线运行中 |
| `succeeded` | 完成，生成待审核题目 |
| `failed` | 处理失败 |

### 4.2 常见失败原因

| 失败原因 | 说明 | 处理建议 |
|----------|------|---------|
| `ocr_empty_text` | OCR 未识别到任何文本 | 检查图片是否清晰、是否有文字 |
| `text_present_but_split_failed` | 识别到文本但无法切分题目 | 检查图片是否包含完整题目 |
| `missing_options` | 识别结果缺少选项 | 可尝试重新导入，或补充清晰选项区域 |
| `stage 'ocr_correction' failed` | AI 纠错阶段异常 | 检查 AI 模型配置是否正确 |
| 无待审核批次 | 管线完成但未生成有效题目 | 检查 OCR 文本质量 |

### 4.3 查看缓存

每张图片的 OCR 原始文本和清洗后文本会缓存。如果 AI 解析失败，可以调整 Prompt 后重新解析（`reparse`），无需重复 OCR。

---

## 5. 后台配置

### 5.1 OCR 纠错相关配置

在 `admin_ai_configs` 表中可配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ocr_fix_feature_flag` | true | false 时降级，仅使用规则纠错 |
| `ocr_correction_prompt` | (内置) | 自定义纠错 Prompt（仅 LLM 文本纠错使用） |
| `ocr_filter_max_chars` | 2000 | 超过此长度的文本跳过 AI 纠错 |
| `ocr_filter_max_tokens` | 4096 | 超过此 token 估计值的文本跳过 AI 纠错 |
| `vision_enabled` | true | 是否启用 PaddleOCR-VL 视觉纠错（链首） |

### 5.2 模型配置

纠错使用的 AI 模型在 `admin_ai_model_configs` 表中配置：

| Feature | 模型 | 用途 | 说明 |
|---------|------|------|------|
| `vision` | PaddleOCR-VL-1.6 | 视觉纠错（路由链首） | 外部高精 OCR API，凭证通过 admin UI 配置 |
| `ocr` | Qwen / GLM（OpenAI-compatible 网关） | 文本纠错回退 | 路由链第二位，凭据存于数据库 `admin_ai_model_configs`，经 admin UI 配置 |

PaddleOCR-VL 凭证通过 `resolve_active_model(feature="vision")` 从 DB 动态获取，管理端 AI 设置页面可切换。pipeline `_run_extract` 中本地 OCR 全失败时也会自动触发 PaddleOCR-VL 回退。

---

## 6. 注意事项

1. **图片清晰度**：PaddleOCR 对清晰图片识别效果较好，模糊、过暗、倾斜严重的图片识别质量会下降
2. **同时并发**：批量导入并发数建议不超过 4，过高的并发可能导致 AI 限流或内存不足
3. **纠错不是重新 OCR**：PaddleOCR-VL 以校验为主，不会补充图片中不存在的内容
4. **必须人工审核**：AI 纠错和标准化结果均为辅助，所有题目需人工确认后才能发布
5. **失败重试**：单张图片失败不影响批量任务中的其他图片，失败后可重新导入或使用缓存重新解析
6. **公式截图**：复杂公式和低置信度公式会触发 math_detect 阶段截图，审核页以图片形式展示公式原图，无需手动校正 LaTeX
7. **Cache 提示**：OCR 结果缓存（SHA256 + config_hash）有效期 14 天，配置变化自动失效；如需手动清理，管理端 → 运维 → Dry-Run → 确认清理
