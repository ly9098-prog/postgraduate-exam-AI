# 项目路线图

> 2026-09-23 重写。旧版仍写着「MVP 完成 + 导入管线开发中」，和现行代码不符。
> 能力细节以仓库根目录 `README.md`、`docs/project/CHANGELOG.md` 和代码为准。本文件只说明现在做到哪，以及哪些旧文档不能再当施工单。

---

## 当前阶段

项目已上线运行，当前处于稳定性治理和全栈兼容重构阶段，不是 MVP 功能开发阶段。

功能主线已经落地。`prompts/tasks/current_task.md` 和 `prompts/tasks/next_task.md` 都没有未完成步骤，也没有排期中的新模块。

不要从本文件或 `prompts/tasks/backlog/` 里再开一套功能。下一步如果要做，是用现有 408 闭环自测，并用管理端导入补题，而不是加子系统。

---

## 相对旧路线图已经补上的部分

旧版只覆盖刷题、错题、SM-2、Excel/PDF/Word 导入和 Docker。其后已进代码、并记在变更日志里的包括：

- **管理端**：Next.js 后台，`/api/admin/v1`，RBAC、审计、导入审核、AI 模型配置。
- **408 考试**：试卷 `public_id`、40 道选择题结构、作答草稿、超时、放弃、交卷、结果、历史、软删除。管理端可组卷、发布、归档、恢复。
- **学习闭环**：知识地图、考纲版本、题库覆盖率、学习计划、错因诊断、考后 AI 教师入口。错题分析用服务端已核对的作答事实约束模型。
- **公式**：公式库、公式卡、函数图。生产用命名卷 `formulas_data` 保存上传图。
- **番茄钟**：统计只计入已结束的 `completed` / `interrupted`。
- **导出**：错题与学习数据导出。
- **题目类型**：`multi_blank_choice`（每空单选）和 `multi_blank_multiple_choice`（每空多选）。
- **向量**：embedding 按 `(question_id, model_id)` 与 `content_hash` 增量写入。
- **生产**：当前入口是 `xzshub.top`（`/opt/22408-ai`）。细节见 `docs/project/DEPLOY_PLAN.md`。

学员端页面以 `miniprogram/app.json` 为准：主包只有登录和首页；学习、考试、知识、公式、番茄钟、导出都在分包里。

---

## 科目边界

408 是唯一有 canonical 科目树和选择题考试域的范围：数据结构、计算机组成原理、操作系统、计算机网络。

高等数学、线性代数、英语、政治可以出现在学员端科目选择里（`backend/app/core/subject_scope.py` 的 `EXTRA_STUDY_SUBJECT_CODES`）。它们不是第二套考试产品，不要按 408 的试卷和知识地图范围去扩。

社区、排行榜、账号密码登录、多方式登录、实时协同、手写 OCR、在线公式编辑器仍然不做，见 `docs/project/PROJECT_RULES.md`。

---

## 不要当成待办

| 位置 | 实际含义 |
|------|----------|
| `prompts/tasks/backlog/` | 历史任务书。文件开头已标明不要施工 |
| `prompts/tasks/current_task.md`、`next_task.md` | 只有完成记录 |
| `docs/planning/TASK_PLAN.md` | 公式图片化的旧阶段设计稿，不是当前排期 |
| `docs/achieve/` | 阶段归档。仓库里没有 `/prompt.md` |
| `docs/project/BUGS.md` 里已标修复的 OCR 案例 | 回归记录，不是新 bug 列表 |

历史审计报告保持原样，不改写成现在的承诺。

---

## 仓库里没有确认的事

- 微信小程序是否已经提交审核。旧路线图把它列在「规划中」，仓库没有提审结果。
- OCR 扫描版 PDF 的全量准确率验收。管线已经实现，生产部署记录里有导入 / OCR / 刷题链路自检；这不等于全量 E2E。`docs/achieve/README.md` 仍把 Phase 8 标为待 E2E 验证。
