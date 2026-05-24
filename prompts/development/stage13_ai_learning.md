# Stage 13: AI 学习引擎

## 1. 阶段目标

让 AI 真正辅助学习，提供题目讲解、错因分析、相似题推荐和学习报告等功能，帮助用户发现薄弱点并针对性提升。

## 2. MVP 范围

### 能做

- AI 题目讲解（用户做完题后可请求 AI 解析）
- AI 错因分析（分析用户做错的原因）
- AI 相似题推荐（基于题目属性，非 embedding）
- AI 学习报告（薄弱知识点、高频错误、学习建议）
- 复用现有 DeepSeek API 调用基础设施
- Token 用量控制和限额管理

### 禁止做

- 不做多轮对话（当前仅单次 AI 调用）
- 不做 embedding 向量检索
- 不做知识图谱构建
- 不做 RAG 检索增强
- 不做多 Agent 编排
- 不做模型微调

## 3. 非目标

- 不实现 AI 一对一辅导对话
- 不做 AI 出题
- 不做 AI 学习路径规划
- 不做语音交互

## 4. 目录结构修改

### 新增文件

| 文件 | 作用 |
|------|------|
| `backend/app/services/ai_learning_service.py` | AI 学习引擎核心 |
| `backend/app/schemas/ai_learning.py` | AI 学习相关模型 |
| `backend/app/ai/prompts_learning.py` | 学习相关 AI Prompt 模板 |
| `backend/tests/test_services/test_ai_learning.py` | 单元测试 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `backend/app/api/v1/ai.py` | 新增学习相关端点 |
| `backend/app/core/config.py` | 新增 AI 学习相关配置 |

### 不修改文件

- `app/ai/client.py` — 复用现有 DeepSeekClient
- `app/features/ai_repair.py` — 不修改现有修复逻辑
- `app/models/*` — 不修改模型

## 5. 数据库变更

无数据库变更。AI 学习引擎无状态（stateless），每次调用独立的 AI API。

## 6. API 设计

### 6.1 AI 题目讲解

```
POST /api/v1/ai/explain
```

**Request Body:**
```json
{
    "question_id": 1,
    "user_answer": "A",
    "is_correct": false,
    "focus": "solution"
}
```

`focus`: `"solution"`（解题思路）| `"mistake"`（错因分析）| `"knowledge"`（知识点讲解）

**Response:**
```json
{
    "question_id": 1,
    "explanation": "这道题考察导数的几何意义...",
    "solution_steps": ["Step 1: 求导", "Step 2: 代入 x=0", "Step 3: 得到斜率"],
    "key_knowledge_points": ["导数几何意义", "切线方程"],
    "common_mistakes": ["常见错误：忘记链式法则..."],
    "tokens_used": 356
}
```

### 6.2 AI 相似题推荐

```
POST /api/v1/ai/recommend
```

**Request Body:**
```json
{
    "question_id": 1,
    "count": 5
}
```

**Response:**
```json
{
    "source_question_id": 1,
    "recommendations": [
        {
            "question_id": 10,
            "subject": "math2",
            "question_type": "single_choice",
            "stem": "相似题内容...",
            "knowledge_points": ["导数"],
            "match_reason": "同知识点 + 同难度"
        }
    ],
    "strategy": "rule_based",
    "tokens_used": 0
}
```

**规则推荐策略（非 AI）：**

推荐策略 MVP 不使用 AI，而是基于规则：
- 同 subject + 同 knowledge_points + 同 difficulty
- ORDER BY RANDOM()
- 排除当前题目和已做过的题目

### 6.3 AI 学习报告

```
POST /api/v1/ai/report
```

**Request Body:**
```json
{
    "subject": "math2",
    "days": 7
}
```

**Response:**
```json
{
    "subject": "math2",
    "period_days": 7,
    "total_answered": 50,
    "accuracy": 0.72,
    "weak_points": [
        {"knowledge_point": "多元函数微分", "accuracy": 0.4, "suggestion": "建议复习链式法则和隐函数求导"},
        {"knowledge_point": "定积分应用", "accuracy": 0.5, "suggestion": "建议多做面积和体积计算题"}
    ],
    "strong_points": [
        {"knowledge_point": "极限计算", "accuracy": 0.95, "suggestion": "继续保持"}
    ],
    "learning_suggestions": ["重点复习多元函数微分章节", "每日练习 3 道定积分应用题"],
    "tokens_used": 890
}
```

### 6.4 AI 错因分析（补充 6.1 的 focus=mistake）

同 6.1 API，仅 `focus` 不同。也可单独端点便于前端调用。

```
POST /api/v1/ai/analyze-mistake
```

**Request Body:**
```json
{
    "question_id": 1,
    "user_answer": "A",
    "correct_answer": "C"
}
```

**Response:**
```json
{
    "error_type": "concept_misunderstanding",
    "error_type_label": "概念理解错误",
    "analysis": "你选择了 A，但正确答案是 C。错误原因可能是...",
    "suggestion": "建议复习 xxx 章节，重点理解..."
}
```

## 7. Service 设计

### 新增：`ai_learning_service.py`

```python
# 核心函数

async def ai_explain(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str | None = None,
    is_correct: bool | None = None,
    focus: str = "solution",
) -> dict:
    """
    AI 题目讲解。

    1. 查询 question（含答案和解析）
    2. 构造 Prompt（复用 app/ai/prompts_learning.py）
    3. 调用 DeepSeek API
    4. 解析并返回 AI 结果
    5. 记录 token 用量
    """

async def ai_analyze_mistake(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    user_answer: str,
    correct_answer: str,
) -> dict:
    """
    AI 错因分析。

    与 ai_explain 共享底层调用，但使用专门的 mistake_analysis prompt。
    """

async def recommend_similar_questions(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    count: int = 5,
) -> dict:
    """
    推荐相似题目。

    MVP 使用规则推荐（非 AI）：
    - 同 subject + 同 knowledge_points + 同 difficulty
    - RANDOM() 排序
    - 排除已做题
    """

async def generate_learning_report(
    db: AsyncSession,
    user_id: int,
    subject: str,
    days: int = 7,
) -> dict:
    """
    生成 AI 学习报告。

    1. 查询用户做题统计数据（practice_records）
    2. 按知识点聚合正确率
    3. 构造 Prompt 发送给 AI
    4. AI 生成薄弱点分析 + 学习建议
    """
```

### Prompt 设计（`app/ai/prompts_learning.py`）

```python
EXPLAIN_PROMPT = """你是一个考研数学/计算机/英语辅导老师。

题目：{stem}
选项：{options}
正确答案：{answer}
用户答案：{user_answer}
是否正确：{is_correct}

请从以下方面讲解：
1. 解题思路（step by step）
2. 涉及知识点
3. 常见错误（如果用户做错）

请用中文回答，保持简洁。"""

MISTAKE_ANALYSIS_PROMPT = """你是一个考研辅导老师。分析学生的错误原因。

题目：{stem}
选项：{options}
正确答案：{correct_answer}
用户答案：{user_answer}

请分析：
1. 错误类型（概念理解/计算错误/审题错误/思路错误）
2. 具体分析
3. 改进建议"""

REPORT_PROMPT = """你是一个考研辅导老师。根据以下学习数据生成学习报告。

科目：{subject}
统计周期：{days} 天
总做题数：{total}
正确率：{accuracy}
各知识点正确率：{knowledge_point_accuracy}

请生成：
1. 薄弱知识点（正确率低于 60% 的）
2. 优势知识点（正确率高于 85% 的）
3. 学习建议（3-5 条具体可执行建议）"""
```

## 8. Schema 设计

### 新增：`schemas/ai_learning.py`

```python
class AIExplainRequest(BaseModel):
    question_id: int
    user_answer: str | None = None
    is_correct: bool | None = None
    focus: str = "solution"  # solution / mistake / knowledge


class AIExplainResponse(BaseModel):
    question_id: int
    explanation: str = ""
    solution_steps: list[str] = []
    key_knowledge_points: list[str] = []
    common_mistakes: list[str] = []
    tokens_used: int = 0


class AIRecommendRequest(BaseModel):
    question_id: int
    count: int = 5


class Recommendation(BaseModel):
    question_id: int
    subject: str
    question_type: str
    stem: str
    knowledge_points: list[str] = []
    match_reason: str = ""


class AIRecommendResponse(BaseModel):
    source_question_id: int
    recommendations: list[Recommendation]
    strategy: str = "rule_based"
    tokens_used: int = 0


class AIReportRequest(BaseModel):
    subject: str
    days: int = 7


class WeakPoint(BaseModel):
    knowledge_point: str
    accuracy: float
    suggestion: str = ""


class StrongPoint(BaseModel):
    knowledge_point: str
    accuracy: float
    suggestion: str = ""


class AIReportResponse(BaseModel):
    subject: str
    period_days: int
    total_answered: int
    accuracy: float
    weak_points: list[WeakPoint] = []
    strong_points: list[StrongPoint] = []
    learning_suggestions: list[str] = []
    tokens_used: int = 0


class AIMistakeAnalysisRequest(BaseModel):
    question_id: int
    user_answer: str
    correct_answer: str


class AIMistakeAnalysisResponse(BaseModel):
    error_type: str = ""
    error_type_label: str = ""
    analysis: str = ""
    suggestion: str = ""
    tokens_used: int = 0
```

## 9. 测试计划

### 新增测试文件

`backend/tests/test_services/test_ai_learning.py`

### 测试用例

| 类别 | 测试用例 | 描述 |
|------|---------|------|
| **AI 讲解** | `test_ai_explain_success` | 调用成功 |
| | `test_ai_explain_with_user_answer` | 带用户答案 |
| | `test_ai_explain_question_not_found` | 题目不存在 |
| | `test_ai_explain_ai_unavailable` | AI API 不可用降级 |
| | `test_ai_explain_api_exception` | API 异常降级 |
| | `test_ai_explain_parse_response` | AI 响应解析 |
| **错因分析** | `test_analyze_mistake` | 错因分析 |
| | `test_analyze_mistake_empty_answer` | 空答案 |
| **相似推荐** | `test_recommend_by_rules` | 规则推荐 |
| | `test_recommend_empty_result` | 无相似题 |
| | `test_recommend_exclude_answered` | 排除已做题 |
| | `test_recommend_exclude_self` | 排除自身 |
| **学习报告** | `test_generate_report` | 生成报告 |
| | `test_generate_report_insufficient_data` | 数据不足提示 |
| | `test_generate_report_empty_data` | 无数据 |
| **Token 控制** | `test_token_usage_tracked` | Token 用量记录 |
| | `test_daily_token_limit` | 日限额控制 |
| | `test_monthly_token_limit` | 月限额控制 |
| **降级** | `test_ai_unavailable_graceful_degradation` | AI 不可用优雅降级 |
| | `test_all_ai_endpoints_fallback` | 所有端点统一降级 |

### 测试策略

- mock DeepSeek API（复用 test_ai_repair.py 的 mock 方式）
- 规则推荐不需要 mock AI
- 学习报告：前半段数据聚合 + 后半段 AI 调用分离测试

## 10. UI 影响范围

### 新增/修改页面

- 答题结果页增加"AI 讲解"按钮
- 错题页面增加"错因分析"按钮
- 统计页面底部增加"生成学习报告"按钮
- 题目详情页增加"相似题推荐"区域

### 交互考虑

- AI 调用时显示加载状态
- AI 不可用时显示"暂时不可用"提示
- Token 超限时提示"今日额度已用尽"
- 流式输出（可选，MVP 不做）

## 11. 风险与兼容性

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| AI API 不可用 | 学习辅助全挂 | 优雅降级 + 错误提示 |
| Token 消耗不可控 | 成本超支 | 日/月限额 + 单次最大 token 控制 |
| AI 结果质量不稳定 | 误导用户 | 不修改题库数据，仅展示建议性内容 |
| 推荐结果重复 | 用户体验差 | 去重 + 随机排序 |

## 12. 开发顺序

### Step 1: Prompt 模板

- 创建 `app/ai/prompts_learning.py`

### Step 2: 规则推荐

- `recommend_similar_questions` 纯 SQL 实现

### Step 3: AI 服务

- `ai_explain`
- `ai_analyze_mistake`
- `generate_learning_report`

### Step 4: API 端点

### Step 5: Token 控制集成

### Step 6: 测试

### Step 7: 前端集成（最小改动）

## 13. 验收标准

- [ ] AI 题目讲解可用（含解题步骤和知识点）
- [ ] AI 错因分析返回有意义的分析
- [ ] 相似题推荐基于规则正常工作
- [ ] 学习报告正确识别薄弱点
- [ ] AI 不可用时优雅降级（不抛异常）
- [ ] Token 限额控制生效
- [ ] 新测试全部通过
- [ ] 全量测试零回归
