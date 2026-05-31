# 项目规则 (长期稳定)

> 2240AI — 考研智能刷题小程序（数学二 / 408 / 英语）

---

## 明确不做什么

- ❌ OCR 识别手写题 / 复杂 OCR pipeline
- ❌ LangChain / Agent / 多模型编排
- ❌ 知识图谱 / 复杂推荐系统
- ❌ 微服务 / Kubernetes
- ❌ 社区 / 论坛 / 排行榜
- ❌ 实时协同 / WebSocket
- ❌ 账号密码登录 / 邮箱注册 / 密码重置
- ❌ 多方式登录体系（仅微信 openid）
- ❌ 在线公式编辑器（LaTeX 手动输入）

---

## 核心约束

1. **无传统账号系统** — 微信 openid 是 App 用户唯一标识；Admin 后台如需权限体系，必须限定在后台管理域内，不改变 App 登录模型
2. **无纯 AI 自动入库** — 所有导入必须经过 `question_imports` + 人工确认
3. **Excel 导题优先** — 能走 Excel 就不要写解析代码
4. **SM-2 字段在 WrongQuestion 表上** — 不拆分独立调度表
5. **后端不管理 App 用户密码** — App 身份验证依赖微信
6. **AI 是辅助** — 不影响核心刷题流程

> 2026-05-31 更新原因：对齐 `CLAUDE.md` 与已存在 Admin 文档分区，明确“不做权限体系”仅指 App 多租户/社区类权限，不否定 Admin 后台 RBAC 文档。

## 导入管线架构原则

1. **OCR 与 AI 解耦** — OCR 只负责文本提取，AI 只负责修复/补全，不互相依赖
2. **Prompt 禁止硬编码** — 所有 Prompt 统一放入 `/prompts`，代码中不内嵌 prompt
3. **AI 仅用于修复/补全/结构化增强** — 禁止将所有内容直接丢给 LLM，优先规则解析
4. **优先规则解析** — 规则能解决的问题不用 AI，AI 仅处理规则无法覆盖的边界情况
5. **核心逻辑必须支持单元测试** — AI 调用可 mock，规则逻辑必须可测
6. **分阶段开发，每阶段可运行/可测试/可回退** — 不一次性重构整个系统

---

## 开发规范

### Python

- Python 3.11+，类型注解全覆盖
- 使用 `ruff` lint + format
- 不写 service 抽象类/接口，不用 `__init__.py` 做重导出
- 一个文件 ≤ 300 行，一个函数 ≤ 50 行

### API

- Base URL: `/api/v1`
- 统一响应：`{code: 0, message: "success", data: {}}`
- 分页：`{items, total, page, pageSize, totalPages}`
- 路由只做参数校验，业务下沉到 services/

### 数据库

- 不提前建索引（等慢查询再建）
- 不写 migration 回滚脚本
- 不超过 3 表 join

### AI

- 不引入 langchain / llamaindex
- 直接 httpx 调 DeepSeek API
- 失败降级优先于重试
- Prompt 放 `prompts.py`，不引入管理平台

### Git 提交

```
<type>: <简短描述>
```

type: `feat` / `fix` / `refactor` / `perf` / `docs` / `chore`
