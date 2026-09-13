# OCR 策略

> 2240AI 的 OCR 策略：可选、轻量、AI 辅助、规则优先。
>
> 更新于 2026-06-21（P8 功能冻结）。OCR 管线已进入生产验证阶段，核心策略不变，AI 视觉能力已从 DeepSeek VL 切换为 PaddleOCR-VL 外部 API。

---

## 当前定位

OCR 是**可选增强模块**，不是核心功能。通过 `OCR_ENABLED` 配置开关控制。

---

## 图片导入状态

- `GET /api/v1/import/pipelines/{pipeline_id}` 状态读取顺序：legacy `get_pipeline_status` → Redis `import:image:pipeline:{pipeline_id}` → 同进程 `_image_pipeline_store`。
- 只有 legacy 与 image 状态都缺失时返回 404。
- 图片上传会在入队前校验 `OCR_ENABLED` 与 PaddleOCR 是否可用，缺失时直接返回可读错误。
- 图片状态写入先更新内存，再 best-effort 写入 Redis，TTL 86400 秒。
- Redis 用于跨 worker 短期状态共享与 TTL 内重启恢复；`REDIS_URL` 未配置或不可用时仅保留同进程内存回退，不保证跨 worker / 重启恢复。
- 终态：`completed`、`failed`；非终态：`queued`、`ocr_running`、`parsing`。前端只应在终态停止轮询。
- 状态响应会保留 OCR 运行时诊断、原始/清洗后文本预览、文本长度/行数差值、OCR stats 与切题诊断。
- 图片导入 `failure_reason` 当前分类：`ocr_empty_text`、`text_present_but_split_failed`、`missing_options`、`pipeline_failed`；切题 fallback 内部原因包括 `text_present_but_no_question_boundary`、`no_text_blocks`，并标记 `fallback_created`。

> 2026-06-01 更新原因：同步图片 OCR 导入诊断字段与失败分类，便于定位 OCR 环境、空文本、切题失败和选项缺失。

生产 Docker Compose 默认注入 `REDIS_URL=redis://redis:6379/0`。

---

## 图片 OCR 预处理与清洗

- 图片 / 扫描页 OCR 统一先做预处理：宽度小于 1000 像素时按比例放大到 1000，再灰度化 + autocontrast，并在转 RGB 前执行 `ImageOps.exif_transpose()` 后交给 PaddleOCR。
- `ocr_pages_with_boxes()` 与普通 OCR 复用同一预处理链路，避免小图含框 OCR 直接走未处理图。
- `clean_ocr_text()` 会在“参考答案 / 正确答案 / 答案:”前补换行，减少选项与答案标记粘连导致的解析失败。
- 裸上标修正规则限定为空格 / Tab，不跨换行，避免 `A\n2.` 这类内容被误改后破坏题号切分。

---

## 技术选型

### 当前（2026-06-21）

- **PaddleOCR**（GPU 本地 / CPU 生产）：通用文字识别引擎
- **PaddleOCR-VL**（外部高精 OCR API）：OCR 纠错路由链首 + 本地 OCR 全失败回退，凭证由 DB 动态管理
- **LLM 纠错（Qwen / GLM，OpenAI-compatible 网关）**：纯文本纠错回退（OCRFixRouter 第二位），凭据存于数据库 `admin_ai_model_configs`
- **PyMuPDF**：PDF 转图片
- **ThreadPoolExecutor**：并发处理多页

### 已移除

| 引擎 | 场景 | 移除原因 |
|------|------|---------|
| ~~Qwen-VL~~ | 视觉纠错 | 2026-06-21 移除，路由链现为 PaddleOCR-VL → LLM（Qwen/GLM）→ Rule |
| ~~DeepSeek VL~~ | 视觉回退 | 切换到 PaddleOCR-VL，凭证由 DB 动态管理 |
| ~~pix2tex~~ | 公式 LaTeX 识别 | 无需 LaTeX 校正，公式截图以图片形式保留 |
| ~~Mathpix~~ | 商业公式识别 | 未使用 |

---

## 触发逻辑（2026-06-21 更新）

```
上传 PDF → pypdf 提取文本
  └→ 文本 < 100字符？→ 判定扫描版 → OCR_ENABLED？
       ├─ YES → PaddleOCR（本地 GPU/CPU）→ 清洗 → 16 阶段管线
       │    └─ 本地 OCR 全失败？→ PaddleOCR-VL 外部 API 回退
       └─ NO  → 报错"扫描版PDF，OCR未启用"
```

图片上传直接进入 PaddleOCR 识别，不经过 pypdf。

---

## 管线架构（当前）

```
PaddleOCR → text_normalizer（13 步规则清洗）
  → OCRFixRouter（PaddleOCR-VL → LLM（Qwen/GLM）→ Rule）
    → 结构分析 → 题目切分 → 答案匹配 → 标准化
      → AI Repair（可选，低置信度触发）
        → 相似匹配 → 公式检测 → 表格检测
          → 审核暂存区 → 人工审核 → 入库
```

所有 16 个阶段支持 checkpoint + artifact resume。

---

## 不做的事（2026-06-21 更新）

- ❌ 手写识别
- ❌ 本地 OCR 模型训练
- ❌ 拍照搜题
- ❌ OCR 结果自动入库（必须人工审核）
- ❌ LLM 输出缓存
- ❌ 纯 AI 自动入库
- ✅ ~~公式深度识别~~ — 公式截图以图片形式保留，无需 LaTeX 校正（已实现）
- ✅ ~~本地 OCR 模型部署~~ — PaddleOCR 已部署（本地 GPU / 生产 CPU）（已实现）

---

## 技术评估记录

### PP-StructureV2 版面分析（2026-06-02 评估）

**结论：不引入。**

| 评估维度 | 说明 |
|----------|------|
| 适用场景 | 混合版面文档（论文、报告：表格+图片+多栏正文） |
| 本项目输入 | 考研截图：均匀文本（题号+选项+答案），无表格/图片混排 |
| 已有方案 | `_detect_column_split` + `_order_ocr_lines_reading_order` 已处理双栏 |
| 引入成本 | 额外模型权重下载、推理时间翻倍、Python 3.12 兼容风险 |
| 项目原则 | "不主动加新依赖" |

当前 `paddleocr==2.7.3` 已包含 `ppstructure` 模块但未使用。如未来需处理含表格/图片的混合版面文档，可重新评估。

---

## 未来方向（2026-06-21 更新）

- ✅ PaddleOCR-VL 已接入（替代 DeepSeek VL 视觉能力），凭证由 DB 动态管理
- ✅ 数学公式截图已实现（math_detect），以图片形式保留公式区域
- ✅ 表格 Markdown 转换已实现（table_detect），保留行列结构
- 考虑：AI 补全并行化（当前 50 题串行，可 asyncio.gather 加速）
- 考虑：代码语义等价性检查（防止 408 C 代码被 AI 改写逻辑）
- 考虑：合并 llm_text_structurer 独立 token budget 到共享 token_budget.py
