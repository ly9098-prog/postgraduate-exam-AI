- # 22408 AI 考研学习助手 — 后续阶段开发规划

  你现在处于：

  “导题系统 MVP 已完成”后的产品化阶段。

  当前已经完成：

  - Stage 1~9：导题流水线
  - OCR fallback
  - AI 修复
  - Review 审核系统
  - Pipeline 编排
  - Question 标准化

  现在需要开始：

  “正式题库 + 刷题学习系统”开发。

  ==================================================
  【总体开发原则】
  ==================================================

  后续阶段目标：

  不是继续增强 parser。

  而是：

  把系统真正变成：
  “可以长期学习的 AI 考研刷题平台”。

  后续阶段优先级：

  正式题库
  → 刷题系统
  → 错题系统
  → SM-2
  → AI 学习引擎
  → 部署优化

  禁止：

  - 提前做复杂 RAG
  - 提前做向量数据库
  - 提前做知识图谱
  - 提前做多 Agent
  - 提前做复杂微服务
  - 提前做多模型编排
  - 过度抽象架构

  保持：

  - FastAPI 单体架构
  - SQLite/Postgres 兼容
  - Service 层解耦
  - 小程序优先
  - MVP 可迭代

  ==================================================
  【阶段文档规范】
  ==================================================

  在开始后续开发前：

  必须先整理：

  /prompts/development/

  阶段开发文档。

  要求：

  每一个 Stage 都必须有独立开发文档。

  格式：

  stage10_question_publish.md
  stage11_practice_system.md
  stage12_sm2_scheduler.md
  stage13_ai_learning.md
  stage14_performance_optimization.md
  stage15_deployment.md

  同时：

  保留已有导题阶段文档：

  stage1_text_normalizer.md
  stage2_structure_analysis.md
  stage3_question_splitter.md
  stage4_answer_matcher.md
  stage5_question_normalizer.md
  stage6_ai_repair.md
  stage7_review_system.md
  stage8_pipeline_integration.md
  stage9_ocr_enhancement.md

  以及：

  standardization.md

  ==================================================
  【阶段文档要求】
  ==================================================

  每个阶段文档必须包含：

  1. 阶段目标
  2. MVP 范围
  3. 非目标（明确不做什么）
  4. 目录结构修改
  5. 数据库变更
  6. API 设计
  7. Service 设计
  8. Schema 设计
  9. 测试计划
  10. UI 影响范围
  11. 风险与兼容性
  12. 开发顺序
  13. 验收标准

  要求：

  - 文档先行
  - 禁止直接跳过设计进入编码
  - 所有阶段必须可独立开发
  - 所有阶段必须可单独测试

  ==================================================
  【阶段开发规则】
  ==================================================

  必须严格：

  “一阶段一开发”。

  禁止：

  同时开发多个 Stage。

  正确流程：

  1. 编写阶段文档
  2. 分析现有架构
  3. 输出 implementation plan
  4. 开发当前阶段
  5. 编写测试
  6. 执行测试
  7. 更新 docs/prompts
  8. 更新阶段完成记录
  9. 再进入下一阶段

  ==================================================
  【文档更新规则】
  ==================================================

  每完成一个阶段：

  必须更新：

  /prompts
  或
  /docs

  相关文档。

  包括但不限于：

  - architecture.md
  - api.md
  - pipeline.md
  - database.md
  - deployment.md
  - changelog.md
  - prompt.md
  - CLAUDE.md

  要求：

  文档内容必须与当前代码同步。

  禁止：

  代码已修改但文档未更新。

  ==================================================
  【测试规则】
  ==================================================

  每完成一个阶段：

  必须新增：

  对应测试文件。

  例如：

  backend/tests/test_services/test_question_publish_service.py
  backend/tests/test_services/test_practice_service.py
  backend/tests/test_services/test_review_scheduler.py

  要求：

  1. 单元测试
  2. API 测试
  3. 集成测试（必要时）
  4. 边界情况测试
  5. 错误场景测试
  6. 回归测试

  必须保证：

  全量测试继续通过。

  禁止：

  - 跳过测试
  - 只做 happy path
  - 不验证异常场景
  - 不验证事务回滚

  ==================================================
  【Stage 10 — 正式题库发布系统】
  ==================================================

  目标：

  建立：

  question_imports（审核区）
      ↓
  questions（正式题库）

  实现：
  “审核通过 → 发布到正式题库”

  ------------------------------------------
  10.1 阶段文档
  ------------------------------------------

  新增：

  /prompts/development/stage10_question_publish.md

  ------------------------------------------
  10.2 Question Publish Service
  ------------------------------------------

  新增：

  backend/app/features/question_publish_service.py

  核心职责：

  1. 将 approved import question 发布到正式题库
  2. 自动去重
  3. 发布状态流转
  4. 批量发布
  5. 发布统计

  建议核心函数：

  publish_questions()
  publish_single_question()
  detect_duplicate_question()
  build_question_model()
  mark_as_published()

  ------------------------------------------
  10.3 正式题库 ORM
  ------------------------------------------

  检查并完善：

  backend/app/models/question.py

  确保具备：

  id
  subject
  question_type
  stem
  options
  answer
  analysis

  difficulty
  source
  year
  chapter
  knowledge_points

  stem_hash

  created_at
  updated_at

  要求：

  - options 使用 JSON
  - knowledge_points 使用 JSON/list
  - stem_hash 建索引
  - 高频查询字段建立索引

  ------------------------------------------
  10.4 去重系统
  ------------------------------------------

  基于：

  stem_hash

  实现：

  导入重复题过滤。

  MVP 策略：

  重复：
      不新增 question
      记录 skipped_duplicate

  不要做：

  - merge
  - versioning
  - embedding similarity

  ------------------------------------------
  10.5 Review 状态机
  ------------------------------------------

  扩展：

  QuestionImport.status

  支持：

  pending
  approved
  rejected
  published

  状态流：

  pending
    ↓
  approved
    ↓
  published

  禁止非法状态跳转。

  ------------------------------------------
  10.6 Batch Review API
  ------------------------------------------

  新增 API：

  POST /api/v1/import/review/approve
  POST /api/v1/import/review/reject
  POST /api/v1/import/review/publish

  支持：

  - 批量 ID
  - 批量状态修改
  - 发布统计
  - duplicate 数量统计

  ------------------------------------------
  10.7 测试要求
  ------------------------------------------

  新增：

  backend/tests/test_services/test_question_publish_service.py

  覆盖：

  - publish success
  - duplicate skip
  - invalid question skip
  - batch publish
  - state transition
  - db rollback
  - transaction consistency

  完成后：

  更新：

  - /docs/database/
  - /docs/api/
  - /prompts/development/stage10_question_publish.md
  - changelog

  ==================================================
  【Stage 11 — 刷题系统】
  ==================================================

  目标：

  实现真正的：

  “用户做题系统”。

  ------------------------------------------
  11.1 阶段文档
  ------------------------------------------

  新增：

  /prompts/development/stage11_practice_system.md

  ------------------------------------------
  11.2 Practice Service
  ------------------------------------------

  新增：

  backend/app/services/practice_service.py

  支持：

  - 顺序刷题
  - 随机刷题
  - 按科目刷题
  - 按章节刷题
  - 按知识点刷题

  ------------------------------------------
  11.3 用户做题记录
  ------------------------------------------

  新增表：

  practice_records

  字段建议：

  user_id
  question_id
  user_answer
  is_correct
  used_time
  created_at

  ------------------------------------------
  11.4 错题系统
  ------------------------------------------

  新增：

  wrong_questions

  支持：

  - 自动加入错题本
  - 错题去重
  - 错题重做
  - 错题统计

  ------------------------------------------
  11.5 小程序刷题页
  ------------------------------------------

  新增页面：

  miniprogram/pages/practice/

  包括：

  - 题目展示
  - 选项点击
  - 答题反馈
  - 下一题
  - 收藏
  - 错题加入提示

  ------------------------------------------
  11.6 测试要求
  ------------------------------------------

  新增：

  backend/tests/test_services/test_practice_service.py

  测试：

  - random practice
  - chapter practice
  - answer submit
  - wrong question creation
  - statistics
  - empty question set

  完成后：

  更新：

  - docs/api/
  - docs/frontend/
  - docs/database/
  - prompts/development/stage11_practice_system.md
  - changelog

  ==================================================
  【Stage 12 — SM-2 复习系统】
  ==================================================

  目标：

  实现：

  记忆曲线复习调度。

  ------------------------------------------
  12.1 阶段文档
  ------------------------------------------

  新增：

  /prompts/development/stage12_sm2_scheduler.md

  ------------------------------------------
  12.2 Review Scheduler
  ------------------------------------------

  新增：

  backend/app/services/review_scheduler.py

  实现：

  SM-2 算法。

  字段：

  review_interval
  ease_factor
  repetitions
  next_review_at
  last_reviewed_at

  ------------------------------------------
  12.3 Review Queue
  ------------------------------------------

  支持：

  GET /api/v1/review/today

  ------------------------------------------
  12.4 Review Record
  ------------------------------------------

  新增：

  review_records

  记录：

  - 用户评分
  - 复习结果
  - interval 变化

  ------------------------------------------
  12.5 错题 + SM2 联动
  ------------------------------------------

  错题自动进入：

  SM-2 调度队列。

  ------------------------------------------
  12.6 测试要求
  ------------------------------------------

  新增：

  backend/tests/test_services/test_review_scheduler.py

  覆盖：

  - sm2 interval
  - ease factor update
  - review queue
  - overdue review
  - wrong question schedule

  完成后：

  更新：

  - docs/algorithm/
  - docs/api/
  - docs/database/
  - prompts/development/stage12_sm2_scheduler.md
  - changelog

  ==================================================
  【Stage 13 — AI 学习引擎】
  ==================================================

  目标：

  让 AI 真正辅助学习。

  ------------------------------------------
  13.1 阶段文档
  ------------------------------------------

  新增：

  /prompts/development/stage13_ai_learning.md

  ------------------------------------------
  13.2 AI 讲题
  ------------------------------------------

  新增：

  AI explain API。

  支持：

  - 题目讲解
  - 解题思路
  - 易错点分析

  ------------------------------------------
  13.3 AI 错因分析
  ------------------------------------------

  分析：

  用户为什么做错。

  ------------------------------------------
  13.4 AI 相似题推荐
  ------------------------------------------

  基于：

  - chapter
  - knowledge_points
  - question_type

  推荐相似题。

  不要提前上 embedding。

  ------------------------------------------
  13.5 AI 学习报告
  ------------------------------------------

  生成：

  - 薄弱知识点
  - 高频错误
  - 学习建议

  ------------------------------------------
  13.6 测试要求
  ------------------------------------------

  新增：

  backend/tests/test_services/test_ai_learning.py

  覆盖：

  - ai explain
  - weak point analysis
  - recommendation
  - ai fallback
  - token control

  完成后：

  更新：

  - docs/ai/
  - docs/api/
  - prompts/development/stage13_ai_learning.md
  - changelog

  ==================================================
  【Stage 14 — 性能优化】
  ==================================================

  目标：

  提升可上线能力。

  ------------------------------------------
  14.1 阶段文档
  ------------------------------------------

  新增：

  /prompts/development/stage14_performance_optimization.md

  包括：

  - Redis cache
  - SQL optimization
  - pagination
  - docker optimization
  - uvicorn/gunicorn optimization

  不要：

  - 微服务
  - Kubernetes
  - 分布式复杂架构

  ------------------------------------------
  14.2 测试要求
  ------------------------------------------

  新增：

  性能测试。

  包括：

  - API latency
  - concurrent requests
  - cache hit
  - db query count

  完成后更新：

  - docs/deployment/
  - docs/performance/
  - changelog

  ==================================================
  【Stage 15 — 上线部署】
  ==================================================

  目标：

  正式可用。

  ------------------------------------------
  15.1 阶段文档
  ------------------------------------------

  新增：

  /prompts/development/stage15_deployment.md

  ------------------------------------------
  15.2 部署内容
  ------------------------------------------

  包括：

  - HTTPS
  - 域名
  - Docker Compose
  - CI/CD
  - 自动备份
  - Sentry
  - 日志系统

  ------------------------------------------
  15.3 测试要求
  ------------------------------------------

  包括：

  - deployment verification
  - health check
  - backup recovery
  - rollback test

  完成后更新：

  - docs/deployment/
  - deploy/
  - changelog

  ==================================================
  【最终要求】
  ==================================================

  每次开发阶段：

  必须输出：

  1. task analysis
  2. implementation plan
  3. modified files
  4. migration files
  5. API changes
  6. test coverage
  7. updated docs

  要求：

  - 所有新增模块必须有测试
  - 所有阶段必须更新文档
  - 全量测试必须零回归
  - 保持 MVP 节奏
  - 不允许过度设计
