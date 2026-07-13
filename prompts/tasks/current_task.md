# MemoGrad 后端任务 Prompt：补齐“已掌握撤销”与统一复习语义

你正在维护 MemoGrad / 22408AI 刷题系统的 FastAPI 后端。请直接在现有仓库中完成代码、迁移（如需要）和自动化测试。**不要修改微信小程序前端或管理端。**

## 一、任务背景

微信小程序的 `pages/review-today` 与 `pages/wrong-detail` 已完成 UI/交互升级，前端现在依赖以下能力：

1. 今日复习中标记某个复习计划为“已掌握”后，允许用户在 5 秒内撤销。
2. 错题详情中通过批量错题接口标记“已掌握”后，允许用户在 5 秒内撤销。
3. “已掌握”的统一业务含义：
   - 停止该题后续自动复习调度；
   - 保留错题历史、练习记录、复习记录和统计所需数据；
   - 不等同于“移出错题本”，也不等同于永久删除。
4. “移出错题本”继续使用现有 `remove_from_book` 行为，本任务不为它增加撤销能力。

## 二、开始编码前必须先做的检查

先在仓库中定位并阅读：

- `backend/app/api/v1/` 下复习、错题相关路由；
- `backend/app/services/` 下复习调度、错题本服务；
- `backend/app/models/` 下 `review_schedule`、`wrong_question`、`review_record` 等模型；
- `backend/app/schemas/` 下错题批量操作与复习相关 schema；
- 当前 `POST /api/v1/review/{schedule_id}/master` 的完整实现；
- 当前 `POST /api/v1/wrong-questions/batch` 中 `mark_mastered`、`remove_from_book` 的实现；
- 今日复习概览、下一批、今日结果和错题统计的计算逻辑。

遵循项目现有分层、命名、事务、异常、审计日志和测试风格。不要在路由层重复堆叠业务逻辑。

## 三、必须实现的 API 契约

### 1. 撤销今日复习“已掌握”

新增或补齐：

```http
POST /api/v1/review/{schedule_id}/unmaster
Authorization: Bearer <token>
Body: 无
```

前端实际调用：

```js
await api.post(`/review/${scheduleId}/unmaster`)
```

要求：

- 只能操作当前登录用户拥有的 schedule；
- 与现有 `/review/{schedule_id}/master` 互为反向操作；
- 恢复该题进入后续复习调度的资格；
- 不删除或改写历史复习记录；
- 操作后 `/review/today/overview`、`/review/today/result`、下一批复习和相关统计必须一致；
- 幂等：重复 unmaster 不得产生重复记录、重复计划或 500；
- 使用数据库事务，避免并发 master/unmaster 造成不一致；
- 返回格式遵循现有 master 接口的项目惯例。前端不依赖特定文案，但必须是 2xx 成功响应。

### 2. 错题批量操作新增 `unmark_mastered`

扩展现有接口：

```http
POST /api/v1/wrong-questions/batch
Content-Type: application/json
Authorization: Bearer <token>

{
  "action": "unmark_mastered",
  "ids": [123]
}
```

前端实际调用：

```js
await api.post('/wrong-questions/batch', {
  action: 'unmark_mastered',
  ids: [wrongQuestionId],
})
```

要求：

- 在 batch action schema/枚举中加入 `unmark_mastered`；
- 保持现有请求结构与响应结构，至少继续返回现有的 `updated_count` 字段；
- 只能操作当前用户拥有的错题记录；
- 与现有 `mark_mastered` 互为反向操作；
- `mark_mastered` 与 `unmark_mastered` 必须复用统一服务逻辑，并与 review master/unmaster 的最终业务状态一致；
- 不创建重复复习计划；
- 不删除错题历史；
- 对空 ids、重复 ids、部分不存在、跨用户 ids 的处理严格遵循现有 batch 接口惯例，不要静默越权；
- 幂等并具备事务一致性。

### 3. 保持现有操作不变

以下前端调用已经存在，不得破坏：

```json
{
  "action": "mark_mastered",
  "ids": [123]
}
```

```json
{
  "action": "remove_from_book",
  "ids": [123]
}
```

`remove_from_book` 本轮不增加恢复接口。确认它是“从当前错题本隐藏/移出”，而不是误删题库题目、练习记录或复习历史。若现有行为与此冲突，先在实现说明中指出，再做最小、安全、向后兼容的修正。

## 四、统一业务语义

请抽取或整理一个服务层入口，保证以下入口不会出现不同状态：

- `POST /review/{schedule_id}/master`
- `POST /review/{schedule_id}/unmaster`
- wrong-question batch `mark_mastered`
- wrong-question batch `unmark_mastered`

### Master 后

- schedule/题目不会进入未来的自动复习候选；
- 错题记录和历史记录保留；
- GET 错题详情能以现有字段或新增的向后兼容字段反映已掌握状态，优先确保返回 `is_mastered: true`；
- 今日复习剩余数、已掌握数等统计按现有产品定义更新。

### Unmaster 后

- 恢复进入复习调度；
- 不能伪造一次“答题”或删除此前掌握操作之前的历史；
- GET 错题详情返回 `is_mastered: false`；
- 今日概览和后续批次可重新看到该题，具体是否“立即到期”应遵循现有调度算法。

## 五、可逆状态的实现要求

先检查现有 master 到底修改了哪些字段。不要猜字段名。

优先级：

1. 如果现有字段足以无损反转，直接复用；
2. 如果 master 会覆盖无法推导的调度状态，请增加**最小必要的可逆元数据**，并提供 Alembic 迁移；
3. 可逆元数据只保存 master 实际覆盖且恢复所需的字段，不复制整行；
4. 对部署前已经处于 mastered、没有快照的旧记录，提供确定性 fallback：优先从最后一条有效复习记录与现有算法恢复；仍无法恢复时，将其恢复为合法的待调度/到期状态，并在代码注释与实现说明中明确；
5. unmaster 成功后清理一次性快照，或按项目审计策略保留，但不能影响下次 master/unmaster。

如模型变更：

- 创建规范 Alembic migration；
- 兼容 PostgreSQL 生产环境与 SQLite 开发/测试环境；
- 不依赖仅在启动时 `create_all` 才能工作的行为。

## 六、并发与事务

至少处理以下情况：

- 同一 schedule 连续 master → unmaster → master；
- 两个请求几乎同时 master/unmaster；
- batch 中包含多个 ids，其中一个处理失败；
- wrong_question 与 review_schedule 关联缺失或已被移出错题本；
- 重试同一请求。

沿用项目现有事务边界和锁策略。PostgreSQL 下必要时对目标记录加行锁；SQLite 测试下保持可运行。不要引入分布式锁，除非现有服务已有统一机制且确有必要。

## 七、测试要求

请补充后端自动化测试，至少覆盖：

1. 当前用户 master schedule 成功；
2. master 后 unmaster 成功；
3. master → unmaster 的状态往返，历史 review records 数量不减少；
4. 重复 master 幂等；
5. 重复 unmaster 幂等；
6. 不能操作其他用户的 schedule；
7. batch `mark_mastered` 后 `unmark_mastered` 状态往返；
8. batch 包含重复 id；
9. batch 包含不存在或跨用户 id，行为与现有规范一致且不越权；
10. 操作后错题详情的 `is_mastered` 正确；
11. 操作后今日 overview/result/next-batch 的关键计数与候选集正确；
12. `remove_from_book` 仍可用且不会永久删除历史；
13. 事务中途异常时不留下半更新状态；
14. 若增加迁移，至少验证 upgrade 可执行，必要时验证 downgrade。

运行与本任务相关的测试，并尽量运行项目完整后端测试集。修复由本次改动引起的失败，不要通过删除断言、跳过测试或放宽权限检查来“通过”。

## 八、兼容性与非目标

- 不修改现有前端调用路径和 payload；
- 不修改微信小程序；
- 不修改管理端；
- 不改变 AI、OCR、导题逻辑；
- 不把“已掌握”实现为永久删除；
- 不给 `remove_from_book` 新增撤销接口；
- 不做无关重构；
- 保持现有 API 错误码和响应风格。

## 九、交付说明

完成后输出：

1. 改动文件列表；
2. API 契约说明；
3. master/unmaster 状态转换说明；
4. 是否增加数据库字段与迁移；
5. 旧 mastered 数据的 fallback 行为；
6. 测试命令和结果；
7. 仍存在的风险或需要产品确认的边界。

先阅读代码与测试，再实施；不要只给方案或伪代码。
