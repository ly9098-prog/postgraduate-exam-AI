# 审计日志规范（Audit Log）

> 版本：v2.1（审计修订版） | 状态：Phase 7 AI 设置审计同步 | 更新：2026-05-30
> 修订自审计报告 C5（分级写入策略）、I7（分区与归档）
> **取代旧文档 OPERATION_LOG.md**

---

## 一、命名变更说明

**v1 文档为 operation_logs，v2 改名为 audit_logs**。原因：
- "operation log" 偏运维场景（系统日志、操作记录）
- "audit log" 准确表达本表用途（合规审计、追责证据）
- 命名与字段 `severity` 更匹配

---

## 二、分级写入策略（C5 关键修订）

> **更新时间**：2026-05-29
> **变更原因**：同步 Phase 5 FastAPI 实现；审计日志查询接口已完成，审计写入仍使用现有 SQLAlchemy 同步写入路径，BullMQ 队列为原规划项，当前未引入。

### 2.1 四级 severity

| Severity | 操作类型 | 写入策略 | 失败处理 |
|----------|---------|---------|---------|
| `critical` | 删除 / 批量操作 / 角色权限变更 / super_admin 相关 / 系统初始化 | **同步事务内** | 写日志失败 → 业务事务回滚 |
| `important` | 编辑 / 封禁 / 审核（approve/reject）/ 普通管理员 CRUD | 优先与业务更新同一 DB 事务；确需事务外时同步重试 | 事务内失败回滚；事务外补偿必须带版本/updated_at 条件，失败需告警并记录失败审计 |
| `normal` | 创建 / 简单字段更新 / 查询敏感数据 | Phase 1 同步写入；后续可评估异步队列 | 失败需记录错误日志，关键链路不得静默丢失 |
| `low` | 登录 / 登出 / token 刷新 | Phase 1 同步或轻量 fire-and-forget（按接口确认） | 仅 error log |

健康检查接口不写 audit_log，仅通过 `X-Request-Id` 响应头保留排障入口。

### 2.2 Critical 实现示例（必须事务内）

```typescript
// admin-users.service.ts
async deleteAdminUser(id: number, operator: AdminUser) {
  const target = await this.prisma.adminUser.findUnique({ where: { id }, include: { role: true } });
  if (!target) throw new NotFoundException();
  if (target.role.name === 'super_admin') throw new ForbiddenException();
  if (target.id === operator.id) throw new UnprocessableEntityException('不可删除自己');

  return this.prisma.$transaction(async (tx) => {
    await tx.adminUser.delete({ where: { id } });
    await tx.auditLog.create({  // 同一事务，失败一起回滚
      data: {
        operatorId: operator.id,
        operatorName: operator.username,
        action: 'admin_user.delete',
        severity: 'critical',
        resourceType: 'admin_user',
        resourceId: String(id),
        detail: { before: target, after: null },
        ip: this.requestContext.ip,
      },
    });
  });
}
```

### 2.3 Important 实现示例（优先同事务；事务外需条件补偿）

会修改核心数据的 important 操作优先采用“业务更新 + audit_log”同一 DB 事务，避免事务外补偿覆盖并发更新：

```typescript
async banAppUser(id: number, reason: string, operator: AdminUser) {
  return this.prisma.$transaction(async (tx) => {
    const before = await tx.user.findUnique({ where: { id } });
    const updated = await tx.user.update({
      where: { id },
      data: { isBanned: true, bannedReason: reason, bannedAt: new Date(), bannedBy: operator.id },
    });
    await tx.auditLog.create({
      data: {
        action: 'app_user.ban',
        severity: 'important',
        detail: { before, after: updated, extra: { reason } },
      },
    });
    return updated;
  });
}
```

若因兼容原因必须先提交业务更新、再事务外同步写 audit_log，补偿回滚必须带 `updated_at` / version 条件，且补偿失败要告警并追加 failed audit，禁止无条件覆盖当前行：

```typescript
try {
  await this.auditLog.writeSyncWithRetry(payload);
} catch (e) {
  const rollback = await this.prisma.user.updateMany({
    where: { id, updatedAt: updated.updatedAt },
    data: { isBanned: before.isBanned, bannedReason: before.bannedReason, bannedAt: before.bannedAt, bannedBy: before.bannedBy },
  });
  if (rollback.count !== 1) {
    this.logger.error('audit compensation failed', { id, action: 'app_user.ban' });
    await this.auditLog.writeFireForget({ action: 'app_user.ban', severity: 'important', status: 'failed', errorMessage: 'audit write failed and compensation skipped' });
  }
  throw new ServiceUnavailableException('审计日志写入失败，操作已回滚或已告警');
}
```

### 2.4 Normal 实现示例（异步队列）

```typescript
// audit-log.service.ts
async writeAsync(payload: AuditLogPayload) {
  await this.queue.add('audit-log', payload, {
    attempts: 5,
    backoff: { type: 'exponential', delay: 1000 },
    removeOnComplete: true,
    removeOnFail: false,  // 保留失败任务到 DLQ
  });
}

// audit-log.processor.ts
@Processor('audit-log')
export class AuditLogProcessor {
  @Process()
  async handle(job: Job<AuditLogPayload>) {
    await this.prisma.auditLog.create({ data: job.data });
  }
}
```

### 2.5 Low 实现（fire-and-forget）

```typescript
this.prisma.auditLog.create({ data: { action: 'system.login', severity: 'low', ... } })
  .catch(e => this.logger.error('audit log low write failed', e));
```

---

## 三、Action 命名规范

格式：`{resource}.{verb}`

```
# 认证（severity: low）
system.login
system.logout
system.token_refresh

# 小程序用户管理
app_user.view             # important（敏感查看）
app_user.edit             # important
app_user.ban              # important
app_user.unban            # important

# 后台管理员管理
admin_user.create         # critical
admin_user.edit           # important
admin_user.delete         # critical
admin_user.role_change    # critical

# 角色 / 权限
role.create               # critical
role.update_permissions   # critical
role.delete               # critical

# 题目操作
question.approve          # important
question.reject           # important
question.edit             # important
question.delete           # critical
question.toggle_active    # important
question.batch_approve    # critical
question.batch_reject     # critical
question.rollback         # critical（保留）

# 科目
subject.create            # important
subject.edit              # important
subject.delete            # critical

# 导入
import.enrich             # normal（触发 AI 解析任务）

# AI 设置
ai_setting.update         # important（更新全局开关或月度调用额度）
ai_setting.disable        # important（关闭全局 AI 解析业务熔断）
ai_quota.exhausted        # normal（月度额度拦截 AI 解析任务）
ai_parse.blocked          # normal（全局关闭拦截 AI 解析任务）

# 系统（操作者为 null）
system.init_super_admin             # critical
system.manual_super_admin_init       # critical
system.seed_permissions             # normal
```

---

## 四、Detail 字段格式

```typescript
type AuditDetail = {
  before?: Record<string, any>;  // 操作前快照（只含变更字段）
  after?: Record<string, any>;   // 操作后快照
  extra?: Record<string, any>;   // 额外信息（reason / batch result / 其他）
}
```

### 示例：题目审核拒绝

```json
{
  "before": { "reviewStatus": "pending" },
  "after": { "reviewStatus": "rejected" },
  "extra": {
    "reason": "题目选项格式错误",
    "requestId": "req_a1b2c3"
  }
}
```

`requestId` 是 Admin 对外唯一追踪标识，也作为内部全链路 traceId 使用。Phase 0/1 不新增 `audit_logs.trace_id` 列；审计查询通过 `detail.extra.requestId` 关联应用日志、响应头 `X-Request-Id` 与前端反馈。

### 示例：批量审核

```json
{
  "extra": {
    "totalRequested": 50,
    "successCount": 47,
    "failedCount": 3,
    "successIds": [1, 2, 3, ...],
    "failedItems": [
      { "id": 12, "reason": "题目不存在" },
      { "id": 23, "reason": "状态不允许" }
    ]
  }
}
```

### 示例：角色权限变更

```json
{
  "before": { "permissions": ["app_user:read", "question:read"] },
  "after": { "permissions": ["app_user:read", "question:read", "question:write", "question:review"] },
  "extra": {
    "roleId": 2,
    "roleName": "admin",
    "added": ["question:write", "question:review"],
    "removed": []
  }
}
```

### 示例：登录失败

```json
{
  "action": "system.login",
  "severity": "low",
  "status": "failed",
  "errorMessage": "用户名或密码错误",
  "detail": { "extra": { "username": "admin001" } },
  "ip": "1.2.3.4",
  "userAgent": "..."
}
```

---

## 五、字段大小限制与截断

- `detail` JSON 字段：上限 10KB
  - 超出时自动截断，并在 `detail.extra.truncated = true` 标记
- `errorMessage` 字段：上限 2KB
- `userAgent`：上限 256 字符
- `ip`：45 字符（IPv6 最大）

---

## 六、Audit Service 实现要点

```typescript
@Injectable()
export class AuditLogService {
  // critical：必须在调用方事务内
  async writeInTx(tx: PrismaTransaction, payload: AuditLogPayload) {
    await tx.auditLog.create({ data: this.normalize(payload) });
  }

  // important：同步 + 重试
  async writeSyncWithRetry(payload: AuditLogPayload, maxAttempts = 3) {
    for (let i = 0; i < maxAttempts; i++) {
      try {
        await this.prisma.auditLog.create({ data: this.normalize(payload) });
        return;
      } catch (e) {
        if (i === maxAttempts - 1) throw e;
        await sleep(100 * Math.pow(2, i));
      }
    }
  }

  // normal：异步队列
  async writeAsync(payload: AuditLogPayload) {
    await this.queue.add('audit-log', this.normalize(payload), {
      attempts: 5,
      backoff: { type: 'exponential', delay: 1000 },
    });
  }

  // low：fire-and-forget
  writeFireForget(payload: AuditLogPayload) {
    this.prisma.auditLog.create({ data: this.normalize(payload) })
      .catch(e => this.logger.error('audit-log low failed', e));
  }

  private normalize(payload: AuditLogPayload) {
    return {
      ...payload,
      detail: this.truncateDetail(payload.detail),
      ip: payload.ip?.slice(0, 45),
      userAgent: payload.userAgent?.slice(0, 256),
    };
  }
}
```

**关键约束**：
- AuditLogInterceptor **仅用于 normal / low** 自动写入
- critical / important **必须**在 Service 层显式调用 AuditLogService 方法
- 调用者负责传入正确的 severity

---

## 七、日志查询 API

> **更新时间**：2026-05-29
> **变更原因**：Phase 5 已在 FastAPI 中实现审计日志查询接口，补充实际查询参数、响应字段与时间范围约束。

```
GET /api/admin/v1/audit-logs
权限：audit:read

查询参数：
  operatorId   number
  action       string         （支持 * 通配，如 question.*；内部转 LIKE）
  resourceType string
  resourceId   string
  severity     critical|important|normal|low
  status       success|failed
  from         ISO datetime
  to           ISO datetime
  page         number         （默认 1）
  pageSize     number         （默认 20，max 100）

响应：标准分页结构；item 字段包含 id、operator_id、operator_name、action、resource_type、resource_id、severity、status、ip、created_at
```

```
GET /api/admin/v1/audit-logs/{id}
权限：audit:read
响应：单条详情；在列表字段基础上包含完整 detail JSON、user_agent、error_message
```

**实际约束（Phase 5）**：
- 未指定 `from` 时默认查询近 183 天。
- `from > to` 返回 422。
- 查询跨度超过 365 天返回 422。

---

## 八、分区与归档（I7 修订）

### 8.1 PostgreSQL 分区策略（生产部署，待确认）

开发环境不启用分区，SQLite 仅使用普通 `audit_logs` 表。分区仅属于生产 PostgreSQL 部署脚本，不由 Prisma schema 直接表达，避免 Prisma model 主键与 PostgreSQL 分区主键出现两套真相。若启用 `pg_partman`，生产 DDL 主键必须包含分区键：

```sql
CREATE TABLE audit_logs (
  id BIGSERIAL,
  operator_id INT,
  -- ... 其他字段
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (id, created_at)  -- 分区需包含分区键
) PARTITION BY RANGE (created_at);

SELECT partman.create_parent(
  p_parent_table := 'public.audit_logs',
  p_control      := 'created_at',
  p_type         := 'range',
  p_interval     := '1 month',
  p_premake      := 4    -- 预创建 4 个月分区
);

-- 自动创建任务
SELECT partman.run_maintenance(p_analyze := true);
-- 加入 cron：每天 02:00 跑一次
```

### 8.2 归档策略

- 6 个月前的分区：分离表（`audit_logs_archive_YYYY_MM`），保留在 DB
- 12 个月前的分区：导出 Parquet 至冷存储（S3 / OSS），DB 中删除
- 归档前必须备份 + 校验行数

### 8.4 Phase 5 实现状态（2026-05-29）

**变更原因**：Phase 5 后端已完成查询 API，但未新增生产分区维护脚本；需区分已实现能力与生产部署规划。

- 已实现：审计日志按时间范围查询，默认近 183 天，单次跨度上限 365 天。
- 已实现：`GET /api/admin/v1/audit-logs` 与 `GET /api/admin/v1/audit-logs/{id}` 均受 `audit:read` 权限保护。
- 未实现：`pg_partman` 月分区创建、每日维护 cron、冷归档导出脚本。
- 当前结论：分区与归档仍为生产部署规划项，不影响 Phase 5 查询 API 使用。

---

## 九、日志保留与合规

- 日志**永久保留**（不自动物理删除，可冷归档）
- 涉及合规要求时（GDPR / 数据隐私法），需提供"导出某用户相关全部日志"接口（预留位）
- 涉及用户删除请求时，仅删除 `detail.extra.userPII` 字段，保留操作元数据

---

## 十、不变式（Invariants）

1. 任何 critical / important 操作都有对应 audit_log 记录
2. critical 日志写入失败 → 业务事务回滚
3. audit_log 一经写入**不可修改**（仅追加，禁止 UPDATE 已有记录）
4. detail 字段不含 Authorization / Cookie / JWT / refresh token / password / passwordHash / session_key / DeepSeek API key / 完整请求体 / 生产 stack trace
5. `detail.extra.requestId` 与响应头 `X-Request-Id`、响应体 `meta.requestId` 使用同一值
6. operator_id 关联的 admin_user 即使被删除，operator_name 字段仍保留可读
