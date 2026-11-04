# 错题详情 AI 后端修复部署（2026-11-01）

用户明确要求“部署改动到服务器中”，并说明“微信端由我手动发布即可”。本批仅同步一个后端运行文件，构建并更新 app、worker、scheduler，2026-11-01 20:41:35（Asia/Shanghai）完成部署核对。小程序由用户手动发布。

## 发布内容

- 文件：`backend/app/services/ai/analysis_review_invocation.py`。
- SHA256：`d95cd4a56dd769f19c4165c40f81082ab28f5460a65f0dc811debb781325023e`；三个运行容器均与此一致。
- 行为：provider 失败或保留历史缓存时直接返回完整响应字典，避免把失败响应当作成功模型结果读取 `.result` / `.runtime`；继续由外层 finally 释放租约。
- 部署前后端 app 源码差异只有该文件；Dockerfile、依赖锁、Compose 与服务器当前版本一致。未同步文档、测试、数据库文件或本地环境配置。

| 服务 | 新运行镜像 ID |
| --- | --- |
| app | `sha256:683576330bea00592d27e78dbea4f5fb4b4471de563ce128d85f27b6852dfedc` |
| worker | `sha256:8550540c304876a930b9f994e4547e12caf2da96a7772961c5a39bac6afce61c` |
| scheduler | `sha256:e0353e2a987e17734d941647bfda0068e742f933423cc650cbb3f8f373b2f3c7` |

## 检查结果

- 复用[本地修复结果](../architecture/refactor-results/wrong-detail-ai-loading-fix-2026-11-01.json)的599项后端及174项错题详情Node回归；本轮核对SHA一致，没有将旧回归记为重新执行。新跑后端compileall、修改Python严格Ruff和diff-check通过。
- 三个新镜像分别在断网、无生产数据卷的临时容器中验证源码SHA、app编译，以及失败/缓存保留/空字典三种响应直接返回；不调用真实模型。
- 最终三个角色运行且重启次数均为0，启动后日志ERROR/CRITICAL/Traceback/ModuleNotFoundError匹配行均为0。该检查仅覆盖本轮部署观察窗口。
- 内部`/health/ready`带生产域名Host请求头返回200，app Docker健康状态为healthy；nginx配置检查及reload通过。公网`/health/live`、`/health`、首页、`/login`均200；公网`/health/ready`继续由nginx保护，返回403。
- 81张表的名称/schema/OID与部署前一致，schema-only导出内容一致（仅忽略pg_dump随机restrict标记），迁移保持`v19_pomodoro_subject_allocations`；没有执行迁移。
- PostgreSQL、Redis、nginx及Admin容器ID/启动时间不变；服务器`.env`、Compose及nginx配置SHA不变。

## 首轮回滚与重试

首轮部署探针漏带生产域名Host，`127.0.0.1`和`localhost`请求均被可信主机校验返回400，脚本误判readiness失败并触发旧镜像回滚。回滚后的旧版本用相同探针同样失败，补齐Host后live/readiness均200；确认是部署探针错误。随后刷新nginx恢复公网，并保留首轮日志和回滚结果。

修正探针、重新核对旧镜像/保护容器及内外健康后，再次依次更新scheduler、worker、app；最终部署检查全部通过，第二次未触发回滚。新旧业务版本均未为解决探针问题放宽可信主机校验。

## 备份与回滚

服务器证据目录：`/data/backups/wrong_detail_ai_deploy_20261101T121401Z/`，目录700，备份文件600。已保留旧源码、三个旧镜像回滚标签及Compose覆盖文件`rollback-images.json`。

| 备份 | 字节数 | SHA256 |
| --- | --- | --- |
| PostgreSQL | 23185834 | `b073ee8e8d201f27a85cab8a8756839d4f5623a9e2c2f4fe3fc2626a8076f4d2` |
| Redis RDB | 9727 | `8caae3f46a766ae873999340266bcad3a0c28a73f97832cf475d0027bc8e11d7` |

PostgreSQL归档TOC和完整解码通过，Redis文件头及redis-check-rdb通过。两份备份为独立时点，不代表跨存储原子恢复点。仅删除本批创建的Redis容器内临时备份文件，未清理既有备份、镜像、缓存或volume。

## 发布边界

小程序四个运行JS文件尚需用户自行发布；管理后台未重建。本批未主动调用真实模型、未修改Admin模型配置，也未执行生产账号业务验收。此前日志中的上游403仍需核对凭据、Base URL与服务权限，本次部署不代表该配置故障已解决；整体ENV门禁状态不变。

[脱敏部署结果](../architecture/refactor-results/wrong-detail-ai-production-deploy-2026-11-01.json)。本轮没有Git提交或推送。

---

## 相关链接

- [[docs/project/PROJECT_RULES.md|PROJECT_RULES]] — 长期项目规则
- [[docs/project/ROADMAP.md|ROADMAP]] — 现行范围
- [[docs/project/CHANGELOG.md|CHANGELOG]] — 项目变更记录
- [[docs/project/DEPLOY_PLAN.md|DEPLOY_PLAN]] — 部署与运维
- [[docs/project/BUGS_HISTORY.md|BUGS_HISTORY]] — 缺陷历史归档
