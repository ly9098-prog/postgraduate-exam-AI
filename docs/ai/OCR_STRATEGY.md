# OCR 策略

> 2240AI 的 OCR 策略：可选、轻量、AI 驱动。

---

## 当前定位

OCR 是**可选增强模块**，不是核心功能。通过 `OCR_ENABLED` 配置开关控制。

---

## 图片导入状态

- `GET /api/v1/import/pipelines/{pipeline_id}` 状态读取顺序：legacy `get_pipeline_status` → Redis `import:image:pipeline:{pipeline_id}` → 同进程 `_image_pipeline_store`。
- 只有 legacy 与 image 状态都缺失时返回 404。
- 图片状态写入先更新内存，再 best-effort 写入 Redis，TTL 86400 秒。
- Redis 用于跨 worker 短期状态共享与 TTL 内重启恢复；`REDIS_URL` 未配置或不可用时仅保留同进程内存回退，不保证跨 worker / 重启恢复。
- 终态：`completed`、`failed`；非终态：`queued`、`ocr_running`、`parsing`。前端只应在终态停止轮询。

生产 Docker Compose 默认注入 `REDIS_URL=redis://redis:6379/0`。

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

## 未来方向

- DeepSeek VL 替换 PaddleOCR（减少依赖体积）
- 数学公式识别接入
- 表格结构化识别
