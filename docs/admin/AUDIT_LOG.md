# 审计日志规范（Audit Log）

> 版本：v2.0（审计修订版） | 状态：可启动开发 | 更新：2026-05-26
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

### 2.1 四级 severity

| Severity | 操作类型 | 写入策略 | 失败处理 |
|----------|---------|---------|---------|
| `critical` | 删除 / 批量操作 / 角色权限变更 / super_admin 相关 / 系统初始化 | **同步事务内** | 写日志失败 → 业务事务回滚 |
| `important` | 编辑 / 封禁 / 审核（approve/reject）/ 普通管理员 CRUD | 同步（事务外） | 重试 3 次失败 → 业务结果回滚（补偿） |
| `normal` | 创建 / 简单字段更新 / 查询敏感数据 | 异步 BullMQ 队列 | DLQ 兜底，可手动重放 |
| `low` | 登录 / 登出 / token 刷新 / 健康检查触发 | fire-and-forget | 仅 error log，可丢失 |

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

### 2.3 Important 实现示例（同步 + 重试）

```typescript
async banAppUser(id: number, reason: string, operator: AdminUser) {
  const before = await this.prisma.user.findUnique({ where: { id } });
  
  const updated = await this.prisma.user.update({
    where: { id },
    data: { isBanned: true, bannedReason: reason, bannedAt: new Date(), bannedBy: operator.id },
  });

  try {
    await this.auditLog.writeSyncWithRetry({  // 重试 3 次
      action: 'app_user.ban',
      severity: 'important',
      detail: { before, after: updated, extra: { reason } },
    });
  } catch (e) {
    // 重试 3 次仍失败 → 业务结果回滚
    await this.prisma.user.update({
      where: { id },
      data: { isBanned: before.isBanned, bannedReason: before.bannedReason, bannedAt: before.bannedAt, bannedBy: before.bannedBy },
    });
    throw new ServiceUnavailableException('审计日志写入失败，操作已回滚');
  }
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
  "extra": { "reason": "题目选项格式错误" }
}
```

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

```
GET /api/admin/v1/audit-logs
权限：audit:read

查询参数：
  operatorId   number
  action       string         （支持 LIKE，如 question.*）
  resourceType string
  resourceId   string
  severity     critical|important|normal|low
  status       success|failed
  from         ISO datetime
  to           ISO datetime
  page         number
  pageSize     number (max 100)

响应：标准分页结构
```

```
GET /api/admin/v1/audit-logs/:id
权限：audit:read
响应：单条详情（含完整 detail JSON）
```

---

## 八、分区与归档（I7 修订）

### 8.1 PostgreSQL 分区策略

使用 `pg_partman` 按月自动分区：

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

### 8.3 查询接口的时间限制

为避免跨大量分区的全表扫描：
- 默认仅查询近 6 个月
- 超过 6 个月需显式指定 `from` 参数
- 一次查询时间跨度上限 1 年（超过返回 422）

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
4. detail 字段不含密码 / token / session_key（敏感字段过滤）
5. operator_id 关联的 admin_user 即使被删除，operator_name 字段仍保留可读
