---
tags:
  - concept
  - development
  - git
  - 工作流
title: Git 工作流 ruoyi-claude
type: concept
---

> 本仓库外部参考文档；原文使用 ruoyi-codex 示例，冲突时以根目录 `AGENTS.md`、`docs/COMMIT_RULES.md` 与本项目代码为准。
> 本仓库实际提交规范（含 Conventional Commits type、显式路径暂存和禁止 AI attribution）以 `docs/COMMIT_RULES.md` 为准。

# Git 工作流 — ruoyi-claude 项目

> 通用 Git 提交与 PR 规范

---

## 提交消息格式

```
<类型>: <描述>

<可选正文>
```

### 类型

| 类型 | 用途 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构 |
| `docs` | 文档 |
| `style` | 不影响逻辑的格式/样式调整 |
| `test` | 测试 |
| `perf` | 性能 |
| `build` | 构建/依赖/打包 |
| `ci` | CI/CD |
| `chore` | 维护性工作 |
| `revert` | 回滚已有提交 |

### 规则
- 第一行不超过 72 字符
- 正文描述"为什么改"而不只是"改了什么"
- 引用 issue/任务编号

---

## 拉取请求工作流

1. 分析完整提交历史（不仅仅是最近提交）
2. 使用 `git diff [base-branch]...HEAD` 查看所有更改
3. 起草全面的 PR 总结
4. 包含测试计划和 TODO
5. 如果是新分支，使用 `-u` 标志推送

---

## 参考

- [[wiki/concepts/development/development-workflow|开发流程]]
- [[wiki/concepts/development/coding-style|编码规范]]
