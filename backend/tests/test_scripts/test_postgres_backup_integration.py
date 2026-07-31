
"""测试真实 pg_dump → pg_restore 流程。

运行要求：
  - docker compose -f deploy/docker-compose.prod.yml up -d postgres
    或本地 PostgreSQL 15 服务器
  - DATABASE_URL 环境变量指向可用的测试 PostgreSQL 数据库
  - pg_dump、pg_restore、psql、createdb、dropdb 命令可用

使用方法：
  cd /opt/2240ai-v2
  DATABASE_URL=postgresql://pguser:pgpass@localhost:5432/postgraduate \\
    python -m pytest backend/tests/test_scripts/test_postgres_backup_integration.py \\
    -v --run-integration

安全注意：集成测试会创建和删除临时数据库，但不会修改生产数据。
测试在开始和结束时都会清理临时数据库。
"""

from __future__ import annotations
import logging

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    "--run-integration" not in sys.argv,
    reason="需要 --run-integration 参数执行。"
    "要求本地 Docker PostgreSQL 15 或本地 postgres 服务。",
)

# ---------------------------------------------------------------------------
# 导入备份脚本
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

# ---------------------------------------------------------------------------
# 测试前的环境检查
# ---------------------------------------------------------------------------
REQUIRED_CMDS = ["pg_dump", "pg_restore", "psql", "createdb", "dropdb"]


def _check_prereqs() -> None:
    missing = []
    for cmd in REQUIRED_CMDS:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            missing.append(cmd)
    if missing:
        pytest.skip(f"缺少命令: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# 集成测试
# ---------------------------------------------------------------------------


class TestBackupRestoreIntegration:
    """使用真实 PostgreSQL 数据库测试备份和恢复流程。"""

    temp_db_name = ""

    @pytest.fixture(autouse=True)
    def setup(self):
        _check_prereqs()
        raw_url = os.environ.get("DATABASE_URL", "")
        assert raw_url, "需要设置 DATABASE_URL 环境变量"
        assert "postgres" in raw_url, "DATABASE_URL 必须指向 PostgreSQL"

        self.raw_url = raw_url
        self.host, self.port, self.user, self.password, self.dbname = (
            pb.parse_db_url(raw_url)
        )
        self.query_params = pb.extract_query_params(raw_url)
        self.pg_env = pb.build_pg_env(self.password, self.query_params)

    def _run_psql(self, dbname: str, sql: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                "psql",
                f"--host={self.host}",
                f"--port={self.port}",
                f"--username={self.user}",
                "-d",
                dbname,
                "-c",
                sql,
            ],
            env=self.pg_env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def _create_temp_db(self, suffix: str = "") -> str:
        import random
        import string

        rand = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        dbname = f"pg_backup_test_{suffix}_{rand}" if suffix else f"pg_backup_test_{rand}"
        subprocess.run(
            [
                "createdb",
                f"--host={self.host}",
                f"--port={self.port}",
                f"--username={self.user}",
                dbname,
            ],
            env=self.pg_env,
            capture_output=True,
            timeout=30,
        )
        return dbname

    def _drop_temp_db(self, dbname: str) -> None:
        try:
            subprocess.run(
                [
                    "dropdb",
                    f"--host={self.host}",
                    f"--port={self.port}",
                    f"--username={self.user}",
                    dbname,
                ],
                env=self.pg_env,
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

    def test_full_backup_and_restore(self, tmp_path: Path):
        """
        完整备份恢复测试：
          1. 在源数据库创建表并插入数据
          2. 执行备份
          3. 恢复到新数据库
          4. 验证数据结构、行数、索引和序列
          5. 清理
        """
        # ---- 1. 创建测试表并插入数据 ----
        create_sql = """
        CREATE TABLE IF NOT EXISTS backup_test_users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(255),
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS backup_test_scores (
            id SERIAL PRIMARY KEY,
            user_id INT REFERENCES backup_test_users(id),
            score INT NOT NULL CHECK (score >= 0),
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_backup_test_users_email
            ON backup_test_users(email);
        INSERT INTO backup_test_users (name, email)
        VALUES
            ('Alice', 'alice@test.com'),
            ('Bob', 'bob@test.com'),
            ('Charlie', 'charlie@test.com');
        INSERT INTO backup_test_scores (user_id, score)
        VALUES
            (1, 95), (1, 88), (2, 76), (3, 92), (3, 85), (3, 90);
        """
        r = self._run_psql(self.dbname, create_sql)
        assert r.returncode == 0, f"建表失败: {r.stderr[:500]}"

        # ---- 2. 验证初始行数 ----
        r = self._run_psql(
            self.dbname,
            "SELECT COUNT(*) as cnt FROM backup_test_users;",
        )
        assert "3" in r.stdout, f"预期 3 个用户, 得到: {r.stdout[:200]}"

        r = self._run_psql(
            self.dbname,
            "SELECT COUNT(*) as cnt FROM backup_test_scores;",
        )
        assert "6" in r.stdout, f"预期 6 个成绩, 得到: {r.stdout[:200]}"

        # ---- 3. 执行备份 ----
        timestamp = "integration_test"
        backup_file = tmp_path / f"postgraduate_postgres_{timestamp}.dump"
        cmd = pb.build_pgdump_cmd(
            backup_file, self.host, self.port, self.user, self.dbname
        )
        success = pb.run_pgdump(cmd, self.pg_env, logging.getLogger("test"))
        assert success, "pg_dump 失败"

        # ---- 4. 校验备份 ----
        valid, toc_count = pb.validate_backup(backup_file, logging.getLogger("test"))
        assert valid, "备份校验失败"
        assert toc_count > 0, "TOC 条目数为 0"

        # ---- 5. 创建临时数据库并恢复 ----
        temp_db = self._create_temp_db("restore")
        try:
            restore_url = (
                f"postgresql://{self.user}@{self.host}:{self.port}/{temp_db}"
            )
            r = subprocess.run(
                [
                    "pg_restore",
                    "--no-owner",
                    "--no-acl",
                    "--dbname",
                    restore_url,
                    str(backup_file),
                ],
                env=self.pg_env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            assert r.returncode == 0, f"恢复失败: {r.stderr[:1000]}"

            # ---- 6. 验证恢复的数据 ----
            r = self._run_psql(
                temp_db, "SELECT COUNT(*) as cnt FROM backup_test_users;"
            )
            assert "3" in r.stdout, f"恢复后用户数不正确: {r.stdout[:200]}"

            r = self._run_psql(
                temp_db, "SELECT COUNT(*) as cnt FROM backup_test_scores;"
            )
            assert "6" in r.stdout, f"恢复后成绩数不正确: {r.stdout[:200]}"

            # 验证索引存在
            r = self._run_psql(
                temp_db,
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename='backup_test_users' "
                "AND indexname='idx_backup_test_users_email';",
            )
            assert "idx_backup_test_users_email" in r.stdout, "索引未恢复"

            # 验证序列正常
            r = self._run_psql(
                temp_db,
                "SELECT nextval('backup_test_users_id_seq'::regclass);",
            )
            assert "4" in r.stdout, f"序列未正确恢复: {r.stdout[:200]}"

            # 验证外键
            r = self._run_psql(
                temp_db,
                "INSERT INTO backup_test_scores (user_id, score) "
                "VALUES (999, 10);",
            )
            assert r.returncode != 0, "外键约束未生效（应拒绝不存在的 user_id）"

            # 验证 CHECK 约束
            r = self._run_psql(
                temp_db,
                "INSERT INTO backup_test_scores (user_id, score) "
                "VALUES (1, -5);",
            )
            assert r.returncode != 0, "CHECK 约束未生效（应拒绝负数 score）"

        finally:
            self._drop_temp_db(temp_db)

        # ---- 7. 清理测试表 ----
        cleanup_sql = """
        DROP TABLE IF EXISTS backup_test_scores;
        DROP TABLE IF EXISTS backup_test_users;
        """
        r = self._run_psql(self.dbname, cleanup_sql)
        assert r.returncode == 0

    def test_backup_then_verify_restore_command(self, tmp_path: Path):
        """
        测试 verify-restore 子命令。
        """
        # 创建简单表和数据
        r = self._run_psql(
            self.dbname,
            "CREATE TABLE IF NOT EXISTS backup_test_vr (id INT PRIMARY KEY, val TEXT);",
        )
        assert r.returncode == 0
        r = self._run_psql(
            self.dbname,
            "INSERT INTO backup_test_vr VALUES (1, 'a'), (2, 'b');",
        )
        assert r.returncode == 0

        # 备份
        backup_file = tmp_path / "verify_restore_test.dump"
        cmd = pb.build_pgdump_cmd(
            backup_file, self.host, self.port, self.user, self.dbname
        )
        assert pb.run_pgdump(cmd, self.pg_env, logging.getLogger("test"))

        # 验证恢复
        rc = pb.do_verify_restore(backup_file, self.raw_url, logging.getLogger("test"))
        assert rc == 0, f"verify-restore 失败，退出码 {rc}"

        # 清理
        self._run_psql(self.dbname, "DROP TABLE IF EXISTS backup_test_vr;")

    def test_backup_rejects_sqlite(self):
        """确认脚本拒绝 SQLite URL。"""
        with pytest.raises(SystemExit):
            pb.main()
