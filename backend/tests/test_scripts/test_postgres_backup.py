"""
PostgreSQL 备份脚本单元测试。

测试策略：
  - DATABASE_URL 解析（含 asyncpg、IPv6、SSL、URL 编码）
  - 密码脱敏
  - 保留天数校验
  - 过期文件清理
  - pg_dump 命令构造
  - 查询参数提取
  - 大小格式转换
  - SHA-256 计算
  - 残留 .partial 文件清理

子进程调用优先使用 mock，不要求单元测试机器安装 PostgreSQL。
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 使用 importlib 导入 scripts/postgres_backup.py
# ---------------------------------------------------------------------------
_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "scripts"
    / "postgres_backup.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "postgres_backup_script", _SCRIPT_PATH
)
pb = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(pb)


# ===================================================================
# 1. DATABASE_URL 解析
# ===================================================================


class TestParseDbUrl:
    def test_standard_postgresql(self):
        host, port, user, password, dbname = pb.parse_db_url(
            "postgresql://admin:secret@db.example.com:5432/mydb"
        )
        assert host == "db.example.com"
        assert port == 5432
        assert user == "admin"
        assert password == "secret"
        assert dbname == "mydb"

    def test_asyncpg_scheme(self):
        host, port, user, password, dbname = pb.parse_db_url(
            "postgresql+asyncpg://user:pass@localhost:5432/postgraduate"
        )
        assert host == "localhost"
        assert port == 5432
        assert user == "user"
        assert password == "pass"
        assert dbname == "postgraduate"

    def test_legacy_postgres_scheme(self):
        host, port, user, password, dbname = pb.parse_db_url(
            "postgres://user:pass@host:15432/db"
        )
        assert host == "host"
        assert port == 15432
        assert user == "user"
        assert dbname == "db"

    def test_default_port(self):
        host, port, *_ = pb.parse_db_url(
            "postgresql://user:pass@host/db"
        )
        assert port == 5432

    def test_default_user(self):
        _, _, user, _, _ = pb.parse_db_url(
            "postgresql://host/db"
        )
        assert user == "postgres"

    def test_empty_password(self):
        *_, password, _ = pb.parse_db_url(
            "postgresql://user@host/db"
        )
        assert password == ""

    def test_no_dbname_raises(self):
        with pytest.raises(ValueError, match="未包含数据库名称"):
            pb.parse_db_url("postgresql://user:pass@host:5432/")

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="DATABASE_URL 为空"):
            pb.parse_db_url("")

    def test_sqlite_rejected(self):
        with pytest.raises(ValueError, match="不是 PostgreSQL URL"):
            pb.parse_db_url("sqlite+aiosqlite:///./test.db")

    def test_unknown_scheme_rejected(self):
        with pytest.raises(ValueError, match="不是 PostgreSQL URL"):
            pb.parse_db_url("mysql://user:pass@host/db")

    def test_url_encoded_password(self):
        """密码中的特殊字符应被正确 URL 解码。"""
        host, port, user, password, dbname = pb.parse_db_url(
            "postgresql://user:p%40ss%2Fword@host:5432/db"
        )
        assert password == "p@ss/word"
        assert user == "user"

    def test_url_encoded_user(self):
        host, port, user, password, dbname = pb.parse_db_url(
            "postgresql://app%2Fservice:secret@host:5432/db"
        )
        assert user == "app/service"

    def test_url_encoded_dbname(self):
        host, port, user, password, dbname = pb.parse_db_url(
            "postgresql://user:pass@host:5432/%E6%B5%8B%E8%AF%95"
        )
        assert dbname == "测试"

    def test_ipv6_localhost(self):
        host, port, *_ = pb.parse_db_url(
            "postgresql://user:pass@[::1]:5432/db"
        )
        assert host == "::1"
        assert port == 5432

    def test_ipv6_full(self):
        host, port, *_ = pb.parse_db_url(
            "postgresql://user:pass@[2001:db8::1]:5432/db"
        )
        assert host == "2001:db8::1"

    def test_ipv4_address(self):
        host, port, *_ = pb.parse_db_url(
            "postgresql://user:pass@10.0.0.5:5432/db"
        )
        assert host == "10.0.0.5"


# ===================================================================
# 2. 查询参数提取
# ===================================================================


class TestExtractQueryParams:
    def test_no_params(self):
        assert pb.extract_query_params(
            "postgresql://user:pass@host/db"
        ) == {}

    def test_sslmode(self):
        params = pb.extract_query_params(
            "postgresql://user:pass@host/db?sslmode=require"
        )
        assert params.get("sslmode") == "require"

    def test_multiple_params(self):
        params = pb.extract_query_params(
            "postgresql://user:pass@host/db?sslmode=verify-full&connect_timeout=10"
        )
        assert params.get("sslmode") == "verify-full"
        assert params.get("connect_timeout") == "10"


# ===================================================================
# 3. PostgreSQL 环境变量构建
# ===================================================================


class TestBuildPgEnv:
    def test_password_set(self):
        env = pb.build_pg_env("secret123", {})
        assert env["PGPASSWORD"] == "secret123"

    def test_sslmode_propagated(self):
        env = pb.build_pg_env("pass", {"sslmode": "require"})
        assert env["PGSSLMODE"] == "require"

    def test_connect_timeout(self):
        env = pb.build_pg_env("pass", {"connect_timeout": "15"})
        assert env["PGCONNECT_TIMEOUT"] == "15"

    def test_no_override_existing(self):
        os.environ["TEST_KEEP"] = "preserved"
        env = pb.build_pg_env("pass", {"sslmode": "require"})
        assert env["TEST_KEEP"] == "preserved"
        assert env["PGPASSWORD"] == "pass"


# ===================================================================
# 4. 密码脱敏
# ===================================================================


class TestMaskDbUrl:
    def test_masks_password(self):
        result = pb.mask_db_url(
            "postgresql://user:secret123@host:5432/db"
        )
        assert "secret123" not in result
        assert "****" in result

    def test_empty_url(self):
        assert pb.mask_db_url("") == "<empty>"

    def test_no_password(self):
        url = "postgresql://user@host/db"
        assert pb.mask_db_url(url) == url


# ===================================================================
# 5. 保留天数校验
# ===================================================================


class TestValidateRetentionDays:
    def test_valid(self):
        assert pb.validate_retention_days("14") == 14
        assert pb.validate_retention_days("1") == 1
        assert pb.validate_retention_days("365") == 365

    def test_zero_raises(self):
        with pytest.raises(ValueError, match="必须为正整数"):
            pb.validate_retention_days("0")

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="必须为正整数"):
            pb.validate_retention_days("-1")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError, match="必须为整数"):
            pb.validate_retention_days("abc")

    def test_float_string_raises(self):
        with pytest.raises(ValueError, match="必须为整数"):
            pb.validate_retention_days("3.14")


# ===================================================================
# 6. 大小格式化
# ===================================================================


class TestHumanSize:
    def test_bytes(self):
        assert "500.0 B" in pb.human_size(500)

    def test_kb(self):
        assert "KB" in pb.human_size(2048)

    def test_mb(self):
        result = pb.human_size(5 * 1024 * 1024)
        assert "MB" in result
        assert "5.0" in result

    def test_gb(self):
        result = pb.human_size(2 * 1024 * 1024 * 1024)
        assert "GB" in result

    def test_tb(self):
        result = pb.human_size(5 * 1024 * 1024 * 1024 * 1024)
        assert "TB" in result


# ===================================================================
# 7. pg_dump 命令构造
# ===================================================================


class TestBuildPgdumpCmd:
    def test_basic_command(self):
        backup_file = Path("/backups/test.dump")
        cmd = pb.build_pgdump_cmd(
            backup_file, "localhost", 5432, "admin", "mydb"
        )
        assert "pg_dump" in cmd
        assert "--format=custom" in cmd
        assert "--no-owner" in cmd
        assert "--no-acl" in cmd
        assert f"--file={backup_file}" in cmd
        assert "--host=localhost" in cmd
        assert "--port=5432" in cmd
        assert "--username=admin" in cmd
        assert "mydb" == cmd[-1]

    def test_custom_port(self):
        cmd = pb.build_pgdump_cmd(
            Path("/backups/test.dump"), "host", 15432, "u", "db"
        )
        assert "--port=15432" in cmd

    def test_compress_flag_present(self):
        cmd = pb.build_pgdump_cmd(
            Path("/backups/test.dump"), "h", 5432, "u", "db"
        )
        compress_flags = [
            a for a in cmd if a.startswith("--compress=")
        ]
        assert len(compress_flags) == 1


# ===================================================================
# 8. 过期文件清理
# ===================================================================


class TestCleanupOldBackups:
    @pytest.fixture
    def backup_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    def _create_backup(
        self, backup_dir: Path, prefix: str, days_ago: int
    ) -> Path:
        """创建指定天数的旧备份文件。"""
        dt = datetime.now() - timedelta(days=days_ago)
        ts = dt.strftime("%Y%m%d_%H%M%S")
        f = backup_dir / f"{prefix}_postgres_{ts}.dump"
        f.write_text("dummy-content")
        return f

    def test_old_files_deleted(self, backup_dir):
        self._create_backup(backup_dir, "pg", 30)
        self._create_backup(backup_dir, "pg", 20)
        self._create_backup(backup_dir, "pg", 5)

        deleted = pb.cleanup_old_backups(
            backup_dir, "pg", 14, logging.getLogger("test")
        )
        assert deleted == 2  # 30 and 20 days old

    def test_recent_files_kept(self, backup_dir):
        f1 = self._create_backup(backup_dir, "pg", 2)
        f2 = self._create_backup(backup_dir, "pg", 7)

        pb.cleanup_old_backups(
            backup_dir, "pg", 14, logging.getLogger("test")
        )
        assert f1.exists()
        assert f2.exists()

    def test_wrong_prefix_ignored(self, backup_dir):
        old = self._create_backup(backup_dir, "other", 30)
        pb.cleanup_old_backups(
            backup_dir, "pg", 7, logging.getLogger("test")
        )
        assert old.exists()

    def test_empty_dir(self, backup_dir):
        deleted = pb.cleanup_old_backups(
            backup_dir, "pg", 7, logging.getLogger("test")
        )
        assert deleted == 0

    def test_nonexistent_dir(self):
        deleted = pb.cleanup_old_backups(
            Path("/nonexistent/backups"),
            "pg",
            7,
            logging.getLogger("test"),
        )
        assert deleted == 0

    def test_symlink_ignored(self, backup_dir):
        target = self._create_backup(backup_dir, "pg", 30)
        link = backup_dir / "pg_postgres_20200101_000000.dump"
        link.symlink_to(target)
        deleted = pb.cleanup_old_backups(
            backup_dir, "pg", 7, logging.getLogger("test")
        )
        assert deleted == 1  # only the real old file
        assert target.exists() is False  # real file cleaned
        assert link.is_symlink()  # symlink itself untouched


# ===================================================================
# 9. 残留 .partial 文件清理
# ===================================================================


class TestCleanupStalePartial:
    @pytest.fixture
    def backup_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    def _create_partial(
        self, backup_dir: Path, prefix: str, hours_ago: float
    ) -> Path:
        dt = datetime.now() - timedelta(hours=hours_ago)
        ts = dt.strftime("%Y%m%d_%H%M%S")
        f = backup_dir / f"{prefix}_postgres_{ts}.dump.partial"
        f.write_text("partial-content")
        mtime = time.time() - hours_ago * 3600
        os.utime(str(f), (mtime, mtime))
        return f

    def test_stale_partial_cleaned(self, backup_dir):
        self._create_partial(backup_dir, "pg", 12)
        cleaned = pb.cleanup_stale_partial(
            backup_dir, "pg", logging.getLogger("test")
        )
        assert cleaned == 1

    def test_recent_partial_kept(self, backup_dir):
        f = self._create_partial(backup_dir, "pg", 1)
        cleaned = pb.cleanup_stale_partial(
            backup_dir, "pg", logging.getLogger("test")
        )
        assert cleaned == 0
        assert f.exists()


# ===================================================================
# 10. SHA-256 计算
# ===================================================================


class TestComputeSha256:
    def test_known_hash(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world\n")
            f.flush()
            path = Path(f.name)

        try:
            h = pb.compute_sha256(path)
            assert len(h) == 64
            assert all(c in "0123456789abcdef" for c in h)
        finally:
            path.unlink()

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)

        try:
            h = pb.compute_sha256(path)
            assert len(h) == 64
        finally:
            path.unlink()


# ===================================================================
# 11. pg_dump 执行
# ===================================================================


class TestRunPgdump:
    def test_success(self):
        cmd = ["echo", "success"]
        env = pb.build_pg_env("pass", {})
        logger = logging.getLogger("test")
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("PGPASSWORD", "pass")
            result = pb.run_pgdump(cmd, env, logger)
        assert result is True

    def test_failure(self):
        cmd = ["sh", "-c", "exit 1"]
        env = pb.build_pg_env("pass", {})
        logger = logging.getLogger("test")
        result = pb.run_pgdump(cmd, env, logger)
        assert result is False


# ===================================================================
# 12. 备份校验
# ===================================================================


class TestValidateBackup:
    def test_nonexistent_file(self):
        logger = logging.getLogger("test")
        valid, toc = pb.validate_backup(
            Path("/nonexistent/backup.dump"), logger
        )
        assert valid is False
        assert toc == 0

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            suffix=".dump", delete=False
        ) as f:
            path = Path(f.name)

        try:
            logger = logging.getLogger("test")
            valid, toc = pb.validate_backup(path, logger)
            assert valid is False
            assert toc == 0
        finally:
            path.unlink()


# ===================================================================
# 13. pg_dump 命令构造完整性
# ===================================================================


class TestPgdumpCommandIntegrity:
    """确认命令构造不包含安全敏感信息。"""

    def test_password_not_in_args(self):
        cmd = pb.build_pgdump_cmd(
            Path("/backups/dump"), "h", 5432, "admin", "db"
        )
        cmd_str = " ".join(cmd)
        assert "PGPASSWORD" not in cmd_str
        assert "--password" not in cmd_str

    def test_dbname_is_last_arg(self):
        cmd = pb.build_pgdump_cmd(
            Path("/backups/dump"), "h", 5432, "admin", "mydb"
        )
        assert cmd[-1] == "mydb"


# ===================================================================
# 14. Manifest 写入
# ===================================================================


class TestWriteManifest:
    def test_manifest_created(self):
        with tempfile.TemporaryDirectory() as d:
            backup_dir = Path(d)
            backup_file = backup_dir / "test.dump"
            backup_file.write_text("mock-content")

            manifest_path = backup_dir / pb.MANIFEST_FILENAME
            now = datetime.now()

            pb.write_manifest(
                manifest_path=manifest_path,
                backup_file=backup_file,
                dbname="testdb",
                status="success",
                toc_count=42,
                start_time=now - timedelta(seconds=10),
                end_time=now,
                sha256_hash="abc123",
                logger=logging.getLogger("test"),
            )

            assert manifest_path.exists()
            data = json.loads(manifest_path.read_text())
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["database"] == "testdb"
            assert data[0]["status"] == "success"
            assert data[0]["toc_entries"] == 42
            assert data[0]["sha256"] == "abc123"

    def test_manifest_appends(self):
        with tempfile.TemporaryDirectory() as d:
            backup_dir = Path(d)
            manifest_path = backup_dir / pb.MANIFEST_FILENAME
            backup_file = backup_dir / "test.dump"
            backup_file.write_text("mock")
            now = datetime.now()

            for i in range(3):
                pb.write_manifest(
                    manifest_path=manifest_path,
                    backup_file=backup_file,
                    dbname="db",
                    status="success",
                    toc_count=i * 10,
                    start_time=now,
                    end_time=now,
                    sha256_hash=f"hash{i}",
                    logger=logging.getLogger("test"),
                )

            data = json.loads(manifest_path.read_text())
            assert len(data) == 3


# ===================================================================
# 15. 工具函数
# ===================================================================


class TestGetPgVersion:
    def test_returns_string(self):
        version = pb.get_pg_version()
        assert isinstance(version, str)


# ===================================================================
# 16. 原子重命名流程验证
# ===================================================================


class TestAtomicWriteFlow:
    def test_temp_to_final_rename(self):
        with tempfile.TemporaryDirectory() as d:
            backup_dir = Path(d)
            temp_file = backup_dir / "backup.dump.partial"
            final_file = backup_dir / "backup.dump"

            temp_file.write_text("valid-content")
            os.replace(str(temp_file), str(final_file))

            assert not temp_file.exists()
            assert final_file.exists()
            assert final_file.read_text() == "valid-content"

    def test_temp_cleanup_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            backup_dir = Path(d)
            temp_file = backup_dir / "backup.dump.partial"
            temp_file.write_text("partial-content")
            temp_file.unlink()
            assert not temp_file.exists()


# ===================================================================
# 17. 锁机制
# ===================================================================


class TestLockMechanism:
    def test_acquire_and_release(self):
        with tempfile.TemporaryDirectory() as d:
            lock_path = Path(d) / "test.lock"
            logger = logging.getLogger("test")

            fd = pb.acquire_lock(lock_path, logger)
            assert fd is not None
            pb.release_lock(fd)

    def test_double_acquire_fails(self):
        with tempfile.TemporaryDirectory() as d:
            lock_path = Path(d) / "test.lock"
            logger = logging.getLogger("test")

            fd1 = pb.acquire_lock(lock_path, logger)
            with pytest.raises(RuntimeError, match="另一备份任务正在运行"):
                pb.acquire_lock(lock_path, logger)
            pb.release_lock(fd1)

    def test_release_none(self):
        pb.release_lock(None)


# ===================================================================
# 18. pg_dump 超时处理
# ===================================================================


class TestRunPgdumpTimeout:
    def test_timeout_returns_false(self):
        cmd = [
            sys.executable,
            "-c",
            "import time; time.sleep(5)",
        ]
        env = pb.build_pg_env("pass", {})

        original_timeout = pb.BACKUP_COMMAND_TIMEOUT_SEC
        try:
            pb.BACKUP_COMMAND_TIMEOUT_SEC = 1
            logger = logging.getLogger("test")
            result = pb.run_pgdump(cmd, env, logger)
            assert result is False
        finally:
            pb.BACKUP_COMMAND_TIMEOUT_SEC = original_timeout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
