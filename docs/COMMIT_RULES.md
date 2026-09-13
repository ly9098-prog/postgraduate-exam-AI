# Git 提交规范

> 本规范适用于本仓库所有人工开发者、自动化工具与 Coding Agent。  
> 目标是保持提交历史清晰、可追踪，并避免自动化工具或 AI 被错误记录为 Git 作者/共同作者。

## 1. 基本原则

1. 每个提交应只包含一个明确目的，避免把无关修改混入同一 commit。
2. 提交前必须确认代码、测试、格式化与静态检查结果符合项目要求。
3. 不提交临时文件、调试输出、本地配置、密钥、Token、凭据或其他敏感信息。
4. 不为“整理历史”而修改已经共享的提交，除非仓库维护者明确批准历史重写。
5. 默认分支上的历史应保持稳定；涉及 `rebase`、`filter-repo`、`force push` 等操作时必须谨慎。

---

## 2. Commit Message 格式

推荐使用 Conventional Commits 风格：

```text
<type>(<scope>): <summary>
```

`scope` 可省略：

```text
<type>: <summary>
```

### 允许的 type

| Type | 用途 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档修改 |
| `style` | 不影响逻辑的格式、样式调整 |
| `refactor` | 不新增功能、不修复 Bug 的代码重构 |
| `perf` | 性能优化 |
| `test` | 测试新增或调整 |
| `build` | 构建系统、依赖、打包相关 |
| `ci` | CI/CD 配置与流程 |
| `chore` | 维护性工作 |
| `revert` | 回滚已有提交 |

### 示例

```text
feat(auth): add password reset flow
fix(api): handle expired session token
docs: update deployment guide
test(search): add ranking regression coverage
chore: refresh test path references
```

---

## 3. Summary 要求

提交标题应：

- 使用简洁、明确的祈使语气；
- 描述“这个提交做了什么”；
- 避免无意义描述，例如 `update files`、`fix stuff`、`changes`；
- 不在标题末尾添加句号；
- 建议控制在 72 个字符以内；
- 与实际变更保持一致。

不推荐：

```text
fix things
update
misc changes
work in progress
```

推荐：

```text
fix(session): align test paths after directory reorganization
refactor(profile): split validation from persistence logic
docs(api): document refresh token behavior
```

---

## 4. AI / Coding Agent 提交规则

AI 或 Coding Agent 可以协助：

- 编写代码；
- 修改文件；
- 运行测试；
- 生成 commit message；
- 执行经授权的 Git 操作。

但 AI / Coding Agent **不得自动把自己添加为 Git 作者、共同作者或贡献者**。

### 严禁自动添加以下 trailer

```text
Co-Authored-By: Claude <...>
Co-authored-by: Claude <...>
Co-Authored-By: Claude Opus <...>
Co-Authored-By: ... <...@anthropic.com>
```

同样，不应自动添加其他 AI 工具、模型或 Agent 的共同作者信息。

除非仓库维护者在当前任务中明确要求，否则不得添加任何 AI 相关：

```text
Co-Authored-By:
Signed-off-by:
Generated-by:
Assisted-by:
```

### 明确规则

> AI 可以协助产生修改，但 Git author / committer / co-author attribution 必须遵循仓库维护者的身份与授权规则。  
> AI 工具名称、模型名称、供应商名称不应因自动化默认行为进入 commit attribution。

---

## 5. Author 与 Committer

提交前应确认：

```bash
git config user.name
git config user.email
```

如需检查最近提交：

```bash
git log -1 --format=fuller
```

不得擅自修改其他开发者的 author identity。

不得为了“美化历史”伪造作者姓名、邮箱或时间。

---

## 6. 提交前检查

提交前至少执行：

```bash
git status
git diff --check
git diff --cached
```

根据项目实际情况，再运行对应测试、lint、类型检查或构建命令。

提交后建议检查：

```bash
git show --stat --oneline HEAD
git log -1 --format=full
```

确认：

- 提交内容符合预期；
- 没有误提交文件；
- commit message 正确；
- 没有意外的 `Co-Authored-By` 或其他 trailer。

---

## 7. AI Attribution 检查

提交后可以运行：

```bash
git log -1 --format=%B
```

仓库维护者可定期扫描：

```bash
git log --format='%H%n%B%n---' | grep -iE 'co-authored-by:.*(claude|anthropic\.com)'
```

正常情况下，该命令不应在新提交中产生匹配结果。

也可以检查整个默认分支：

```bash
git log main --format='%H%n%B%n---' | grep -iE 'co-authored-by:.*(claude|anthropic\.com)'
```

---

## 8. 禁止直接提交的内容

以下内容原则上不得进入仓库：

- `.env` 或本地环境变量文件；
- API Key、Access Token、Cookie、私钥；
- 数据库密码；
- 云服务凭据；
- 用户隐私数据；
- 大型临时文件；
- IDE 临时缓存；
- 本地日志；
- 调试 dump；
- 无必要的生成产物。

如不确定，应先检查 `.gitignore`。

---

## 9. 默认分支与历史重写

对 `main` 或其他共享分支：

- 不随意执行 `git push --force`；
- 如确需历史重写，优先使用：

```bash
git push --force-with-lease
```

- 历史重写前必须创建可恢复的备份引用；
- 重写前后应验证最终 tree 内容一致；
- 不得在未经授权的情况下修改 branch protection、ruleset 或仓库权限；
- 不得擅自重写 tags 或其他开发者分支。

---

## 10. Coding Agent 执行要求

Coding Agent 在提交代码时必须遵守：

1. 提交前检查 `git status`。
2. 只提交当前任务相关文件。
3. 不自动添加 AI co-author。
4. 不自动修改 Git author identity。
5. 不执行未经授权的 force push。
6. 不关闭 branch protection / ruleset。
7. 不提交 secrets。
8. 提交完成后检查完整 commit message。
9. 如果检测到 AI attribution trailer，应在 push 前移除。
10. 遇到历史重写、删除分支、删除 tag 等高风险操作时，应先获得明确授权。

---

## 11. 推荐的 Agent Prompt 约束

可在 Claude Code、Codex、Copilot 或其他 Coding Agent 的项目级规则中加入：

```text
When creating Git commits for this repository:

- Follow the repository commit convention.
- Do not add yourself, any AI model, AI vendor, or coding agent as an author or co-author.
- Never add Co-Authored-By trailers for Claude, Anthropic, OpenAI, Codex, Copilot, or other AI tools unless explicitly requested by the repository maintainer in the current task.
- Preserve the configured human Git author identity.
- Inspect the complete commit message before committing.
- Do not use git push --force. If history rewriting is explicitly authorized, use --force-with-lease.
- Do not modify branch protection, repository rulesets, tags, or unrelated branches without explicit authorization.
```

---

## 12. 最终检查清单

每次提交前确认：

- [ ] 修改范围只包含当前任务；
- [ ] 测试 / lint / build 已按需要执行；
- [ ] `git diff --check` 无异常；
- [ ] commit type 与 summary 正确；
- [ ] author identity 正确；
- [ ] 没有 secrets；
- [ ] 没有意外生成文件；
- [ ] 没有 Claude / Anthropic / 其他 AI 的 `Co-Authored-By`；
- [ ] 没有未经授权的其他 trailers；
- [ ] 不需要历史重写或 force push。

---

## 13. 例外

如确有业务、法律、审计或协作流程要求记录共同作者，应由仓库维护者明确指定具体 identity 与 trailer。

任何例外都应是**显式授权**，不得由工具默认行为自动产生。
