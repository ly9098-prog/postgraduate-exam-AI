# PostgreSQL 生产数据库备份与恢复

## 设计原则

生产 PostgreSQL 备份使用独立脚本 `scripts/postgres_backup.py`，通过服务器级
定时任务（systemd timer / crontab）执行，**不放入 FastAPI 应用进程内部**。

### 为什么备份不能放入 FastAPI 进程内部？

| 问题 | 说明 |
|------|------|
| 多 worker 重复执行 | FastAPI 通常启动多个 worker/进程，每个都会执行备份，浪费资源甚至冲撞 |
| 多实例冲突 | 横向扩展到多台服务器后，每台都跑备份会导致重复 |
| 应用重启中断 | 部署重启时备份可能被中断，产生不完整备份文件 |
| 内存竞争 | `pg_dump` 消耗较多内存，与业务请求争抢资源 |
| 进程内定时不可靠 | Gunicorn 的 preload、worker 回收、信号处理都可能干扰定时器 |
| 职责分离 | 备份是运维职责，不应与应用代码耦合 |

正确的做法：操作系统级定时任务 → 独立进程 → 备份脚本 → 数据库。

---

## 备份脚本说明

### 文件位置

```text
scripts/postgres_backup.py
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串（必填） | — |
| `BACKUP_DIR` | 备份文件输出目录 | `./backups` |
| `BACKUP_RETENTION_DAYS` | 备份保留天数 | `14` |
| `BACKUP_PREFIX` | 备份文件名前缀 | `postgraduate` |
| `BACKUP_LOG_FILE` | 日志文件路径 | `logs/postgres_backup.log` |
| `BACKUP_LOCK_FILE` | 文件锁路径（防并发） | `/tmp/postgraduate_postgres_backup.lock` |
| `BACKUP_COMMAND_TIMEOUT_SEC` | pg_dump 超时秒数 | `3600` |
| `BACKUP_COMPRESSION_LEVEL` | pg_dump 压缩级别 0-9 | `6` |
| `BACKUP_VERIFY_RESTORE_ENABLED` | 是否启用自动恢复验证 | `false` |
| `APP_ENV` | 环境标识，仅用于日志 | — |

### 支持的 DATABASE_URL 格式

```text
postgresql://user:password@host:5432/dbname
postgresql+asyncpg://user:password@host:5432/dbname
postgres://user:password@host:5432/dbname
```

如果 `DATABASE_URL` 指向 SQLite，脚本会直接报错退出。

### 手动执行（测试用）

```bash
# 宿主机直接执行
cd /opt/2240ai-v2
source .venv/bin/activate
python scripts/postgres_backup.py

# Docker 模式执行
cd /opt/2240ai-v2
docker compose -f deploy/docker-compose.prod.yml --env-file backend/.env run --rm backup
```

### 验证备份恢复（安全测试）

使用临时数据库验证备份文件的完整性：

```bash
# 恢复到临时库并检查关键表
python scripts/postgres_backup.py verify-restore /backups/postgraduate_postgres_20260704_030000.dump

# Docker 模式
docker compose -f deploy/docker-compose.prod.yml --env-file backend/.env run --rm backup \
  verify-restore /backups/postgraduate_postgres_20260704_030000.dump
```

### 备份流程（原子写入）

每次备份执行以下步骤：

1. **写入临时文件** — pg_dump 输出到 `.partial` 后缀的临时文件
2. **校验** — pg_restore --list 检查 TOC 条目数
3. **原子重命名** — os.replace() 将临时文件改为最终 `.dump` 文件
4. **SHA-256** — 计算备份文件哈希值
5. **Manifest** — 将备份元数据追加到 `manifest.json`
6. **清理** — 删除过期备份和残留的 `.partial` 文件

如果任何步骤失败，`.partial` 文件会被自动清理，不会产生伪成功文件。

### 备份文件

命名格式：

```text
{prefix}_postgres_YYYYMMDD_HHMMSS.dump
```

示例：

```text
postgraduate_postgres_20260704_030000.dump
```

备份格式为 `pg_dump --format=custom`，可使用 `pg_restore` 灵活恢复。

---

## 生产定时任务配置

### 方案 A：systemd timer（推荐）

#### 1. 复制服务文件

```bash
sudo cp deploy/systemd/postgres-backup.service /etc/systemd/system/
sudo cp deploy/systemd/postgres-backup.timer  /etc/systemd/system/
```

#### 2. 根据实际部署路径修改 EnvironmentFile 和 ExecStart

编辑 `/etc/systemd/system/postgres-backup.service`，将 `/opt/2240ai-v2`
替换为实际部署路径：

```bash
sudo systemctl edit postgres-backup.service
```

或直接修改：

```bash
sudo sed -i 's|/opt/2240ai-v2|/your/actual/path|g' \
  /etc/systemd/system/postgres-backup.service
```

> **宿主机关联**：systemd service 默认使用宿主机 Python 环境 + pg_dump。
> 如果宿主机未安装 PostgreSQL 客户端，改用 Docker 模式（见下方注释）。

#### 3. 启动定时器

```bash
sudo systemctl daemon-reload
sudo systemctl enable postgres-backup.timer
sudo systemctl start  postgres-backup.timer
```

#### 4. 验证启用状态

```bash
sudo systemctl status postgres-backup.timer
sudo systemctl list-timers --all | grep -i backup
```

#### 5. 查看备份日志

```bash
sudo journalctl -u postgres-backup.service -n 100 --no-pager
```

#### 6. 查看下次执行时间

```bash
systemctl list-timers --all | grep postgres-backup
systemctl show postgres-backup.timer | grep NextElapse
```

---

### 备选方案 B：Docker Compose backup 服务

生产 Compose 文件中已定义 `backup` 服务（带 `profiles: [manual]`，不随 `compose up` 自动启动）。

#### 通过 systemd timer 执行 Docker 备份

修改 `deploy/systemd/postgres-backup.service`，将 ExecStart 替换为：

```ini
ExecStart=/usr/bin/docker compose -f /opt/2240ai-v2/deploy/docker-compose.prod.yml --env-file /opt/2240ai-v2/backend/.env run --rm backup
```

#### 手动执行

```bash
# 通过 deploy.sh（推荐）
bash deploy/scripts/deploy.sh backup

# 直接调用 Docker Compose
docker compose -f deploy/docker-compose.prod.yml --env-file backend/.env run --rm backup
```

#### Docker 备份模式的优点

- 不需要宿主机安装 PostgreSQL 客户端
- 备份容器与 postgres 在同一 Docker 网络
- 资源隔离（不占用 app 容器资源）
- 备份数据卷 `backup_data` 持久化存储

---

### 备选方案 C：crontab

**注意：不要同时启用 systemd timer 和 crontab，避免重复备份。**

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每天凌晨 3:00 执行）
0 3 * * * cd /opt/2240ai-v2 && /opt/2240ai-v2/.venv/bin/python scripts/postgres_backup.py >> logs/postgres_backup.log 2>&1
```

---

### 安全考虑

- 数据库密码通过环境变量 `DATABASE_URL` 传入，不在脚本中硬编码
- 日志中密码被脱敏（显示为 `****`）
- `pg_dump` 使用 `PGPASSWORD` 环境变量传递密码，不在进程命令行中暴露
- 备份目录建议权限：`chmod 700 /var/backups/postgraduate`
- 备份文件建议权限：`chmod 600 /var/backups/postgraduate/*.dump`
- 备份文件不应提交到 Git（已在 `.gitignore` 中排除）

---

## 恢复说明

### 重要：恢复前必读

1. **确认目标数据库** — 检查 `DATABASE_URL` 指向的是哪个数据库
2. **先停止应用服务** — 防止恢复过程中业务写入产生数据不一致
3. **恢复会覆盖现有数据** — `--clean` 参数会删除已有对象再重建
4. **建议先恢复到临时库验证** — 确认备份内容符合预期
5. **不要在未验证的生产库上盲目恢复**

### 1. 查看备份内容

```bash
pg_restore --list backups/postgraduate_postgres_20260704_030000.dump
```

输出为 TOC（Table of Contents），包含所有表、索引、函数等对象列表。
以 `;` 开头的行为注释，非注释行即为备份中包含的对象。

### 2. 恢复到临时库验证

> **密码处理**：以下命令中的密码直接写在 URL 里会被 `ps aux` 看到。
> 建议通过 `PGPASSWORD` 环境变量或 `~/.pgpass` 文件传递密码：
> ```bash
> export PGPASSWORD='your_password'
> createdb -h host -p 5432 -U postgres postgraduate_restore_test
> pg_restore --no-owner --no-acl --dbname "postgresql://postgres@host:5432/postgraduate_restore_test" backups/...
> unset PGPASSWORD
> ```

```bash
# 创建临时数据库
createdb -h host -p 5432 -U postgres postgraduate_restore_test

# 恢复备份到临时库
pg_restore \
  --no-owner \
  --no-acl \
  --dbname postgresql://postgres:password@host:5432/postgraduate_restore_test \
  backups/postgraduate_postgres_20260704_030000.dump

# 验证数据
psql -h host -p 5432 -U postgres -d postgraduate_restore_test -c "\dt"
psql -h host -p 5432 -U postgres -d postgraduate_restore_test -c "SELECT count(*) FROM questions;"

# 验证完成后删除临时库
dropdb -h host -p 5432 -U postgres postgraduate_restore_test
```

### 3. 恢复到正式库

> **密码处理**：使用 `"$DATABASE_URL"` 引用环境变量是安全的（密码不暴露在命令行参数中）。
> 如果手动指定 URL，请使用 `PGPASSWORD` 环境变量方式：
> ```bash
> export PGPASSWORD='your_password'
> pg_restore --clean --if-exists --no-owner --no-acl \
>   --dbname postgresql://postgres@host:5432/postgraduate \
>   backups/...
> unset PGPASSWORD
> ```

```bash
pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --dbname "$DATABASE_URL" \
  backups/postgraduate_postgres_20260704_030000.dump
```

参数说明：

| 参数 | 作用 |
|------|------|
| `--clean` | 恢复前删除已存在的数据库对象 |
| `--if-exists` | 配合 `--clean`，删除时使用 `IF EXISTS`，避免不存在时报错 |
| `--no-owner` | 不恢复对象所有权（适用于不同用户间迁移） |
| `--no-acl` | 不恢复权限信息 |

### 4. 恢复到完全不同的数据库名

```bash
# 注意：custom format 的 dump 文件内部记录了原始数据库名。
# pg_restore 默认恢复到同名数据库，但可以通过 --dbname 指定任意目标。
export PGPASSWORD='your_password'
createdb -h target_host -p 5432 -U postgres new_database_name

pg_restore \
  --no-owner \
  --no-acl \
  --dbname postgresql://postgres@target_host:5432/new_database_name \
  backups/postgraduate_postgres_20260704_030000.dump
unset PGPASSWORD
```

---

## 生产服务器命令参考

### 检查现有备份任务

```bash
# crontab
crontab -l

# cron 目录
sudo ls -lah /etc/cron.d/

# systemd timer
sudo systemctl list-timers --all | grep -i postgres-backup
sudo systemctl status postgres-backup.timer

# systemd 服务日志
sudo journalctl -u postgres-backup.service -n 100 --no-pager

# 检查最近一次 systemd timer 运行记录
sudo systemctl show postgres-backup.timer | grep LastTrigger
```

### 备份文件管理

```bash
# 查看备份目录
ls -lah /var/backups/postgraduate/

# 统计备份文件大小总和
du -sh /var/backups/postgraduate/

# 手动查看某次备份内容
pg_restore --list /var/backups/postgraduate/postgraduate_postgres_20260704_030000.dump
```

### Docker 部署环境

如果生产使用 Docker Compose 部署，需要确保 PostgreSQL 端口暴露给宿主机，
或者修改备份脚本通过 Docker 网络执行：

```bash
# 验证容器状态
docker ps
docker compose -f deploy/docker-compose.prod.yml ps

# 查看日志
docker compose -f deploy/docker-compose.prod.yml logs postgres
```

如果 PostgreSQL 不暴露端口到宿主机，可以通过 `docker exec` 运行 `pg_dump`：

```bash
docker compose -f deploy/docker-compose.prod.yml exec -T postgres \
  pg_dump --format=custom --no-owner --no-acl \
  --file=/tmp/backup.dump -U postgraduate postgraduate

docker compose cp postgres:/tmp/backup.dump ./backups/
```

---

## 排错指南

### pg_dump 未找到

```bash
# 安装 PostgreSQL 客户端工具
sudo apt-get install postgresql-client  # Debian/Ubuntu
sudo yum install postgresql             # CentOS/RHEL
```

### 连接拒绝

```bash
# 检查 PostgreSQL 是否在监听
pg_isready -h host -p 5432

# 测试连接
psql -h host -p 5432 -U postgres -d dbname -c "SELECT 1"
```

### 备份目录磁盘空间不足

```bash
# 检查磁盘
df -h /var/backups/postgraduate/

# 手动清理过期备份（调整保留天数）
BACKUP_RETENTION_DAYS=7 python scripts/postgres_backup.py
```
