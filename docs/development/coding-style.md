---
tags:
  - concept
  - development
  - ruoyi-codex
  - 编码规范
title: 编码规范 ruoyi-codex
type: concept
---

> 本仓库外部参考文档；原文使用 ruoyi-codex 示例，冲突时以根目录 `AGENTS.md`、`docs/COMMIT_RULES.md` 与本项目代码为准。

# 编码规范 — ruoyi-codex 项目

> 基于通用编码规范的 ruoyi-codex 项目适用准则
> 原始参考：[[wiki/concepts/development/development-workflow|开发流程]]

---

## 项目阶段原则（2026-11-02 起）

- 项目已上线：设计以长期稳定性、可维护性、可扩展性、可靠性和生产安全优先；“能运行”不是交付标准。
- 高内聚低耦合：模块职责单一，依赖方向清晰；不为形式添加抽象层，也不做无业务价值的重构。
- 新增或拆出的业务模块遵循 300 行 / 50 行预算；既有超限模块按有限重构账本处置，不为行数盲目拆分。
- 技术债务显式登记并按批次治理，不用临时脚本或旁路逻辑掩盖缺陷。

## 核心原则：不可变性

**默认返回新对象，避免无意的共享可变状态。** 数据库 ORM 实体可在明确事务所有权内按现有模式修改；跨模块传递的数据优先使用不可变或复制后更新。

```python
# ❌ 错误：原处修改
modify(original, field, value)  # original 被改变

# ✅ 正确：返回新副本（dataclasses.replace / model_copy / dict 浅拷贝）
updated = replace(original, field=value)  # 返回新对象，original 不变
```

**理由**：减少隐藏副作用，简化调试并支持安全并发；但不应为了形式上的不可变而无条件复制大对象或破坏 ORM 生命周期。

---

## 文件组织

| 原则              | 说明          |
| --------------- | ----------- |
| **多小文件 > 少大文件** | 高内聚、低耦合     |
| **300 行 / 50 行** | 本仓库新增或拆出业务模块的文件/函数预算 |
| **既有超限模块**     | 按有限重构账本处置，不因行数自动拆分 |
| **按功能/领域组织**    | 不按类型组织      |
| **提取工具模块**      | 大幅模块中提取公共逻辑 |

---

## 错误处理

- 每层显式处理错误
- 用户界面 → 友好错误提示
- 服务端 → 详细日志上下文（`structlog` / 标准 `logging`）
- 绝不静默吞掉错误（禁止裸 `except: pass`）

---

## 输入验证

- 所有系统边界验证用户输入
- 使用基于 schema 的验证：**Pydantic v2**（FastAPI 原生集成）
- 快速失败 + 清晰错误消息
- 绝不信任外部数据（API 响应、用户输入、文件内容）

---

## 质量检查清单

- [ ] 代码可读且命名良好
- [ ] 函数 < 50 行
- [ ] 新增模块 ≤ 300 行；既有超限模块已评估并按账本处置
- [ ] 嵌套不超过 4 层
- [ ] 错误处理完整
- [ ] 无硬编码值（使用常量或 Pydantic `Settings` 配置）
- [ ] 无突变（使用不可变模式）
- [ ] 模块职责与依赖方向清晰，无新增跨层反向依赖
- [ ] 新增依赖已评估安全、维护成本、兼容性与回退方式

---

## 参考

- [[wiki/concepts/development/development-workflow|开发流程]]
- [[projects/english/_README|ruoyi-codex 项目架构]]

---

## 相关链接

- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/COMMIT_RULES.md|COMMIT_RULES]] — 提交规范
- [[docs/development/development-workflow.md|development-workflow]] — 开发工作流
- [[docs/development/git-workflow.md|git-workflow]] — Git 工作流
- [[docs/development/agents-and-commands.md|agents-and-commands]] — Agent 与命令
