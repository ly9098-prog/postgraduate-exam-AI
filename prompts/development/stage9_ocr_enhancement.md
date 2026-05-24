# Stage 9: OCR 增强

## 阶段目标

为扫描版 PDF（无可复制文本）提供 OCR 图片文字识别能力，将识别结果以与 stage1 `normalized_blocks` 兼容的格式接入现有 pipeline。

## 当前阶段范围

### 能做

- 检测扫描版 PDF（stage1 文本提取为空/过少时触发）
- PDF 页面转图片（`pdf2image` 或 `PyMuPDF`）
- 调用 AI API（DeepSeek VL 或其他视觉模型）识别图片中的文字
- 识别结果格式化为 `normalized_blocks` 兼容格式，与 stage1 输出一致
- 数学公式/表格/图片题预留接口（不深度优化）
- 与 stage1 的 `ImportTextNormalizer` 集成（自动降级）

### 禁止做

- 不引入本地 OCR 模型（Tesseract / PaddleOCR 等）
- 不做手写识别
- 不做数学公式深度优化（预留接口即可）
- 不修改 stage1-8 的内部逻辑
- 不允许 OCR 结果直接入库（必须经过审核）
- 不新增 GPU 依赖

## 输入输出结构

### 输入

```python
# 来自 stage1 的降级检测
{
    "file_path": "/tmp/scan.pdf",
    "source_type": "pdf",
    "metadata": {
        "total_pages": 10,
        "extracted_text_length": 15,    # 文本极短，触发 OCR
        "is_scanned": True
    }
}
```

### 输出

```python
# 与 stage1 normalized_blocks 兼容的格式
[
    {
        "page": 1,
        "block_index": 0,
        "raw_text": "OCR 原始识别文本...",
        "normalized_text": "OCR 识别出的文本内容...",
        "metadata": {
            "ocr_method": "deepseek_vl",
            "confidence": 0.85,
            "has_formula": False,
            "has_image": False
        }
    }
]
```

### 核心函数

```python
def ocr_fallback(file_path: str) -> list[dict]:
    """对扫描版 PDF 进行 OCR 识别，返回 normalized_blocks 兼容格式。"""

def _pdf_to_images(file_path: str) -> list[bytes]:
    """PDF 每页转图片。"""

def _call_ocr_api(image: bytes, page_num: int) -> dict | None:
    """调用 AI API 识别图片文字。"""

def _is_scanned_pdf(file_path: str) -> bool:
    """检测是否为扫描版 PDF（无可复制文本）。"""
```

### 与 stage1 的集成点

在 `text_normalizer.py` 的 `ImportTextNormalizer` 中集成 OCR 降级检测：

```python
class ImportTextNormalizer:
    def normalize(self, raw_blocks):
        # 检测扫描版：总文本过短
        total_text = sum(len(b.get("text", "")) for b in raw_blocks)

        if total_text < 100 and is_ocr_enabled():
            # 扫描版 → 触发 OCR 降级
            ocr_blocks = ocr_fallback(file_path)
            raw_blocks = ocr_blocks  # 替换为 OCR 结果

        # 继续标准化流程
        for block in raw_blocks:
            ...
```

## 推荐实现方式

### 文件位置

`backend/app/features/ocr_service.py`

### 实现方案

1. **扫描检测**：
   - pypdf 提取文本后检查总字符数
   - 少于 100 字符 → 判定为扫描版

2. **PDF 转图片**：
   - 方案 A：`pdf2image`（依赖 poppler，推荐开发环境）
   - 方案 B：`PyMuPDF`（fitz，纯 Python，推荐生产环境）
   - 输出：每页一张 JPEG/PNG bytes

3. **AI OCR 调用**：
   - 调用 DeepSeek VL API（或类似视觉模型）
   - Prompt：提取图片中所有文字，保留原始格式
   - 每页单独调用，结果按页码组织

4. **结果格式化**：
   - AI 返回的文本按自然段落切分 block
   - 每个 block 标注 `page` 和 `block_index`
   - 记录 `ocr_method` 和 `confidence`

5. **接口预留**：
   ```python
   # 备用 OCR 接口（当前不做实现）
   def ocr_math_formula(image: bytes) -> str:
       """数学公式识别接口（预留）。"""
       raise NotImplementedError

   def ocr_table(image: bytes) -> list[list[str]]:
       """表格识别接口（预留）。"""
       raise NotImplementedError
   ```

### 当前阶段的重点

- 优先保证普通文字的 OCR 识别质量
- 不要深度优化数学公式（当前阶段不做）
- 确保 OCR 结果能无缝接入现有 pipeline

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/ocr_service.py` | OCR 增强服务 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/features/text_extractor.py` | 集成 OCR 降级检测和调用 |
| `backend/requirements.txt` | 新增依赖：`PyMuPDF` 或 `pdf2image` |

### 不修改

- 不修改 stage2-8 任何模块
- 不修改 model / API 路由

## 测试要求

### 单元测试

`backend/tests/test_services/test_ocr_service.py`

| 测试用例 | 描述 |
|---------|------|
| 扫描版检测 | 检测无可复制文本的 PDF |
| 文本型 PDF 不触发 | 有文本的 PDF 不走 OCR |
| OCR 调用（mock） | mock AI API 验证调用流程 |
| OCR 结果格式化 | AI 返回结果正确转为 normalized_blocks 兼容格式 |
| OCR 不可用降级 | OCR 模块关闭时不阻塞 |
| API 超时 | AI API 超时，静默降级 |

### 注意

- OCR 的 AI 调用需要 mock，不真的调 DeepSeek VL
- 测试数据使用 1 页的扫描版 PDF 图片

## 完成标准

- [ ] 扫描版 PDF 自动检测（文本 < 100 字符触发）
- [ ] OCR 结果格式与 stage1 `normalized_blocks` 完全兼容
- [ ] AI API 不可用时静默降级（不抛异常）
- [ ] OCR 功能可通过配置开关控制
- [ ] 所有单测通过

## docs 更新要求

- `/docs/architecture/OCR_FLOW.md`：新增 OCR 架构和触发逻辑
- `/docs/ai/AI_PIPELINE.md`：新增 ocr_service 模块说明

## 下一阶段衔接

Stage 9 是导入管线的最后一个增强模块。完成后，整个"复杂题库 PDF/Word 导入 + 自动结构化标准化系统"的 prompt 工程化拆分目标完成。
