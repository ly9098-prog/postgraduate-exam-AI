
# 项目文档统一知识库计划

> 状态：已完成；`docs/` 是唯一权威项目知识源，`knowledge_wiki` MCP 检索要求已撤销。
> 说明：下文“目标与约束 / 当前基线 / 执行步骤 / 验收标准”保留原始计划记录；最终目标、结果和验收以“后续修订”为准。

## 目标与约束

- 权威文档保留在仓库 `docs/`，继续通过 Git 与源码一起审查、追踪和发布。
- 知识库 MCP 直接以 `/home/lmh/projects/postgraduate-ai/docs` 为根目录，使用现有目录结构、`docs/INDEX.md` 和文件搜索/读取能力。
- Windows 侧 `C:\Users\Devil\wikis\postgraduate-ai-wiki` 保留为只读归档；不删除、不继续维护项目正文。
- 不新增手工维护的文档副本、生成式索引或依赖。个人笔记不属于本任务迁移范围。
- 仅修改与本任务相关的文档、Agent 指引、MCP 配置和本任务记录；保留工作区中的其他改动、删除与未跟踪文件。

## 当前基线

- 根目录 `AGENTS.md` 同时规定文档检索使用 Graphify 和外部 `knowledge_wiki` MCP，二者与新目标不一致，需要收敛为直接检索仓库 `docs/`。
- Windows Wiki 包含正式项目页、Obsidian 索引/写作规则，以及 `wiki/memory/` 中的待审同步摘要；必须逐项核对，不能把摘要或历史过程直接当作当前事实。
- Codex MCP 配置位于 `/mnt/c/Users/Devil/.codex/config.toml`，`knowledge_wiki` 当前 filesystem 根目录为 `/mnt/c/Users/Devil/wikis/postgraduate-ai-wiki`。
- `docs/INDEX.md` 已是仓库文档分区与常用入口；检查并沿用，不另建一套 Wiki 正文或索引。
- 当前 MCP 仍连接 Windows Wiki；修改配置后需重连 MCP 才能验证新根目录。

## 执行步骤

1. **盘点与核对**
   - 盘点旧 Wiki 的正式页面、索引、写作规范、日志、原始材料和待审摘要。
   - 将每项候选内容与 `docs/` 及当前代码/配置核对，记录来源与去向。
   - 对每项标记为“已由 docs 覆盖”“有效独有内容待归并”“过时/仅历史、不晋升”或“个人笔记、不迁移”。
   - 仅将已验证且尚未记录的持久项目知识归并到对应权威文档；保留必要来源说明，不复制整篇 Wiki 页面。

2. **收敛文档检索规则**
   - 更新根目录 `AGENTS.md` 的文档/知识检索路由：项目知识以 `docs/` 为唯一权威来源，通过根目录 MCP 的 `list_directory`、`search_files`、`read_file` 检索。
   - 移除要求先查询 Graphify 的冲突性路由；不声称存在未配置或未验证的文档图索引。
   - 检查根 `CLAUDE.md`、`.claude/rules/`、Agent 文档和 `admin-frontend/` 规则；仅在存在冲突的项目知识来源/检索说明时同步修订。
   - 明确旧 Windows Wiki 为只读归档，不再作为当前项目规则依据；代码、运行时配置和仓库 `docs/` 是当前事实核验来源。

3. **切换 MCP 并归档旧 Wiki**
   - 仅修改 Codex `knowledge_wiki` filesystem server 的根路径为 `/home/lmh/projects/postgraduate-ai/docs`，保留现有 server 名称及其他参数。
   - 保留旧 Wiki 文件原样可读，不清理、不搬移、不删除；记录切换日期和只读归档状态。
   - MCP 配置修改后重连工具，确认目录列表、文档搜索和文件读取均落在仓库 `docs/` 下。

4. **任务收尾**
   - 在旧 Wiki 的逐项对照中记录每篇正式页及每个待审摘要的处置结果与 `docs/` 目标路径或不晋升理由。
   - 检查 `docs/INDEX.md` 是否需要最小增补，确保已归并内容可从现有入口发现；不为形式而重复列出正文。
   - 检查相对链接、Markdown 格式、MCP 根路径和变更范围，保留用户已有工作区改动。

## 验收标准

- MCP 重连后只把仓库 `docs/` 暴露为该项目知识库根目录，能成功列目录、按主题搜索并读取文档。
- 旧 Wiki 正式页和待审摘要逐项有明确处置；所有晋升内容均已核对当前实现，过时/历史内容未被写成现行规则。
- 仓库 Agent 指引对项目知识来源和检索方式一致，不再要求同时维护/查询外部项目正文或另一套 Graphify 索引。
- Windows Wiki 保持完整且可读，并有只读归档说明；未删除任何原始材料。
- `docs/INDEX.md`、新增或修改文档中的相关链接有效，Markdown 检查通过。
- `git diff --check` 通过；最终改动仅涉及知识库统一所需路径，其他预存改动、删除和未跟踪内容均保留。

## 执行结果（2026-11-04）

- 已逐页核对旧 Wiki 正式页与待审摘要，处置记录见 `docs/project/KNOWLEDGE_BASE_MIGRATION_2026-11-04.md`；旧 Wiki 未写入。
- `AGENTS.md` 和 `.claude/rules/docs-index.md` 已收敛为仓库 `docs/` 唯一权威来源，移除 Graphify 项目文档路由。
- `docs/backend/API_SPEC.md`、`docs/frontend/UI_RULES.md`、`docs/frontend/DESIGN_SYSTEM.md` 和 `docs/project/DEPLOY_PLAN.md` 已按核对到的当前实现做最小修订；未新增第二套项目知识正文。
- Codex `/mnt/c/Users/Devil/.codex/config.toml` 中 `knowledge_wiki` filesystem 根目录已改为 `/home/lmh/projects/postgraduate-ai/docs`。
- 当前会话的 MCP 实例仍连接旧 Wiki；这不是配置回退，重启/重连后需以 `docs/` 为根目录重新验证列目录、搜索和读取。
- 2026-11-04 追加核对：配置文件确为新路径；尝试结束仍指向旧 Wiki 的旧 MCP 进程后，Codex 会话中的 `knowledge_wiki` 连接转为 closed，未在当前进程内自动重连。剩余验证必须在 Codex 重启/重连后执行。

## 后续修订（2026-11-04）

- 用户确认：既然 `docs/` 已在项目工作区内，普通文件工具即可完成检索，继续保留 `knowledge_wiki` MCP 属于多余层。
- `AGENTS.md`、`.claude/rules/docs-index.md`、`docs/INDEX.md` 和迁移对照已改为普通文件工具检索；不再要求 MCP。
- Codex `/mnt/c/Users/Devil/.codex/config.toml` 中 `knowledge_wiki` server 已停用，保留原配置项用于回退。
- 原“MCP 重连后验证根目录”的验收项被本修订取代；最终验收改为确认 Agent 指引一致、配置停用且普通文件工具可直接访问 `docs/`。

## 不在范围内

- 删除、重命名或批量搬迁 Windows Wiki 文件。
- 迁移个人学习笔记或无关项目内容。
- 引入 Graphify、向量检索、embedding、文档生成器或新的运行依赖。
- 修改业务代码、生产环境、数据库、部署流程或用户数据。
