#!/usr/bin/env python3
"""
PostgreSQL 生产数据库定期备份脚本。

只处理 PostgreSQL，不处理 SQLite。
通过 DATABASE_URL 环境变量识别，使用 pg_dump custom format 备份，
pg_restore --list 校验，fcntl.flock 防并发，按 BACKUP_RETENTION_DAYS 清理旧备份。

使用方式：
  DATABASE_URL=postgresql://user:pass@host:5432/dbname python scripts/postgres_backup.py

生产建议通过 systemd timer 或 crontab 定时执行，不要放入 FastAPI 进程内部。
"""

from __future__ import annotations

import fcntl
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 环境变量配置（默认值）
# ---------------------------------------------------------------------------
BACKUP_PREFIX = os.environ.get("BACKUP_PREFIX", "postgraduate")
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "14"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "./backups"))
LOG_FILE = Path(os.environ.get("BACKUP_LOG_FILE", "logs/postgres_backup.log"))
LOCK_FILE_PATH = Path("/tmp/postgraduate_postgres_backup.lock")


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
    user = parsed.username or "postgres"
    password = parsed.password or ""
    dbname = (parsed.path or "").lstrip("/")

    if not dbname:
        raise ValueError("DATABASE_URL 中未包含数据库名称")

    return host, port, user, password, dbname


def human_size(bytes_: int) -> str:
    """将字节数转为可读格式。"""
    size = float(bytes_)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


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

def build_pgdump_cmd(backup_file: Path, host: str, port: int, user: str, dbname: str) -> list[str]:
    """构造 pg_dump 命令。使用 PGPASSWORD 环境变量传递密码。"""
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--no-password",
        f"--file={backup_file}",
        f"--host={host}",
        f"--port={port}",
        f"--username={user}",
        dbname,
    ]


def run_pgdump(cmd: list[str], password: str, logger: logging.Logger) -> bool:
    """执行 pg_dump，返回是否成功。"""
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    # 掩码 --username 的值（密码通过 PGPASSWORD 环境变量传递，不出现于命令行）
    masked_cmd = [arg if not arg.startswith("--username=") else "--username=***" for arg in cmd]
    logger.info("执行: %s", " ".join(masked_cmd))

    start = time.time()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
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
        logger.error("pg_dump 执行失败（退出码 %d，耗时 %.1f 秒）", result.returncode, elapsed)
        return False


def validate_backup(backup_file: Path, logger: logging.Logger) -> bool:
    """
    校验备份文件：
      1. 文件存在
      2. 文件大小 > 0
      3. pg_restore --list 可正常读取
    """
    if not backup_file.exists():
        logger.error("校验失败：备份文件不存在 — %s", backup_file)
        return False

    size = backup_file.stat().st_size
    if size == 0:
        logger.error("校验失败：备份文件大小为 0 — %s", backup_file)
        return False

    logger.info("备份文件大小: %s", human_size(size))

    result = subprocess.run(
        ["pg_restore", "--list", str(backup_file)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("校验失败：pg_restore --list 返回码 %d", result.returncode)
        for line in result.stderr.strip().splitlines():
            if line.strip():
                logger.error("[pg_restore] %s", line.strip())
        return False
    else:
        # 校验通过，记录 TOC 条目数
        toc_lines = [l for l in result.stdout.splitlines() if l.strip() and not l.startswith(";")]
        logger.info("pg_restore --list 校验通过（TOC 条目数: %d）", len(toc_lines))
        return True


def cleanup_old_backups(
    backup_dir: Path, prefix: str, retention_days: int, logger: logging.Logger
) -> int:
    """
    删除过期备份文件。只删除匹配 {prefix}_postgres_*.dump 的文件。
    返回删除数量。
    """
    if not backup_dir.exists():
        logger.info("备份目录不存在，跳过清理: %s", backup_dir)
        return 0

    pattern = f"{prefix}_postgres_*.dump"
    now = datetime.now()
    cutoff = now - timedelta(days=retention_days)
    deleted = 0

    for f in sorted(backup_dir.glob(pattern)):
        # 从文件名提取时间戳：{prefix}_postgres_YYYYMMDD_HHMMSS.dump
        try:
            stem = f.stem
            # 去掉前缀部分，取最后两个下划线分隔段
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
                logger.info("清理过期备份: %s（%s 之前）", f.name, human_size(size))
                deleted += 1
            except OSError as e:
                logger.warning("清理失败: %s — %s", f.name, e)

    if deleted > 0:
        logger.info("共清理 %d 个过期备份（保留 %d 天）", deleted, retention_days)
    else:
        logger.info("无过期备份需清理（保留 %d 天）", retention_days)

    return deleted


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    script_dir = Path(__file__).resolve().parent
    project_dir = script_dir.parent

    # 解析路径（相对路径基于项目根目录）
    backup_dir = BACKUP_DIR if BACKUP_DIR.is_absolute() else project_dir / BACKUP_DIR
    log_file = LOG_FILE if LOG_FILE.is_absolute() else project_dir / LOG_FILE

    logger = setup_logging(log_file)

    start_time = datetime.now()
    logger.info("=" * 70)
    logger.info("  PostgreSQL 生产备份开始")
    logger.info("  时间                : %s", start_time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  环境 (APP_ENV)      : %s", os.environ.get("APP_ENV", "未设置"))
    logger.info("  备份前缀 (BACKUP_PREFIX) : %s", BACKUP_PREFIX)
    logger.info("  保留天数 (BACKUP_RETENTION_DAYS) : %d", BACKUP_RETENTION_DAYS)
    logger.info("  备份目录            : %s", backup_dir)
    logger.info("=" * 70)

    # ---- 1. 解析 DATABASE_URL ----
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        logger.error("环境变量 DATABASE_URL 未设置，退出")
        sys.exit(1)

    # 检查不是 SQLite
    if raw_url.startswith("sqlite"):
        logger.error("DATABASE_URL 指向 SQLite，本脚本只支持 PostgreSQL 备份，退出")
        sys.exit(1)

    logger.info("数据库类型: PostgreSQL")
    logger.info("数据库 URL : %s", mask_db_url(raw_url))

    try:
        host, port, user, password, dbname = parse_db_url(raw_url)
    except ValueError as e:
        logger.error("DATABASE_URL 解析失败: %s", e)
        sys.exit(1)

    logger.info("数据库名称: %s", dbname)
    logger.info("数据库地址: %s:%d", host, port)
    logger.info("数据库用户: %s", user)

    # ---- 2. 获取文件锁 ----
    try:
        lock_fd = acquire_lock(LOCK_FILE_PATH, logger)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    try:
        # ---- 3. 创建备份目录 ----
        backup_dir.mkdir(parents=True, exist_ok=True)

        # ---- 4. 执行 pg_dump ----
        timestamp = start_time.strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{BACKUP_PREFIX}_postgres_{timestamp}.dump"
        backup_file = backup_dir / backup_filename

        cmd = build_pgdump_cmd(backup_file, host, port, user, dbname)
        logger.info("备份文件: %s", backup_file)

        if not run_pgdump(cmd, password, logger):
            sys.exit(1)

        # ---- 5. 校验 ----
        if not validate_backup(backup_file, logger):
            logger.error("备份校验未通过，本次备份视为失败")
            sys.exit(1)

        # ---- 6. 清理过期备份 ----
        cleanup_old_backups(backup_dir, BACKUP_PREFIX, BACKUP_RETENTION_DAYS, logger)

        # ---- 7. 完成 ----
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info("-" * 70)
        logger.info("备份完成，总耗时 %.1f 秒", elapsed)
        logger.info("备份文件: %s", backup_file)
        logger.info("文件大小: %s", human_size(backup_file.stat().st_size))
        logger.info("-" * 70)

    except Exception:
        logger.exception("备份过程发生未预期异常")
        sys.exit(1)
    finally:
        release_lock(lock_fd)


if __name__ == "__main__":
    main()
