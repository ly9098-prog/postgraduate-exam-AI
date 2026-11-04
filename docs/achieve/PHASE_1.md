# 阶段 1 + 2：核心刷题闭环 + 错题本与 AI 分析 ✅

## 阶段 1：核心刷题闭环

**目标**：能登录（微信 wx.login）、能刷题、能导入题目、能记录对错

| 项目 | 内容 |
|------|------|
| 数据库 | users + questions + question_imports + practice_records |
| 后端 | 微信 code 登录、题库 CRUD、文件上传+导入解析+审核、提交练习、练习历史 |
| 前端 | 微信静默登录、刷题页（选择题）、提交答案、查看结果 |
| AI | ❌ 无 |
| 部署 | docker-compose 本地、Docker 生产 |

**验收**：小程序静默登录→随机抽题→作答→判对错→练习记录可查→Excel 导入审核

## 阶段 2：错题本 + AI 分析

**目标**：错题自动收录、AI 分析错因、生成复习计划

| 项目 | 内容 |
|------|------|
| 数据库 | wrong_questions + review_plans + ai_chats |
| 后端 | 错题 CRUD、AI 解析、AI 建议、复习计划生成 |
| 前端 | 错题本页面、AI 解析展示、复习计划列表 |
| AI | DeepSeek 错题解析 + 学习建议 + 知识点总结 |

**验收**：做错的题自动进错题本 → AI 分析错因 → 每日复习计划 → 标记已掌握后消失

### 关键文件

```
backend/app/api/v1/users.py            # 用户 API
backend/app/api/v1/questions.py        # 题库 API
backend/app/api/v1/practice.py         # 练习 API
backend/app/api/v1/wrong_questions.py  # 错题 API
backend/app/api/v1/review.py           # 复习计划 API
backend/app/api/v1/ai.py              # AI 分析 API
backend/app/ai/client.py              # DeepSeek HTTP 客户端
backend/app/ai/prompts.py             # Prompt 模板
backend/app/services/ai_service.py    # AI 服务
```

详细设计见 `/docs/API_SPEC.md`、`/docs/DB_SCHEMA.md`。

---

## 相关链接

- [[docs/INDEX.md|INDEX]] — 文档总索引
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/planning/TASK_PLAN.md|TASK_PLAN]] — 任务计划
