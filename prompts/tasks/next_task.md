继续执行 Phase 5：发布工程化收口、迁移兼容性与稳定性验收。

当前基准状态：

- Phase 3 已完成
- Phase 4 已完成
- 3 个严格 xfail 已通过根因修复移除
- 新增 2 个 `TestAsyncSessionIsolation` 隔离回归测试
- 两轮全量测试结果一致：
  - 1422 passed
  - 24 xfailed
  - 0 failed
  - 0 xpassed
- OCR regression 全部通过
- OCR case 025 为真正 PASS，不是 xfail 或 skip
- Merge atomicity/idempotency：6/6 passed
- SSE terminal：5/5 passed
- Phase 4 完成报告位于：
  `backend/docs/project/phase4_completion.md`

当前记录的非阻塞风险：

1. 约 112 个 `datetime.utcnow()` 弃用警告
2. Alembic migration 在 SQLite 上执行 `upgrade head` 不兼容，此问题为预存问题
3. 24 个预存 xfail，主要涉及 PDF fixture、AI API key 和其他外部依赖
4. `_pipeline_store` 使用全局字典，存在轻微状态残留或内存增长风险

Phase 5 总目标：

在不破坏 Phase 3、Phase 4 已确认不变量的前提下，完成发布工程化收口，建立明确的数据库迁移策略、时区策略、xfail 治理规则、进程内状态生命周期和发布验收门禁。

不要新增业务功能，不要进行与本阶段无关的大规模重构。

一、建立执行前基线

首先阅读并核对：

- `backend/docs/project/phase4_completion.md`
- 当前 pytest 配置
- Alembic 配置及全部 migration
- CI 配置
- Docker、环境变量示例及启动脚本
- 与时间处理相关的公共工具
- `_pipeline_store` 的定义、写入、读取和清理路径
- 全部 24 个 xfail 的位置及原因

执行并记录初始基线：

1. 全量 pytest collection 数量
2. 全量测试结果
3. warning 分类及数量
4. 24 个 xfail 的完整清单
5. 当前 Alembic：
   - upgrade head
   - downgrade
   - 空数据库初始化
   - 已有数据库升级
     的实际行为
6. `_pipeline_store` 在正常完成、失败、取消和重复执行后的状态

所有后续修改必须与此基线对比。

二、统一 datetime 和时区策略

目标：

消除项目代码中 `datetime.utcnow()` 引起的弃用警告，并明确数据库与 API 的时间语义。

要求：

1. 搜索全部以下用法：
   - `datetime.utcnow()`
   - `datetime.now()`
   - `datetime.today()`
   - `utcnow`
   - naive datetime 与 aware datetime 的比较
2. 区分：
   - 生产代码
   - migration
   - 测试代码
   - 第三方依赖警告
3. 生产代码原则上使用 timezone-aware UTC：
   - `datetime.now(timezone.utc)`
   - 或项目统一的 UTC 时间工具函数
4. 不允许直接机械替换后造成：
   - aware 与 naive datetime 混用
   - 数据库字段比较异常
   - JSON 序列化格式变化
   - 测试冻结时间失效
5. 明确数据库 datetime 字段当前实际约定：
   - 是否存储 naive UTC
   - 是否存储 timezone-aware UTC
6. 如果数据库当前约定必须继续使用 naive UTC，应：
   - 在系统边界生成 aware UTC
   - 在数据库写入边界显式转换
   - 在代码中写明兼容原因
   - 不允许隐式去除 tzinfo
7. API 输出保持 ISO 8601，明确是否带 `Z` 或 `+00:00`
8. 增加回归测试，至少覆盖：
   - 时间对象是否具有预期 tzinfo
   - 序列化格式
   - 时间比较
   - 数据库存取往返
   - 冻结时间测试
9. 最终报告中区分：
   - 已消除的项目警告
   - 无法控制的第三方警告
   - 暂时保留的 migration 警告

禁止仅使用 pytest warning filter 隐藏项目自身警告。

三、Alembic migration 兼容性审计

目标：

确认生产数据库迁移可靠，并明确 SQLite 的支持范围。

首先确定项目正式支持的数据库：

- PostgreSQL
- SQLite
- 或其他数据库

不得默认 SQLite 一定需要完整生产级支持，应根据项目配置、测试和部署文件判断。

执行以下测试：

1. 全新空数据库：
   - `alembic upgrade head`
2. 从当前已知历史 revision 升级到 head
3. `alembic current`
4. `alembic heads`
5. 检查是否存在多个未合并 head
6. 至少验证一次 downgrade，再重新 upgrade
7. 检查 migration 是否：
   - 依赖数据库特有 SQL
   - 修改约束或列时不兼容 SQLite
   - 缺少 batch mode
   - 依赖隐式事务
   - 在数据迁移中假定表为空
   - 不具备幂等或失败恢复能力

如果 SQLite 属于正式支持范围：

1. 修复 `upgrade head` 不兼容问题。
2. 优先使用 Alembic 官方 batch migration 机制。
3. 不允许为了 SQLite 删除生产数据库需要的约束。
4. 增加 SQLite 空库升级回归测试。
5. 如 CI 可运行 PostgreSQL，同时增加 PostgreSQL migration smoke test。

如果 SQLite 只用于轻量测试而不属于正式部署数据库：

1. 不要强行扭曲生产 migration。
2. 在文档和测试配置中明确支持矩阵。
3. 将 migration 集成测试绑定到正式数据库。
4. SQLite 测试只验证其实际承担的功能。
5. 对不适用的 SQLite migration 测试使用明确、窄范围的条件，而不是宽泛 skip。

新增 migration 验收脚本或测试，验证失败时不会留下无法识别的半迁移状态。

四、审计并治理 24 个预存 xfail

为全部 24 个 xfail 建立清单，每项至少记录：

- 测试文件
- 测试名称
- 原因
- strict 是否为 True
- 对应依赖
- 是否可在本地复现
- 是否属于真实缺陷
- 是否属于缺失 fixture
- 是否属于凭证或外部服务依赖
- 是否仍然有效
- 建议处理方式

将其分为四类：

A. 可以直接根因修复
B. 缺少本地 fixture 或测试资源
C. 依赖真实外部服务或 API key
D. 平台、数据库或环境限定

处理要求：

1. 失效的 xfail 必须移除。
2. 可通过补充本地 fixture 修复的，优先补充 fixture。
3. AI API 类测试应优先改为：
   - 单元层 mock/stub
   - 协议契约测试
   - 可选的真实服务集成测试
4. 不得在普通全量测试中强制要求真实 API key。
5. 真实外部服务测试必须有明确 marker，例如：
   - `integration`
   - `external`
   - `requires_api_key`
6. 缺失凭证时应在测试收集或执行前给出明确原因。
7. 不得使用非 strict xfail。
8. 不得把当前失败原因与 xfail reason 不一致的测试继续保留为 xfail。
9. PDF fixture 缺失问题应优先确认：
   - fixture 是否应纳入仓库
   - 是否可程序化生成
   - 是否受版权或体积限制
10. 可以安全生成的 PDF fixture，应使用确定性脚本生成，并增加校验。

本阶段不要求无条件清零全部 24 个 xfail，但必须：

- 尽可能减少可本地解决的 xfail
- 确保剩余 xfail 全部真实、严格、分类清楚
- 外部依赖测试与普通测试套件明确分离

五、修复 `_pipeline_store` 生命周期

目标：

避免全局字典无限增长、跨测试残留或过期任务长期占用内存。

首先分析：

1. `_pipeline_store` 的 key 和 value
2. 创建位置
3. 更新位置
4. 读取者
5. 删除或清理路径
6. 并发访问模型
7. 多 worker 环境下的实际语义
8. 进程重启后的行为
9. 是否保存数据库已有的信息
10. 是否可能被重复 job id 覆盖

根据实际用途选择最小安全方案：

- 任务结束后立即删除
- 终态保留有限时间后清理
- TTL cache
- 有界 LRU
- 使用数据库或 Redis 替代
- 使用 weak reference，仅在语义正确时采用

要求：

1. 不允许只在测试 teardown 中清理生产泄漏。
2. 正常完成、失败、取消和异常路径均必须清理。
3. 清理操作必须具有幂等性。
4. 并发读取和删除不得抛出未处理异常。
5. 如 SSE 或轮询仍需读取终态，必须先确认安全保留窗口。
6. 不得让清理导致客户端无法读取最终结果。
7. 如使用 TTL：
   - TTL 必须可配置
   - 测试中不得依赖真实长时间 sleep
   - 使用可控时钟或直接触发清理
8. 增加测试覆盖：
   - completed 清理
   - failed 清理
   - cancelled 清理
   - 重复清理
   - 并发读取与清理
   - 大量短任务后 store 不持续增长
   - 测试间隔离

六、性能与资源基线

只做发布基线，不做无证据的提前优化。

选择关键路径进行可重复测量：

1. OCR regression 单案例和完整 31 案例
2. batch merge
3. SSE job summary polling
4. pipeline 创建、完成和清理
5. 常用数据库查询
6. 应用启动和测试 collection

记录：

- 执行时间
- 峰值内存，如现有工具可稳定测量
- 数据库查询数量，如项目已有 instrumentation
- 外部调用数量
- PP-OCR 预扫是否产生重复 OCR 成本

重点检查 case 025 修复中 PP-OCR 预扫是否导致同一输入执行两次高成本 OCR。

如果存在重复执行：

1. 优先复用已有 OCR 原始结果。
2. 不得仅为了测试 runner 正确而在生产路径引入额外 OCR。
3. 如果额外预扫仅存在于 regression runner，要在报告中明确。
4. 添加调用次数断言，防止以后出现意外双调用。

不设置没有依据的强制性能数字。先形成稳定基线，再判断是否需要优化。

七、故障注入和恢复验证

对以下场景进行定向测试：

1. Merge commit 前异常
2. Merge commit 后、SSE 读取前异常
3. 数据库连接中断
4. OCR 失败
5. Pipeline 取消
6. 后台 task 被取消
7. Redis/cache 不可用，如项目使用
8. 外部 AI API 超时或返回非法响应
9. 同一请求重复提交
10. 并发重复 merge

验证：

- 不产生部分数据库状态
- 事务和锁被释放
- job 进入明确终态
- SSE 不无限等待
- 重试不会生成重复 batch
- `_pipeline_store` 不残留永久脏状态
- 错误信息可诊断但不泄漏敏感信息

不得通过真实 sleep 制造竞态，使用事件、barrier、mock 或可控 future。

八、发布门禁与 CI 分层

检查并完善测试分层：

1. 默认单元和本地集成测试
2. 数据库 migration 测试
3. 外部服务测试
4. 慢速 OCR/PDF regression
5. 并发与故障注入测试

建议建立明确命令，例如：

- 快速测试
- 全量本地测试
- OCR regression
- migration smoke test
- external integration test
- release candidate validation

具体命令必须以项目当前工具为准，不要凭空引入新的测试框架。

发布候选门禁至少要求：

- 0 failed
- 0 unexpected xpass
- 所有 xfail 均为 strict
- xfail reason 与实际失败一致
- 无项目自身 `datetime.utcnow()` 弃用警告，或有明确保留说明
- 正式数据库可从空库 upgrade 到 head
- migration head 唯一
- OCR case 025 真正 PASS
- Merge 6/6 passed
- SSE 5/5 passed
- Phase 4 隔离回归测试全部通过
- `_pipeline_store` 生命周期测试通过
- 全量测试至少连续执行两轮结果一致
- 不输出 API key、数据库凭证或敏感请求正文

九、回归验证

修改完成后至少执行：

1. 与 datetime 修改直接相关的测试
2. migration 测试
3. 全部原 xfail 相关测试
4. pipeline store 生命周期测试
5. OCR regression
6. Merge atomicity/idempotency
7. SSE terminal
8. Phase 4 的 AsyncSession isolation 测试
9. 全量测试连续两轮
10. warning 汇总

如全量测试数量变化，解释新增、移除或取消 xfail 的具体原因。

十、完成报告

输出：

```
backend/docs/project/phase5_completion.md
```

报告至少包含以下章节：

1. 执行摘要
2. Phase 4 初始基线
3. datetime 与时区策略
4. Alembic migration 审计及支持矩阵
5. 24 个 xfail 分类和处理结果
6. `_pipeline_store` 根因与生命周期方案
7. 修改文件列表
8. 新增和修改测试列表
9. 性能基线
10. 故障注入结果
11. CI 与发布门禁
12. 完整测试命令及实际输出
13. warning 修复前后对比
14. xfail 修复前后对比
15. Phase 3、Phase 4 不变量复验
16. 剩余风险
17. 是否达到正式发布候选标准

最终回复中同时给出简洁摘要：

- 修改了什么
- 修复了多少 warning
- xfail 从多少降到多少
- migration 是否通过
- `_pipeline_store` 是否已解决
- 两轮全量测试结果
- 是否建议发布

重要限制：

- 直接检查、修改并运行测试，不要只输出分析建议。
- 不要通过 warning filter 隐藏项目自身警告。
- 不要把 strict xfail 改成非 strict。
- 不要通过新增 skip 或扩大 xfail 掩盖失败。
- 不要使用真实 API key 写入测试或文档。
- 不要把 SQLite 特性错误地当成正式数据库行为。
- 不要破坏现有 PostgreSQL 迁移语义。
- 不要用 sleep 解决异步问题。
- 不要更改业务断言来迎合当前实现。
- 不要重新引入 Phase 3、Phase 4 已修复的问题。
- 所有完成结论必须有实际命令和测试输出作为证据。
