# OCR 策略

> 2240AI 的 OCR 策略：可选、轻量、AI 驱动。

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

### 当前

- **PaddleOCR**（CPU 模式）：生产中实际使用的 OCR 引擎
- **PyMuPDF**：PDF 转图片
- **ThreadPoolExecutor**：并发处理多页

### 预留接口

| 引擎 | 场景 | 使用方式 |
|------|------|---------|
| PaddleOCR | 通用文字识别 | 当前实现 |
| DeepSeek VL | 复杂版面/公式 | 未来可选 |
| pix2tex | 数学公式 LaTeX 识别 | 预留接口 |
| Mathpix | 商业公式识别 | 预留接口 |

---

## 触发逻辑

```
上传 PDF → pypdf 提取文本
  └→ 文本 < 100字符？→ 判定扫描版 → OCR_ENABLED？
       ├─ YES → PaddleOCR → 文本清洗 → 结构化
       └─ NO  → 报错"扫描版PDF，OCR未启用"
```

---

## 不做的事

- ❌ 手写识别
- ❌ 本地 OCR 模型训练
- ❌ 拍照搜题
- ❌ 公式深度识别（当前预留接口）
- ❌ OCR 结果自动入库（必须人工审核）

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

## 未来方向

- DeepSeek VL 替换 PaddleOCR（减少依赖体积）
- 数学公式识别接入
- 表格结构化识别
