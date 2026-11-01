# Agent 与命令体系

> 本仓库外部参考文档；原文使用 ruoyi-codex 示例，冲突时以根目录 `AGENTS.md`、`docs/COMMIT_RULES.md` 与本项目代码为准。
> 子 agent 协作模式参考 [Superpowers](https://github.com/obra/superpowers) 的 subagent-driven-development 与 dispatching-parallel-agents。

> Codex CLI 的全部子 Agent 和常用指令参考手册
> 适用项目：[[projects/english/_README|ruoyi-codex]]

---

## 全局 Agent 体系设计

### 层级结构

Agent 定义采用**两级优先级**体系：

```
~/.codex/agents/              # 全局 Agent（用户级，所有项目共享）
└── <agent-name>.toml

<project>/.codex/agents/      # 项目 Agent（项目级，覆盖全局同名 agent）
└── <agent-name>.toml
```

- **全局目录** `~/.codex/agents/`：所有项目共享
- **项目目录** `<project>/.codex/agents/`：可选的覆盖，优先级高于全局同名 agent
- **查找顺序**：先找项目目录 → 没找到再找全局目录

### Agent 配置文件格式

每个 Agent 是一个 TOML 配置文件，声明元数据，正文（`developer_instructions`）是系统指令：

```toml
name = "<agent-name>"                # 必填，Agent 唯一标识符
description = "<一句话描述>"           # 必填，供用户/系统选择时识别用途
sandbox_mode = "workspace-write"     # 可选，该 Agent 的沙箱模式（read-only / workspace-write / danger-full-access）
developer_instructions = """
## 完成须知

<任何 Agent 启动时必须要做的事情>

# Agent Title — 中文职责标题

你是一名 <角色定义>，专门负责 <范围描述>。

## 技术栈                    # 可选

## 编码规范                    # 可选

## 注意事项                    # 可选
"""
```

### 必填字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `name` | Agent 唯一 ID，用于多 agent 派发调用 | `backend-developer` |
| `description` | 用户可见的一句话描述 | `Python 后端开发工程师 — 负责 FastAPI 服务...` |
| `sandbox_mode` | 该 Agent 的沙箱模式 | `"read-only"`（审查类）/ `"workspace-write"`（开发类） |

### 模型选择策略

| 模型 | 适用场景 | Agent 示例 |
|------|----------|------------|
| `medium` 推理档位 | 主流开发工作（编码/审查/设计） | `backend-developer`, `code-reviewer`, `frontend-developer` |
| `low` 推理档位 | 低成本高频任务（项目经理/分类） | `project-manager` |
| `high` / `xhigh` 推理档位 | 深度推理/架构决策 | `planner`, `architect` |

### 全局 Agent 列表

| Agent                                  | 角色                          | 沙箱模式          |
| -------------------------------------- | --------------------------- | ------------- |
| **backend-developer**                  | Python 后端开发（FastAPI 服务）     | workspace-write |
| **mini-program-developer**             | 微信小程序前端开发                   | workspace-write |
| **frontend-developer**                 | 管理端前端开发（Vue / Next.js 等按项目技术栈） | workspace-write |
| **dba**                                | DBA — 关系型数据库设计/迁移/优化（MySQL / PostgreSQL 等） | read-only（SQL 建议输出） |
| **project-manager**                    | 项目经理 — 需求拆解/进度跟踪/风控         | read-only     |
| **code-reviewer**                      | 全栈代码审查/质量检测/安全审计            | read-only     |
| **planner**                            | 实现计划制定专家                    | read-only     |
| **architect**                          | 软件架构 — 系统设计/技术决策            | read-only     |
| **build-error-resolver**               | 构建/依赖/类型错误修复                | workspace-write |
| **python-reviewer**                    | Python/FastAPI 代码审查         | read-only     |
| **security-reviewer**                  | 安全漏洞检测/修复                   | workspace-write |
| **doc-updater**                        | 文档和 Codemap 更新              | workspace-write |
| **e2e-runner**                         | Playwright E2E 测试           | workspace-write |
| **refactor-cleaner**                   | 死代码清理/重构                    | workspace-write |
| **rust/go/cpp/kotlin-reviewer**        | 各语言代码审查                     | read-only     |
| **python-build-resolver**              | Python/pip/uv/poetry 构建错误修复 | workspace-write |
| **rust/go/cpp/kotlin-build-resolver**  | 各语言构建错误修复                   | workspace-write |
| **loop-operator**                      | 自主 Agent 循环监控               | workspace-write |
| **chief-of-staff**                     | 沟通分诊（邮件/Slack/LINE）         | workspace-write |
| **harness-optimizer**                  | Agent Harness 配置优化          | workspace-write |
| **docs-lookup**                        | 库/框架文档查询                    | read-only     |
| **tdd-guide**                          | TDD 强制方法论                   | workspace-write |
| **tars**                               | 通用编程助手                      | workspace-write |

### 项目级覆盖规则

```bash
mkdir -p <project>/.codex/agents/
cp ~/.codex/agents/backend-developer.toml <project>/.codex/agents/
# 修改项目级 Agent 内容匹配本项目技术栈
# 项目级文件优先级高于全局同名
```

### 添加新 Agent 步骤

```bash
# 1. 创建全局 Agent 定义文件
mkdir -p ~/.codex/agents/
cat > ~/.codex/agents/<name>.toml << 'EOF'
name = "<name>"
description = "<一句话职责描述>"
sandbox_mode = "workspace-write"
developer_instructions = """
# Agent Title

你是一名 <角色定义>...

## 技术栈

...

## 编码规范

...
"""
EOF

# 2. 更新项目文档的全量 Agent 列表
```

### 设计原则

1. **全局先行**：Agent 定义优先放 `~/.codex/agents/`，所有项目共享
2. **项目按需覆盖**：仅当技术栈不同时创建 `.codex/agents/` 同名文件
3. **职责单一**：每个 Agent 只做一件事
4. **最小权限**：沙箱模式给最小集（审查只读、开发才可写）
5. **模型匹配成本**：medium(开发) / low(PM) / high/xhigh(架构)
6. **审查强制**：开发者 Agent 完成须知中强制调用 code-reviewer

---

## Agent 新 Session 失效排查

### 常见症状

新开 session 后，Agent 调不通、并行派发不生效、子 agent 卡死。

### 排查三步

```bash
# 1️⃣ 验证 multi_agent 开关
codex features list | grep multi_agent

# 2️⃣ 验证 agent 注册文件
ls ~/.codex/agents/ | head -5

# 3️⃣ 验证 Codex 运行时健康
codex doctor
```

| 检查项 | ✅ 正常输出 |
|--------|------------|
| multi_agent | `multi_agent   stable   true` |
| agents 目录 | `backend-developer.toml`, `code-reviewer.toml` 等 |
| doctor | auth / config / runtime 均无错误报告 |

### 根因：`multi_agent` 功能开关丢失

**现象：** 上一 session 能用，新 session 就不行了。子 agent 派发工具不生效。

**常见丢失场景：**

| 场景 | 说明 |
|------|------|
| 代理工具链切换 | API proxy 重写 config.toml 排除了功能开关 |
| 手动编辑出错 | 修改 config.toml 误删了字段 |
| 版本升级回退 | Codex 升级重建配置丢失功能开关 |
| 多设备同步冲突 | 旧版 config 覆盖了新版 |

**修复：**

```bash
codex features enable multi_agent
```

或直接在 `~/.codex/config.toml` 中：

```toml
[features]
multi_agent = true
```

### 根因：项目目录未受信任

**现象：** 全局信任配置被覆盖时所有项目一起受影响。

**修复：** 为项目目录添加信任级别：

```toml
[projects."<project-abs-path>"]
trust_level = "trusted"
```

### 一行确认命令

```bash
MULTI=$(codex features list | grep -c "multi_agent .*true")
AGENTS_COUNT=$(ls ~/.codex/agents/*.toml 2>/dev/null | wc -l)
DOCTOR=$(codex doctor >/dev/null 2>&1 && echo 1 || echo 0)
echo "MULTI_AGENT=$MULTI Agents=$AGENTS_COUNT DoctorOK=$DOCTOR"
echo "STABLE=$([ "$MULTI" -gt 0 ] && [ "$AGENTS_COUNT" -gt 5 ] && [ "$DOCTOR" -gt 0 ] && echo '✅' || echo '❌')"
```

### Agent 载入原理

1. **Codex 启动时**：读 `config.toml`，`multi_agent = true` 启用多 agent 派发能力
2. **启动时**：扫描 `~/.codex/agents/*.toml` 和 `<project>/.codex/agents/*.toml`，注册可用 agent 配置
3. **用到子 agent 时**：按 name 匹配对应 toml 文件，注入 `developer_instructions` 并套用 `sandbox_mode`
4. **项目级覆盖**：项目目录有同名文件则用它，否则回退全局

### config.toml 配置速查

```toml
[features]
multi_agent = true

[projects."<project-abs-path>"]
trust_level = "trusted"
```

---

## 常用指令体系

Codex 不使用 `/` 前缀的 slash 命令；以下指令通过两种方式使用：**对话提示词**（在 Codex 会话中直接发出）或 **CLI 单次执行**（`codex exec "<指令>"`）。

### 开发工作流

| 指令              | 功能                             | 用法        |
| --------------- | ------------------------------ | --------- |
| `制定实施计划`         | 复述需求 → 评估风险 → 逐步计划，等确认后才写代码    | 复杂功能前     |
| `按 TDD 实现`       | 强制 TDD：RED → GREEN → 重构，以行为覆盖为准 | 新功能/Bug修复 |
| `审查未提交的变更`        | 全面安全+质量审查未提交变更（内置：`codex review --uncommitted`） | 代码写完后     |
| `全面验证代码库状态`       | 运行全面验证                         | 提交前       |
| `对 <范围> 运行质量流水线`  | 对文件或项目范围运行质量检查                 | 发布前       |
| `记录 Bug 到清单`       | 将发现的问题自动记录到 Bug 清单             | 发现Bug时    |
| `创建工作流检查点`         | 创建检查点（create/verify/list）      | 阶段完成时     |

### 语言专精

| 指令               | 语言     | 功能                        |
| ---------------- | ------ | ------------------------- |
| `修复 Rust 构建`      | Rust   | 修复构建/借用检查/依赖              |
| `审查 Rust 代码`      | Rust   | 所有权/生命周期/unsafe 审查        |
| `测试 Rust 代码`      | Rust   | TDD + cargo-llvm-cov 行为覆盖 |
| `修复 Go 构建`        | Go     | 修复构建/vet/linter           |
| `审查 Go 代码`        | Go     | 惯用模式/并发安全/错误处理            |
| `测试 Go 代码`        | Go     | TDD + go test -cover 行为覆盖 |
| `修复 Kotlin 构建`    | Kotlin | 修复构建/编译/依赖                |
| `审查 Kotlin 代码`    | Kotlin | 惯用模式/空安全/协程               |
| `测试 Kotlin 代码`    | Kotlin | TDD + Kover 行为覆盖       |
| `修复 C++ 构建`       | C++    | 修复构建/CMake/链接             |
| `审查 C++ 代码`       | C++    | 内存安全/现代C++/并发             |
| `测试 C++ 代码`       | C++    | TDD + gcov/lcov           |
| `审查 Python 代码`     | Python | PEP8/类型提示/安全/异步正确性        |
| `修复 Python 构建`     | pip/uv/poetry | 修复依赖/虚拟环境/类型检查      |
| `测试 Python 代码`     | Python | TDD + pytest-cov 行为覆盖  |

### 多模型协作

| 指令 | 功能 |
|------|------|
| `多模型协作规划` | 上下文检索 + 双模型分析 |
| `多模型协作开发` | 前端→Gemini，后端→Codex |
| `后端专注流程` | 后端专注（研究→构思→计划→执行→优化→审查）|
| `前端专注流程` | 前端专注流程 |
| `多模型并行执行` | 并行执行 |
| `按任务复杂度推荐模型层级` | 模型路由 |
| `编排执行策略` | 顺序/tmux/worktree 编排指导 |

### 并行与自主

| 指令 | 功能 |
|------|------|
| `并行派发 Agent` | 编排并行子 Agent |
| `启动自主循环模式` | 自主循环 |
| `生成服务管理命令` | 自动分析项目生成服务管理命令（PM2/systemd） |
| `回答快速问题不中断当前任务` | 快速旁路问答 |

### 构建与修复

| 指令 | 功能 |
|------|------|
| `递增式修复构建和类型错误` | 构建与类型修复 |
| `安全识别和移除死代码` | 死代码清理 |
| `运行仓库 Harness 审计` | Harness 审计 |

### 文档与知识

| 指令 | 功能 |
|------|------|
| `查询最新框架文档` | 通过 Context7 查询最新文档 |
| `生成架构 Codemap` | 生成 token 精简的架构文档 |
| `根据源码同步文档` | 文档同步 |
| `分析 Git 历史生成 SKILL.md` | 技能沉淀 |
| `分析并生成进化结构` | 本能/模式进化 |
| `提取当前会话模式为 skill` | 会话模式提取 |
| `优化草稿提示词` | 提示词优化 |
| `管理评测驱动开发工作流` | 评测管理 |
| `分析测试覆盖情况` | 覆盖率分析（本仓库不设统一百分比门禁） |

### 会话管理

| 指令 | 功能 |
|------|------|
| `保存会话状态` | 保存会话（Codex 自动持久化会话，可用 `codex resume` 恢复） |
| `恢复最近会话` | `codex resume --last` |
| `浏览历史会话` | `codex agents` |
| `列出已知项目` | 列出项目与统计 |
| `导出/导入配置` | 配置迁移 |

### E2E 与安全

| 指令 | 功能 |
|------|------|
| `生成并运行 Playwright E2E 测试` | E2E 测试 |
| `检测安全漏洞` | 安全审查 |
| `运行安全扫描` | 安全扫描 |

---

## Agent 调用方式

### 调用前判断

派发子 agent 前先回答两个问题，避免不必要协调（Superpowers: dispatching-parallel-agents）：

1. **任务是否独立** — 多个任务之间无共享状态或顺序依赖才可并行派发；有依赖的按顺序串行
2. **是否有现成 Agent** — 本项目已有分工（见上表）；不要为通用操作创建新 Agent，优先复用

### 任务委派上下文

子 agent 不继承主会话上下文。派发时必须显式提供（Superpowers: subagent-driven-development）：

- **目标**：一段话说明要做什么、为什么
- **涉及文件**：精确路径 + 行号范围（适用时）
- **验证方法**：完成后应运行什么命令、期望什么输出
- **边界**：明确"不做"的内容，防止子 agent 扩大范围

子 agent 汇报"成功"时，主会话独立验证（检查 diff、运行测试），不信汇报。

### 方式一：多 Agent 工具（对话中派发）

Codex 内置多 Agent 派发工具（`spawn_agent` / `wait_agent` / `send_input` / `close_agent`）。在主会话中要求 Codex 派发子 agent，或由工作流规则自动触发：

```
派发 backend-developer 子 agent：
任务：在 service 模块新增 xxx 接口...
要求：后台运行，完成后汇报。

派发 code-reviewer 子 agent：
任务：审查 service 模块的代码变更...
```

主会话负责等待结果并整合；子 agent 不应再互相派发嵌套任务。

### 方式二：codex exec CLI 命令

```bash
codex exec "任务指令..."                                    # 当前目录非交互执行
codex exec -C /path/to/project "任务指令..."                # 指定项目目录
codex exec -s workspace-write "任务指令..."                 # 在 workspace-write 沙箱内执行（不绕过审批）
codex exec -s read-only "只读分析任务..."                     # 只读沙箱执行
codex exec --json "任务指令..."                             # JSONL 事件流输出（供编排脚本解析）
codex review --uncommitted                                # 审查未提交变更（内置代码审查）
codex agents                                              # 查看后台/历史 agent 会话
```

### Workflow Subagent Dispatch

> 解决子 agent 后台权限弹窗无人确认卡死的问题

```
多 Agent 工具 → 子 agent → 写文件 → 弹窗（无人确认） → ❌ 卡死
codex exec -s workspace-write → 子进程 → 写文件 → ⚠️ 受沙箱/审批策略约束
```

```bash
# 顺序编排
codex exec -s workspace-write "阶段1：生成 FastAPI 路由骨架..."
codex exec -s workspace-write "阶段2：为阶段1产出编写 pytest 测试..."
codex exec -s workspace-write "阶段3：审查前两阶段的变更..."
```

**并行（shell 层面）：**

```bash
codex exec -s workspace-write "任务1：..." > /tmp/task-1.log &
codex exec -s workspace-write "任务2：..." > /tmp/task-2.log &
wait
```

| 测试方式 | 子 agent 写文件 |
|----------|----------------|
| 多 Agent 工具（默认沙箱） | ⚠️ 受沙箱/审批策略限制 |
| **codex exec -s workspace-write** | ⚠️ **受控沙箱内写入；仍受审批策略约束** |

### 方式三：对话内直接指令

```
按 planner agent 的思路制定计划
以 code-reviewer 的标准审查这次提交
以 backend-developer 的角色完成接口实现
```

### 调用常用指令

```
制定实施计划
按 TDD 实现
审查未提交的变更
记录 Bug 模块: mall-mini-program | 分类页点击报错
```

---

## 参考

- [[wiki/concepts/development/development-workflow|开发流程]]
- [[wiki/concepts/development/coding-style|编码规范]]
- [[projects/english/_README|ruoyi-codex 项目架构]]
