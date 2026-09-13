你正在 Claude Code 中工作，并且已经连接 GitHub MCP。

目标：
清理 GitHub 仓库 OWNER/REPO 的默认分支历史，从 commit messages 中删除 Claude / Anthropic 的 Co-Authored-By trailer，使 Claude 不再因为这些 trailer 被识别为该仓库的共同贡献者。

这是一次 Git 历史重写操作。必须极其谨慎。

仓库：
OWNER/REPO

请优先使用 GitHub MCP 获取和验证 GitHub 侧的信息；对于必须进行本地 Git 历史重写的步骤，使用 Claude Code 的 Bash/git。

不要修改仓库中的任何代码或文件内容。

========================================
安全约束
========================================

必须遵守：

1. 只能删除属于 Claude / Anthropic 的 Co-Authored-By trailer。

典型目标包括：

Co-Authored-By: Claude ...
Co-authored-by: Claude ...
Co-Authored-By: ... <...@anthropic.com>
Co-authored-by: ... <noreply@anthropic.com>

判断规则：

- trailer key `Co-Authored-By` 大小写不敏感；
- 姓名明确包含 Claude，或者；
- email domain 明确属于 anthropic.com。

如果不能明确确认是 Claude / Anthropic，不要删除。

2. 不允许删除其他人的：

Co-Authored-By
Signed-off-by
Reviewed-by
Tested-by
Acked-by
或其他 Git trailers。

3. 不修改：

- repository file contents
- file modes
- directories
- commit author name
- commit author email
- commit committer identity，除非 Git 重写机制不可避免；如果不可避免，先报告
- author date
- 原 commit message 正文
- tags
- 其他 branches

4. 只操作默认分支。

5. 不得：

- 删除仓库
- 删除 branch protection
- 删除 ruleset
- 修改仓库权限
- 修改 GitHub Actions secrets
- 重写 tags
- 重写其他 branches
- 使用 `git push --force`

如需要更新远端历史，只允许：

git push --force-with-lease

6. 在任何 destructive 操作之前必须建立恢复点。

7. 如果任何验证失败，立即停止，不允许 push。

========================================
阶段 1：通过 GitHub MCP 检查仓库
========================================

首先使用 GitHub MCP：

1. 确认 OWNER/REPO 存在并且当前凭据有权限访问。
2. 获取默认分支名称。
3. 获取默认分支当前 HEAD SHA。
4. 检查默认分支是否存在：
   - branch protection
   - repository ruleset
   - 禁止 force push 的规则
5. 检查仓库是否有 open PR 依赖当前默认分支历史。
6. 查询 tags 和其他 branches 是否引用默认分支历史中的 commits。

此阶段不要做任何修改。

输出简洁的 preflight 报告。

如果 GitHub MCP 表明当前身份没有 push 权限，立即停止。

如果规则明确禁止 force push，不要修改规则，停止并告诉我是哪条规则阻止操作。

========================================
阶段 2：取得完整 Git 仓库
========================================

使用本地 git 创建或使用一个干净的 repository clone。

确保不是 shallow clone。

执行等价于：

git fetch --all --tags --prune

确认：

git status

必须 clean。

记录：

OLD_HEAD=<默认分支原始 HEAD>
OLD_TREE=$(git rev-parse "$OLD_HEAD^{tree}")

保存 OLD_HEAD 和 OLD_TREE。

========================================
阶段 3：建立恢复分支
========================================

在执行历史重写之前创建：

backup/pre-remove-claude-coauthors-YYYYMMDD-HHMMSS

该 branch 必须准确指向 OLD_HEAD。

先在本地建立，然后 push 到 GitHub。

优先使用正常 git push 创建该 backup ref。

然后使用 GitHub MCP 再次确认：

backup branch 存在
backup branch HEAD == OLD_HEAD

只有验证成功后才能继续。

绝对不要在整个任务结束时自动删除这个 backup branch。

========================================
阶段 4：扫描历史
========================================

扫描默认分支完整 reachable history。

识别所有 commit message 中的 Co-Authored-By trailers。

注意：

- key 大小写不敏感
- 必须按 trailer 行判断，不要简单删除正文中出现的 Claude 字样
- 不要修改 commit message 正文中正常提到 Claude/Anthropic 的句子
- 只针对 Co-Authored-By trailer

生成报告：

1. 默认分支 commit 总数
2. 含任何 Co-Authored-By 的 commit 数量
3. 明确属于 Claude / Anthropic 的 commit 数量
4. 不同 Claude / Anthropic identity：
   - name
   - email
5. 每一个预计修改的：
   - SHA
   - subject
   - 将删除的 trailer 原文
6. 是否发现无法明确分类的 trailer

如果发现模糊 identity，将其保留。

========================================
阶段 5：重写历史
========================================

优先使用 git-filter-repo。

如果系统没有 git-filter-repo，可以安装到当前用户环境，但不要对项目依赖文件进行任何修改。

不要使用几十次手工 interactive rebase。

message callback / rewrite logic 必须实现：

对于每一个 commit message：

- 逐行处理；
- 找到大小写不敏感的 Co-Authored-By trailer；
- 如果该 trailer 对应：
  - name 包含 Claude（大小写不敏感），或
  - email domain 为 anthropic.com
  才删除这一整行；
- 其他行原样保留；
- 其他人的 Co-Authored-By 原样保留；
- 其他 Git trailers 原样保留；
- 不重新排版 commit message；
- 仅清理因为删除目标 trailer 导致的尾部多余空白行。

不要通过 regex 粗暴删除所有包含 "Claude" 或 "Anthropic" 的 commit message 内容。

========================================
阶段 6：本地验证
========================================

历史重写完成后，不要立即 push。

记录：

NEW_HEAD=$(git rev-parse <default-branch>)
NEW_TREE=$(git rev-parse "$NEW_HEAD^{tree}")

必须验证：

OLD_TREE == NEW_TREE

这是硬性要求。

如果不同：
立即停止。
不要 push。

然后进一步验证：

1. 对比旧 HEAD 和新 HEAD 的最终 repository tree。
2. 确认没有文件增加、删除或修改。
3. 确认 file modes 没变化。
4. 确认工作区 clean。
5. 扫描新历史，确认不存在属于 Claude / Anthropic 的 Co-Authored-By trailer。
6. 确认原本属于其他人的 Co-Authored-By trailer 仍然存在。
7. 确认 Signed-off-by、Reviewed-by 等其他 trailer 没被误删。
8. 对预计被修改的 commits 做 old/new message 抽样或完整验证。

还要比较 rewrite 前后的 commit metadata。

对于被修改 commit，尽可能确认：

- author name 相同
- author email 相同
- author timestamp 相同
- tree 相同
- parent topology 对应保持一致
- 唯一预期变化是 commit message、commit SHA，以及由祖先 SHA 改变导致的后续 SHA

如果 committer metadata 因历史重写发生变化，明确报告。

========================================
阶段 7：检查远端是否变化
========================================

在 push 前：

git fetch origin

再次确认 GitHub 当前默认分支 HEAD 仍等于 OLD_HEAD。

也通过 GitHub MCP 获取一次远端默认分支 HEAD。

如果其他人在操作期间更新了默认分支：

立即停止。

不要覆盖对方的新 commits。

不要尝试自动 rebase 或强制继续。

========================================
阶段 8：更新默认分支
========================================

只有前面所有验证都通过后才允许 push。

使用：

git push --force-with-lease origin <default-branch>

绝对不要改成：

git push --force

如果 GitHub 拒绝 push：

- 不要关闭 branch protection
- 不要修改 ruleset
- 不要尝试绕过安全策略

直接报告错误。

========================================
阶段 9：GitHub MCP 最终验证
========================================

push 成功后，使用 GitHub MCP：

1. 获取默认分支新的 HEAD。
2. 确认 HEAD == NEW_HEAD。
3. 确认 backup branch 仍存在。
4. 确认 backup branch HEAD == OLD_HEAD。
5. 检查是否有 branches/tags 仍指向旧历史。
6. 检查是否有 PR 因此次 rewrite 受到影响。

然后本地重新：

git fetch origin

验证：

origin/<default-branch> == NEW_HEAD

并再次确认最终 tree 与 OLD_TREE 相同。

========================================
最终报告
========================================

完成后输出：

Repository:
Default branch:

Commits scanned:
Commits rewritten:

Removed identities:
- name <email>

Old HEAD:
New HEAD:

Old tree:
New tree:
Tree identical: YES/NO

File content changed: YES/NO

Other co-author trailers preserved: YES/NO

Backup branch:
Backup branch SHA:

Push method:
--force-with-lease

GitHub push successful: YES/NO

Branch protection/ruleset status:

Branches still referencing old history:
...

Tags still referencing old history:
...

Open PRs potentially affected:
...

Claude/Anthropic Co-Authored-By remaining on rewritten default branch:
0 / number

最后明确给出：

SAFE RESULT: repository contents are identical; only Git commit history metadata was rewritten.

只有所有验证确实通过时才能输出 SAFE RESULT。

========================================
重要执行原则
========================================

这是执行任务，不只是给我说明命令。

你可以自主执行无破坏性的读取、扫描、clone、fetch 和验证步骤。

创建 backup branch 是允许的。

真正重写远端默认分支之前，请把：

- OLD_HEAD
- NEW_HEAD
- OLD_TREE / NEW_TREE
- 将修改的 commit 数量
- 将删除的 identities
- backup branch
- GitHub branch protection/ruleset 检查结果

展示给我，并等待我的明确确认。

只有我确认后，才能执行最终的 `git push --force-with-lease`。
