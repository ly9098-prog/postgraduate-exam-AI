# 部署结构分析

> 更新时间：2026-05-29
> 变更原因：生产部署入口已收敛到 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`，日常更新使用 app-only 构建与替换；服务器 `.env`、证书和密钥由服务器侧独立维护，普通同步不得覆盖。

## 1. 当前部署问题

当前项目曾同时存在多套部署入口，现已确认生产入口收敛为 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`：

> 运维参考信息（仅用于服务器对齐和排查，不代表密钥或证书应提交/同步到仓库）：公网 IP `8.163.56.109`，内网 IP `172.18.50.44`，域名 `xzshub.top`，服务器侧密钥路径 `/loginkey.pem`；旧部署路径 `/opt/2240ai/`，新版建议部署路径 `/opt/2240ai-v2/`；服务器证书目录已确认为 `/cert`，通过 compose 映射到容器内 `/etc/nginx/ssl`。

- 根目录 `docker-compose.yml`：开发环境，包含 `db`、`redis`、`app`，`app` 使用 `./backend` 构建并挂载 `./backend:/app`，对应 `backend/Dockerfile`。
- `deploy/docker-compose.prod.yml`：已验证的生产 compose 入口，包含 `postgres`、`redis`、`app`、`nginx`；`app` 使用 `../backend` 作为 build context，Dockerfile 为当前服务器健康运行的 `backend/docker/Dockerfile`；nginx 挂载 `./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro`、`./../cert:/etc/nginx/ssl:ro` 和 `./../certbot/www:/var/www/certbot:ro`，容器内 nginx 读取 `/etc/nginx/ssl/www.xzshub.top.pem` 与 `/etc/nginx/ssl/www.xzshub.top.key`。
- `deploy/scripts/deploy.sh`：当前推荐生产部署脚本入口，使用 `deploy/docker-compose.prod.yml` 并通过 `--env-file backend/.env` 读取服务器侧环境变量；日常更新执行缓存构建和 `up -d --no-deps app`，不默认 `git pull`，不默认迁移。
- `deploy/deploy.sh`：旧推荐入口，当前已被 `deploy/scripts/deploy.sh` 取代；如服务器仍存在该文件，应视为历史/备用入口，避免作为日常生产部署命令。
- `deploy/scripts/backup.sh`：备份流程应使用 `deploy/docker-compose.prod.yml`、数据库服务名 `postgres` 和服务器侧 `backend/.env`。
- `deploy/docker-compose.yml`：历史/备用生产部署入口；不再作为推荐生产入口。
- `deploy/docker-compose.dev.yml`：开发部署入口，不用于生产。
- `backend/docker/docker-compose.yml`：后端目录内历史部署配置，服务器已从运行入口中清理；不用于当前生产部署。

主要问题：

1. **部署入口已收敛但历史入口仍存在**：当前推荐生产入口为 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`，数据库服务名为 `postgres`，nginx 使用 `deploy/nginx/nginx.conf`；`deploy/deploy.sh`、`deploy/docker-compose.yml` 等历史入口应避免误用。
2. **高风险部署动作已从推荐日常路径移除**：推荐 `update` 不再执行全服务 `down/up`，不禁用缓存，不默认 `git pull`，不默认迁移。
3. **敏感文件仍需按部署流程隔离**：当前 ignore 体系已移除 `!loginkey.pem` 放行并排除密钥/本地 `.env`；服务器 `.env` 已确认为 `backend/.env`，应由服务器侧独立维护。`/loginkey.pem` 是服务器侧根目录密钥位置，不代表仓库内 `loginkey.pem` 应提交或通过本地同步上传；仓库内 `loginkey.pem` 仍应被忽略。服务器证书目录已确认为 `/opt/2240ai-v2/cert`，生产 nginx 通过 `./../cert:/etc/nginx/ssl:ro` 映射到容器内，并读取 `/etc/nginx/ssl/www.xzshub.top.pem` 与 `/etc/nginx/ssl/www.xzshub.top.key`。

## 2. 当前耗时来源

从当前本地采样快照看，以下数字只反映本机当前工作区状态，不应视为稳定事实：

| 路径 | 体积 | 说明 |
| --- | ---: | --- |
| `backend/` | 238M | 本地采样快照；主要由 `backend/.venv`、测试目录、SQLite 数据库构成 |
| `backend/.venv` | 201M | 本地 Python 虚拟环境，不应同步或进入镜像上下文 |
| `.claude/` | 145M | 本地采样快照；Claude 工作区与 agent worktree，不应同步 |
| `.claude/worktrees` | 145M | 本地采样快照；临时工作树，不应同步 |
| `.git` | 23M | 本地采样快照；Git 元数据，不应通过 rsync 同步 |
| `miniprogram/` | 804K | 本地采样快照；小程序源码，体积较小 |
| `docs/` | 468K | 本地采样快照；文档，生产部署通常不需要 |
| `deploy/` | 72K | 本地采样快照；部署配置和脚本 |

当前最可能的耗时来源：

1. **全量同步本地项目**：如果部署脚本未使用 `.deployignore` 或等价排除规则，仍可能把 `.claude/`、`.git/`、`backend/.venv/`、`.pytest_cache/`、测试数据库等上传到服务器。
2. **Docker build 上下文过大**：已确认推荐生产入口 `deploy/docker-compose.prod.yml` 的 build context 从 `deploy` 目录视角指向 `../backend`，应命中 `backend/.dockerignore`；后续服务器对齐时仍需只读核验实际执行路径是否一致。
3. **依赖层重复安装**：`--no-cache` 或 Dockerfile 层设计不当会导致 pip 依赖每次重装。
4. **全服务 down/up**：`docker compose down` 会停止所有服务，数据库、nginx、redis 都会被影响；小改动不应触发该动作。
5. **`--pull` 每次检查/拉取基础镜像**：日常代码更新通常不需要每次 `--pull`。

## 3. Docker 缓存问题

当前 Dockerfile 情况：

- `backend/Dockerfile` 已经先 `COPY requirements.txt .` 再 `pip install`，最后 `COPY . .`，基础层顺序是合理的。
- `deploy/Dockerfile.prod` 和 `backend/docker/Dockerfile` 也采用多阶段构建，并先安装依赖再复制源码。
- 当前推荐脚本 `deploy/scripts/deploy.sh` 的日常 `update` 已保留 Docker layer cache，不使用 `--no-cache` 或默认 `--pull`。
- `deploy/deploy.sh`、`deploy/docker-compose.yml` 等历史入口不作为当前日常生产路径；如未来清理或复用，需先确认其中没有高影响动作。
- 已确认推荐生产入口 `deploy/docker-compose.prod.yml` 使用 `../backend` 作为 build context，应应用 `backend/.dockerignore`；服务器已验证构建缓存可命中。

当前 `backend/.dockerignore` 第一阶段已补充排除：

- 版本控制与本地 agent 状态：`.git/`、`.claude/`
- 本地环境和依赖：`.venv/`、`venv/`、`backend/.venv/`、`node_modules/`、`miniprogram/miniprogram_npm/`
- Python 缓存和测试产物：`__pycache__/`、`*.pyc`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、覆盖率产物
- 本地数据库和备份：`*.db`、`*.sqlite*`、`*.db.backup-*`、`backend/*.db*`
- 敏感文件和本地环境变量：`.env`、`.env.*`、`*.pem`、`*.key`、`*.crt`、`loginkey.pem`
- 运行时/生成文件：`logs/`、`tmp/`、`cache/`、`uploads/`、`backend/static/`、`backend/static/uploads/`、`backend/debug_snapshots/`
- 构建输出、IDE/OS 噪声、文档和本地项目笔记

仍需注意：

- `.dockerignore` 只控制 Docker build context，不控制 rsync/scp 同步范围。
- 若未来新增生产 compose 的 build context 不是 `backend`，需要单独确认对应 ignore 是否生效。
- 服务器端运行所需 `backend/.env`、证书和密钥不应进入镜像上下文，也不应从本地工作区同步覆盖。
- `/loginkey.pem` 指服务器侧根目录密钥位置；仓库内 `loginkey.pem` 仍应保持忽略，不能通过 Git 或本地同步上传。

## 4. 不合理同步项

部署同步时仍需区分三类 ignore：Git 忽略、Docker build context 忽略、rsync/部署同步忽略。

### 第一阶段已完成

- 根目录 `.gitignore` 已移除 `!loginkey.pem` 放行规则，并补充 `.claude/`、虚拟环境、缓存、数据库/备份、`backend/static/`、日志、上传目录、密钥等忽略项。
- `backend/.dockerignore` 已补充 `.venv/`、`.pytest_cache/`、SQLite/备份、密钥、上传/static、日志缓存等排除项，降低 Docker build context 污染。
- 新增 `.deployignore`，用于后续 rsync/scp 同步时排除 `.git/`、`.claude/`、`backend/.venv/`、数据库、密钥、本地 `.env`、缓存和运行产物。
- 已验证 `loginkey.pem`、`backend/postgraduate.db*`、`backend/static`、`.claude/worktrees`、`backend/.venv`、`.pytest_cache` 均会被 Git 忽略。

### 部署同步必须排除

- `.git/`
- `.claude/`
- `.venv/`、`venv/`、`backend/.venv/`
- `node_modules/`
- `dist/`、`build/`
- `__pycache__/`、`*.pyc`
- `.pytest_cache/`
- `*.db`、`*.sqlite`、`*.sqlite3`、`*.db.backup-*`
- `.env`、`.env.*`、`*.pem`、`*.key`、`*.crt`、密钥文件
- `logs/`、`*.log`
- `tmp/`、`cache/`
- `uploads/`、`static/uploads/`、`backend/static/`
- OCR 缓存、AI 中间结果目录

### 当前已发现的本地文件

- `loginkey.pem`
- `postgraduate.db`
- `backend/postgraduate.db`
- `backend/postgraduate.db.backup-*`
- `backend/test_stage3_migration.db`
- `backend/_test_phase8_7f0928.db`
- `backend/.env`
- `.claude/worktrees/`
- `backend/.venv/`
- `backend/static/`

这些文件不应通过普通部署同步上传。

## 5. 可优化项

### 5.1 统一部署入口

当前推荐生产入口已收敛为 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`，数据库服务名为 `postgres`，nginx 配置为 `deploy/nginx/nginx.conf`，服务器侧环境变量文件为 `backend/.env`。

日常部署命令：

```bash
# 本地先使用 .deployignore 同步代码到 /opt/2240ai-v2/
rsync -az --exclude-from=".deployignore" -e "ssh -i loginkey.pem -o BatchMode=yes" ./ root@8.163.56.109:/opt/2240ai-v2/

# 服务器执行 app-only 更新
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh update
```

显式迁移命令：

```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh migrate
```

`deploy/deploy.sh`、`deploy/docker-compose.yml`、`deploy/docker-compose.dev.yml`、`backend/docker/docker-compose.yml` 均不作为当前生产日常入口；如需清理，应另行评估，不在普通部署中直接删除。

### 5.2 部署脚本改为单服务更新

日常后端代码更新应优先使用：

```bash
docker compose -f <compose-file> build app
docker compose -f <compose-file> up -d --no-deps app
```

避免：

```bash
docker compose down
docker system prune -a
docker compose build --no-cache
```

### 5.3 小改动支持快速重启

仅 Python 代码或配置变更时，可支持：

```bash
docker compose -f <compose-file> restart app
```

如果镜像内代码未变化但服务器代码通过 volume 挂载，重启可在 10 秒级完成；生产镜像部署则仍需 build + up。

### 5.4 ignore 体系状态

第一阶段已完成三套边界不同的 ignore 体系建设：

- Git 忽略：根目录 `.gitignore`，用于降低误提交风险；已移除 `!loginkey.pem` 放行并补充本地运行产物、密钥、数据库备份、`.claude/` 等规则。
- Docker build context 忽略：`backend/.dockerignore`，用于减少镜像构建上下文并避免本地缓存/数据库/上传文件影响 `COPY . .` 层。
- rsync/部署同步忽略：新增 `.deployignore`，用于控制从本地同步到服务器的文件范围。

后续不再把“补充 ignore 体系”作为下一阶段主任务；下一阶段应进行服务器对齐和只读核验，并让实际部署同步命令显式使用 `.deployignore` 或等价排除规则。`.env` 策略需要按场景区分：本地开发 `.env` 不应同步；服务器部署目录使用服务器侧 `backend/.env`，由运维或部署流程独立维护，不应从本地工作区直接覆盖。

### 5.5 保持 Docker layer cache

后续 Dockerfile 优化重点不是大改结构，而是：

- 保持 `requirements.txt` 先复制、依赖先安装、源码后复制。
- 移除日常部署中的 `--no-cache`。
- 日常部署默认不使用 `--pull`，需要基础镜像升级时再显式指定。
- 确保已确认推荐生产入口 `deploy/docker-compose.prod.yml` 的 build context 在服务器执行时仍能应用 `backend/.dockerignore`。
- 不同 compose 对应不同用途：根目录 `docker-compose.yml` 用于开发，`deploy/docker-compose.prod.yml` 用于当前生产，`deploy/docker-compose.dev.yml` 用于开发/备用场景，`deploy/docker-compose.yml` 为历史入口。当前生产 `deploy/docker-compose.prod.yml` 保持服务器健康运行的 `backend/docker/Dockerfile` 构建入口；切换到 `deploy/Dockerfile.prod` 应单独 staging 验证。

### 5.6 服务拆分部署建议

当前服务可按变更类型拆分：

- 后端代码变更：只更新 `app`。
- nginx 配置变更：只 reload/restart `nginx`。
- 数据库迁移：只在需要 schema 变更时运行 `alembic upgrade head`。
- redis/postgres 镜像和 volume：日常部署不动。

## 6. 风险分析

1. **生产入口误用风险**：当前推荐生产入口已收敛为 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`；`deploy/deploy.sh` 和历史 compose 仍存在时，应按历史/备用入口处理，避免新成员误用。
2. **Nginx 配置历史分叉风险**：实际 nginx 配置已确认为 `deploy/nginx/nginx.conf`，多余的 `deploy/nginx.conf` 将删除；后续修改 Nginx 时应只维护已确认路径，并确认服务器挂载路径一致。
3. **数据库中断风险**：`docker compose down` 会停止数据库服务，生产环境应避免作为日常更新动作。
4. **volume 风险**：禁止在部署脚本中删除 volumes，避免 PostgreSQL 数据丢失。
5. **缓存误清理风险**：`docker system prune -a` 会清理所有未使用镜像，可能影响同机其他服务和下次构建速度。
6. **敏感文件风险**：第一阶段已通过 `.gitignore`、`backend/.dockerignore`、`.deployignore` 降低误提交、build context 泄漏和部署同步误传风险；服务器 `backend/.env`、证书和密钥仍需独立维护，不能从本地同步覆盖。`/loginkey.pem` 是服务器侧根目录密钥位置，不代表仓库内 `loginkey.pem` 应提交或同步上传。
7. **服务器 `.env` 维护风险**：本地 `.env` 不应同步；服务器部署目录使用 `backend/.env` 或等价环境变量，不能简单理解为生产目录不需要环境配置。
8. **构建上下文污染风险**：第一阶段已降低该风险；后续仍需只读核验服务器实际执行 `deploy/docker-compose.prod.yml` 时 build context 是否命中 `backend/.dockerignore`。
9. **过度改造风险**：当前目标是轻量部署提速，不应一次性重构所有 compose 文件；建议按阶段完成服务器对齐、接入同步、验证回滚，再逐步收敛入口。

## 7. 自动化部署后续阶段规划

### 第二阶段：服务器对齐和只读核验

**目标**：在推荐入口已确认并开始收敛后，只读核验服务器实际部署目录、执行命令、compose 项目名、服务名、环境变量和挂载路径，确保仓库调整与服务器真实运行方式一致。

**具体任务**：

1. 在服务器上只读核验当前部署目录、执行入口、compose 文件路径和项目名称是否已对齐到 `deploy/docker-compose.prod.yml` + 推荐部署脚本。
2. 记录实际服务名：`app`、`nginx`、`postgres`、`redis` 是否与推荐生产 compose 一致。
3. 核验 nginx 配置来源为 `deploy/nginx/nginx.conf`，并确认多余 `deploy/nginx.conf` 已不再作为挂载来源。
4. 核验服务器 `.env` 位于 `backend/.env`，确认 `/loginkey.pem` 为服务器侧根目录密钥位置；服务器对齐时核验 `/cert` 挂载和证书文件 `/cert/www.xzshub.top.pem`、`/cert/www.xzshub.top.key` 存在，并确认容器内映射为 `/etc/nginx/ssl`。
5. 只做只读检查和记录，不执行全服务重启，不删除 volume，不修改运行中服务。

**验收标准**：

- 明确“当前推荐生产入口”在服务器上已对齐，包括 compose 文件、部署脚本、工作目录和服务名。
- 明确服务器 `backend/.env` 独立维护位置，确认不会由本地同步覆盖。
- 明确日常后端更新只需要影响 `app` 服务，数据库和 nginx 默认不动。

**风险/回滚要点**：

- 本阶段不应执行 `docker compose down`、volume 删除、`system prune` 或破坏性脚本替换。
- 如发现服务器实际运行方式与推荐入口不一致，先补充记录并回到主会话确认，不直接迁移。
- 如检查命令需要进入服务器，应优先使用只读命令，避免对运行容器产生副作用。

### 第二阶段只读核验结果（2026-05-28）

已通过 SSH 使用只读命令核验 `/opt/2240ai-v2` 当前服务器状态，未执行 `up/down/restart/build/migrate` 等变更动作。

**已确认项**：

- 当前服务器新版部署目录存在：`/opt/2240ai-v2`。
- 推荐入口相关文件存在：`deploy/docker-compose.prod.yml`、当时的 `deploy/deploy.sh`、`deploy/nginx/nginx.conf`、`backend/.env`。
- compose 项目前缀为 `deploy-`，运行容器包括 `deploy-app-1`、`deploy-nginx-1`、`deploy-postgres-1`、`deploy-redis-1`。
- `postgres`、`redis` 当前为 healthy，`nginx` 当前为 Up。
- `/opt/2240ai-v2/cert/www.xzshub.top.pem` 与 `/opt/2240ai-v2/cert/www.xzshub.top.key` 存在。

**发现的不一致/风险项**：

1. 服务器当前 `deploy/docker-compose.prod.yml` 与仓库推荐生产 compose 尚未对齐：服务器 compose 仍包含 `version: "3.8"`，`config --services` 仅输出 `postgres`、`redis`、`app`，未包含 `nginx`。
2. `deploy-nginx-1` 虽在运行，但当前 compose 配置中不再声明 `nginx` 服务，属于历史容器/历史配置残留风险；后续迁移前不能直接假设 `nginx` 已由当前推荐 compose 管理。
3. 服务器 nginx 实际挂载为 `/opt/2240ai-v2/deploy/nginx/ssl -> /etc/nginx/ssl`，不是当前仓库目标的 `/cert -> /etc/nginx/ssl`。
4. 服务器 nginx 配置仍读取 `/etc/nginx/ssl/fullchain.pem` 与 `/etc/nginx/ssl/privkey.pem`，尚未对齐到 `/etc/nginx/ssl/www.xzshub.top.pem` 与 `/etc/nginx/ssl/www.xzshub.top.key`。
5. 根目录 `/cert/www.xzshub.top.pem`、`/cert/www.xzshub.top.key` 与 `/loginkey.pem` 在本次只读核验中未发现；证书实际文件出现在 `/opt/2240ai-v2/cert/`。
6. `deploy-app-1` 当前状态为 `unhealthy`，原因是容器 healthcheck 使用 `curl -f http://localhost:8000/health`，但 app 镜像内没有 `curl`，不是健康接口本身已被证明失败。
7. `DATABASE_URL` 当前展开为 `postgresql+asyncpg://postgraduate:change-me@postgres:5432/postgraduate`，仍需确认服务器 `backend/.env` 是否已替换默认密码占位值。

**第二阶段结论**：

服务器已具备新版目录和部分推荐入口文件，但运行态尚未完全对齐到当前仓库目标。下一步不应直接执行全量部署或重启，应先设计一次小范围、可回滚的服务器对齐方案：同步 compose/nginx 目标配置、确认证书实际目录策略、修复 app healthcheck，再决定是否接入 `.deployignore` 同步流程。

### 第二阶段补充只读核验结果（2026-05-28）

本次通过 SSH 在 `/opt/2240ai-v2` 上再次只读核验，未执行 `up/down/restart/build/migrate` 等变更动作，补充确认如下：

- `deploy/docker-compose.prod.yml` 的 `config --services` 仅输出 `postgres`、`redis`、`app`，当前 compose 配置中**不再声明 nginx 服务**。
- `deploy-nginx-1` 仍在运行，但属于历史容器残留，不应误认为当前推荐 compose 已完整接管 nginx。
- nginx 当前仍挂载 `deploy/nginx/ssl -> /etc/nginx/ssl`，还未切换为当前目标的 `/cert -> /etc/nginx/ssl`。
- nginx 配置仍读取 `/etc/nginx/ssl/fullchain.pem` 与 `/etc/nginx/ssl/privkey.pem`，尚未对齐到 `/etc/nginx/ssl/www.xzshub.top.pem` 与 `/etc/nginx/ssl/www.xzshub.top.key`。
- `deploy-app-1` 的 healthcheck 仍是 `curl -f http://localhost:8000/health`，但 app 镜像内没有 `curl`，导致容器被标记为 `unhealthy`。
- 证书文件实际仍位于 `/opt/2240ai-v2/cert/`，分别是 `www.xzshub.top.pem` 与 `www.xzshub.top.key`；根目录 `/cert` 在这次核验中未发现。
- `backend/.env` 存在，`DATABASE_URL` 仍展开为 `postgresql+asyncpg://postgraduate:change-me@postgres:5432/postgraduate`，占位密码尚未替换为服务器实际值。

**补充结论**：

当前服务器仍停留在“目录已收敛、运行态未完全对齐”的状态。下一步应优先做一次小范围对齐：统一 nginx 证书挂载和证书路径、修复 app healthcheck，再决定是否继续接入 `.deployignore` 同步流程。

### 第二阶段最小配置修复结果（2026-05-28）

已通过 SSH 对服务器 `/opt/2240ai-v2` 做最小配置修复。执行前已在服务器创建配置备份目录 `deploy/backup-config-20260528-221743`，备份了 `deploy/docker-compose.prod.yml`、`deploy/nginx/nginx.conf` 和 `backend/.env`。本次未执行 `up/down/restart/build/migrate`，没有重启运行中容器。

**已修改项**：

- `backend/.env`：将 `DATABASE_URL` 密码从 `change-me` 改为 `postg2536`，并补充/对齐 `POSTGRES_USER=postgraduate`、`POSTGRES_PASSWORD=postg2536`、`POSTGRES_DB=postgraduate`。
- `deploy/docker-compose.prod.yml`：补回 `nginx` 服务声明，使 `config --services` 输出包含 `postgres`、`redis`、`app`、`nginx`。
- `deploy/docker-compose.prod.yml`：将 nginx 证书挂载对齐为服务器实际存在目录 `/opt/2240ai-v2/cert -> /etc/nginx/ssl`（compose 中使用 `./../cert:/etc/nginx/ssl:ro`）。
- `deploy/docker-compose.prod.yml`：将 app healthcheck 从依赖镜像内 `curl` 改为使用 Python 标准库访问 `http://localhost:8000/health`，避免因镜像内缺少 `curl` 被误判 unhealthy。
- `deploy/nginx/nginx.conf`：将证书读取路径改为 `/etc/nginx/ssl/www.xzshub.top.pem` 与 `/etc/nginx/ssl/www.xzshub.top.key`。

**已校验项**：

- `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml config --services` 已输出 `postgres`、`redis`、`app`、`nginx`。
- compose 展开后 nginx 证书挂载源为 `/opt/2240ai-v2/cert`，容器内目标为 `/etc/nginx/ssl`。
- `deploy/nginx/nginx.conf` 已读取 `www.xzshub.top.pem` 与 `www.xzshub.top.key`。
- 使用 `postg2536` 在 postgres 容器内只读连接数据库成功，返回当前用户和数据库均为 `postgraduate`。

**仍未生效项**：

- 运行中的容器尚未重启或重新创建，`deploy-app-1` 仍显示旧 healthcheck 状态 `unhealthy`，`deploy-nginx-1` 仍使用旧挂载；需要后续显式执行小范围 `up -d --no-deps app` 与 nginx 重建/重载后才会生效。
- 本次服务器配置仍保留当前服务器使用的 `backend/docker/Dockerfile` 构建路径，尚未切换到仓库推荐的 `deploy/Dockerfile.prod`；如需完全对齐推荐入口，应单独评估并测试。

### 第二阶段小范围生效结果（2026-05-28）

经用户确认后，已在服务器执行小范围生效动作：

```bash
docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml up -d --no-deps app nginx
```

过程中仅重新创建 `app` 与 `nginx`，`postgres`、`redis` 未重启且仍保持 healthy。首次生效后发现 app 使用新 `DATABASE_URL` 连接失败，原因是数据库用户实际仍接受旧密码；随后在 postgres 容器内执行 `ALTER USER postgraduate WITH PASSWORD 'postg2536';`，并重新启动 app。

**最终验证结果**：

- `deploy-app-1` 状态为 healthy。
- `deploy-nginx-1` 正常运行。
- `deploy-postgres-1` 与 `deploy-redis-1` 未重启，状态仍为 healthy。
- app 容器内 `http://localhost:8000/health` 返回 200。
- nginx 本机 HTTPS 入口 `https://127.0.0.1/health` 携带 `Host: xzshub.top` 返回 200。
- nginx 实际挂载已变为 `/opt/2240ai-v2/cert -> /etc/nginx/ssl`。
- nginx 配置校验通过，并读取 `/etc/nginx/ssl/www.xzshub.top.pem` 与 `/etc/nginx/ssl/www.xzshub.top.key`。

**遗留注意项**：

- PostgreSQL 在本次核验中旧密码 `change-me` 仍可认证成功，说明数据库认证状态可能存在旧连接/密码校验缓存或角色密码未按预期完全失效；后续如要严格收敛密码，应单独只读核验 `pg_authid` 加密值或重载数据库认证配置，避免误判。
- compose 文件仍保留 `version: "3.8"`，Docker Compose 会提示 obsolete 警告，但不影响当前运行。
- 服务器 compose 仍使用 `backend/docker/Dockerfile`，尚未切换为仓库推荐 `deploy/Dockerfile.prod`。

### 第二阶段遗留项收敛结果（2026-05-28）

已按“先解决第二阶段遗留问题，再开始第三阶段”的要求继续核验和收敛：

- 旧密码 `change-me` 只在 postgres 容器本机 `127.0.0.1` / `localhost` 连接时仍可通过，原因是容器内 `pg_hba.conf` 对 local、127.0.0.1 和 ::1 使用 `trust`；这不是 app/compose 网络侧认证仍接受旧密码。
- 从 compose 网络 `deploy_default` 连接 `postgres` 时，`postg2536` 可认证成功，`change-me` 已认证失败；app 实际通过 compose 网络连接，因此生产服务侧密码已收敛到 `postg2536`。
- 已移除服务器 `deploy/docker-compose.prod.yml` 顶部 `version: "3.8"`，`docker compose config --services` 不再出现 obsolete 警告。
- 当前服务名已对齐为 `postgres`、`redis`、`app`、`nginx`。
- `deploy-app-1`、`deploy-postgres-1`、`deploy-redis-1` 均为 healthy，`deploy-nginx-1` 正常运行。
- app 容器内 `/health` 与 nginx HTTPS `/health` 均返回 200。

**第二阶段剩余决策项**：

服务器 compose 仍使用 `backend/docker/Dockerfile`，尚未切换为仓库推荐的 `deploy/Dockerfile.prod`。该项会触发 app 镜像重建，属于构建入口切换，不建议在进入 `.deployignore` 同步前强行修改；当前运行态已健康，建议把它放入第四阶段“日常 app 单服务更新脚本/构建入口收敛”一起处理。

### 第三阶段：接入 `.deployignore` 同步流程

**目标**：让部署同步显式使用 `.deployignore` 或等价排除规则，先减少上传体积和敏感文件误传风险，不改变生产启动方式。

**具体任务**：

1. 基于第二阶段核验后的部署目录，设计 rsync/scp 同步命令。
2. 同步命令必须排除 `.git/`、`.claude/`、`backend/.venv/`、本地 `.env`、密钥、数据库、缓存、上传/static 和日志。
3. 优先使用 dry-run 或测试目录验证 `.deployignore` 覆盖范围。
4. 确认同步内容只包含运行所需源码、部署配置和必要静态配置，不包含服务器独立维护的 `backend/.env`、证书和密钥。
5. 明确 `/loginkey.pem` 仅是服务器侧根目录密钥位置，不能通过 Git 或本地同步上传仓库内 `loginkey.pem`。
6. 保留旧手工同步方式作为回滚路径，暂不删除旧部署入口。

**验收标准**：

- dry-run 输出中不包含 `loginkey.pem`、`backend/postgraduate.db*`、`backend/static/`、`.claude/`、`backend/.venv/`、`.pytest_cache/`。
- 实际同步不会覆盖服务器 `backend/.env`、证书、密钥和数据库 volume。
- 同步耗时和传输体积相对全量工作区同步明显下降。

**风险/回滚要点**：

- `.deployignore` 是同步边界，不等同于服务器运行文件清单；首次接入应 dry-run 并人工复核。
- 如果排除规则误排除了生产必需文件，回滚到旧同步方式并补充规则。
- 不在本阶段修改 compose 的服务拓扑或删除旧部署文件。

### 第三阶段 dry-run 验证结果（2026-05-28）

已在本地使用 `.deployignore` 对服务器测试目录执行 rsync dry-run，目标为 `/opt/2240ai-v2-sync-dryrun/`，未对生产目录 `/opt/2240ai-v2/` 执行实际同步，也未重启或修改任何生产容器。

使用的 dry-run 命令形态：

```bash
rsync -azn --itemize-changes --stats --exclude-from=".deployignore" -e "ssh -i loginkey.pem -o BatchMode=yes" ./ root@8.163.56.109:/opt/2240ai-v2-sync-dryrun/
```

**首次 dry-run 结果**：

- dry-run 输出未包含 `loginkey.pem`、本地 `.env`、数据库文件、`.claude/`、`backend/.venv/`、`.pytest_cache/`、`backend/static/` 等敏感或本地运行产物。
- 发现 `backend/tests/`、`backend/test_e2e_stage11.py`、`miniprogram/__mocks__/` 仍会进入同步范围，属于生产同步噪声。
- 统计结果为 `318` 个文件、`266` 个 regular files，总文件大小 `36,424,668` bytes。

**已修复同步边界**：

`.deployignore` 已补充测试文件和 fixture 排除规则：

```gitignore
# Test files and fixtures
backend/test_*.py
backend/tests/
miniprogram/__mocks__/
```

**二次 dry-run 结果**：

- dry-run 输出中敏感路径检查为空，测试目录和 mock fixture 已不再进入同步范围。
- 统计结果降为 `268` 个文件、`221` 个 regular files，总文件大小 `1,105,705` bytes。
- 相比首次 dry-run，同步边界明显收窄，当前 `.deployignore` 已满足第三阶段 dry-run 验收要求。

**仍未执行项**：

- 尚未对生产目录 `/opt/2240ai-v2/` 执行实际 rsync，同步仍停留在 dry-run 验证阶段。
- 尚未将 rsync 命令固化到 `deploy/deploy.sh` 或独立部署脚本；脚本接入和 app 单服务更新应放入第四阶段处理。
- 服务器 `backend/.env`、证书、密钥和数据库 volume 仍应保持服务器侧独立维护，不应由本地同步覆盖。

### 第三阶段实际同步完成结果（2026-05-28）

已先对生产目录 `/opt/2240ai-v2/` 执行同一 `.deployignore` 边界的 rsync dry-run，敏感路径检查为空，然后执行实际同步。本阶段同步只更新服务器工作区文件，不执行 `build`、`up`、`restart`、`migrate` 或 `down`。

实际同步命令形态：

```bash
rsync -az --itemize-changes --stats --exclude-from=".deployignore" -e "ssh -i loginkey.pem -o BatchMode=yes" ./ root@8.163.56.109:/opt/2240ai-v2/
```

**实际同步统计**：

- 同步文件清单规模：`268` 个文件、`221` 个 regular files。
- 实际传输 regular files：`105` 个。
- 总文件大小：`1,105,705` bytes。
- 实际传输文件大小：`725,273` bytes。
- `loginkey.pem`、本地 `.env`、数据库文件、`.claude/`、`.git/`、`backend/.venv/`、测试目录和 mock fixture 未进入同步范围。

**同步后修正项**：

首次实际同步后发现本地 `deploy/docker-compose.prod.yml` 覆盖了服务器已收敛的 compose 形态，使 `redis` 服务从 `config --services` 中消失。已立即修正本地生产 compose，使其重新包含 `postgres`、`redis`、`app`、`nginx`，保持服务器 `POSTGRES_*` / `DATABASE_URL` 环境变量策略、`backend/docker/Dockerfile` 构建入口、`./../cert:/etc/nginx/ssl:ro` 证书挂载和 Python healthcheck，然后仅重新同步该 compose 文件。

**最终验证结果**：

- `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml config --services` 输出 `postgres`、`redis`、`app`、`nginx`。
- `deploy-app-1` 仍为 running/healthy，`deploy-nginx-1` 正常运行，`deploy-postgres-1` 与 `deploy-redis-1` 仍为 running/healthy。
- app 容器内 `http://localhost:8000/health` 返回 `200`。
- nginx HTTPS 入口 `https://127.0.0.1/health` 携带 `Host: xzshub.top` 返回 `{"status":"ok","env":"production"}`。
- 服务器 `backend/.env`、`cert/www.xzshub.top.pem`、`cert/www.xzshub.top.key` 仍存在；`loginkey.pem`、根目录 `.env`、`.claude/`、`.git/`、`backend/.venv/`、`miniprogram/__mocks__/` 不存在于部署目录。

**第三阶段结论**：

`.deployignore` 已完成 dry-run 验证并实际用于同步生产目录，敏感文件和本地运行产物未上传，生产容器未因同步动作被重启。下一步可以进入第四阶段，但应注意本地生产 compose 已按服务器当前健康运行态修正；后续构建入口从 `backend/docker/Dockerfile` 切换到 `deploy/Dockerfile.prod` 应作为第四阶段单独决策，不应和同步边界混在一起。

### 第四阶段：改造日常 app 单服务更新脚本

**目标**：把日常后端部署从全服务重启改为 `app` 单服务 build/up，保留 Docker layer cache，避免影响数据库、redis 和 nginx。

**具体任务**：

1. 基于已确认的生产 compose 文件 `deploy/docker-compose.prod.yml` 改造或新增日常部署命令。
2. 日常路径使用 `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml build app` 或等价命令。
3. 更新容器使用 `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml up -d --no-deps app` 或等价命令。
4. 默认不使用 `docker compose down`、`--no-cache`、`--pull`、`docker system prune -a`；注意当前 `deploy/deploy.sh` 仍存在 `--no-cache`，且迁移默认执行，尚未完成本阶段改造。
5. 如需要基础镜像升级，设计显式参数或独立维护流程，而不是日常默认执行 `--pull`。
6. 保留旧脚本或旧命令说明，作为紧急回退入口；不删除旧部署入口。

**验收标准**：

- 日常后端部署只重建并替换 `app` 服务。
- 部署过程中 postgres/redis 容器不重启，nginx 不被无关重启。
- requirements 未变化时，pip 安装层能够命中缓存。
- 部署完成后健康检查或核心接口可访问。

**风险/回滚要点**：

- 如果新 `app` 容器启动失败，回滚到上一镜像或旧脚本路径。
- 修改脚本前应保留当前脚本备份或通过 Git 可回退。
- 不在脚本中删除 volumes，不执行 `down --remove-orphans` 作为日常默认动作。

### 第四阶段脚本改造和验证结果（2026-05-28）

本阶段先将 `deploy/deploy.sh` 改造为 app 单服务更新脚本并完成验证；第五阶段后，当前推荐生产脚本已进一步收敛为 `deploy/scripts/deploy.sh`。

**脚本改造结果**：

- `deploy/deploy.sh update` 不再执行 `git pull`，代码同步由第三阶段已验证的 rsync 流程负责。
- `deploy/deploy.sh update` 不再使用 `--no-cache`，改为 `docker compose ... build app`，保留 Docker layer cache。
- `deploy/deploy.sh update` 不再默认执行数据库迁移；迁移保留为显式命令 `bash deploy/deploy.sh migrate`。
- 日常更新使用 `docker compose ... up -d --no-deps app`，只替换 `app` 服务，不主动重启 `postgres`、`redis`、`nginx`。
- `status` / `update` 增加健康检查：先检查 app 容器内 `http://localhost:8000/health`，再用本机 nginx HTTPS 入口和 `Host: xzshub.top` 检查 `/health`。
- `deploy/scripts/deploy.sh` 后续已承接为当前推荐生产入口，日常生产部署使用 `bash deploy/scripts/deploy.sh update`。

**验证过程和修正项**：

- 本地已通过 `bash -n deploy/deploy.sh` 和 `bash -n deploy/scripts/deploy.sh`。
- 服务器已通过 `bash -n deploy/deploy.sh`、`bash -n deploy/scripts/deploy.sh` 和 `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml config --services`，服务输出为 `redis`、`postgres`、`app`、`nginx`。
- 首次执行 `bash deploy/deploy.sh update` 时，构建层命中缓存，但 app 刚启动即检查健康接口，出现短暂 `ConnectionRefusedError`。已在脚本健康检查中加入有限重试，避免 app 启动窗口期误判失败。
- 排查过程中发现一次全服务被停止，随后使用 `docker compose --env-file backend/.env -f deploy/docker-compose.prod.yml up -d` 恢复服务；该恢复动作导致 `postgres`、`redis`、`nginx` 启动时间刷新，不属于最终日常 update 路径的预期行为。
- 全服务恢复后，PostgreSQL volume 内实际只存在旧角色 `pguser`，与服务器 `.env` 中 `postgraduate` 角色不一致，导致 app 认证失败。已在 postgres 容器内创建/修复 `postgraduate` 登录角色、数据库和授权，并重启 app 恢复健康。

**最终 app-only 更新验证结果**：

- 再次执行 `bash deploy/deploy.sh update` 成功完成。
- Docker build 输出显示依赖安装层和源码层均命中缓存，未使用 `--no-cache`。
- 更新过程中只执行 `deploy-app-1` recreate；`deploy-nginx-1`、`deploy-postgres-1`、`deploy-redis-1` 的 `StartedAt` 未变化，说明最终验证中的日常 update 未主动重启 nginx/db/redis。
- 更新完成后 nginx HTTPS `/health` 返回 `{"status":"ok","env":"production"}`。
- 等待健康检查稳定后，`deploy-app-1`、`deploy-postgres-1`、`deploy-redis-1` 均为 healthy，`deploy-nginx-1` 正常 running。

**第四阶段结论**：

日常部署路径已收敛为：先使用第三阶段 rsync 同步代码，再在服务器执行 `bash deploy/scripts/deploy.sh update`。该路径不默认 `git pull`、不默认迁移、不禁用 Docker 缓存、不执行全服务 `down/up`，最终验证只替换 app 服务。构建入口仍保持当前服务器健康运行的 `backend/docker/Dockerfile`，切换到 `deploy/Dockerfile.prod` 应作为后续独立验证项处理。

### 第五阶段：补充健康检查、迁移与回滚流程

**目标**：让自动化部署具备部署前检查、部署后验证和失败回滚能力，同时保持数据库迁移为显式动作。

**具体任务**：

1. 增加部署前检查：服务器 `.env` 是否存在、compose 文件是否存在、Docker daemon 是否可用、目标服务名是否存在。
2. 增加部署后检查：`app` 容器状态、日志尾部、健康接口或核心 API 返回。
3. 数据库迁移仅在 schema 变更时显式执行 `alembic upgrade head`，不作为所有部署的无条件步骤；当前 `deploy/deploy.sh` 仍默认执行迁移，需在本阶段后续改造中处理。
4. 设计失败处理：新容器失败时查看日志、停止继续操作、保留旧数据和 volume。
5. 记录手工回滚步骤：切回上一镜像/上一代码版本，重新 `up -d --no-deps app`。

**验收标准**：

- 部署失败能在脚本或流程中被明确发现，而不是静默成功。
- 未涉及 schema 变更的普通代码部署不会执行数据库迁移。
- 回滚步骤清晰，不依赖删除数据库 volume 或全服务 down。

**风险/回滚要点**：

- 健康检查不能误判 AI/OCR 外部依赖失败为核心服务失败；AI 是辅助，核心刷题功能优先。
- 数据库迁移前需要备份策略；迁移失败不得自动清理数据库。
- 回滚流程应优先回滚 `app`，避免扩大到 nginx/db/redis。

### 第五阶段脚本强化和验证结果（2026-05-29）

已将当前推荐生产脚本 `deploy/scripts/deploy.sh` 补充为带部署前检查、部署后健康验证和失败日志输出的 app-only 更新入口，并同步到服务器 `/opt/2240ai-v2/deploy/scripts/deploy.sh` 验证。

**脚本强化结果**：

- 部署前检查 Docker CLI、Docker Compose v2、Docker daemon、`deploy/docker-compose.prod.yml`、服务器侧 `backend/.env` 和 `app` 服务声明。
- `update` 仍只执行 `build app` 和 `up -d --no-deps app`，不执行 `git pull`，不默认执行数据库迁移，不主动重启 `postgres`、`redis`、`nginx`。
- `migrate` 保留为显式命令 `bash deploy/scripts/deploy.sh migrate`，仅在确认 schema 变更时执行。
- 部署后先检查 app 容器内 `http://localhost:8000/health`，再检查 nginx 本机 HTTPS 入口并携带 `Host: xzshub.top`。
- app 健康检查最终失败时会输出最近 80 行 app 日志，并让 `update` 以非零状态失败，避免静默成功。

**验证结果**：

- 本地已通过 `bash -n deploy/scripts/deploy.sh`。
- 服务器已通过 `bash -n deploy/scripts/deploy.sh` 和 `bash deploy/scripts/deploy.sh status`，状态检查显示 `app`、`postgres`、`redis` 为 healthy，`nginx` 正常 running，app 容器内健康检查和 nginx HTTPS 健康检查均通过。
- 已执行 `bash deploy/scripts/deploy.sh update` 验证 app-only 更新：Docker build 命中缓存，更新过程中只重新创建 `deploy-app-1`。
- 更新后 `https://127.0.0.1/health` 携带 `Host: xzshub.top` 返回 `{"status":"ok","env":"production"}`。
- `deploy-postgres-1`、`deploy-redis-1`、`deploy-nginx-1` 的运行时间保持约 12 小时，说明本次 Stage 5 验证未主动重启数据库、redis 或 nginx。
- `deploy-app-1` 在 Docker healthcheck 启动窗口后恢复为 healthy。

**回滚/失败处理口径**：

- 普通代码部署失败时优先查看脚本输出的 app 日志和 `docker compose ... logs --tail=80 app`，不要执行 `down` 或删除 volume。
- 若新 app 镜像不可用，先回滚服务器代码到上一同步版本，再执行 `bash deploy/scripts/deploy.sh update` 重新构建并替换 app。
- 涉及 schema 的变更必须先备份并显式执行 `bash deploy/scripts/deploy.sh migrate`；迁移失败不得自动清理数据库。

### 第六阶段：收敛部署入口与文档化运维规范

**目标**：在新部署流程稳定后，将“推荐生产入口”和“历史/备用入口”标注清楚，减少后续误用。

**具体任务**：

1. 根据服务器实际对齐结果固化推荐生产 compose 和部署脚本：`deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`。
2. 在文档中标注推荐入口、适用环境和禁止的高风险命令。
3. 对未使用的历史入口先标记为 legacy/备用，不直接删除。
4. 统一部署命令示例、环境变量维护说明、密钥不同步规则和回滚步骤。
5. 如未来确认某些入口长期不用，再单独评估删除或归档。

**验收标准**：

- 文档明确日常部署应该使用哪一个入口。
- 新成员不会在多个 compose 文件之间误选生产入口。
- 高风险命令（`down`、`--no-cache`、默认 `--pull`、volume 删除、`system prune -a`）在文档中有明确限制。

**风险/回滚要点**：

- 不在未验证稳定前删除旧部署入口。
- 如果生产入口发生变化，先更新文档和脚本说明，再逐步清理历史文件。
- 文档必须保持“服务器 `.env` 独立维护、敏感文件不从本地同步”的约束。

### 第六阶段收敛结果（2026-05-29）

已按服务器当前健康运行态完成部署入口文档收敛，避免继续把历史入口误认为推荐生产路径。

**当前推荐路径**：

1. 本地同步代码时使用 `.deployignore`：

```bash
rsync -az --exclude-from=".deployignore" -e "ssh -i loginkey.pem -o BatchMode=yes" ./ root@8.163.56.109:/opt/2240ai-v2/
```

2. 服务器日常 app-only 更新：

```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh update
```

3. 仅在 schema 变更经过确认后显式迁移：

```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh migrate
```

4. 查看状态和健康检查：

```bash
cd /opt/2240ai-v2
bash deploy/scripts/deploy.sh status
```

**入口说明**：

- `deploy/docker-compose.prod.yml` 是当前生产 compose 入口，服务为 `postgres`、`redis`、`app`、`nginx`。
- `deploy/scripts/deploy.sh` 是当前推荐生产部署脚本入口。
- `deploy/scripts/backup.sh` 是当前推荐备份脚本入口。
- `deploy/scripts/health-check.sh` 可用于独立健康检查。
- `deploy/deploy.sh` 是旧推荐入口，当前仅作为兼容转发入口；日常生产部署应直接使用 `deploy/scripts/deploy.sh`。
- `deploy/docker-compose.yml`、`deploy/docker-compose.dev.yml` 和历史 `backend/docker/docker-compose.yml` 不作为当前生产入口。

**禁止作为日常部署默认动作**：

- 不执行 `docker compose down` 或全服务 `up` 来处理普通后端代码更新。
- 不使用 `docker compose build --no-cache`。
- 不默认使用 `--pull`。
- 不执行 `docker system prune -a`。
- 不删除 Docker volumes。
- 不从本地覆盖服务器 `backend/.env`、`cert/`、`certbot/`、密钥或数据库数据。

### 第六阶段历史入口归档结果（2026-05-29）

已完成低风险历史入口标注与兼容转发，避免删除文件导致已有命令或自动化任务直接失效。

- `deploy/deploy.sh` 改为 legacy compatibility entry，仅提示并转发到 `deploy/scripts/deploy.sh`。
- `deploy/backup.sh` 改为 legacy compatibility entry，仅提示并转发到 `deploy/scripts/backup.sh`。
- `deploy/docker-compose.yml` 增加 legacy production-like 标注；当前生产入口仍为 `deploy/docker-compose.prod.yml`。
- `deploy/docker-compose.dev.yml` 增加 development-only 标注，不作为生产入口。
- `deploy/scripts/init-db.sh` 增加 legacy 标注；当前生产迁移入口仍为 `bash deploy/scripts/deploy.sh migrate`。
- GitHub Actions 部署步骤已从旧 compose + unconditional migration + down/up 改为调用 `bash deploy/scripts/deploy.sh update`，避免 CI 默认触发全服务重启和默认迁移。

**注意**：当前 CI 部署脚本不再执行服务器侧 `git pull`。如后续要启用 GitHub Actions 自动部署，需要另行明确代码同步策略；当前已验证的生产路径仍是先 `.deployignore` rsync，再在服务器执行 `bash deploy/scripts/deploy.sh update`。



部署流程已文档化为“`.deployignore` 同步 + `deploy/scripts/deploy.sh update` app-only 更新 + 显式迁移 + 健康检查/日志失败处理”。历史入口暂不删除，只在文档中降级为备用/历史路径；如后续要物理删除或归档，应单独执行一次低风险清理。

### 最终完成标准

自动化部署可视为完成时，应同时满足：

1. 已确认并文档化推荐生产入口为 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`，服务器验证结果一致。
2. 同步流程使用 `.deployignore` 或等价规则，敏感文件、本地数据库、缓存、`.claude/`、虚拟环境不会上传。
3. 日常部署只更新 `app` 服务，不默认重启 postgres/redis/nginx。
4. 日常部署不默认使用 `docker compose down`、`--no-cache`、`--pull`、`docker system prune -a`。
5. 服务器 `backend/.env`、证书、密钥独立维护，不由本地工作区覆盖；`/loginkey.pem` 为服务器侧根目录密钥位置，仓库内 `loginkey.pem` 仍应忽略且不得同步上传。
6. 部署后有健康检查，失败时有明确回滚路径。
7. 数据库迁移是显式、可审查步骤，不与所有普通代码部署强绑定。

## 阶段结论

当前部署慢和误用风险已完成阶段性治理：

1. 本地同步范围已通过 `.gitignore`、`backend/.dockerignore`、`.deployignore` 收敛，敏感文件、本地数据库、缓存、`.claude/`、虚拟环境不会进入普通同步范围。
2. 推荐生产部署入口已收敛为 `deploy/docker-compose.prod.yml` + `deploy/scripts/deploy.sh`。
3. 日常部署路径为 `.deployignore` 同步后执行 `bash deploy/scripts/deploy.sh update`，只重建并替换 `app`，不默认重启 postgres/redis/nginx。
4. 推荐日常路径不执行 `git pull`、不默认迁移、不使用 `--no-cache`、不默认 `--pull`、不执行 `docker compose down` 或 `docker system prune -a`。
5. 服务器 `backend/.env`、证书、密钥和数据卷独立维护，不由本地工作区覆盖；`/loginkey.pem` 是服务器侧根目录密钥位置，不代表仓库内 `loginkey.pem` 应提交或同步上传。
6. 部署后已有 app 容器内健康检查、nginx HTTPS 健康检查和失败日志输出；数据库迁移保留为显式命令。

后续如果要继续优化，应优先做小范围事项：归档/删除历史入口、为证书续签建立自动化、或在 staging 中验证是否切换到 `deploy/Dockerfile.prod`。这些都不应混入普通 app 日常部署流程。
