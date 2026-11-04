# 错题 AI 可用性门禁生产部署（2026-11-01）

用户要求修复错题详情 AI 分析持续加载并部署后端，同时说明微信端由用户手动发布。本批在 2026-11-01 23:38 左右（Asia/Shanghai）完成 app、worker、scheduler 新镜像替换；Admin、PostgreSQL、Redis 和 nginx 容器未重建。

## 发布内容

本批同步 16 个后端运行文件，包括：

- `backend/app/services/ai/model_health.py`：按模型配置 ID 与配置指纹保存共享健康状态，成功 TTL 30 秒，临时故障 `30/60/120/300` 秒退避，额度/鉴权/模型不存在冷却 5 分钟。
- `backend/app/services/ai/analysis_availability.py`：复用错题分析候选链、合并并发探测、调用真实 OpenAI-compatible `chat/completions`，并提供 availability 查询与运行时拒绝。
- `backend/app/services/ai/analysis_admin_health.py`：把与已保存模型完全匹配的 Admin 测试连接绑定到同一健康状态；保存相关配置后强制重新探测。
- `backend/app/services/ai/connection_probe.py`：Admin 与用户侧共用的最小连接探测。
- `backend/app/services/ai/provider_invocation.py`、`analysis_provider_failure.py`、`analysis_review_invocation.py`：失败响应、缓存保留和可用性拒绝不再按成功模型结果解析。
- `backend/app/services/ai_teacher_408_service.py`、`backend/app/api/v1/ai.py`：AI 老师使用同一门禁，禁用时返回 HTTP 503 的结构化 `ai_service_unavailable`。
- `backend/app/ai/client.py`、`provider_exception.py`、`gateway.py`、`admin_ai_config.py`、`ai.py`、`schemas/ai.py` 及 `admin_ai_config_service.py`：额度分类、候选 runtime、Admin 测试和响应 schema 接线。

源码 SHA 与本地一致，并与三个运行容器内的文件逐一匹配。

## 运行版本

| 服务 | 镜像 ID | 容器 ID |
| --- | --- | --- |
| app | `sha256:45e872e36a0798f37bc15fc68aed7bfdda85cecabdc85c8d1322a6cf14d416b5` | `889f8be8760143f62c5a30da6c3def06168dee92533615d8c067e8e170d45eb6` |
| worker | `sha256:99f41003fff4eae89d0e6dafe2b3cd566644bb1bd944b61cd6c44521e51ab1bf` | `62be2ee42fdc4e498a6be466e5d73f1460189b64a91a63b809954fa2dcfe086a` |
| scheduler | `sha256:d83fb1ee48eeb2e1d18271deb475c1c8f4d3e398f1e95e3028810e3c0a68c324` | `a4b4338e6d9f345c9715228296ca6c25ec59f737837c0c57e5600f56b1ce49a` |

三个服务均处于运行状态，重启次数为 0；本轮启动日志中的
`ERROR`/`CRITICAL`/`Traceback`/`ModuleNotFoundError` 匹配行为 0。app Docker
健康状态为 `healthy`，带生产域名 Host 的内部 `/health/ready` 返回 200。

## 检查结果

- nginx 配置检查通过并完成 reload；公网 `/health/live`、`/health`、`/login` 返回 200。
- 公网 `/` 首次返回 307，跟随跳转后返回 200；公网 `/health/ready` 继续由 nginx 保护并返回 403。
- PostgreSQL 仍为 81 张表、71 个序列、384 个索引；schema/catalog 未变，迁移保持
  `v19_pomodoro_subject_allocations`，本批没有执行迁移。
- Admin、PostgreSQL、Redis、nginx 的容器身份与部署前快照一致；未覆盖生产 `.env`、Compose 或 nginx 配置。

## 备份与回滚

服务器证据目录：

```text
/data/backups/wrong_detail_ai_availability_20261101T231332
```

本批保留了旧源码、变更前后容器快照、构建日志、源码/镜像哈希及保护配置 SHA 文件。

| 备份 | 字节数 | SHA256 |
| --- | ---: | --- |
| PostgreSQL dump | 23,187,081 | `9de80427b113de863decac264561084917feb436ab5dcdef4c0ed13b531121fd` |
| Redis RDB | 9,738 | `60f692acd0f3b1ebe307f646a8aabbc11fe770464015e245c5c980aaf148a3d6` |

回滚镜像标签：

- `deploy-app:rollback-ai-availability-20261101T231332`
- `deploy-worker:rollback-ai-availability-20261101T231332`
- `deploy-scheduler:rollback-ai-availability-20261101T231332`

未执行数据库、Redis、volume 或镜像清理，也未覆盖其他用户数据。

## 发布边界

本次没有主动调用真实生产模型，也没有修改 Admin 模型配置。此前日志中的上游 403
仍可能是凭据、Base URL 或服务调用权限问题；管理员修复并通过已保存模型的连接测试后，
共享健康状态才会自动解除禁用。小程序源码未上传或发布，微信端由用户手动发布；
开发者工具编译、模拟器和真机验收仍未执行。该部署不等于完整 ENV-01..06 验收通过。

结构化机器结果见
[错题 AI 可用性结果](../architecture/refactor-results/wrong-detail-ai-availability-2026-11-01.json)。
上一批 20:41 的单文件修复部署保留在
[AI 后端部署记录](PRODUCTION_AI_ANALYSIS_DEPLOY_2026-11-01.md)。

后续已于2026-11-02完成内聚/耦合复核、提交及新镜像部署，见
[后续部署记录](PRODUCTION_AI_MODEL_HEALTH_REVIEW_DEPLOY_2026-11-02.md)。本页保留2026-11-01部署事实。

---

## 相关链接

- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
