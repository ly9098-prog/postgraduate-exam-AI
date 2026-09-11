/goal 修复刷题 sequential 模式在并发“开始刷题”请求下可能分配重复题目的遗留问题。

背景：
当前 sequential 进度仍主要基于已经持久化的 PracticeRecord 计算，因此存在一个并发窗口：

1. 请求 A 和请求 B 几乎同时执行“开始刷题”；
2. 两个请求都在 PracticeRecord 尚未写入前读取到相同的 sequential progress；
3. 两者可能选择到同一批题目；
4. 当前实现不能保证数据库层面的绝对不重复。

此前为了避免擅自扩大 schema，没有处理这个问题。现在允许为此增加必要且最小化的数据库 schema / Alembic migration。

目标：
对代码仓库进行完整排查并直接实现数据库级 reservation 机制，使同一用户、同一刷题范围下的多个并发“开始刷题”请求，在 sequential 模式下不能 reservation 到相同题目。

不要只给设计方案，直接修改代码、补充迁移和测试，并完成验证。

核心正确性要求：

1. 数据库是 reservation 的最终一致性来源。
   - 不能仅依赖 Python asyncio.Lock、进程锁、Redis lock 或“先查再写”的应用层逻辑。
   - 多进程、多 worker、多实例并发时也必须成立。

2. sequential 选题必须同时排除：
   - 已经通过 PracticeRecord 持久化完成/进入历史进度的题目；
   - 当前仍有效、已被其他并发 start 请求 reservation 的题目。

3. “选择题目 + 建立 reservation”必须具有数据库原子性。
   必须消除以下竞态：
       SELECT candidate questions
       -> 两个事务得到相同结果
       -> 分别 INSERT reservation
   不允许用捕获唯一约束异常后直接返回重复结果这种伪修复。

4. 数据库层必须存在足以保证“不重复 reservation”的约束。
   优先采用最小、清晰且可维护的 schema。
   可以新增 reservation 表或等价结构，但必须说明为什么这样设计。

5. reservation 至少应能关联：
   - user
   - practice/session/start request（选择符合项目现有模型的标识）
   - question/item
   - practice scope / mode 中实际需要区分 reservation 唯一性的字段
   - created_at
   如系统确实需要 lease/expiry 才能安全恢复，再增加 expires_at/status；
   不要为了“可能以后有用”无限扩展字段。

6. 明确定义 reservation 生命周期：
   - start 成功返回后 reservation 如何存在；
   - PracticeRecord 成功落库后 reservation 如何转化/释放；
   - start 中途抛异常如何处理；
   - 客户端拿到题目后长期不提交怎么办；
   - 重试同一个 start/request_id 时是否应该复用原 reservation，而不是再次占题；
   - reservation 过期后如何安全回收。
   必须避免永久占题，也不能因为清理过早重新发出仍在作答的题。

7. 保持 sequential 的原有业务顺序。
   reservation 机制用于解决并发占用，不得把 sequential 改成随机选题。
   单请求情况下，行为应与当前 sequential 逻辑兼容。

8. 不破坏其他模式。
   仔细检查 random、wrong questions、favorites、知识点筛选或仓库中其他 practice mode。
   如果 reservation 只应该作用于 sequential，就把作用范围限制清楚，不要改变其他模式语义。

9. 考虑幂等。
   如果现有“开始刷题”接口已经有 request_id/session_id/idempotency key，应复用现有机制。
   同一个逻辑请求因网络重试重复调用时，不应生成第二份 reservation 或跳过额外一批题。

10. 并发事务必须基于项目实际使用的数据库实现正确处理。
    重点验证生产数据库 PostgreSQL。
    如果测试环境使用 SQLite，也应尽量保持测试兼容，但不能为了 SQLite 测试牺牲 PostgreSQL 下的并发正确性。
    可以使用符合当前 SQLAlchemy 版本的：
    - row locking
    - SELECT ... FOR UPDATE / SKIP LOCKED
    - advisory lock
    - 唯一约束 + 原子 INSERT/UPSERT
    或其他数据库方案。
    请根据当前模型和查询方式选择最小且可靠的实现，不要机械套用某一种方案。

11. 注意死锁和锁粒度。
    不要无必要地锁整个 questions 表。
    优先限制到同一 user + practice scope 对应的资源。
    并发请求应能够正常完成，而不是靠串行化整个系统实现正确性。

12. 增加 Alembic migration。
    - revision/down_revision 必须接到当前真实 migration head；
    - upgrade/downgrade 可执行；
    - 索引和 unique constraint 要与实际并发查询匹配；
    - 不要修改已有历史 migration；
    - 检查 migration graph 仍然只有预期 head。

重点先检查这些链路，实际路径以仓库为准：
- “开始刷题”API/router/service
- sequential 题目选择逻辑
- PracticeRecord 的读取和写入逻辑
- batch/session/request_id 创建逻辑
- 提交答案/结束刷题逻辑
- pending/resume/recovery 逻辑
- SQLAlchemy models
- Alembic migrations

验收测试必须至少包含：

A. 基础 sequential：
同一个用户连续开始两次，第二批从正确的后续位置开始。

B. 真并发：
对同一个 user + 相同 practice scope 同时发起至少 2 个 start 请求。
使用真正并发事务，而不是顺序调用。
断言：
    set(batch_A.question_ids) ∩ set(batch_B.question_ids) == empty
并验证各请求得到的题目仍符合 sequential 顺序约束。

C. 更高并发：
例如同时 5～10 个 start 请求，在题量足够时所有 reservation 两两无交集。
题量不足时应按照现有业务约定稳定返回，不得重复发题填满 batch。

D. 不同用户：
两个不同用户可以各自拿到相同题目，不能因为全局 reservation 被错误互斥。

E. request 幂等：
相同 request_id/session key 重试，不额外 reservation 下一批题。

F. 事务失败：
模拟 reservation 创建后的事务异常/rollback，确认不会留下幽灵 reservation。

G. stale reservation：
若设计包含 expiry，验证过期 reservation 可以恢复；
尚未过期 reservation 不会被抢占。

H. PracticeRecord 衔接：
reservation 对应题目提交并持久化后，后续 sequential progress 正确推进；
不能因为 reservation 清理造成题目再次出现。

I. 其他 practice mode：
相关已有测试保持通过，确认未改变非 sequential 模式行为。

J. migration：
在空数据库和已有 schema 场景验证 upgrade；
必要时验证 downgrade；
检查 Alembic revision graph。

完成修改后执行：
- 与 practice/start/sequential/session/submit 相关的测试
- 新增的 reservation 并发测试
- 后端 compileall / 静态语法检查
- Alembic migration graph 检查
- 仓库已有适用测试套件

在实现前先阅读现有代码，不要凭上述名称猜测文件路径或模型。
优先复用项目已有 session、request_id、UTC 时间、事务和 repository/service 约定。

如果调查后发现现有 schema 中已经存在可以提供同等数据库级互斥保证的结构，应优先复用，而不是无条件新增表；但必须通过并发测试证明不存在重复 reservation。

不要：
- 只加 asyncio.Lock/threading.Lock；
- 只加 Redis 锁；
- 只把 PracticeRecord 查询放进事务却没有真正产生数据库互斥；
- 用 sleep 降低竞态概率；
- 通过单进程测试就宣称并发安全；
- 为了修这个问题大规模重构整个刷题系统；
- 修改无关功能；
- 静默吞掉 IntegrityError；
- 在没有测试证明的情况下宣称“已解决并发问题”。

最终输出：
1. 根因和原并发窗口；
2. 最终采用的 reservation/locking 设计；
3. schema/migration 变化；
4. 实际修改文件；
5. reservation 生命周期和异常恢复语义；
6. 并发安全为什么成立；
7. 执行过的测试及结果；
8. 仍存在的边界或限制。

只有在真正跑完验证后才能声明完成。

```
实现取舍上优先选择“最小 schema 变化 + 明确数据库唯一约束 + 短事务原子 reservation”，不要让数据库事务覆盖 OCR、LLM、网络请求或其他耗时操作；锁只应覆盖候选题确定和 reservation 落库所需的最短临界区。
```

