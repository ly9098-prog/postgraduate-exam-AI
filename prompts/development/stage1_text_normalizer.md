# Stage 1: 导入文本标准化层

## 阶段目标

统一当前已有 OCR / PDF / DOCX 输出，实现 `ImportTextNormalizer`。不做 AI 分析、不做题目识别、不做答案匹配——只做"文本标准化"。

## 当前阶段范围

### 能做

- 清洗换行（多余换行、断行合并）
- 清洗乱码（不可见字符、常见 OCR 乱码）
- 统一空格（全角→半角、连续空格合并）
- OCR 字符纠正（常见 OCR 识别错误）
- 保留原始 `raw_text`
- 输出 `normalized_blocks`

### 必须支持

- OCR 脏文本纠正（数字/字母常见混淆）
- A/B/C/D 错误识别修复
- 页码保留
- `block_index` 保留

### 禁止做

- 不做 AI 分析
- 不做题目识别
- 不做答案匹配
- 不做结构分析
- 不做文件格式解析（复用 `import_service.py` 现有的提取能力）
- 不修改 Question 或 QuestionImport 模型
- 不修改现有 `import_service.py` 的内部逻辑

## 输入输出结构

### 输入

```
raw_blocks: list[dict]    # 来自现有 OCR/PDF/DOCX 解析的输出
```

现有解析能力已存在于 `import_service.py`（`_parse_pdf` 等），本阶段不重新实现提取逻辑。

### 输出

```python
[
    {
        "page": 1,                  # 页码（保留原始页码）
        "block_index": 0,           # 块序号（保留原始序号）
        "raw_text": "...",           # 原始文本（不做任何修改）
        "normalized_text": "..."     # 标准化后的文本
    }
]
```

### 核心函数

```python
class ImportTextNormalizer:
    """导入文本标准化器。"""

    def normalize(self, raw_blocks: list[dict]) -> list[dict]:
        """标准化文本块，返回 normalized_blocks。"""

    def _clean_newlines(self, text: str) -> str:
        """清洗换行：断行合并、多余换行压缩。"""

    def _clean_garbled(self, text: str) -> str:
        """清洗乱码：不可见字符、常见 OCR 乱码。"""

    def _normalize_spaces(self, text: str) -> str:
        """统一空格：全角→半角、连续空格合并。"""

    def _correct_ocr_errors(self, text: str) -> str:
        """OCR 字符纠正：数字/字母常见混淆。"""
```

## 推荐实现方式

### 文件位置

`backend/app/features/text_normalizer.py`

### 实现方案

1. **换行清洗** (`_clean_newlines`)：

```python
# 常见 OCR 断行模式
NEWLINE_RULES = [
    # 非中文句末的换行 → 空格（中文字后换行一般是 OCR 断行）
    (r"(?<=[^。！？；\n])\n(?=[^。！？；\n])", ""),
    # 连续 3+ 换行 → 2 换行（段落边界）
    (r"\n{3,}", "\n\n"),
    # 行首多余空白
    (r"\n\s+", "\n"),
]
```

2. **乱码清洗** (`_clean_garbled`)：

```python
GARBLED_RULES = [
    # 移除不可见字符（保留换行和制表符）
    (r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", ""),
    # 替换 Unicode 替换字符
    ("�", ""),
    # 常见 OCR 乱码模式
    (r"□+", ""),
]
```

3. **空格统一** (`_normalize_spaces`)：

```python
SPACE_RULES = [
    # 全角空格 → 半角
    ("　", " "),
    (" ", " "),
    # 连续空格 → 单空格
    (r" {2,}", " "),
]
```

4. **OCR 字符纠正** (`_correct_ocr_errors`)：

```python
# 常见 OCR 混淆映射
OCR_CORRECTIONS = [
    # 数字混淆
    ("O", "0"), ("o", "0"),       # O → 0（题号中）
    ("l", "1"), ("I", "1"),       # l/I → 1（题号中）
    ("S", "5"),                    # S → 5
    # 选项字母混淆
    ("8", "B"), ("6", "B"),       # 8/6 → B（选项中）
    ("0", "D"),                    # 0 → D（选项中）
]
```

注意：OCR 纠正需要上下文判断，避免误伤正常文本。建议：
- 题号场景：`(?<=\d)[Oo]` → `0`
- 选项场景：`^[8６]`（行首选项标记）→ `B`

5. **标准化流程**：

```python
def normalize(self, raw_blocks):
    normalized = []
    for block in raw_blocks:
        text = block.get("text", "")
        raw_text = text  # 保留原始文本
        text = self._clean_newlines(text)
        text = self._clean_garbled(text)
        text = self._normalize_spaces(text)
        text = self._correct_ocr_errors(text)
        normalized.append({
            "page": block.get("page", 1),
            "block_index": block.get("block_index", 0),
            "raw_text": raw_text,
            "normalized_text": text
        })
    return normalized
```

### 依赖调整

- 无新依赖（纯 Python 字符串处理 + 正则）

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/text_normalizer.py` | 文本标准化核心模块 |

### 修改文件

无（本阶段不修改现有代码，只新增模块）

### 不修改

- 不修改 `services/import_service.py`（现有逻辑保留不动）
- 不修改任何 model
- 不修改任何 API 路由
- 不修改 `requirements.txt`

## 测试要求

### 单元测试

`backend/tests/test_services/test_text_normalizer.py`

| 测试用例 | 描述 |
|---------|------|
| 换行清洗 | OCR 断行合并、多余换行压缩 |
| 乱码清洗 | 不可见字符移除、Unicode 替换字符 |
| 空格统一 | 全角→半角、连续空格合并 |
| OCR 字符纠正 | 数字/字母常见混淆纠正 |
| A/B/C/D 错误修复 | 选项标记 OCR 识别错误修复 |
| 空文本 | 空字符串，返回空 normalized_text |
| 纯正常文本 | 无噪声文本，raw_text == normalized_text |
| 页码保留 | 原始 page/block_index 正确传递 |
| 批量 blocks | 多 block 输入，每个独立标准化 |

### 测试数据

`backend/tests/fixtures/` 下准备：
- `normalizer_ocr_noise.txt` — 含 OCR 各种噪声的文本
- `normalizer_newlines.txt` — 含 OCR 断行的文本
- `normalizer_clean.txt` — 干净文本（验证不误伤）

## 与现有系统的关系

```
现有 OCR/PDF/DOCX 解析（import_service.py）
  → raw_blocks
    → ImportTextNormalizer.normalize()
      → normalized_blocks（供 stage2+ 使用）
```

本阶段是新增标准化层，不改变现有导入流程。`import_service.py` 的输出先经过标准化，再进入后续阶段。

## 完成标准

- [ ] 换行清洗覆盖常见 OCR 断行模式
- [ ] 乱码清洗能处理不可见字符/Unicode 替换字符
- [ ] 空格统一正确（全角→半角，连续→单空格）
- [ ] OCR 字符纠正覆盖数字/字母常见混淆
- [ ] `raw_text` 始终保留原始内容，不做修改
- [ ] `page` / `block_index` 原样传递
- [ ] 所有单测通过
- [ ] 不修改任何现有代码

## docs 更新要求

- `/docs/architecture/OCR_FLOW.md`：新增文本标准化层说明
- `/docs/ai/AI_PIPELINE.md`：新增 text_normalizer 模块说明

## 下一阶段衔接

Stage 2（文档结构分析层）以本阶段输出的 `normalized_blocks` 作为输入进行结构分析。本阶段确保 `normalized_blocks` 格式稳定即可，不预测 stage 2 的内部实现。
