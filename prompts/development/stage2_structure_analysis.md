# Stage 2: 文档结构分析器

## 阶段目标

分析文档的宏观结构，识别题目区域、答案区域、解析区域，判断文档的题目-答案组织模式（混合/分离/未知）。

## 当前阶段范围

### 能做

- 接收 stage1 输出的 `normalized_blocks` 作为输入
- 检测文档模式：`INLINE`（题目答案混合）、`SEPARATED`（题目答案分离）、`UNKNOWN`
- 识别题目区域（出现连续题号的页面/块）
- 识别答案区域（出现"答案""参考答案"等关键字的页面/块）
- 识别解析区域（出现"解析""解答"等关键字的页面/块）
- 使用规则 + 正则实现，不依赖 LLM

### 禁止做

- 不做逐题切分（那是 stage3 的事）
- 不做答案与题目的逐条匹配（那是 stage4 的事）
- 不调用 AI/LLM
- 不修改文本内容
- 不修改数据库模型

## 输入输出结构

### 输入

```
normalized_blocks: list[dict]     # stage1 的输出
file_metadata: dict               # 文件级元信息（文件名、类型等）
```

`normalized_blocks` 格式（来自 stage1）：

```python
[
    {"page": 1, "raw_text": "...", "normalized_text": "...", "block_index": 0},
    {"page": 2, "raw_text": "...", "normalized_text": "...", "block_index": 1}
]
```

注意：分析时应使用 `normalized_text`（标准化后的文本），而非 `raw_text`。

### 输出

```python
{
    "mode": "INLINE" | "SEPARATED" | "UNKNOWN",
    "question_pages": [1, 2, 3],        # 包含题目的页面/块索引
    "answer_pages": [4, 5],              # 包含答案的页面/块索引
    "explanation_pages": [5, 6],         # 包含解析的页面/块索引
    "confidence": 0.85,                  # 结构分析的置信度
    "details": {                         # 分析细节
        "total_blocks": 10,
        "matched_patterns": {
            "question_header": 15,       # 匹配到的题号模式次数
            "answer_keyword": 3,         # 匹配到的答案关键词次数
            "analysis_keyword": 2        # 匹配到的解析关键词次数
        }
    }
}
```

### 核心函数

```python
def analyze_structure(normalized_blocks: list[dict]) -> dict:
    """分析文档结构，返回结构分析结果。"""
```

## 推荐实现方式

### 文件位置

`backend/app/features/structure_analyzer.py`

### 实现方案

1. **模式匹配规则**（顶层的常/变量定义）：

```python
# 题号模式
QUESTION_PATTERNS = [
    r"^\s*\d+[.、)）]",
    r"^\s*\(\d+\)",
    r"^\s*【\d+】",
    r"^第\s*\d+\s*题"
]

# 答案区域关键词
ANSWER_KEYWORDS = [
    "答案", "参考答案", "正确答案", "answer", "Answer", "KEY"
]

# 解析区域关键词  
ANALYSIS_KEYWORDS = [
    "解析", "解答", "讲解", "分析", "explanation", "Explanation",
    "【解析】", "【解答】"
]
```

2. **检测算法**：
   - 遍历所有 `normalized_blocks`，对每块的 `normalized_text` 扫描模式匹配
   - 统计题号模式出现次数 → 标记为 `question_pages`
   - 扫描答案关键词 → 标记为 `answer_pages`
   - 扫描解析关键词 → 标记为 `explanation_pages`
   - 根据题目和答案区域的分布关系判断模式：
     - 交替出现 → `INLINE`
     - 题目全部在前，答案全部在后 → `SEPARATED`
     - 无法判断 → `UNKNOWN`

3. **置信度计算**：
   - 模式匹配数量越多，置信度越高
   - 单种模式匹配超过阈值且区域分布清晰 → 高置信度
   - 匹配稀疏或区域重叠 → 低置信度

### 关键设计决策

- 纯规则实现：当前阶段不引入 LLM，保持零外部依赖
- 后续可以在 stage6（AI 修复层）中引入 LLM 分析 `UNKNOWN` 场景

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/structure_analyzer.py` | 结构分析核心模块 |

### 不修改

- 不修改 `text_extractor.py`
- 不修改任何 model / service / API 路由
- 不修改 `requirements.txt`（纯正则，无新依赖）

## 测试要求

### 单元测试

`backend/tests/test_services/test_structure_analyzer.py`

| 测试用例 | 描述 |
|---------|------|
| INLINE 模式检测 | 题目答案交替出现的文档 |
| SEPARATED 模式检测 | 题目在前答案在后的文档 |
| 无答案文档 | 纯题目，无答案区 |
| 空输入 | 空列表，返回 UNKNOWN |
| 单 block 输入 | 单段文本的边界情况 |
| 多种题号格式 | 1. / 1、/ (1) / 【1】 等混用 |
| 英文关键词 | Answer: / Key: 等 |
| OCR 噪声文本 | 含乱码但不影响关键词匹配 |

## 完成标准

- [ ] 能准确判断 `INLINE` / `SEPARATED` / `UNKNOWN` 三种模式
- [ ] 能正确标记题目/答案/解析区域
- [ ] 纯正则实现，无 LLM 依赖
- [ ] 所有单测通过
- [ ] 输入 `normalized_blocks` 内容不被修改（无副作用）

## docs 更新要求

- `/docs/ai/AI_PIPELINE.md`：新增 structure_analyzer 模块说明
- `/docs/project/PROJECT_RULES.md`：更新管线阶段说明，新增结构分析器描述

## 下一阶段衔接

Stage 3 以本阶段的输出（结构分析结果 + 原始 `normalized_blocks`）作为输入进行题目切分。本阶段不涉及逐题解析。
