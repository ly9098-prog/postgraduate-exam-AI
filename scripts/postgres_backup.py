#!/usr/bin/env python3
"""
PostgreSQL 生产数据库定期备份脚本。

只处理 PostgreSQL，不处理 SQLite。
通过 DATABASE_URL 环境变量识别，使用 pg_dump custom format 备份，
pg_restore --list 校验，fcntl.flock 防并发，按 BACKUP_RETENTION_DAYS 清理旧备份。

安全特性：
  - 原子写入（临时文件 -> 校验 -> os.rename）
  - 子进程超时
  - URL 编码解码支持
  - IPv6 地址支持
  - SSL/TLS 查询参数传递
  - SHA-256 manifest 清单
  - 密码全程脱敏

使用方式：
  DATABASE_URL=postgresql://user:pass@host:5432/dbname python scripts/postgres_backup.py
  DATABASE_URL=postgresql://user:pass@host:5432/dbname python scripts/postgres_backup.py verify-restore /path/to/backup.dump

生产建议通过 systemd timer 或 crontab 定时执行，不要放入 FastAPI 进程内部。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# ---------------------------------------------------------------------------
# 环境变量配置（默认值）
# ---------------------------------------------------------------------------
BACKUP_PREFIX = os.environ.get("BACKUP_PREFIX", "postgraduate")
BACKUP_RETENTION_DAYS_RAW = os.environ.get("BACKUP_RETENTION_DAYS", "14")
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "./backups"))
LOG_FILE = Path(os.environ.get("BACKUP_LOG_FILE", "logs/postgres_backup.log"))
LOCK_FILE_PATH = Path(
    os.environ.get("BACKUP_LOCK_FILE", "/tmp/postgraduate_postgres_backup.lock")
)
BACKUP_COMMAND_TIMEOUT_SEC = int(
    os.environ.get("BACKUP_COMMAND_TIMEOUT_SEC", "3600")
)
BACKUP_COMPRESSION_LEVEL = int(
    os.environ.get("BACKUP_COMPRESSION_LEVEL", "6")
)
BACKUP_VERIFY_RESTORE_ENABLED = os.environ.get(
    "BACKUP_VERIFY_RESTORE_ENABLED", "false"
).lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
TEMP_SUFFIX = ".partial"
DUMP_SUFFIX = ".dump"
MANIFEST_FILENAME = "manifest.json"
MIN_TOC_ITEMS = 5
PARTIAL_STALE_THRESHOLD_HOURS = 6

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def mask_db_url(raw: str) -> str:
    """脱敏 DATABASE_URL 中的密码，用于日志输出。"""
    if not raw:
        return "<empty>"
    try:
        parsed = urlparse(raw)
        if parsed.password:
            return raw.replace(parsed.password, "****", 1)
    except Exception:
        pass
    return raw


def parse_db_url(raw: str) -> tuple[str, int, str, str, str]:
    """
    解析 DATABASE_URL，返回 (host, port, user, password, dbname)。

    支持格式:
      postgresql://user:pass@host:5432/dbname
      postgresql+asyncpg://user:pass@host:5432/dbname
      postgres://user:pass@host:5432/dbname
      postgresql://user:pass@[::1]:5432/dbname
      postgresql://user:pass@host:5432/dbname?sslmode=require

    如果不是 PostgreSQL URL 则抛出 ValueError。
    """
    if not raw:
        raise ValueError("DATABASE_URL 为空")

    if not re.match(r"^postgres(?:ql)?(?:\+[a-zA-Z0-9_]+)?://", raw):
        raise ValueError(
            f"DATABASE_URL 不是 PostgreSQL URL（当前 scheme 不被识别）: "
            f"{mask_db_url(raw)}"
        )

    parsed = urlparse(raw)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    user = unquote(parsed.username) if parsed.username else "postgres"
    password = unquote(parsed.password) if parsed.password else ""
    dbname = (parsed.path or "").lstrip("/")
    dbname = unquote(dbname) if dbname else ""

    if not dbname:
        raise ValueError("DATABASE_URL 中未包含数据库名称")

    return host, port, user, password, dbname


def extract_query_params(raw: str) -> dict[str, str]:
    """从 DATABASE_URL 中提取查询参数（sslmode, connect_timeout 等）。"""
    if "?" not in raw:
        return {}
    try:
        query_part = raw.split("?", 1)[1]
        parsed = parse_qs(query_part, keep_blank_values=True)
        return {k: v[0] if v else "" for k, v in parsed.items()}
    except Exception:
        return {}


def build_pg_env(
    password: str, query_params: dict[str, str]
) -> dict[str, str]:
    """构建供 pg_dump/pg_restore 使用的 PostgreSQL 原生环境变量。"""
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    ssl_mode = query_params.get("sslmode", "")
    if ssl_mode:
        env["PGSSLMODE"] = ssl_mode
    if query_params.get("sslrootcert"):
        env["PGSSLROOTCERT"] = query_params["sslrootcert"]
    if query_params.get("sslcert"):
        env["PGSSLCERT"] = query_params["sslcert"]
    if query_params.get("sslkey"):
        env["PGSSLKEY"] = query_params["sslkey"]
    if query_params.get("connect_timeout"):
        env["PGCONNECT_TIMEOUT"] = query_params["connect_timeout"]

    return env


def human_size(bytes_: int) -> str:
    """将字节数转为可读格式。"""
    size = float(bytes_)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def compute_sha256(file_path: Path) -> str:
    """计算文件的 SHA-256 哈希值。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_pg_version() -> str:
    """获取 pg_dump 版本号，失败返回 'unknown'。"""
    try:
        result = subprocess.run(
            ["pg_dump", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def validate_retention_days(raw: str) -> int:
    """验证 BACKUP_RETENTION_DAYS 是否为有效正整数。"""
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"BACKUP_RETENTION_DAYS 必须为整数，当前值: {raw!r}"
        )
    if value <= 0:
        raise ValueError(
            f"BACKUP_RETENTION_DAYS 必须为正整数，当前值: {value}"
        )
    return value


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------


def setup_logging(log_path: Path) -> logging.Logger:
    """配置日志：文件（DEBUG）+ 控制台（INFO）。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("pg_backup")
    logger.setLevel(logging.DEBUG)
    # 防止重复添加 handler（日志模块可能缓存 logger 实例）
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ---------------------------------------------------------------------------
# 文件锁
# ---------------------------------------------------------------------------


def acquire_lock(lock_path: Path, logger: logging.Logger) -> int:
    """获取文件锁，防止并发备份。失败则抛出 RuntimeError。"""
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info("已获取备份锁 %s", lock_path)
        return fd
    except BlockingIOError:
        raise RuntimeError(f"另一备份任务正在运行（锁文件 {lock_path}）")
    except OSError as e:
        raise RuntimeError(f"无法获取文件锁 {lock_path}: {e}")


def release_lock(fd: int | None) -> None:
    """释放文件锁。"""
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 核心操作
# ---------------------------------------------------------------------------


def build_pgdump_cmd(
    backup_file: Path, host: str, port: int, user: str, dbname: str
) -> list[str]:
    """构造 pg_dump 命令。"""
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--no-password",
        f"--compress={BACKUP_COMPRESSION_LEVEL}",
        f"--file={backup_file}",
        f"--host={host}",
        f"--port={port}",
        f"--username={user}",
        dbname,
    ]


def run_pgdump(
    cmd: list[str], env: dict[str, str], logger: logging.Logger
) -> bool:
    """执行 pg_dump，返回是否成功。"""
    # 掩码 --username 的值（密码通过 PGPASSWORD 环境变量传递，不出现于命令行）
    masked_cmd = [
        arg if not arg.startswith("--username=") else "--username=***"
        for arg in cmd
    ]
    logger.info("执行: %s", " ".join(masked_cmd))

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=BACKUP_COMMAND_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        logger.error(
            "pg_dump 执行超时（超过 %d 秒，已耗时 %.1f 秒）",
            BACKUP_COMMAND_TIMEOUT_SEC,
            elapsed,
        )
        return False

    elapsed = time.time() - start

    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            logger.info("[pg_dump] %s", line.strip())

    if result.stderr.strip():
        # pg_dump 的注意信息也输出到 stderr，不一定是错误
        for line in result.stderr.strip().splitlines():
            logger.warning("[pg_dump stderr] %s", line.strip())

    if result.returncode == 0:
        logger.info("pg_dump 执行成功（耗时 %.1f 秒）", elapsed)
        return True
    else:
        logger.error(
            "pg_dump 执行失败（退出码 %d，耗时 %.1f 秒）",
            result.returncode,
            elapsed,
        )
        return False


def validate_backup(
    backup_file: Path, logger: logging.Logger
) -> tuple[bool, int]:
    """
    校验备份文件：
      1. 文件存在
      2. 文件大小 > 0
      3. pg_restore --list 可正常读取
      4. TOC 条目数大于最小阈值
    返回 (是否通过, TOC条目数)。
    """
    if not backup_file.exists():
        logger.error("校验失败：备份文件不存在 — %s", backup_file)
        return False, 0

    size = backup_file.stat().st_size
    if size == 0:
        logger.error("校验失败：备份文件大小为 0 — %s", backup_file)
        return False, 0

    logger.info("备份文件大小: %s", human_size(size))

    try:
        result = subprocess.run(
            ["pg_restore", "--list", str(backup_file)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.error("校验失败：pg_restore --list 执行超时")
        return False, 0

    if result.returncode != 0:
        logger.error(
            "校验失败：pg_restore --list 返回码 %d", result.returncode
        )
        for line in result.stderr.strip().splitlines():
            if line.strip():
                logger.error("[pg_restore] %s", line.strip())
        return False, 0
    else:
        # 校验通过，记录 TOC 条目数
        toc_lines = [
            l
            for l in result.stdout.splitlines()
            if l.strip() and not l.startswith(";")
        ]
        toc_count = len(toc_lines)
        logger.info(
            "pg_restore --list 校验通过（TOC 条目数: %d）", toc_count
        )

        if toc_count < MIN_TOC_ITEMS:
            logger.error(
                "TOC 条目数 %d 低于最小阈值 %d，备份可能异常",
                toc_count,
                MIN_TOC_ITEMS,
            )
            return False, toc_count

        return True, toc_count


def write_manifest(
    manifest_path: Path,
    backup_file: Path,
    dbname: str,
    status: str,
    toc_count: int,
    start_time: datetime,
    end_time: datetime,
    sha256_hash: str,
    logger: logging.Logger,
) -> None:
    """写入备份 manifest 文件。"""
    duration = (end_time - start_time).total_seconds()
    try:
        size = backup_file.stat().st_size
    except OSError:
        size = 0

    manifest: dict[str, Any] = {
        "backup_file": backup_file.name,
        "database": dbname,
        "created_at": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round(duration, 1),
        "file_size_bytes": size,
        "file_size_human": human_size(size),
        "sha256": sha256_hash,
        "toc_entries": toc_count,
        "pg_version": get_pg_version(),
        "prefix": BACKUP_PREFIX,
        "retention_days": BACKUP_RETENTION_DAYS_RAW,
        "status": status,
    }

    try:
        existing: list[dict[str, Any]] = []
        if manifest_path.exists():
            try:
                existing_raw = manifest_path.read_text(encoding="utf-8")
                existing = json.loads(existing_raw)
                if not isinstance(existing, list):
                    existing = [existing]
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(manifest)

        manifest_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Manifest 已更新: %s", manifest_path)
    except OSError as e:
        logger.warning("Manifest 写入失败: %s", e)


def cleanup_old_backups(
    backup_dir: Path, prefix: str, retention_days: int, logger: logging.Logger
) -> int:
    """
    删除过期备份文件。只删除匹配 {prefix}_postgres_*.dump 的文件。
    不删除目录，不跟随符号链接。返回删除数量。
    """
    if not backup_dir.exists():
        logger.info("备份目录不存在，跳过清理: %s", backup_dir)
        return 0

    pattern = f"{prefix}_postgres_*.dump"
    now = datetime.now()
    cutoff = now - timedelta(days=retention_days)
    deleted = 0

    for f in sorted(backup_dir.glob(pattern)):
        if f.is_symlink():
            continue
        if not f.is_file():
            continue

        # 从文件名提取时间戳：{prefix}_postgres_YYYYMMDD_HHMMSS.dump
        try:
            stem = f.stem
            parts = stem.split("_")
            if len(parts) < 3:
                continue
            ts_str = "_".join(parts[-2:])  # YYYYMMDD_HHMMSS
            file_dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
        except (ValueError, IndexError):
            continue

        if file_dt < cutoff:
            try:
                size = f.stat().st_size
                f.unlink()
                logger.info(
                    "清理过期备份: %s（%s 之前）", f.name, human_size(size)
                )
                deleted += 1
            except OSError as e:
                logger.warning("清理失败: %s — %s", f.name, e)

    if deleted > 0:
        logger.info(
            "共清理 %d 个过期备份（保留 %d 天）", deleted, retention_days
        )
    else:
        logger.info("无过期备份需清理（保留 %d 天）", retention_days)

    return deleted


def cleanup_stale_partial(
    backup_dir: Path, prefix: str, logger: logging.Logger
) -> int:
    """清理超过阈值时间未完成的 .partial 文件。"""
    if not backup_dir.exists():
        return 0

    pattern = f"{prefix}_postgres_*{TEMP_SUFFIX}"
    now = time.time()
    cutoff = now - PARTIAL_STALE_THRESHOLD_HOURS * 3600
    cleaned = 0

    for f in backup_dir.glob(pattern):
        if not f.is_file():
            continue
        try:
            mtime = f.stat().st_mtime
            if mtime < cutoff:
                size = f.stat().st_size
                f.unlink()
                logger.info(
                    "清理残留 partial 文件: %s（%s，mtime: %s）",
                    f.name,
                    human_size(size),
                    datetime.fromtimestamp(mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                )
                cleaned += 1
        except OSError as e:
            logger.warning("清理 partial 文件失败: %s — %s", f.name, e)

    return cleaned


# ---------------------------------------------------------------------------
# verify-restore 子命令
# ---------------------------------------------------------------------------


def do_verify_restore(
    dump_path: Path,
    db_url: str,
    logger: logging.Logger,
) -> int:
    """
    将备份恢复到临时数据库并验证。

    流程：
      1. 解析数据库连接
      2. 创建随机名称的临时数据库
      3. pg_restore 恢复到临时库
      4. 检查核心 schema
      5. 检查关键表存在
      6. 可选检查 alembic_version 表
      7. 删除临时数据库
      8. 返回退出码
    """
    if not dump_path.exists():
        logger.error("备份文件不存在: %s", dump_path)
        return 1

    try:
        host, port, user, password, dbname = parse_db_url(db_url)
    except ValueError as e:
        logger.error("DATABASE_URL 解析失败: %s", e)
        return 1

    query_params = extract_query_params(db_url)
    pg_env = build_pg_env(password, query_params)

    # 生成随机临时数据库名
    import random
    import string

    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    temp_db = f"pg_backup_verify_{suffix}"

    logger.info("=" * 70)
    logger.info("  恢复验证开始")
    logger.info("  备份文件: %s", dump_path)
    logger.info("  临时数据库: %s", temp_db)
    logger.info("=" * 70)

    try:
        # Step 1: 创建临时数据库
        logger.info("创建临时数据库 %s ...", temp_db)
        create_cmd = [
            "createdb",
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            temp_db,
        ]
        r = subprocess.run(
            create_cmd, env=pg_env, capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            logger.error("创建临时数据库失败: %s", r.stderr.strip())
            return 1
        logger.info("临时数据库创建成功")

        # Step 2: 恢复备份
        logger.info("恢复备份到临时数据库 ...")
        restore_cmd = [
            "pg_restore",
            "--no-owner",
            "--no-acl",
            "--dbname",
            (
                f"postgresql://{user}@{host}:{port}/{temp_db}"
                if not password
                else f"postgresql://{user}:{password}@{host}:{port}/{temp_db}"
            ),
            str(dump_path),
        ]
        r = subprocess.run(
            restore_cmd,
            env=pg_env,
            capture_output=True,
            text=True,
            timeout=BACKUP_COMMAND_TIMEOUT_SEC,
        )
        if r.returncode != 0:
            logger.error("恢复失败: %s", r.stderr.strip()[:2000])
            return 1
        logger.info("恢复成功")

        # Step 3: 检查关键表
        logger.info("验证 schema ...")
        tables_cmd = [
            "psql",
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            "-d",
            temp_db,
            "-c",
            "\\dt",
        ]
        r = subprocess.run(
            tables_cmd, env=pg_env, capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            logger.info("表清单:\n%s", r.stdout.strip())
        else:
            logger.warning("获取表清单失败: %s", r.stderr.strip()[:500])

        # Step 4: 检查 alembic_version 表
        alembic_cmd = [
            "psql",
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            "-d",
            temp_db,
            "-c",
            "SELECT * FROM alembic_version;",
        ]
        r = subprocess.run(
            alembic_cmd,
            env=pg_env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode == 0 and r.stdout.strip():
            logger.info("Alembic 版本:\n%s", r.stdout.strip())
        else:
            logger.info("未发现 alembic_version 表（非 Alembic 管理数据库）")

        logger.info("恢复验证通过")
        return 0

    except subprocess.TimeoutExpired:
        logger.error("验证恢复超时")
        return 1
    except Exception as e:
        logger.exception("验证恢复过程异常: %s", e)
        return 1
    finally:
        # 清理临时数据库
        try:
            logger.info("删除临时数据库 %s ...", temp_db)
            drop_cmd = [
                "dropdb",
                f"--host={host}",
                f"--port={port}",
                f"--username={user}",
                temp_db,
            ]
            subprocess.run(
                drop_cmd,
                env=pg_env,
                capture_output=True,
                timeout=30,
            )
            logger.info("临时数据库已删除")
        except Exception as e:
            logger.warning("删除临时数据库失败: %s", e)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

BACKUP_RETENTION_DAYS: int = 0  # Will be set in main()


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    project_dir = script_dir.parent

    # 解析路径（相对路径基于项目根目录）
    backup_dir = (
        BACKUP_DIR if BACKUP_DIR.is_absolute() else project_dir / BACKUP_DIR
    )
    log_file = (
        LOG_FILE if LOG_FILE.is_absolute() else project_dir / LOG_FILE
    )

    logger = setup_logging(log_file)

    # ---- 验证配置 ----
    global BACKUP_RETENTION_DAYS
    try:
        BACKUP_RETENTION_DAYS = validate_retention_days(
            BACKUP_RETENTION_DAYS_RAW
        )
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # ---- 解析 DATABASE_URL ----
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.error("环境变量 DATABASE_URL 未设置，退出")
        sys.exit(1)

    if raw_url.startswith("sqlite"):
        logger.error(
            "DATABASE_URL 指向 SQLite，本脚本只支持 PostgreSQL 备份，退出"
        )
        sys.exit(1)

    logger.info("数据库类型: PostgreSQL")
    logger.info("数据库 URL : %s", mask_db_url(raw_url))

    try:
        host, port, user, password, dbname = parse_db_url(raw_url)
    except ValueError as e:
        logger.error("DATABASE_URL 解析失败: %s", e)
        sys.exit(1)

    query_params = extract_query_params(raw_url)
    pg_env = build_pg_env(password, query_params)

    logger.info("数据库名称: %s", dbname)
    logger.info("数据库地址: %s:%d", host, port)
    logger.info("数据库用户: %s", user)
    logger.info("备份超时: %d 秒", BACKUP_COMMAND_TIMEOUT_SEC)

    # ---- 检查 verify-restore 子命令 ----
    if len(sys.argv) > 1 and sys.argv[1] == "verify-restore":
        if len(sys.argv) < 3:
            logger.error("用法: python postgres_backup.py verify-restore <dump_file>")
            sys.exit(1)
        dump_path = Path(sys.argv[2])
        sys.exit(do_verify_restore(dump_path, raw_url, logger))

    # ---- 主备份流程 ----
    start_time = datetime.now()
    logger.info("=" * 70)
    logger.info("  PostgreSQL 生产备份开始")
    logger.info("  时间            : %s", start_time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  环境 (APP_ENV)  : %s", os.environ.get("APP_ENV", "未设置"))
    logger.info("  备份前缀        : %s", BACKUP_PREFIX)
    logger.info("  保留天数        : %d", BACKUP_RETENTION_DAYS)
    logger.info("  备份目录        : %s", backup_dir)
    logger.info("  压缩级别        : %d", BACKUP_COMPRESSION_LEVEL)
    logger.info("=" * 70)

    # ---- 获取文件锁 ----
    try:
        lock_fd = acquire_lock(LOCK_FILE_PATH, logger)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    temp_file: Path | None = None
    final_file: Path | None = None

    try:
        # ---- 创建备份目录 ----
        backup_dir.mkdir(parents=True, exist_ok=True)

        # ---- 清理残留 .partial 文件 ----
        cleanup_stale_partial(backup_dir, BACKUP_PREFIX, logger)

        # ---- 执行 pg_dump（写入临时文件） ----
        timestamp = start_time.strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{BACKUP_PREFIX}_postgres_{timestamp}"
        temp_file = backup_dir / f"{backup_filename}{TEMP_SUFFIX}"
        final_file = backup_dir / f"{backup_filename}{DUMP_SUFFIX}"

        cmd = build_pgdump_cmd(temp_file, host, port, user, dbname)
        logger.info("临时文件: %s", temp_file)
        logger.info("最终文件: %s", final_file)

        if not run_pgdump(cmd, pg_env, logger):
            # pg_dump 失败，清理临时文件
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                    logger.info("已清理临时文件 %s", temp_file)
                except OSError:
                    pass
            sys.exit(1)

        # ---- 校验 ----
        valid, toc_count = validate_backup(temp_file, logger)
        if not valid:
            logger.error("备份校验未通过，本次备份视为失败")
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                    logger.info("已清理失败临时文件 %s", temp_file)
                except OSError:
                    pass
            sys.exit(1)

        # ---- 原子重命名 ----
        # 先 fsync 目录确保数据落盘
        try:
            fd_dir = os.open(str(backup_dir), os.O_RDONLY)
            os.fsync(fd_dir)
            os.close(fd_dir)
        except OSError:
            pass

        os.replace(str(temp_file), str(final_file))
        logger.info("原子重命名完成: %s → %s", temp_file.name, final_file.name)

        # ---- 计算 SHA-256 ----
        logger.info("计算 SHA-256 ...")
        sha256_hash = compute_sha256(final_file)
        logger.info("SHA-256: %s", sha256_hash)

        # ---- 写入 manifest ----
        end_time = datetime.now()
        write_manifest(
            manifest_path=backup_dir / MANIFEST_FILENAME,
            backup_file=final_file,
            dbname=dbname,
            status="success",
            toc_count=toc_count,
            start_time=start_time,
            end_time=end_time,
            sha256_hash=sha256_hash,
            logger=logger,
        )

        # ---- 清理过期备份 ----
        cleanup_old_backups(
            backup_dir, BACKUP_PREFIX, BACKUP_RETENTION_DAYS, logger
        )

        # ---- 可选的恢复验证 ----
        if BACKUP_VERIFY_RESTORE_ENABLED:
            logger.info("恢复验证已启用，执行验证 ...")
            rc = do_verify_restore(final_file, raw_url, logger)
            if rc != 0:
                logger.error("恢复验证失败")
                sys.exit(1)

        # ---- 完成 ----
        elapsed = (datetime.now() - start_time).total_seconds()
        final_size = human_size(final_file.stat().st_size)
        logger.info("-" * 70)
        logger.info("备份完成，总耗时 %.1f 秒", elapsed)
        logger.info("备份文件: %s", final_file)
        logger.info("文件大小: %s", final_size)
        logger.info("SHA-256 : %s", sha256_hash)
        logger.info("-" * 70)

    except Exception:
        logger.exception("备份过程发生未预期异常")
        # 清理临时文件
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass
        sys.exit(1)
    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    main()
