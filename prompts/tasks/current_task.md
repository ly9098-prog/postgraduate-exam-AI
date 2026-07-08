你是一名资深全栈工程师和系统审计架构师。请基于当前项目代码，完整修复并优化管理后台的审计日志功能。不要只提供修改建议，需要直接分析代码、完成代码修改、补充测试，并给出最终变更说明。

# 一、项目技术背景

当前项目主要包括：

- 后端：FastAPI、SQLAlchemy AsyncSession、Pydantic、SQLite/PostgreSQL 兼容架构。
- 管理端：Next.js、React、TypeScript、TanStack Query。
- 审计日志模型：`AuditLog`。
- 审计日志写入服务：`write_admin_audit()`。
- 审计日志接口前缀：`/api/admin/v1/audit-logs`。
- 管理端审计日志页面：`/audit-logs`。
- 管理端题库页面：`/questions`。
- 项目中已经使用 APScheduler，并且 FastAPI 已通过 `lifespan` 管理后台任务的启动和停止。

重点检查以下文件及其调用链：

后端：

- `models/admin.py`
- `schemas/admin_audit.py`
- `services/admin_audit_service.py`
- `api/v1/admin_audit_logs.py`
- `services/admin_question_service.py`
- `api/v1/admin_questions.py`
- `core/config.py`
- `main.py`
- 所有 `api/v1/admin_*.py`
- 所有管理后台写操作对应的 service 文件

前端：

- `src/app/(admin)/audit-logs/page.tsx`
- `src/app/(admin)/questions/page.tsx`
- `src/lib/api/client.ts`
- `src/lib/api/types.ts`

# 二、需要解决的问题

## 问题1：其他管理页面的操作没有显示在审计日志中

当前 `/audit-logs` 页面无法完整显示管理员在其他管理页面执行的操作日志。

请系统排查所有管理端写操作接口，包括但不限于：

- POST
- PUT
- PATCH
- DELETE

重点覆盖以下业务模块：

- 题库管理
- 科目管理
- 管理员管理
- 普通用户管理
- 角色与权限管理
- 导入任务管理
- AI 模型配置
- AI 系统设置
- 向量配置
- 水印规则
- 推荐策略和实验管理
- 知识点管理
- 其他管理后台存在数据变更的页面

要求：

1. 扫描所有 `/api/admin/v1` 下的非 GET 接口。
2. 输出一份“接口—操作—是否已有审计—修复方式”的审计覆盖清单。
3. 对没有审计日志的管理操作补充审计写入。
4. 对已有审计日志但字段不完整、事务不正确或无法显示的情况进行修复。
5. 保持已有 action 命名兼容，不要随意修改已经使用的 action 名称。
6. 新增 action 时统一采用：

```text
资源类型.操作
```

例如：

```text
question.update
question.delete
subject.create
admin_user.reset_password
role.update_permissions
import.approve
ai_model.create
watermark_rule.delete
```

1. 审计日志至少记录：

```text
operator_id
operator_name
action
resource_type
resource_id
severity
status
detail
ip
user_agent
error_message
created_at
```

1. 禁止在审计日志中记录以下敏感信息：

- 明文密码
- 密码哈希
- Access Token
- Refresh Token
- API Key 完整值
- Authorization 请求头
- Cookie
- 用户隐私数据的完整原文

API Key 等敏感配置只能记录是否变更或脱敏后的值。

# 三、统一审计写入规范

## 1. 成功操作

成功日志应与业务操作处于合理的事务边界内。

推荐行为：

1. 完成业务数据修改。
2. `flush` 获取资源 ID 和最终状态。
3. 调用 `write_admin_audit()`。
4. 由 API 层统一提交事务。
5. 如果业务事务失败，成功审计日志也不应被错误提交。

## 2. 失败操作

对于已经通过身份验证、进入业务执行阶段但最终失败的管理写操作，应记录失败日志：

```text
status = "failed"
error_message = 对管理员可理解但不包含敏感数据的错误信息
```

由于原业务 Session 可能已经回滚，失败日志不能继续依赖已回滚的事务。

请设计一个安全辅助方法，例如：

```python
async def write_failed_admin_audit_safely(...)
```

该方法应：

- 使用独立数据库 Session。
- 独立提交失败日志。
- 审计写入失败不能覆盖原业务异常。
- 写入失败时只记录应用程序日志。
- 不得造成递归异常。
- 不记录密码、Token、API Key 等敏感参数。

对于请求参数校验阶段直接返回的普通 422，可不强制写入审计日志；但权限拒绝、资源冲突、业务规则拒绝等关键事件可根据严重程度记录。

## 3. 严重程度建议

统一使用：

```text
low
normal
important
critical
```

建议规则：

- 查询或低风险配置测试：`low`
- 普通新增、编辑：`normal`
- 审核、发布、启用、禁用、权限修改：`important`
- 删除、封禁、密码重置、强制退出、角色权限变更：`critical`

# 四、修复 `/audit-logs` 页面查询和显示问题

请完整检查前后端审计日志查询参数是否一致。

当前管理端可能发送：

```text
page
pageSize
keyword
severity
status
resourceType
from
to
```

后端当前支持的参数主要包括：

```text
page
pageSize
operatorId
action
resourceType
resourceId
severity
status
from
to
```

请重点处理以下问题。

## 1. keyword 参数未被后端消费

前端发送了 `keyword`，但后端没有完整接收和处理。

请在后端增加 `keyword` 查询参数，并支持对以下字段进行模糊搜索：

- `action`
- `resource_type`
- `resource_id`
- `operator_name`

在数据库兼容性允许的情况下，可进一步搜索 `detail` 中的题目摘要，但不能因此破坏 SQLite 与 PostgreSQL 的兼容性。

搜索条件应使用 OR 组合。

## 2. 日期结束时间问题

前端的日期控件可能发送：

```text
2026-07-04
```

后端解析后会得到当天 `00:00:00`，从而把当天后续日志全部排除。

请将日期范围处理为用户直觉中的闭区间：

```text
from = 当天 00:00:00
to = 当天 23:59:59.999999
```

或者内部转换为：

```text
created_at >= from
created_at < to + 1 day
```

需要避免时区和午夜边界问题，并统一使用项目现有的 UTC 时间工具。

## 3. 查询结果实时刷新

完成其他页面操作后，进入 `/audit-logs` 页面必须能够看到最新日志。

检查：

- TanStack Query 缓存策略。
- 页面重新进入时是否重新请求。
- 是否需要设置 `staleTime`。
- 是否需要提供“刷新”按钮。
- 操作完成后是否需要使 `["audit-logs"]` 缓存失效。

审计页面至少增加一个明显的“刷新”按钮，并在刷新时保留当前筛选条件。

## 4. 错误状态

当前日志请求失败时不能只显示空列表。

请增加：

- 接口加载失败提示。
- 重试按钮。
- 422 日期范围错误的具体提示。
- 无权限时的明确提示。
- 加载状态和空状态区分。

# 五、为 `/questions` 页面操作增加题目详情

当管理员在 `/questions` 页面执行操作时，对应审计日志必须包含可识别的题目信息，不能只保存题目 ID 或 `is_active`。

需要覆盖以下操作：

- 编辑题目
- 删除题目
- 批量删除题目
- 启用题目
- 停用题目
- 题目向量批量回填
- 其他题库页面实际存在的数据变更操作

## 1. 统一题目审计快照

请在 `admin_question_service.py` 中增加统一快照方法，例如：

```python
def build_question_audit_snapshot(question: Question) -> dict:
    ...
```

建议包含：

```json
{
  "id": 123,
  "subject_id": 1,
  "subject_code": "math",
  "subject_name": "数学",
  "question_type": "choice",
  "content": {},
  "options": {},
  "answer": "A",
  "analysis": "解析内容",
  "knowledge_points": [],
  "difficulty": 3,
  "source": "来源",
  "source_type": "manual",
  "source_file": null,
  "import_batch_id": null,
  "year": 2026,
  "review_status": "approved",
  "is_active": true
}
```

如果 `content` 结构复杂，应保留原始 JSON 结构。

同时生成一个适合列表显示的简短摘要：

```json
{
  "content_preview": "题目前100至200个字符",
  "subject_name": "数学",
  "question_type": "choice"
}
```

不得因为题目正文很长而造成审计列表接口响应过大。

## 2. 编辑题目日志

编辑日志建议采用以下结构：

```json
{
  "question": {
    "id": 123,
    "content_preview": "...",
    "subject_name": "数学",
    "question_type": "choice"
  },
  "changed_fields": [
    "content",
    "answer",
    "difficulty"
  ],
  "before": {
    "content": {},
    "answer": "A",
    "difficulty": 2
  },
  "after": {
    "content": {},
    "answer": "B",
    "difficulty": 3
  },
  "edit_reason": "修正答案"
}
```

要求：

- `changed_fields` 只包含真正发生变化的字段。
- `before` 和 `after` 只保留发生变化的字段，避免保存大量重复数据。
- 同时保留题目摘要，便于审计列表直接识别题目。
- 如果没有发生实际变化，不应生成无意义的版本和审计日志，或者应明确记录为 no-op，选择一种符合现有业务的方案并说明。

## 3. 删除题目日志

删除前必须获取完整题目快照。

日志结构建议：

```json
{
  "question": {
    "...": "删除前题目完整快照"
  },
  "before": {
    "is_active": true
  },
  "after": {
    "is_active": false
  }
}
```

因为当前删除可能是软删除，所以 action 可以继续使用：

```text
question.delete
```

但 detail 中需要明确：

```json
{
  "delete_mode": "soft"
}
```

## 4. 启用和停用日志

日志中不能只有 `is_active`，还需要题目摘要：

```json
{
  "question": {
    "id": 123,
    "content_preview": "...",
    "subject_name": "数学",
    "question_type": "choice"
  },
  "before": {
    "is_active": false
  },
  "after": {
    "is_active": true
  }
}
```

## 5. 批量删除日志

当前批量删除如果逐题调用单题删除服务，可能会生成多条日志。

请保留逐题日志，同时增加一条批量汇总日志，例如：

```text
action = question.batch_delete
resource_type = question_batch
```

detail：

```json
{
  "requested_ids": [1, 2, 3],
  "success_ids": [1, 2],
  "failed_items": [
    {
      "id": 3,
      "error": "题目不存在"
    }
  ],
  "success_count": 2,
  "failed_count": 1,
  "questions": [
    {
      "id": 1,
      "content_preview": "..."
    },
    {
      "id": 2,
      "content_preview": "..."
    }
  ]
}
```

需要避免重复记录过大的完整题目正文，批量汇总日志只保留摘要。

## 6. 向量回填日志

题目向量回填属于管理写操作，也需要审计。

detail 至少记录：

```json
{
  "subject": "...",
  "limit": 100,
  "force": false,
  "after_id": 0,
  "processed": 100,
  "success_count": 98,
  "failed_count": 2
}
```

不能记录向量原始数据。

# 六、优化审计日志接口返回结构

当前列表接口不返回 `detail`，详情接口才返回。

请在不显著增加列表接口数据量的前提下，为列表接口增加可选的展示摘要，例如：

```python
detail_summary: dict | None
```

或增加以下计算字段：

```text
resource_label
content_preview
```

建议列表数据示例：

```json
{
  "id": 1001,
  "action": "question.update",
  "resource_type": "question",
  "resource_id": "123",
  "resource_label": "数学｜选择题｜关于二叉树的题目……",
  "severity": "important",
  "status": "success",
  "operator_name": "admin",
  "created_at": "...",
  "detail_summary": {
    "question_id": 123,
    "subject_name": "数学",
    "question_type": "choice",
    "content_preview": "..."
  }
}
```

要求：

- 保持现有字段兼容。
- 不要让列表接口返回完整的 before、after 和完整题目正文。
- 完整数据仍通过 `/audit-logs/{id}` 获取。

# 七、优化 `/audit-logs` 前端展示

## 1. 日志列表

对于题目相关日志，列表中显示：

```text
操作名称
题目ID
科目
题型
题目内容摘要
操作人
操作时间
状态
严重程度
```

例如：

```text
编辑题目
题目 #123
数学 · 选择题
关于二叉树遍历，下列说法正确的是……
操作人：admin
```

对非题目日志继续显示通用资源信息。

## 2. 操作名称中文化

增加 action 到中文名称的映射，例如：

```text
question.update       → 编辑题目
question.delete       → 删除题目
question.batch_delete → 批量删除题目
question.toggle_active → 修改题目启用状态
subject.create        → 新增科目
subject.update        → 编辑科目
admin_user.create     → 新增管理员
```

未知 action 回退显示原始 action，不能因缺少映射导致页面报错。

## 3. 题目详情抽屉

当日志属于 `resource_type = "question"` 时，详情抽屉增加独立的“题目详情”区域，结构化展示：

- 题目 ID
- 科目
- 题型
- 题干
- 选项
- 答案
- 解析
- 知识点
- 难度
- 年份
- 审核状态
- 启用状态

编辑日志还要展示：

- 修改字段
- 修改前
- 修改后
- 编辑原因

不要只把所有内容作为一整块 JSON 展示。

页面底部仍可保留“原始 JSON”折叠区域，方便技术排查。

需要兼容：

- 老日志没有 `question` 字段。
- `detail` 为 null。
- `content` 是字符串或对象。
- `options` 是对象、数组或 null。
- 部分字段缺失。
- 已被清理或关联资源已不存在。

# 八、增加审计日志定时清理任务

为防止 `audit_logs` 表持续增长，请增加可配置的定时清理任务。

## 1. 配置项

在 `core/config.py` 增加：

```python
AUDIT_LOG_CLEANUP_ENABLED: bool = True
AUDIT_LOG_RETENTION_DAYS: int = 180
AUDIT_LOG_CLEANUP_HOUR_UTC: int = 3
AUDIT_LOG_CLEANUP_BATCH_SIZE: int = 1000
```

配置要求：

- `AUDIT_LOG_RETENTION_DAYS` 最小值建议为 7。
- `AUDIT_LOG_CLEANUP_HOUR_UTC` 必须为 0～23。
- `AUDIT_LOG_CLEANUP_BATCH_SIZE` 必须为合理正整数。
- 配置无效时应在启动阶段明确报错或使用安全默认值。

## 2. 清理服务

在 `admin_audit_service.py` 或独立服务文件中增加：

```python
async def cleanup_expired_admin_audit_logs(
    db: AsyncSession,
    retention_days: int,
    batch_size: int,
) -> int:
    ...
```

清理规则：

```text
created_at < utcnow() - retention_days
```

要求：

- 按批次删除，避免一次事务删除大量记录。
- 每批完成后合理提交事务。
- 返回总删除数量。
- 没有过期日志时返回 0。
- 单批失败时正确回滚。
- 充分利用 `created_at` 已有索引。
- SQLite 和 PostgreSQL 均可运行。
- 不依赖数据库特有的 DELETE LIMIT 语法，除非实现了数据库方言兼容。
- 可以先查询一批 ID，再按 ID 删除。
- 不删除保留期边界内的日志。
- 不因日志中存在异常 JSON 而失败。

## 3. 定时调度器

优先复用项目已有的 APScheduler 及 FastAPI lifespan 管理方式，新增独立调度器，例如：

```python
audit_log_cleanup_scheduler
```

建议使用每天一次的 cron 任务。

要求：

- 应用启动时注册并启动。
- 应用关闭时安全停止。
- `AUDIT_LOG_CLEANUP_ENABLED=false` 时不启动。
- `max_instances=1`。
- `coalesce=True`。
- 调度器异常不能导致整个 FastAPI 应用退出。
- 清理成功后记录普通应用日志：

```text
审计日志清理完成：删除 xxx 条，保留天数 xxx
```

- 清理失败时记录异常堆栈。
- 不要每次清理后再向 `audit_logs` 表写入一条新的清理日志，防止形成自循环；清理执行情况写入应用运行日志即可。

## 4. 多实例和多 Worker

项目配置中可能存在多个 Gunicorn Worker。

定时清理任务必须避免每个 Worker 同时执行。

请使用以下任一种可靠方案：

- Redis 分布式锁。
- PostgreSQL advisory lock。
- 项目已有缓存锁机制。
- 独立调度进程。

如果复用项目缓存锁，需要确保：

- 获取锁失败时立即跳过本轮清理。
- 不能在没有获得锁的情况下继续执行。
- 锁有合理 TTL。
- finally 中只释放当前实例持有的锁。
- Redis 未配置时，可以在开发环境单进程降级运行。
- 生产多 Worker 且无分布式锁时，需要输出明显警告，避免静默重复执行。

# 九、兼容性与代码质量要求

1. 保持现有 API 路径不变。
2. 保持现有审计日志字段兼容。
3. 非必要不要新增数据库字段。
4. 题目详情优先存储在现有 `detail` JSON 字段。
5. 不破坏现有权限系统。
6. 不破坏现有题目版本功能。
7. 不修改无关业务逻辑。
8. 所有时间统一使用项目现有 UTC 工具。
9. 所有新增 Python 函数增加类型标注。
10. 避免在 API 路由中堆积大量业务代码。
11. 公共审计逻辑应放在 service 或辅助模块中。
12. 前端 TypeScript 不允许使用无必要的 `any`。
13. 前端必须兼容历史审计日志结构。
14. 对 JSON 内容进行安全渲染，不能使用不安全的 HTML 注入。
15. 题目内容过长时在列表中截断，但详情中可完整显示。
16. 如果题目正文包含 LaTeX，保持原始内容，不要破坏公式字符串。

# 十、测试要求

请补充后端测试，至少覆盖以下场景。

## 审计写入

1. 编辑题目后生成 `question.update` 日志。
2. 日志包含操作人、资源 ID、IP、User-Agent。
3. 日志包含题目摘要。
4. `changed_fields` 正确。
5. before 和 after 只包含发生变化的字段。
6. 删除题目后保留删除前题目快照。
7. 启用、停用日志包含题目摘要。
8. 批量删除产生逐题日志和汇总日志。
9. 业务事务回滚后不应留下错误的 success 日志。
10. 失败操作能够安全记录 failed 日志。

## 审计查询

1. 按 action 查询。
2. 按 resourceType 查询。
3. 按 status 查询。
4. 按 severity 查询。
5. keyword 可以搜索动作、资源和操作人。
6. 日期结束日包含当天全部日志。
7. 分页总数正确。
8. 默认日期范围正确。
9. 查询跨度超过一年时返回明确错误。
10. 历史日志没有 detail 时仍可正常返回。

## 定时清理

1. 删除超过保留期的日志。
2. 不删除保留期内的日志。
3. 边界时间处理正确。
4. 支持分批删除。
5. 没有过期数据时返回 0。
6. 清理异常时事务正确回滚。
7. 定时任务关闭时不启动。
8. 未取得分布式锁时不执行清理。
9. 多次执行具有幂等性。

前端至少验证：

1. 审计列表能显示题目摘要。
2. 详情抽屉能结构化展示题目详情。
3. 老日志不会导致组件报错。
4. keyword 查询参数正确。
5. 日期筛选正确。
6. 请求失败时显示错误和重试按钮。
7. 刷新按钮可以重新获取最新日志。

# 十一、验收标准

完成修改后必须满足：

1. 在 `/questions` 页面编辑任意题目后，打开 `/audit-logs` 能看到对应日志。
2. 日志列表能直接识别是哪一道题，而不是只显示题目 ID。
3. 打开日志详情后能看到题目内容、选项、答案、解析等信息。
4. 删除题目后，即使题目以后无法查询，审计日志仍保留删除前快照。
5. 启用或停用题目后能看到状态变化。
6. 批量删除能查看成功项和失败项。
7. 在科目、用户、管理员、AI 配置等页面执行写操作后，均能在审计日志中查询到。
8. 选择某一天作为结束日期时，该日期当天晚间产生的日志仍能查询到。
9. keyword 搜索真实生效。
10. 应用启动后定时清理任务正常注册。
11. 超过配置保留期的日志会被自动分批清理。
12. 多 Worker 环境不会同时重复执行清理任务。
13. 审计功能异常不能影响正常业务操作。
14. 日志中不包含密码、Token、完整 API Key 等敏感数据。

# 十二、执行流程

请按照以下顺序完成：

1. 扫描当前管理后台全部写接口。
2. 分析现有审计日志缺失的真实原因。
3. 输出审计覆盖差异清单。
4. 修复审计写入。
5. 完善题目操作的审计详情。
6. 修复审计查询参数和日期范围。
7. 优化审计日志前端列表和详情抽屉。
8. 增加定时清理服务与调度器。
9. 接入 FastAPI lifespan。
10. 补充自动化测试。
11. 执行测试、类型检查和构建检查。
12. 修复检查中发现的问题。
13. 给出最终修改报告。

# 十三、最终输出格式

完成开发后，请按以下格式报告：

## 1. 问题根因

说明为什么其他页面的操作日志没有显示，包括：

- 哪些接口没有写审计。
- 哪些查询参数不一致。
- 是否存在日期边界问题。
- 是否存在事务回滚导致日志丢失的问题。
- 是否存在前端缓存或展示问题。

## 2. 修改文件

逐个列出修改的文件及修改内容。

## 3. 审计覆盖清单

用表格列出：

```text
模块｜接口｜action｜resource_type｜严重程度｜是否已覆盖
```

## 4. 题目日志数据结构

给出编辑、删除、启用、批量删除的实际 detail 示例。

## 5. 定时清理机制

说明：

- 保留天数。
- 执行时间。
- 批次大小。
- 多实例锁方案。
- 启停方式。
- 异常处理方式。

## 6. 测试结果

列出：

- 后端测试结果。
- 前端类型检查结果。
- 前端构建结果。
- 未能执行的检查及原因。

## 7. 风险和兼容性

说明是否存在数据库迁移、历史日志兼容、多 Worker 部署等风险。

不要只输出代码片段或伪代码。请直接在当前项目中完成全部必要修改，并确保修改后的代码可以运行。
