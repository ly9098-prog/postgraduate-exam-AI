# Task Execution Prompt

Before coding:

1. Read CLAUDE.md
2. Read related docs in /docs
3. Analyze existing architecture
4. Avoid breaking API compatibility
5. Keep UI consistent with UI_RULES.md
6. Do not overengineer MVP features
7. Reuse existing components whenever possible

---

Output:
- task analysis
- implementation plan
- modified files
- code

---

# Coding Rules

- Keep code modular and minimal
- Avoid unnecessary abstraction
- Prefer readability over cleverness
- Maintain consistent naming
- Avoid duplicate logic

---

# Project Context

AI考研错题本 + 智能刷题系统

Tech stack:
- FastAPI
- Vue / UniApp
- SQLite/PostgreSQL
- SM-2 review algorithm

---

# 22408 AI 考研学习助手 — prompt.md

> 阶段性开发任务、产品需求、功能规划。**会随开发阶段更新，不是长期规则。**

---

## 项目目标

> 一套能真实投入使用的 AI 考研刷题小程序。

### MVP 目标

1. **用户系统** — 微信小程序登录（openid 唯一身份体系）、JWT 会话管理、个人设置
2. **题目管理** — 数学二/408/英语 三科题库，支持导入和在线练习
3. **错题本** — 自动收录错题，标记错误类型，支持重做
4. **AI 错题解析** — 每题调用 DeepSeek 分析错因，生成薄弱点标注
5. **AI 学习建议** — 根据错题分布给出日/周学习建议
6. **智能复习计划** — 按艾宾浩斯/薄弱程度生成每日复习列表

### 长期目标

- 政治题库接入
- 错题数据统计看板
- 学习进度可视化
- 知识点掌握度热力图
- 真题模考模式
- 多端（管理后台 Web）
- **SM-2 间隔重复复习系统**
- **记忆曲线 / 知识点掌握度模型**

---

## API 列表（全量）

| 方法 | 路径 | 说明 | 阶段 |
|------|------|------|------|
| POST | /api/v1/auth/login | 微信 code 换 token（唯一登录入口） | 1 |
| GET | /api/v1/users/me | 获取个人信息 | 1 |
| PUT | /api/v1/users/me | 更新个人设置 | 1 |
| GET | /api/v1/questions | 获取题目列表（分页+筛选） | 1 |
| GET | /api/v1/questions/{id} | 获取单题详情 | 1 |
| GET | /api/v1/questions/random | 随机抽题（支持按科目/知识点） | 1 |
| POST | /api/v1/practice/submit | 提交练习答案 | 1 |
| GET | /api/v1/practice/records | 练习记录列表 | 1 |
| GET | /api/v1/practice/records/{id} | 练习详情（含逐题结果） | 1 |
| GET | /api/v1/wrong-questions | 错题本列表（分页+筛选） | 1 |
| GET | /api/v1/wrong-questions/stats | 错题统计（按科目/类型） | 1 |
| PUT | /api/v1/wrong-questions/{id} | 更新错题（标记已掌握） | 1 |
| POST | /api/v1/ai/error-analysis | AI 错题分析 | 2 |
| POST | /api/v1/ai/study-advice | AI 学习建议 | 2 |
| POST | /api/v1/ai/summary | AI 知识点总结 | 2 |
| GET | /api/v1/ai/chats | AI 对话历史 | 2 |
| GET | /api/v1/review-plans | 获取复习计划列表 | 2 |
| POST | /api/v1/review-plans/generate | AI 生成复习计划 | 2 |
| PUT | /api/v1/review-plans/{id} | 更新复习计划状态 | 2 |
| POST | /api/v1/import/upload | 上传文件（Excel/Word/PDF/Markdown） | 1 |
| GET | /api/v1/import/batches | 导入批次列表 | 1 |
| GET | /api/v1/import/batches/{id} | 批次详情（待审核题目列表） | 1 |
| PUT | /api/v1/import/questions/{id} | 审核单题（通过/拒绝/编辑） | 1 |
| POST | /api/v1/import/batches/{id}/approve | 批量通过审核 | 1 |

### 待开发（SM-2 阶段）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/review/submit | 提交复习结果（含质量评分） |
| GET | /api/v1/review/due | 获取今日待复习题列表 |
| GET | /api/v1/review/stats | 复习统计数据 |
| PUT | /api/v1/wrong-questions/{id}/quality | 错题质量评分（触发 SM-2） |

### 待开发（数据看板阶段）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/stats/overview | 学习总览统计 |
| GET | /api/v1/stats/subject/{subject} | 学科维度统计 |
| GET | /api/v1/stats/knowledge-points | 知识点掌握度列表 |
| GET | /api/v1/stats/trends | 学习趋势数据 |
| GET | /api/v1/stats/behavior | 学习行为分析 |
| GET | /api/v1/stats/forget-trends | 遗忘趋势分析 |
| GET | /api/v1/knowledge-points | 知识点树（全量） |
| PUT | /api/v1/questions/{id}/knowledge-points | 题目关联知识点 |

---

## 开发阶段

### 阶段 1：核心刷题闭环 ✅

**目标**：能登录（微信 wx.login）、能刷题、能导入题目、能记录对错

| 项目 | 内容 |
|------|------|
| 数据库 | users + questions + question_imports + practice_records |
| 后端 API | 微信 code 登录、题库 CRUD、文件上传+导入解析+审核、提交练习、练习历史 |
| 前端 | 微信静默登录、刷题页（选择题）、提交答案、查看结果 |
| AI | ❌ 无 |
| 部署 | docker-compose 本地、Docker 生产 |

**验收标准**：
- [x] 小程序 wx.login() → 后端 jscode2session → 自动创建用户 → 返回 JWT
- [x] 可以随机抽题并作答
- [x] 提交后显示对错
- [x] 练习记录可查
- [x] 通过 Excel 导入 10 道题并审核入库

### 阶段 2：错题本 + AI 分析 ✅

**目标**：错题自动收录、AI 分析错因、生成复习计划

| 项目 | 内容 |
|------|------|
| 数据库 | wrong_questions + review_plans + ai_chats |
| 后端 API | 错题 CRUD、AI 解析、AI 建议、复习计划生成 |
| 前端 | 错题本页面、AI 解析展示、复习计划列表 |
| AI | DeepSeek 错题解析 + 学习建议 + 知识点总结 |

**验收标准**：
- [x] 做错的题自动进入错题本
- [x] AI 分析显示错因和建议
- [x] 可以查看每日复习计划
- [x] 标记已掌握后不再出现在复习列表

### 阶段 3：完善 + 打磨 ✅

**目标**：体验优化、数据统计、稳定性

| 项目 | 内容 |
|------|------|
| 前端 | 加载态、空态、错误态覆盖、数据看板 |
| AI | 降级方案完善、token 统计看板 |
| 部署 | Nginx 配置、HTTPS、日志收集 |

**验收标准**：
- [x] 所有页面有加载/空/错误状态
- [x] 复习计划按时推送提醒
- [x] AI 降级正常（API 挂了不影响刷题）
- [x] 可部署上线

### 阶段 4（MVP 后增强）：SM-2 智能复习系统

**目标**：升级为间隔重复驱动的动态复习系统

| 项目 | 内容 |
|------|------|
| 数据库 | review_schedules（新增） |
| 后端 | SM-2 算法实现、复习调度逻辑、质量评分接口 |
| 前端 | 复习评分交互、待复习队列、复习统计 |
| AI | ❌ 无（纯算法调度） |

**前置条件**：已有一定量的错题数据（建议至少 30 道以上）

### 总开发周期预估

| 阶段 | 时间 | 状态 |
|------|------|------|
| 阶段 1 | 1-2 周 | ✅ 核心可用 |
| 阶段 2 | 1-2 周 | ✅ 完整可用 |
| 阶段 3 | 1 周 | ✅ 可上线 |
| 阶段 4（后期） | 1 周 | 🔜 SM-2 增强 |
| 阶段 5（后期） | 2 周 | 📊 数据分析看板 |

---

## 题库导入方案

### 核心理念

> **"Excel + 人工校对"是考研个人开发者的最优方案。**
>
> 不要追求完全自动化。稳定 > 效率 > 自动化。

### Excel 优先级最高的原因

1. **最稳定** — 行列结构天然对应题目字段，不会出现解析错位
2. **最容易维护** — 任何时候打开 Excel 都能修改，不依赖系统
3. **最适合个人长期整理** — 所有题目在一个文件里，搜索、筛选、排序都方便
4. **最适合 AI 批量生成** — DeepSeek 可以直接输出 Excel 格式的题目列表
5. **最方便后期修改** — 改一个单元格就能更新题目，不需要重新导入
6. **出错率最低** — 结构化格式决定了字段不会混淆

### 导入模板字段

| 字段 | 必填 | 说明 |
|------|------|------|
| subject | ✅ | math2 / exam408 / english |
| question_type | ✅ | choice / fill / subjective |
| stem | ✅ | 题目题干，纯文本（含 LaTeX 公式用 $...$ 包裹） |
| options | ❌ | 选择题选项，多行用 `\n` 分隔：`A:xxx\nB:xxx\nC:xxx\nD:xxx` |
| answer | ✅ | 标准答案。选择题填 `A`/`B`/`C`/`D` |
| explanation | ❌ | 解析/官方解答 |
| difficulty | ❌ | 1-5，默认 3 |
| tags | ❌ | 知识点标签，逗号分隔 |

### PDF 导入（辅助）

**MVP 原则**：不做 OCR，只处理文本型 PDF。接受局限性：
- 扫描版 PDF（图片）无法处理，需手动录入
- 排版复杂的 PDF 切分不准确，需人工调整
- 数学公式可能乱码，需人工校对
- PDF 只做辅助导入，不要花时间优化解析准确率

### Word / Markdown 导入

- Word：按 `## 题目` / `## 选项` / `## 答案` 等标题切分
- Markdown：主要用于 AI 批量生成场景

### 导题工作流

```
准备题目文件 (Excel/Word/PDF)
  → 上传 + 解析 → 进暂存区 (status=pending)
  → 人工审核 + 调整 ← 核心步骤，不要跳过
  → 确认入库 (status=approved → questions 表)
```

### 分阶段实施

| 阶段 | 方案 | 自动化程度 |
|------|------|-----------|
| 阶段 1（MVP） | Excel 导题（核心） | 低（人工为主） |
| 阶段 2（MVP） | Word/PDF 辅助导入 | 中（解析自动，审核人工） |
| 阶段 3（后期） | AI 自动标签分类 | 高（AI辅助，人工确认） |
| 阶段 4（可选） | OCR 识别 | 高（纯AI） |

---

## AI 辅助导题（后期扩展）

当前不做。预留以下 AI 能力，但**必须人工确认后再入库**：

1. **自动生成标签** — 对已入库题目，AI 批量补充 `knowledge_points`
2. **自动识别知识点** — 根据题干分析所属知识点章节
3. **自动生成难度** — 根据题目复杂度 AI 评估 1-5 难度
4. **自动总结题型** — 根据题目特征分类（计算题/证明题/概念题）
5. **AI 批量生成题目** — 通过 Prompt 生成 Markdown/Excel 格式的练习题

所有 AI 生成的内容，必须经过人工审核后才能进入 `questions` 表。不允许 AI 直接写入正式题库。

---

## SM-2 智能复习系统（MVP 后增强）

### 设计原则

> **不要推翻现有 wrong_questions / review_plans，基于现有架构渐进式增强。**

### 核心目标

1. 根据真实掌握情况动态调整复习间隔
2. 自动计算下一次复习时间
3. 区分"会了"和"暂时记住了"
4. 复习计划从"静态题单"升级为"动态记忆系统"
5. 为后续记忆曲线模型预留扩展

### SM-2 算法

每次复习后根据质量评分更新间隔：

```
质量评分 q (0-5):
  5 = 完全正确，毫不犹豫
  4 = 正确，稍有犹豫
  3 = 正确，但较困难
  2 = 错误，但能想起来正确答案
  1 = 错误，想起来正确答案但很困难
  0 = 完全错误，毫无印象

更新规则:
  if q < 3:
      repetitions = 0, interval = 1
  else:
      if repetitions == 0: interval = 1
      elif repetitions == 1: interval = 6
      else: interval = round(interval * ease_factor)
      repetitions += 1

  ease_factor = max(1.3, ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
  next_review_date = today + interval
```

### 文件结构

```
backend/app/services/sm2_service.py  # SM-2 算法核心 + 调度逻辑
```

不需要新增 model（复用 wrong_questions 的 SM-2 字段或 review_schedules 表）。

### 集成方式

| 方式 | 说明 | 推荐度 |
|------|------|--------|
| 方式一：错题复习集成 | 答完题评分 → 更新 SM-2 → 加入复习计划 | ⭐ 推荐 |
| 方式二：独立调度 | review_schedules 独立管理复习队列 | ⭐⭐ |
| **方式三：混合** | wrong_questions 短期复习 + review_schedules 长期巩固 | ⭐⭐⭐ 推荐 |

### 与现有 review_plans 的关系

```
review_plans：面向用户的"每日复习题单"
  ↕ 同步
review_schedules / wrong_questions.SM2：后端的"调度引擎"
```

- `review_plans` 保持现有接口不变
- SM-2 作为调度引擎，自动计算每天要复习哪些题
- 用户不感知 SM-2，只看到"今天需要复习 5 道题"
- 复习完成后自动更新 SM-2 参数，生成明天的计划

### SM-2 不做的事

- ❌ 强化学习 / AI 自动预测遗忘率
- ❌ 多维知识图谱
- ❌ 超复杂记忆模型（如 DSR、ACT-R）
- ❌ 个性化机器学习推荐
- ❌ 实时动态调度系统
- ❌ 跨用户协同过滤

---

## 阶段 5：学习数据系统 + 分析看板

### 核心目标

基于已有数据：

- `practice_records` — 练习记录
- `wrong_questions` — 错题记录
- `review_plans` — 复习计划
- SM-2 复习调度数据（`review_schedules`）
- 答题耗时、查看答案次数、AI 分析结果

建立：

1. **学习数据统计系统** — 多维度学习数据聚合与展示
2. **知识点掌握度系统** — 基于正确率 + 间隔重复的知识点级掌握评估
3. **学习趋势分析系统** — 正确率、学习量、掌握度的时序变化
4. **遗忘趋势分析系统** — 识别短期记住但长期遗忘的假掌握
5. **长期学习画像** — 基于累计数据的个性化学习诊断

目标是让系统不仅能"刷题"，还能分析用户薄弱点、识别假掌握知识点、分析遗忘趋势、提供长期学习反馈。

### 一、学习数据统计看板

#### 前端新增页面

- **Dashboard 学习主页** — 今日学习概览 + 核心指标卡片
- **学习统计页** — 多维度统计详情
- **学习趋势页** — 正确率/刷题量趋势图表
- **学科分析页** — 按学科维度的深度分析

#### 数据展示内容

##### 1. 学习总览

- 累计刷题数
- 总正确率
- 总学习时长
- 连续学习天数
- 今日学习数据（刷题数、正确率、学习时长）
- 最近 7 天学习趋势（折线图）

##### 2. 学科维度统计

- 数学二正确率、学习量
- 408 正确率、学习量
- 英语正确率、学习量
- 支持周/月时间维度切换
- 学科难度分布

##### 3. 知识点热力图

按学科展示知识点掌握度热力图：

- 高数知识点掌握情况
- 408 各科知识点掌握情况
- 英语知识点掌握情况
- 掌握度百分比（0-100%）
- 高频错题知识点排名
- 遗忘率统计（结合 SM-2）

##### 4. 学习行为分析

- 平均答题耗时（按学科/题型）
- 高频查看答案的题型
- 高频错误题型分布
- 学习活跃时间段（几点最爱刷题）
- 复习完成率（计划 vs 实际）

##### 5. 遗忘趋势分析

结合 SM-2 复习数据：

- 高频遗忘知识点 Top N
- 长期未掌握题目（多次复习仍不通过）
- "短期记住但长期遗忘"的假掌握题目
- 最近记忆衰减最快的内容

### 二、知识点体系升级（阶段 5 核心）

#### 目标

将当前的简单 `tags` 标签系统升级为结构化、可量化、可追踪的知识点体系。

#### 当前状态

```text
# 当前：单层扁平标签，无法量化掌握度
tags: 极限,导数,定积分
```

#### 升级目标

```text
# 目标：分层知识点体系，每层可量化掌握度
{
  "subject": "math2",
  "chapter": "高等数学",
  "section": "一元函数积分学",
  "knowledge_point": "定积分的换元积分法",
  "tags": ["换元法", "定积分", "积分计算"],
  "parent": "定积分",
  "difficulty_level": 3,
  "mastery": 0.72,          # 掌握度 [0, 1]
  "forget_rate": 0.15,       # 遗忘率
  "total_attempts": 25,
  "correct_attempts": 18,
  "avg_response_time": 45.2, # 秒
  "last_reviewed": "2026-05-18"
}
```

#### 知识点分层结构

```
├── math2 (数学二)
│   ├── 高等数学
│   │   ├── 函数与极限
│   │   ├── 一元函数微分学
│   │   ├── 一元函数积分学
│   │   ├── 多元函数微积分学
│   │   ├── 常微分方程
│   │   └── 无穷级数（仅数一，数学二跳过）
│   └── 线性代数
│       ├── 行列式
│       ├── 矩阵
│       ├── 向量
│       ├── 线性方程组
│       ├── 特征值与特征向量
│       └── 二次型
├── exam408 (计算机统考)
│   ├── 数据结构
│   ├── 计算机组成原理
│   ├── 操作系统
│   └── 计算机网络
└── english (英语)
    ├── 词汇与语法
    ├── 完形填空
    ├── 阅读理解
    ├── 翻译
    └── 写作
```

#### 知识点掌握度模型

掌握度 = f(正确率, 做题量, 遗忘因子, 时间衰减)

```text
mastery = correct_rate * (1 - forget_factor) * recency_bonus

其中：
  correct_rate     = 该知识点历史正确率
  forget_factor    = SM-2 间隔衰减因子（间隔越长，因子越大）
  recency_bonus    = 近期答题加分（7 天内有练习则加分）

阈值：
  mastery >= 0.8   → 掌握良好（绿色）
  0.5 <= mastery < 0.8 → 需巩固（黄色）
  mastery < 0.5    → 薄弱（红色）
```

#### 升级路径

| 步骤 | 内容 | 备注 |
|------|------|------|
| 1. 数据结构落地 | 设计 `knowledge_points` 表和树形结构 | 新增 migration |
| 2. 数据回填 | 将现有 `tags` 映射到新知识点体系 | 脚本迁移 |
| 3. 题目挂载 | 每题可关联多个知识点 | questions 表增加 `knowledge_point_ids` |
| 4. 答题更新 | 每次答题后更新知识点掌握度 | 异步/同步更新 |
| 5. 聚合展示 | 按知识点维度聚合统计 | API + 前端 |

#### 新增/修改 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/stats/overview | 学习总览统计 |
| GET | /api/v1/stats/subject/{subject} | 学科维度统计 |
| GET | /api/v1/stats/knowledge-points | 知识点掌握度列表 |
| GET | /api/v1/stats/trends | 学习趋势数据 |
| GET | /api/v1/stats/behavior | 学习行为分析 |
| GET | /api/v1/stats/forget-trends | 遗忘趋势分析 |
| GET | /api/v1/knowledge-points | 知识点树（全量） |
| PUT | /api/v1/questions/{id}/knowledge-points | 题目关联知识点 |

### 三、后端新增/改造

#### 新增文件

| 文件 | 说明 |
|------|------|
| `app/models/knowledge_point.py` | 知识点 model（树形结构） |
| `app/schemas/stats.py` | 统计相关 schema |
| `app/services/stats_service.py` | 统计数据聚合服务 |
| `app/services/knowledge_service.py` | 知识点管理服务 |
| `app/api/v1/stats.py` | 统计 API 路由 |
| `app/api/v1/knowledge_points.py` | 知识点 API 路由 |

#### Model 设计

```python
class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: int = Column(Integer, primary_key=True)
    subject: str = Column(String(20), nullable=False)       # math2 / exam408 / english
    name: str = Column(String(100), nullable=False)          # 知识点名称
    full_name: str = Column(String(200), nullable=False)     # 完整路径名（如 "高等数学 > 一元函数积分学 > 定积分"）
    parent_id: int = Column(Integer, ForeignKey("knowledge_points.id"), nullable=True)
    level: int = Column(Integer, default=1)                  # 层级：1=学科, 2=章, 3=节, 4=知识点
    sort_order: int = Column(Integer, default=0)             # 排序
```

#### questions 表修改

```python
# questions 表新增字段（在已有基础上增加）
knowledge_point_ids: list[int] = Column(ARRAY(Integer), default=[])
mastery_data: dict = Column(JSONB, default=dict)  # 缓存该题各知识点的掌握度
```

### 四、数据库 migration 计划

| 版本 | 内容 |
|------|------|
| 005 | 创建 `knowledge_points` 表 + 初始种子数据 |
| 006 | questions 表增加 `knowledge_point_ids` + `mastery_data` 字段 |
| 007 | 创建统计相关索引 |

### 与现有阶段 4 的关系

- 阶段 4 的 SM-2 复习数据（`review_schedules`）是阶段 5 遗忘趋势分析的输入源
- 阶段 5 的知识点掌握度模型会调用 SM-2 的间隔数据计算遗忘因子
- **不修改阶段 4 的现有接口**，只新增不破坏

### 验收标准

- [ ] Dashboard 页面展示学习总览指标
- [ ] 知识点掌握度热力图可按学科查看
- [ ] 遗忘趋势分析识别出假掌握题目
- [ ] 学习趋势展示 7 天/30 天正确率变化
- [ ] 所有统计接口响应时间 < 500ms

---

## 阶段 6：生产部署 + 正式上线

### 核心目标

让系统真正具备：

- 可部署
- 可维护
- 可恢复
- 可监控
- 可长期稳定运行

的能力。

阶段 6 不再新增核心业务功能。

重点是：

> 从"开发项目"
>
> 升级为
>
> "真实可长期使用的产品"。

---

### 一、生产环境部署

#### 目标

建立完整生产环境：

- FastAPI
- MySQL/PostgreSQL
- Redis
- Nginx
- Docker
- HTTPS

支持：

- 云服务器部署
- 小程序正式环境
- 长期稳定运行

---

### 二、部署架构

#### 服务器架构

```text
用户 → HTTPS → Nginx (反向代理) → FastAPI (Gunicorn + Uvicorn)
                                        ├── PostgreSQL
                                        └── Redis (可选)
```

#### Nginx 配置

需要实现：

- 静态资源缓存
- gzip 压缩
- HTTPS 证书（Let's Encrypt）
- 请求限流
- 反向代理到 FastAPI
- 日志记录

#### Docker 配置

多阶段构建：

- 开发：`docker-compose up`（热重载）
- 生产：多阶段 Dockerfile（slim 镜像）

#### 数据库

使用 PostgreSQL 15+，生产环境配置：

- 连接池大小调优
- 慢查询日志
- 自动备份
- 迁移版本管理（alembic）

---

### 三、HTTPS + 域名

#### 必须完成

- [ ] 购买域名（或使用已有域名）
- [ ] DNS 解析到服务器 IP
- [ ] Nginx 配置 HTTPS（Certbot / Let's Encrypt）
- [ ] 强制 HTTPS 重定向
- [ ] HTTP/2 支持（可选）

#### 小程序端

- [ ] 修改 `config.js` 的 `BASE_URL` 为生产域名
- [ ] 微信小程序管理后台配置合法域名
- [ ] 关闭开发模式（`DEV = false`）

---

### 四、环境变量与安全

#### 生产环境变量

```bash
APP_ENV=production
APP_SECRET=<随机 64 位密钥>
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
DEEPSEEK_API_KEY=<真实 API Key>
WECHAT_APP_ID=<微信小程序 AppID>
WECHAT_APP_SECRET=<微信小程序 AppSecret>
```

#### 安全措施

- [ ] `.env` 文件禁止提交到 git
- [ ] 生产密钥使用环境变量而非文件
- [ ] JWT 密钥独立且高强度
- [ ] API 限流（Rate Limiting）
- [ ] CORS 配置仅允许小程序域名
- [ ] 数据库只创建最小权限用户
- [ ] 定期轮换密钥

---

### 五、日志与监控

#### 日志系统

- [ ] 请求日志（结构化 JSON）
- [ ] 慢查询日志（数据库）
- [ ] 错误日志（自动捕获 + 告警）
- [ ] AI 调用日志（耗时、token、错误率）

#### 部署后监控检查清单

- [ ] 服务器基础监控（CPU / 内存 / 磁盘）
- [ ] 应用健康检查（`/health` 端点）
- [ ] API 错误率监控
- [ ] API 响应时间监控
- [ ] 数据库连接数监控
- [ ] 磁盘空间监控（日志轮转）
- [ ] AI API 调用成功率
- [ ] 小程序前端错误日志（wx.onError）

---

### 六、数据安全与备份

#### 数据库备份

- [ ] 每日自动备份（pg_dump）
- [ ] 备份保留 7 天
- [ ] 异地备份（可选）
- [ ] 备份恢复演练（季度）

#### 数据安全

- [ ] 用户数据不落日志
- [ ] 敏感字段加密（如有）
- [ ] 数据库备份加密
- [ ] 定期清理过期数据

---

### 七、部署流程

#### 首次部署

```text
1. 购买云服务器（2C4G 起步）
2. 安装 Docker + Docker Compose
3. 配置域名 DNS + HTTPS
4. 修改 .env 生产配置
5. docker-compose up -d
6. 运行 alembic upgrade head
7. 验证所有 API 正常
8. 小程序切换正式环境
9. 全链路回归测试
```

#### 日常更新

```text
1. git pull
2. docker-compose build app
3. docker-compose up -d app
4. 如有 migration：docker-compose exec app alembic upgrade head
```

---

### 八、上线前检查清单

#### 功能检查

- [ ] 微信登录完整流程
- [ ] 刷题 / 交卷 / 判分
- [ ] 错题本 / 标记掌握
- [ ] 复习计划 / SM-2 质量评分
- [ ] 学习统计 / Dashboard
- [ ] 题库导入（Excel / PDF）
- [ ] AI 错题分析 / 学习建议
- [ ] AI 降级正常（无 API Key 时能运行）

#### 安全检查

- [ ] 所有 API 有认证保护（除 /auth/login）
- [ ] JWT 过期处理正常
- [ ] CORS 正确配置
- [ ] 数据库只有最小必要权限
- [ ] .env 不包含在代码仓库中

#### 性能检查

- [ ] API 首页响应 < 200ms
- [ ] 统计接口响应 < 500ms
- [ ] 并发 50 用户无崩溃
- [ ] 数据库连接池不泄露

#### 监控检查

- [ ] `/health` 端点可用
- [ ] 错误日志能查看
- [ ] AI 调用失败能告警

---

### 九、部署后维护

#### 日常运维

- 每周检查服务器磁盘
- 每月检查数据库性能
- 每季度更新依赖版本
- 持续监控 AI API 费用

#### 故障恢复

- 数据库损坏 → 从备份恢复
- 服务器宕机 → 重新部署
- AI API 不可用 → 自动降级（不影响刷题）

#### 版本更新

- 小更新：直接 git pull + docker-compose restart
- 大更新：新开端口 + 灰度切换

### 十、与已有阶段的关系

- 阶段 1-5 的所有功能在部署后保持不变
- 阶段 6 不修改任何业务逻辑
- 部署后如需新增功能，作为单独迭代（阶段 7+）

### 总开发周期预估

| 阶段 | 时间 | 状态 |
|------|------|------|
| 阶段 1 | 1-2 周 | ✅ 核心可用 |
| 阶段 2 | 1-2 周 | ✅ 完整可用 |
| 阶段 3 | 1 周 | ✅ 可上线 |
| 阶段 4（后期） | 1 周 | ✅ SM-2 增强 |
| 阶段 5（后期） | 2 周 | ✅ 数据分析看板 |
| 阶段 6（部署） | 3-5 天 | ✅ 生产部署 |

---

## 当前优先事项

- [x] 阶段 4：SM-2 智能复习系统
- [x] 阶段 5：学习数据系统 + 分析看板
- [x] 部署基础设施（Dockerfile.prod / nginx / docker-compose.prod）
- [x] 健康检查 + 日志 + CORS
- [x] 部署脚本 + 备份脚本
- [x] `.gitignore` + `.env.example` 完善
- [x] 云服务器部署（2C2G, Alibaba Cloud Linux）
- [x] Docker 镜像构建 + 服务编排（PostgreSQL + app + Nginx）
- [x] HTTPS 证书签发（Let's Encrypt）+ 自动续期
- [x] Nginx 反向代理 + gzip + 安全头
- [x] API 全链路验证通过
- [ ] 微信小程序正式环境切换（需提交审核）

---

## 阶段七：AI 辅助导题与智能题库增强系统

本阶段目标：

在现有题目录入、审核、导入系统稳定运行的基础上，引入 AI 辅助导题能力，用于提升题库整理效率、知识点标注效率与后期题库扩展能力。

注意：
本阶段 AI 仅作为"辅助工具"，不能直接替代人工审核。
所有 AI 生成、补全、分析的内容，必须经过人工确认后才能正式入库。

### 核心开发原则

1. AI 只能生成"待审核数据"
2. AI 不允许直接写入正式 questions 表
3. 所有 AI 输出必须进入审核流
4. 必须保留"AI生成"标记
5. 用户必须可以：
   - 查看 AI 原始结果
   - 修改 AI 内容
   - 拒绝 AI 建议
   - 手动确认后再入库

系统需要明确区分：

- 用户手动录入
- OCR识别内容
- AI推理补全内容
- AI自动生成内容

避免后期题库污染。

### 1. AI 自动生成知识点标签

对已导入题目自动分析并补充 knowledge_points。

要求：

- AI 根据题干、答案、解析分析知识点
- 支持单知识点、多知识点、主次知识点
- AI 结果进入"待审核状态"
- 用户可修改、删除、手动新增
- 不允许 AI 直接覆盖已有人工标签

后续预留：

- 知识点树
- 知识图谱
- 知识点权重系统

### 2. AI 自动识别章节与考点归属

根据题目内容自动识别所属章节。

例如：

- 高数 → 导数
- 线代 → 特征值
- 英语 → 阅读理解
- 政治 → 马原

要求：

- AI 输出必须附带"置信度"
- 低置信度结果需要重点提醒
- 支持人工重新选择章节
- 支持后期接入知识树系统

### 3. AI 自动生成题目难度

AI 根据题目复杂度评估难度等级。

要求：

- 难度范围 1~5 级
- 评估维度包括计算量、推理深度、知识点复杂度、综合程度
- AI 需要输出难度等级和简要原因
- 人工可重新调整难度

后期可结合用户正确率、平均耗时、错误率动态修正真实难度。

### 4. AI 自动总结题型

自动分析题目类型。

例如：

- 概念题、计算题、证明题、选择题、填空题、综合题、应用题

要求：

- 支持多标签分类
- 支持人工修改
- 不允许覆盖人工已确认分类

后期可用于智能刷题、专项训练、AI组卷、错题归类。

### 5. AI 批量生成练习题

基于 Prompt、知识点、章节自动生成练习题。

支持格式：

- Markdown / Excel / JSON

生成内容包括：

- 题干、选项、答案、解析、难度、知识点

注意：

- AI 生成题目默认进入"待审核题库"
- 不允许直接进入正式题库
- 必须支持批量审核
- 必须支持一键丢弃

后期可扩展：

- 真题风格模拟
- 指定难度/知识点生成
- 错题相似题生成
- 个性化刷题生成

### 6. AI 自动补全缺失题目信息

当 OCR 或导题过程中存在缺失信息时，由 AI 辅助补全。

可补全内容：

- 学科、章节、答案、知识点、难度、题型、解析

**重点要求**：

如果 AI 自动补全的是"答案"：

- 必须明确标记"AI生成答案"
- 必须进入人工审核
- 必须提示用户注意甄别
- 不允许默认视为正确答案

系统需要保留：

- 原始OCR内容
- AI补全过程
- AI推理结果
- 人工最终确认结果

避免后期数据不可追溯。

### 审核流设计要求

新增 AI 审核流程：

```
AI输出 → 待审核 → 人工确认 → 正式入库
```

严禁：

```
AI结果 → 自动写入 questions 表
```

必须新增字段：

- `ai_generated`
- `ai_confidence`
- `ai_review_status`
- `ai_source`
- `ai_reviewed_by`
- `ai_review_time`

确保后期所有 AI 数据可追踪、可回滚、可审计。

### 数据库与架构要求

建议新增表：

- `ai_question_drafts`
- `ai_generation_logs`
- `ai_review_records`

避免 AI 数据直接污染正式题库。

同时需要：

- 保留 Prompt 日志
- 保留 AI 返回原文
- 支持重新生成
- 支持多模型兼容
- 支持后期接入 RAG

### 本阶段最终目标

构建一套"AI辅助生成 + 人工审核确认"的安全题库增强系统。

核心目标不是"完全自动化"，而是：

- 提升导题效率
- 提升知识点整理效率
- 降低人工录入成本
- 保证题库质量
- 为后期智能学习系统提供结构化数据基础

确保：

**AI 永远只是辅助工具，正式题库的数据控制权始终掌握在人工审核流程中。**

---

## 阶段八：OCR 扫描版 PDF 支持（最小侵入式扩展）

本阶段目标：

在现有 MVP 基础上，为 AI 导入题库功能增加 OCR 能力。

注意：
本阶段必须兼容"阶段七 AI 分析导入题目功能"，不得破坏现有导入流程、LLM 结构化流程、数据库结构与接口设计。

目标：
在保持原有代码结构基本不变的前提下，实现：
"文本型 PDF 直接解析"
+
"扫描版 PDF 自动 OCR 识别"

形成完整双通道导入能力。

---

### 核心功能要求

#### 1. 自动判断 PDF 类型

- 判断当前 PDF 页面是否可直接提取文本
- 若页面文本为空/极少，则视为图片型页面
- 仅对图片型页面执行 OCR
- 普通文本 PDF 不允许走 OCR（避免浪费性能）

#### 2. OCR 识别能力

- 使用 PaddleOCR
- 支持中文识别
- 后续保留英文扩展能力
- OCR 必须支持 CPU 模式运行

#### 3. OCR 并发处理

- OCR 页面必须支持并发执行
- 提升大 PDF 导入速度
- 推荐：`ThreadPoolExecutor` 或 `asyncio + 线程池`

#### 4. OCR 文本清洗

OCR 输出后必须进行：

- 去除乱码
- 合并断行
- 去除重复空格
- 修复 OCR 常见换行问题
- 清理特殊符号

#### 5. 接入原有 LLM 结构化流程

OCR 结果最终必须进入原有 AI 解析流程，不允许新增另一套题目结构化逻辑。

完整流程：

```
PDF
→ PDF分类
→ 文本提取 / OCR
→ 文本清洗
→ 原有LLM结构化
→ 入库
```

---

### 严格架构要求

必须保持 MVP 原有架构稳定：

- 不允许重写原有导入系统
- 不允许修改已有数据库结构
- 不允许破坏阶段七功能
- 不允许让 OCR 与普通 PDF 流程耦合混乱

以"扩展模块"方式接入。

---

### 新增模块

#### `backend/app/services/ocr_service.py`

职责：
- PaddleOCR 初始化（单例）
- 页面 OCR 识别
- 并发 OCR 处理
- OCR 文本清洗

#### `backend/app/services/pdf_classifier.py`

职责：
- 判断 PDF 页面是否为图片型
- 判断是否需要 OCR
- 页面分类

---

### 推荐技术方案

| 用途 | 方案 |
|------|------|
| PDF 解析 | PyMuPDF（fitz） |
| OCR | PaddleOCR |
| 图片转换 | `page.get_pixmap()` |
| 并发 | `concurrent.futures.ThreadPoolExecutor` |

---

### 推荐处理流程

```
Step 1：使用 PyMuPDF 读取 PDF
Step 2：遍历页面
          if page.get_text() 有效 → 直接使用文本
          else → 标记为 OCR 页面
Step 3：仅对 OCR 页面
          → 转图片
          → PaddleOCR 识别
          → 并发处理
Step 4：OCR 结果文本清洗
Step 5：合并全部页面文本
Step 6：进入原有 LLM 结构化流程
```

---

### OCR 文本清洗要求

必须实现 `clean_ocr_text(text)`，至少包含：

- 去除连续空格
- 去除连续换行
- 合并被错误拆开的句子
- 去除乱码字符
- 清理页眉页脚残留
- 修复如 `"第\n一章"` 这种断裂问题

---

### 并发要求

- OCR 必须支持 `max_workers` 可配置
- 禁止串行逐页 OCR

---

### 性能优化要求

1. 仅 OCR 必要页面
2. OCR 对象单例化，避免重复初始化
3. 大 PDF 避免内存爆炸
4. 图片分辨率合理控制

---

### 错误处理要求

- OCR 失败页面跳过机制
- PDF 损坏异常处理
- PaddleOCR 异常处理
- 超大 PDF 保护
- 空结果保护

系统不能因为某一页 OCR 失败而整体崩溃。

---

### 新增配置项

```bash
OCR_ENABLED=true
OCR_MAX_WORKERS=4
OCR_LANGUAGE=ch
OCR_USE_GPU=false
```

---

### 新增依赖

```
paddleocr
paddlepaddle
PyMuPDF
```

---

### 验收标准

- [ ] 文本型 PDF 走原有流程，不触发 OCR
- [ ] 扫描版 PDF 自动识别并走 OCR 通道
- [ ] OCR 多页并发处理，不串行
- [ ] OCR 失败单页跳过，不影响整体
- [ ] OCR 结果经清洗后进入原有 LLM 结构化流程
- [ ] 原有 Excel / 文本型 PDF / AI 生成导入流程全部正常（无回归）
- [ ] 通过 `OCR_ENABLED=false` 可完全关闭 OCR，退化为原有行为

---

### 后续可扩展方向

- 表格 OCR（题目附带表格识别）
- 数学公式 OCR（专用公式识别模型）
- 图像题识别（题目中包含图片的处理）
- 多语言 OCR（英语题目）
- GPU 加速（生产环境可选开启）

---

## 待做（按需后续）

- 未实际跑 PDF→OCR→入库端到端：本机无 paddleocr / paddlepaddle 环境，依赖体积大（约 500MB+），建议在容器或专用环境内安装验证
