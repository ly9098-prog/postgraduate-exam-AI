# AGENTS.md

本文件是仓库根目录的协作与开发说明，遵循 [agents.md](https://agents.md) 开放格式，适用于整个 `postgraduate-ai` 项目。进入更深层目录后，应同时遵循该目录中的 `AGENTS.md`（就近生效，最内层优先）；例如管理后台还必须遵循 `admin-frontend/AGENTS.md`。Claude Code 用户另见根目录 `CLAUDE.md` 与 `.claude/rules/`（按路径生效的专项规则）。项目长期约束以 `docs/project/PROJECT_RULES.md` 和相关专项文档为准，代码与运行时配置是实现事实的最终依据。

## 项目概述

MemoGrad / 22408AI 是面向考研场景的智能刷题与题库治理系统，当前由三个主要运行部分组成：

- `backend/`：Python 3.11+、FastAPI、SQLAlchemy 2.0 异步 ORM、Alembic；开发可用 SQLite，生产使用 PostgreSQL 15，并依赖 Redis 7 承载缓存和任务队列。
- `admin-frontend/`：Next.js 16.2.12、React 19.2.4（项目锁定版本）、TypeScript 的管理后台，使用 App Router、TanStack Query/Table、Zustand、Tailwind CSS 等依赖。
- `miniprogram/`：原生微信小程序，包含刷题、复习、错题、公式、导出和番茄钟等页面与分包；npm 依赖目前主要是 `lottie-miniprogram`。

后端还包含 OCR/PDF 导题流水线、AI 辅助修复与结构化、知识图谱/推荐、复习调度、导出和审计/RBAC。OCR、向量检索、AI 模型等能力受环境变量和部署画像控制，并非每个本地环境都可用。

根目录没有统一的 `package.json` 或 `pyproject.toml`。依赖、测试和 lint 配置分别位于 `backend/` 与 `admin-frontend/`；小程序没有统一 npm scripts、TypeScript 配置或仓库级 lint 配置，这一点不能假定为已提供。

## 核心约束

- 微信 openid 唯一用户身份，不存密码；Admin 使用独立用户名与 JWT 域。
- 无纯 AI 自动入库：所有导入必须经过 `question_imports` + 人工确认。
- AI 是辅助：不可用时不影响核心刷题。
- OCR 纠错链路固定为 `PaddleOCR-VL → LLM 纠错（Qwen/GLM）→ rule fallback`，不可绕过质量门禁。
- **IMPORTANT**：跨环境数据同步必须用 `sync_uuid` 匹配记录，严禁按 numeric id 直接修改生产库（本地与生产 id 已发散）。
- `knowledge_points` 是科目归属的权威来源；`admin_ai_model_configs` 为软删除，模型 ID 必须保持稳定。
- 项目已上线并进入稳定性治理阶段：优先长期稳定性、可靠性、可维护性、可扩展性和生产安全；不以“功能能运行”作为设计或交付标准。
- 保持高内聚、低耦合与清晰的模块职责和依赖边界；抽象必须有真实复用或测试收益，新增依赖须评估安全、维护成本和回退方式；避免过度设计和无实际价值的重构。
- 技术债务显式登记并按批次治理；既有结构按有限账本处置，不为行数盲目拆分；生产变更须单独授权。

## Agent 执行与沟通约束

编程助手应以完成已授权任务为目标，避免无新增证据的反复推演、自检和重复验证；保留项目要求的测试、验收与安全边界。

1. **动作明确**：围绕明确目标执行必要动作，以可观察事实和验收标准作判断；不以“可能有风险”“再谨慎一点”等模糊理由扩大任务、拖延执行或追加流程。仅在缺失信息会影响正确执行或授权范围时澄清。
2. **程序优先校验**：数据、文件内容、格式、数量及一致性优先通过脚本、测试或现有工具校验，避免依赖人工逐项比对和主观推断。检查通过后，只有新增改动、失败或未解决的问题才触发相关复验。
3. **优先复用**：先确认仓库现有实现；需要外部方案时，优先查找并适配 GitHub 已有成熟方案，避免从头开发已有通用能力。采用前按项目规范核对兼容性、许可、安全和维护成本。
4. **Bug 检索顺序固定**：完成本地错误信息采集与复现后，外部线索按“社交媒体 → 技术社区 → GitHub → 官方文档”检索；无相关结果或来源不可用时进入下一项，不重复空查。检索顺序不代表证据优先级，最终结论须结合项目实际复现，涉及 API 和版本行为时以对应版本的官方资料核实。
5. **两次失败必须换角度**：同一 Bug 连续两次修复或假设验证失败后，停止沿原思路反复试错；改用不同输入、最小复现、调用层级或环境对照重新定位，并记录已排除的假设和新证据。
6. **存疑方案交叉挑错**：方案存在尚未消除的疑点时，调用其他可用 AI 模型进行独立审查，提供必要上下文，要求指出反例、遗漏和可验证的缺陷；对意见先验证再采纳。没有可用的其他模型时，如实说明，改用可执行验证收敛疑点，不得将同一模型自检冒充交叉审查。

在保证正确、证据充分的前提下尽量精简输出，优先交代结果、验证和必要的阻塞信息；遵循用户明确指定的流程，不擅自增删、替换步骤或降低质量门禁。

## 检索路由规则

**代码检索 → codebase memory MCP**

- 先通过 `index_status` 检查索引是否就绪；未就绪时执行 `index_repository` 重建索引，再进行 `search_code`、`query_graph`、`get_architecture`、`get_code_snippet`。
- 禁止回退到递归 `grep` 或逐文件 `view_file`；仅在准备编辑某个已定位文件时才允许 `view_file`。
- 优先使用 codebase-memory 知识图谱工具而非 grep/glob 进行代码搜索，减少文件读取次数。

**项目文档/知识检索 → 仓库 `docs/`**

- `docs/` 是项目文档的唯一权威正文来源；`docs/INDEX.md` 是目录与维护入口。不要在外部 Wiki 维护平行的项目规则、架构、API 或运维正文。
- 项目知识检索直接使用仓库内的普通文件工具，按 `docs/INDEX.md` 和既有目录结构列目录、搜索和读取。
- Windows 侧 `C:\Users\Devil\wikis\postgraduate-ai-wiki` 是只读历史归档，不作为现行项目规则或实现事实来源。归档中的内容必须先与仓库文档、代码和运行时配置核对。
- 本仓库不要求维护 Graphify 文档图、生成式索引或 `knowledge_wiki` MCP；文档事实仍须按本文件规则与代码和运行时配置核对。

**通用原则**

- 代码归代码工具，文档归文档工具，不交叉使用。
- 每次任务先判断检索对象类型，再选择对应路径。

## 部署与 CI 陷阱

- `deploy.sh migrate` 在旧 app 容器内执行：新增迁移须先 build 新镜像，再 `docker compose run --rm app alembic upgrade head` 应用。
- `nginx.conf` 为文件级 bind mount：rsync 换 inode 后不生效，须 `--force-recreate`。
- CI 架构测试使用 `.github/workflows/ci.yml` 中的固定文件清单：移动、重命名或新增测试文件后必须同步该清单。

## 目录说明

```text
.
├── backend/
│   ├── app/                  # FastAPI 应用、API、模型、schema、服务、AI/OCR 特性
│   ├── alembic/              # 数据库迁移；生产 schema 变更的入口
│   ├── tests/                # 后端单元、API、集成、OCR、可靠性和手工测试
│   ├── pyproject.toml        # 包元数据、可选依赖、Ruff/Mypy/Pytest 配置
│   ├── pytest.ini            # 后端测试路径、标记和 pytest 默认参数
│   ├── ruff.toml             # 后端 Ruff lint 规则
│   ├── requirements*.txt     # 运行时依赖和可选 OCR 依赖
│   └── Dockerfile*           # 本地/生产镜像构建文件
├── admin-frontend/
│   ├── src/app/              # Next.js App Router 页面
│   ├── src/components/       # 布局、表格、题目、公式、审计和 UI 组件
│   ├── src/lib/              # API client、鉴权、权限和工具
│   ├── contracts/            # OpenAPI 生成的前端合约检查入口
│   ├── scripts/              # 管理端辅助脚本
│   ├── package.json          # npm scripts 与依赖
│   ├── eslint.config.mjs     # ESLint 9 + Next 配置
│   ├── vitest.config.ts      # Vitest 配置，仅包含 `src/**/*.test.ts`
│   └── tsconfig.json         # strict TypeScript 配置，`@/*` 指向 `src/*`
├── miniprogram/
│   ├── pages/                # 主包页面
│   ├── subpackages/          # study、productivity、formulas、export、animation 等分包
│   ├── components/、utils/   # 小程序组件和工具
│   ├── tests/                # 独立 Node 回归脚本和渲染 fixture
│   ├── app.js、app.json、config.js
│   └── package.json          # 当前仅声明 npm 依赖，无统一 scripts
├── deploy/                   # Docker Compose、Nginx、systemd、部署与健康检查脚本
├── docs/                     # 架构、API、数据库、前端、Admin、OCR、项目规则文档
├── prompts/                  # 系统 Prompt、开发阶段 Prompt、任务模板
├── scripts/                  # 根级导入、审计、OCR 和数据工具脚本
├── tests/                    # 少量仓库级/OCR 回归测试
├── run.sh                    # Linux/WSL 后端一键启动
├── run-admin-linux.sh        # Linux/WSL 管理端一键启动
└── sync-to-windows.sh        # WSL 到 Windows 的镜像同步工具
```

`node_modules/`、`.next/`、`.venv/`、缓存、数据库、备份和运行时产物不是源码目录。它们通常已被 `.gitignore` 排除；已跟踪文件除外。

## 开发规范

- 先阅读目标模块、相邻测试和对应 `docs/` 文档，再修改代码；不要把历史报告、设计草案或 README 的过时描述当作当前实现。
- 后端 API 路由负责协议和参数校验，业务逻辑放在 `backend/app/services/` 或对应 feature 模块；数据库模型放在 `backend/app/models/`，schema 放在 `backend/app/schemas/`，迁移统一使用 Alembic。
- 后端使用异步 FastAPI/SQLAlchemy 约定和现有错误、日志、配置边界。新增 Python 代码应满足 `backend/ruff.toml`；项目也在 `backend/pyproject.toml` 中声明了 Python 3.11、100 列和 Mypy 规则。
- Public API 前缀为 `/api/v1`，Admin API 前缀为 `/api/admin/v1`。不要混用用户 JWT 与 Admin JWT，也不要绕过既有 RBAC、审计和安全校验。
- 运行时 AI Prompt 模板集中在 `backend/app/ai/prompts*.py`，Agent/开发 Prompt 在 `prompts/`；修改运行时 Prompt 须同步版本号、缓存兼容和回归测试。AI 只能作为辅助，导入数据必须经过现有导入与人工确认链路。项目明确不引入 LangChain、LlamaIndex、微服务或 Kubernetes。
- 管理端遵循 `admin-frontend/AGENTS.md`、Next.js App Router 和 strict TypeScript 约定。修改后优先使用 `npm ci`（存在 `package-lock.json` 时）保持锁文件一致。
- 小程序使用原生微信开发者工具工作流；保持主包/分包边界、现有渲染不变性和环境配置逻辑。由于仓库没有统一小程序 lint/test 配置，不得声称存在未确认的检查命令。
- 配置通过 `.env.example` 了解变量名；真实 `.env`、Token、密码、AppSecret、AI/OCR 凭据和私钥不得写入文档、日志或提交。AI 模型凭据（API Key / Base URL / model name）不使用环境变量，统一存于数据库 `admin_ai_model_configs`，经 Admin API 管理，由 `AI_CONFIG_ENCRYPT_KEY` 加密；生产已不通过 `DEEPSEEK_API_KEY` 等环境变量提供 AI 凭据。
- 文档只记录已实现或已验证事实；无法从代码、配置、CI 或现有文档确认的内容必须标注“待确认/未验证”。
- 当用户提到“项目知识库”“Wiki”或“知识库”时，默认将其理解为仓库 `docs/`，并使用普通文件工具检索；代码、运行时配置和当前 `docs/` 是事实核验依据。外部只读 Wiki 仅用于历史差异追溯，不得与 `docs/` 并列为现行规范来源。

## 常用命令

以下命令均来自现有脚本、配置或 CI；运行前确认当前工作目录和所需服务。

### 后端本地开发

```bash
cd backend
python -m venv .venv
source .venv/bin/activate                 # Windows 使用 .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-ocr.txt       # 仅在需要本地 OCR 时

cp .env.example .env                      # 不提交生成的 .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

根目录也提供 `./run.sh`，它会进入 `backend/`、准备依赖并启动开发 API。后端独立角色入口已在代码中提供：`python -m app.worker_main`、`python -m app.scheduler_main`；生产 Compose 会分别启动它们，不能用 HTTP 入口替代。

### 管理端

```bash
cd admin-frontend
npm ci
npm run dev
npm run typecheck
npm run lint
npm run test
npm run build
npm run check                            # typecheck + lint + test + build
```

`./run-admin-linux.sh` 是现有的 Linux/WSL 启动封装。管理端默认开发地址和 API 地址以脚本及 `NEXT_PUBLIC_ADMIN_API_BASE_URL` 为准。

### 微信小程序

```bash
cd miniprogram
npm install
node tests/test-code-mode.js
node tests/test-config-resolution.js
node tests/test-export-capability-error.js
node tests/test-latex-symbols.js
node tests/test-multi-blank-answer.js
node tests/test-render-invariant.js
node tests/render_regression/run.js
```

这些是独立 Node 脚本，不是 `npm test` 的别名；修改页面或渲染逻辑后还需要用微信开发者工具编译、模拟器/真机验证。

### 后端质量、测试与迁移

```bash
cd backend
python -m compileall -q app
ruff check app/ --ignore I001,F401,N818
ruff check path/to/changed_file.py             # 修改 Python 文件的严格检查
ruff format --check app/                      # 当前在 CI 中为提示性检查
mypy app/                                     # 当前在 CI 中为提示性检查
python -m pytest tests/ -v --tb=short
alembic upgrade head
alembic current
alembic heads
```

部分集成、Redis/PostgreSQL、OCR、GPU、手工和慢测试需要额外服务或环境；测试标记和默认路径见 `backend/pytest.ini` 与 `backend/pyproject.toml`。集成测试环境的 Compose 文件是 `deploy/docker-compose.test.yml`，不要假定本地已启动依赖。

### Docker/生产运维

生产入口是 `deploy/scripts/deploy.sh`，支持已实现的 `init`、`update`、`update-admin`、`update-scheduler`、`update-all`、`build`、`build-admin`、`backup`、`status`、`migrate` 子命令。`deploy/Makefile` 还封装了 `up`、`down`、`restart`、`logs`、`status`、`build`、`backup`、`deploy`、`update`、`migrate`、`health-check`。

生产使用 `deploy/docker-compose.prod.yml`，包含 `app`、`worker`、`scheduler`、`admin`、`nginx`、PostgreSQL、Redis 和备份服务。生产必须使用 `APP_ENV=production` 与 `DEPLOYMENT_PROFILE=cloud_api`，并由运维人员提供真实环境配置。

## 测试要求

- 后端改动至少运行受影响目录/模块的 pytest；涉及路由、模型、迁移、队列、OCR 或安全边界时，补充对应 API、集成或回归测试。
- 提交前应至少完成后端 `compileall`、Ruff 检查和相关 pytest；管理端改动应完成 `npm run typecheck`、`npm run lint`、`npm run test`，构建相关改动再执行 `npm run build` 或 `npm run check`。
- CI 的可靠性流程会使用 PostgreSQL/pgvector、Redis、Alembic migration、OpenAPI 合约和管理端构建；本地没有这些服务时，应明确记录测试未执行原因，而不是伪造通过结果。
- OCR 外部服务、GPU、慢测试和手工测试按 pytest 标记/目录隔离。修改 OCR 或题目渲染时，应运行现有回归脚本；出现新的渲染回归应按现有 fixture 机制补充案例。
- 测试不得使用生产凭据或真实用户数据；测试配置应使用仓库已有的 `.env.ci`/测试环境变量模式。

## Git 规则

提交消息、type 与 attribution 的完整规范见 `docs/COMMIT_RULES.md`，要点：

- 提交消息使用 Conventional Commits 格式 `<type>(<scope>): <简短描述>`，允许的 type 为 `feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`build`、`ci`、`chore`、`revert`。
- 严禁在提交中自动添加任何 AI（Claude/Anthropic、Codex/OpenAI 等）的 `Co-Authored-By`、`Generated-by`、`Assisted-by` 等 attribution trailer；保留仓库维护者的 Git author identity。
- 提交前检查 `git status`、`git diff --check` 和受影响文件的测试；只提交与当前任务相关的变更，保留用户已有改动。
- 不提交 `.env`、数据库文件、备份、日志、缓存、构建产物、`node_modules`、`.next`、虚拟环境、证书或任何密钥文件，即使它们在本机可用。
- API、数据库、OCR/AI、前端规则和部署变化要同步对应 `docs/` 文档；文档更新不能替代必要的代码测试或迁移。
- 不使用 `git reset --hard`、`git checkout --` 等破坏性命令覆盖未确认的用户改动；不执行未经授权的 force push 或历史重写。

## 禁止事项

- 禁止把真实 Token、密码、私钥、微信 AppSecret、AI/OCR 凭据或生产连接串写入源码、文档、测试 fixture、截图或日志。
- 禁止在未确认数据备份和影响范围时删除数据库、Docker volume、备份或用户文件；生产日常操作禁止使用 `docker compose down`、`docker compose build --no-cache`、`docker system prune -a` 或删除 volume。
- 禁止绕过人工审核将 AI/OCR 结果直接入库，禁止绕过质量门禁、鉴权、RBAC、审计和部署画像约束。
- 禁止为解决单个问题擅自引入 LangChain/LlamaIndex、微服务、Kubernetes、账号密码登录、多方式登录、社区/排行榜或其他 `docs/project/PROJECT_RULES.md` 明确不做的范围。
- 禁止凭空补写不存在的命令、服务、目录、API 或技术栈；不确定内容必须标注，并回到代码、配置、CI 或运行时 OpenAPI 核实。
- 与这些规则配套的仓库内文档见 `docs/development/`：`coding-style.md`、`development-workflow.md`、`git-workflow.md`、`agents-and-commands.md`；这些文档来自外部参考，冲突时以本文件、`docs/project/PROJECT_RULES.md`、`docs/COMMIT_RULES.md` 和代码为准。
- 禁止修改与任务无关的业务代码、删除用户已有文件，或把历史文档中的伪代码当作可执行实现。
