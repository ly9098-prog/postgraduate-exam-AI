# Stage 6: AI 修复层

## 阶段目标

对规则解析失败的低置信度题目进行 AI 辅助修复和补全，提高导入覆盖率和结构化质量。

## 当前阶段范围

### 能做

- 接收 stage5 输出中 `confidence_score` 低于阈值或 `is_valid=False` 的题目
- 调用 DeepSeek API 修复混乱文本 → 标准 Question Schema
- 实现触发条件控制（低频触发，不全量走 AI）
- 实现 token 成本控制（日/月限额）
- 支持 AI 不可用时的静默降级
- 对比修复前后的效果

### 禁止做

- 不允许全量走 AI（必须有触发条件）
- 不允许 AI 结果直接进入题库（必须经过 stage7 审核）
- 不修改 AI 模块现有架构（`app/ai/` 已有基础设施）
- 不引入 langchain / 多轮对话
- 不改数据库模型

## 输入输出结构

### 输入

```python
# 来自 stage5
{
    "questions": [
        {
            "stem": "...",
            "options": None,           # 规则解析失败
            "answer": "",              # 答案缺失
            "question_type": "unknown",
            "is_valid": False,
            "errors": ["stem_empty"],
            "confidence_score": 0.15,
            "raw_question_text": "..."  # 保留原始文本供 AI 修复
        }
    ],
    "config": {
        "confidence_threshold": 0.6,   # 低于此值触发 AI
        "daily_token_limit": 100000,
        "monthly_token_limit": 2000000,
        "enabled": True                # 全局开关
    }
}
```

### 输出

```python
{
    "repaired": [
        {
            "question_index": 3,
            "before": { ... },         # 修复前的 schema
            "after": { ... },          # 修复后的 schema
            "repair_actions": [         # 修复动作记录
                "answer_filled",
                "options_restructured"
            ],
            "confidence": 0.85,        # AI 修复置信度
            "token_used": 350          # 本次修复消耗 token
        }
    ],
    "unrepaired": [                    # AI 也无法修复的
        {
            "question_index": 7,
            "reason": "insufficient_text"
        }
    ],
    "skipped": [                       # 未达到触发条件的
        {
            "question_index": 1,
            "reason": "above_threshold",
            "confidence": 0.75
        }
    ],
    "stats": {
        "total_candidates": 10,
        "repaired": 3,
        "unrepaired": 1,
        "skipped": 6,
        "total_tokens": 1050
    }
}
```

### 核心函数

```python
def repair_questions(
    questions: list[dict],
    config: dict | None = None
) -> dict:
    """对低置信度题目进行 AI 修复。"""

def _should_repair(question: dict, threshold: float) -> bool:
    """判断是否达到修复触发条件。"""

def _call_ai_for_repair(raw_text: str) -> dict | None:
    """调用 DeepSeek 修复单题。"""

def _check_token_limit(daily_used: int, monthly_used: int, config: dict) -> bool:
    """检查 token 限额。"""
```

## 推荐实现方式

### 文件位置

`backend/app/features/ai_repair.py`

### 实现方案

1. **触发条件**：

```python
def _should_repair(question, threshold):
    # 触发条件（任一满足）：
    # 1. confidence_score < threshold
    # 2. is_valid == False
    # 3. options 为空且题型是选择题
    # 4. answer 为空
    # 5. stem 异常短（< 5 字符）
    pass
```

2. **AI 调用流程**：
   ```
   raw_text + prompt → DeepSeek API → 解析 JSON 响应 → 校验 schema → 返回
   ```
   - 复用 `app/ai/client.py` 的 httpx 客户端
   - Prompt 模板放在 `app/ai/prompts.py`（新增修复场景 prompt）
   - Temperature = 0.3（准确优先）
   - 要求返回 JSON 格式

3. **Token 控制**：
   - 调用前估算 token（`app/ai/token_counter.py`）
   - 超出日限额 → 跳过修复，记录日志
   - 修复消耗记录到 `ai_chats` 表

4. **降级方案**（AI 不可用）：
   - 静默跳过修复
   - 返回 `{"repaired": [], "unrepaired": all, "skipped": []}`
   - 不抛异常，不阻塞 pipeline

### 关键设计

- **低频触发**：只修复规则解析失败的低置信度题目
- **修复动作可审计**：记录每个修复动作，方便审核时追溯
- **token 可配置**：阈值、限额全部走配置，不硬编码
- **AI 可开关**：关闭后直接跳过修复步骤
- **不修改原始数据**：修复结果独立于原始 raw text

## 文件修改建议

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/features/ai_repair.py` | AI 修复核心模块 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `app/ai/prompts.py` | 新增修复场景的 Prompt 模板 |

### 不修改

- 不修改 `text_extractor.py` / `structure_analyzer.py` / `question_splitter.py` / `answer_matcher.py` / `question_normalizer.py`
- 不修改 `app/ai/client.py`（复用）
- 不修改 `app/ai/token_counter.py`（复用）
- 不修改任何 model / service / API 路由

## 测试要求

### 单元测试

`backend/tests/test_services/test_ai_repair.py`

| 测试用例 | 描述 |
|---------|------|
| 触发条件检测 | confidence 低于阈值触发修复 |
| 不触发条件 | 高置信度题目跳过修复 |
| AI 修复成功 | mock API 返回修复后的 schema |
| AI 修复失败 | mock API 返回空，标记 unrepaired |
| token 超限 | 日限额耗尽，跳过修复 |
| AI 不可用 | API 抛异常，静默降级 |
| 空输入 | 空列表，返回空结果 |
| 全局关闭 | enabled=False，全部 skipped |

### 注意

- AI 调用需要 mock，不真的调用 DeepSeek API
- 使用 `unittest.mock` 或 `pytest-mock`

## 完成标准

- [ ] 触发条件准确过滤低置信度题目
- [ ] AI 修复成功时正确输出标准 schema
- [ ] AI 不可用时静默降级（不抛异常）
- [ ] Token 限额控制生效
- [ ] 全局开关生效（关闭后不调用 AI）
- [ ] 所有单测通过

## docs 更新要求

- `/docs/ai/AI_PIPELINE.md`：新增 ai_repair 模块说明和触发逻辑
- `/docs/project/PROJECT_RULES.md`：更新 AI 修复策略说明

## 下一阶段衔接

Stage 7（审核系统）以 stage5 的输出作为基础数据，以 stage6 的修复结果作为增强数据，无论 AI 是否可用，审核系统都能独立运行。
