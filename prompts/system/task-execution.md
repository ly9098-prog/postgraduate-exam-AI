# 任务执行规范

> 状态：早期导入管线 Prompt，不是当前最高规则。以根目录 `AGENTS.md`、`docs/project/PROJECT_RULES.md` 和代码为准。下文里的模型、JWT 天数和目录树可能已过时。

> 如何拆分任务、编码、测试、提交。

---

## 任务拆解

1. 先读 `prompts/README.md`。`tasks/current_task.md` 只表示有没有被明确打开的一次性任务，没有就不要发明任务
2. 复杂任务拆分为 ≤5 步的可执行子任务
3. 每一步完成后运行测试确认
4. 每步提交一次（`feat:` / `fix:` / `refactor:` / `docs:`）

## 编码规范

- Python 3.11+，类型注解全覆盖
- 一个文件 ≤ 300 行，一个函数 ≤ 50 行
- 路由只做参数校验，业务下沉到 services/
- 不写 interface/abstract class
- 尽量少用 `@property`
- 不用 `__init__.py` 做重导出
- 遇到重复：三个重复抽函数，六个重复抽类

## 数据库规范

- 不提前建索引
- 不写 migration 回滚脚本
- 不超过 3 表 join
- CRUD 直接在 service 中写 SQLAlchemy，不用 repository 层

## AI 模块规范

- 不引入 langchain / llamaindex
- 直接 httpx 调 DeepSeek API
- Temperature = 0.3
- 失败降级优先于重试
- AI 结果必须经过 question_imports

## 测试规范

- 只写核心 service 单测
- 不写 controller 集成测试
- 不追求覆盖率，追求核心功能稳定
- 每个阶段结束运行该阶段所有单测

## Git 提交

```
<type>: <简短描述>
```

type: `feat` / `fix` / `refactor` / `perf` / `docs` / `chore`

示例：
```
feat: 新增 AI 错题分析接口
fix: 修复复习计划日期重复问题
docs: 更新 API_SPEC.md
```
