# 错题 AI 规范复核与后端部署（2026-11-02）

用户要求按 `docs/development/` 检查新代码的内聚性、耦合性，不符合则修改，随后提交并部署。
本轮代码提交为 `9742993a9b89889eed51706a3f9173b4f5801964`，后端于 `2026-11-02T03:17:01.243198+08:00` 完成部署。
小程序源码已包含在代码提交中，微信端仍由用户手动发布。

## 代码与结构

- Admin 连接诊断拆入 `admin_ai_model_test_service`，原 CRUD 服务由 882 降至 626 行；
  新服务325行，共享 Chat 探测177行。新增模块均小于800行、新增函数均小于50行。
- 共用 URL 校验和额度标记；Admin 通过公开候选入口访问模型，避免对私有函数的依赖。
- 提交后探测 best-effort，查询/健康存储异常记录日志，不覆盖已成功的保存结果；
  测试超时使用真实耗时。模型不存在的真实失败写入共享配置冷却。
- 分析准备对象用不可变替换；前端只更新五个检查字段，结构化失败不再额外刷新，普通失败
  没有 availability 时仍会刷新。静默检查持续按冷却时间重试，直到探测成功。
- 额度分类不再重复维护；JSON解码错误继续返回格式错误，API错误码提升限于
  `ai_service_unavailable`。既有匹配缓存补充契约保留。

原有 AI 老师1244行、Admin CRUD及缓存检查长函数属于存量问题，本轮没有扩大拆分范围，
不宣称整个AI领域的所有文件与函数均已满足预算。先前独立审查的8项发现均已修复；
补充审查未返回结果即停止，没有第二次审查完成声明。

## 验证

- 后端相关回归：1435 passed，0 failed；35条既有弃用警告。
- 小程序全量：2564 passed，0 failed；5个渲染fixture共31项通过。
- 运行代码/测试formatter、compileall、workflow YAML、详情边界与页面预算通过。
- Ruff正确性与变更文件债务不增检查通过；保留 `ai_service.py` 既有21个兼容导入F401，
  新增模块严格Ruff通过。代码图谱MCP未在本会话暴露，直接核对已定位源码。
- 三个新镜像均以 `--network none` 验证18份源码SHA、编译与合成模型健康状态逻辑，
  没有连接生产Redis、数据库或上游模型。

## 运行版本

| 服务 | 镜像 ID | 容器 ID |
| --- | --- | --- |
| app | `sha256:26e36717d95e72b1f6ca2c48702de96f8bc66670718110c394c336ba32730589` | `736343d26b8b32ed3ed1651f8a8e418fb9ccf2f9e143fc50357a2e82a945ad3b` |
| worker | `sha256:b749d1a5dc7c90d17ba6c38d8b40f60f0b66add35804d2e74834dde1bd678c57` | `71b663f05c17121b6678256cef6c4c7ebf38a29849c48c8dc008614ba550dcb3` |
| scheduler | `sha256:db23dca7a796234ee224504e00aeb8b31d443e223ee3d7c5d57f347b2166c0f0` | `b45738d6ed3707c90ddd99e2bfb59d3eb8abe6dd7b613f7a1064d35d4f386afe` |

三个运行容器各18份源码均与提交一致；重启次数与启动错误匹配数均为0。
app为healthy，带生产Host的内部 `/health/ready` 返回200；nginx配置检查与reload成功。
公网 `/health/live`、`/health`、`/login` 以及跟随跳转后的 `/` 返回200，公网ready继续受保护返回403。

额外匿名检查中，availability与Admin模型接口均返回既有 `HTTP_403` 鉴权错误。
首轮将预期写成401，核对 `HTTPBearer()` 后按现有403契约复查；没有提供JWT、调用探测或修改鉴权。
这不构成真实用户AI业务链路验收。

## 数据与配置边界

PostgreSQL catalog、完整schema及迁移保持不变：81张表、71个序列、384个索引，
迁移为 `v19_pomodoro_subject_allocations`。未执行迁移。
Admin、PostgreSQL、Redis、nginx容器ID及启动时间不变；生产 `.env`、Compose和nginx配置SHA不变。
本次仅重建app/worker/scheduler，nginx仅检查与reload。

## 备份与回滚

服务器证据目录：`/data/backups/ai_health_review_20261102T030950`。
旧源码、缺失文件清单、容器快照、配置哈希、构建与部署日志和回滚镜像标签均保留。

| 备份 | 字节数 | SHA256 |
| --- | ---: | --- |
| postgraduate.dump | 23,187,010 | `2cf700fb4c26efdd356047c7015a42b3571ff79b2735da5edc3b35602a0673b4` |
| redis.rdb | 9,772 | `460dd590cc3f9a735532a193e710d9b95bd938e1593a3f9cb61423751123e6dd` |

PostgreSQL dump已校验TOC并完整解码，Redis RDB通过 `redis-check-rdb`。
首轮备份脚本假定Redis带口令而停止；核实当前内部Redis无口令且PING成功后完成RDB备份，
原失败记录保留。服务替换发生在两份备份均验证完成之后。

回滚标签：

- `deploy-app:rollback-ai-health-review-20261102T030950`
- `deploy-worker:rollback-ai-health-review-20261102T030950`
- `deploy-scheduler:rollback-ai-health-review-20261102T030950`

本次未触发回滚，没有清理数据库、volume、备份或镜像。

## 验收限制

没有主动发起真实生产模型探测/生成，也没有更新模型配置；历史上游403的凭据、Base URL或权限问题
仍可能需要管理员处理并测试。微信开发者工具编译、模拟器与真机未执行，小程序由用户手动发布。
限定部署检查不等于完整ENV-01..06验收。没有推送Git。

结构化结果：[本轮部署结果](../architecture/refactor-results/wrong-detail-ai-health-review-deploy-2026-11-02.json)。
职责复核：[AI兼容说明 §19](../architecture/AI_ANALYSIS_COMPATIBILITY.md#19-可用性实现的内聚与耦合复核2026-11-02)。
前次部署：[2026-11-01可用性部署](PRODUCTION_AI_ANALYSIS_AVAILABILITY_DEPLOY_2026-11-01.md)。
