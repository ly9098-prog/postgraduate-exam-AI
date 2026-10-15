# GitHub Packages 发布说明

本项目通过 GitHub Container Registry（GHCR）发布可部署的容器镜像。容器包由
`.github/workflows/publish-images.yml` 构建，不在仓库中保存个人访问令牌。

## 发布的镜像

| 镜像 | 构建入口 | 用途 |
| --- | --- | --- |
| `ghcr.io/ly9098-prog/postgraduate-exam-ai-backend` | `backend/docker/Dockerfile` | FastAPI Web、worker、scheduler 共用运行时 |
| `ghcr.io/ly9098-prog/postgraduate-exam-ai-admin` | `admin-frontend/Dockerfile` | Next.js 管理后台 |

后端三个进程使用同一镜像，通过 Docker Compose 的 `command` 和环境变量区分角色，
不分别发布 worker 或 scheduler 镜像。GHCR 镜像仅包含应用代码和运行依赖，不包含
`.env`、生产凭据、数据库、上传文件、导出文件或备份。

## 触发方式

正式 Release 发布时，`Publish Container Images` 工作流自动构建 Release 标签指向的
提交并推送两个镜像。工作流也支持手动触发，用于补发已经存在的 Release：

1. 在 GitHub 仓库的 Actions 页面打开 `Publish Container Images`。
2. 选择 `Run workflow`。
3. 输入已存在的语义化标签，例如 `v3.6.6`。
4. 正式稳定版本启用 `publish_latest`；预发布版本应关闭。

工作流只接受 `vX.Y.Z` 形式的标签，可带预发布后缀。自动发布预发布 Release 时不会
更新 `latest`。

## 镜像标签

以 `v3.6.6` 为例，稳定版本发布后生成：

```text
v3.6.6
3.6.6
3.6
3
sha-4c0794bf
latest
```

`sha-*` 使用 Release 标签实际指向的 Git 提交，不使用工作流文件所在分支的提交。
镜像还携带源码仓库、版本和提交号等 OCI 标签，并生成 provenance 与 SBOM。

## 拉取镜像

公开 Package 可以直接拉取：

```bash
docker pull ghcr.io/ly9098-prog/postgraduate-exam-ai-backend:v3.6.6
docker pull ghcr.io/ly9098-prog/postgraduate-exam-ai-admin:v3.6.6
```

私有 Package 需要先使用具备 `read:packages` 权限的凭据登录 GHCR。生产部署当前仍由
`deploy/docker-compose.prod.yml` 在服务器本地构建镜像；切换为拉取 GHCR 镜像属于
单独的部署变更，必须经过回滚和服务器凭据方案评审后再实施。

## 权限与安全

工作流仅使用 GitHub Actions 自动提供的 `GITHUB_TOKEN`，权限限制为：

```yaml
permissions:
  contents: read
  packages: write
```

不得将个人访问令牌写入工作流、仓库 Secrets 以外的位置、文档或部署日志。首次发布后，
应在 Package 设置中确认可见性和仓库关联符合预期。
