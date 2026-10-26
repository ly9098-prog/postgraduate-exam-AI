"""Launch the unmodified worker module in a private cwd with an explicit environment."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

from tests.integration.owned_postgres import OwnedPostgres
from tests.integration.owned_process import (
    capture_owned_children,
    private_environment,
    spawn_owned,
    stop_owned_group,
)
from tests.integration.owned_redis import OwnedRedis

BACKEND = Path(__file__).resolve().parents[2]


class OwnedWorker:
    def __init__(self):
        self.directory = Path(tempfile.mkdtemp(prefix="worker-runtime-"))
        self.postgres = OwnedPostgres()
        self.redis = OwnedRedis()
        self.children = []
        self.events = []

    def record(self, action, **details):
        self.events.append({"action": action, "time": time.time(), **details})
        (self.directory / "evidence.json").write_text(
            json.dumps(self.events, indent=2) + "\n",
            encoding="utf-8",
        )

    def environment(self):
        # An empty private cwd avoids loading the repository's real .env.
        imports = [
            str(BACKEND),
            *(
                path
                for path in sys.path
                if path and Path(path).name in {"site-packages", "dist-packages"}
            ),
        ]
        return {
            **private_environment(self.directory),
            "PYTHONPATH": os.pathsep.join(dict.fromkeys(imports)),
            "PYTHONUNBUFFERED": "1",
            "APP_ENV": "test",
            "DEPLOYMENT_PROFILE": "local_import",
            "APP_SECRET": "owned-worker-synthetic-secret",
            "DATABASE_URL": self.postgres.url,
            "REDIS_URL": self.redis.url,
            "STAGING_STORAGE_DIR": str(self.directory / "staging"),
            "WORKER_SCRATCH_DIR": str(self.directory / "scratch"),
            "EXPORT_DIR": str(self.directory / "exports"),
            "OCR_ENABLED": "false",
            "OCR_EXECUTION_BACKEND": "disabled",
            "OCR_USE_GPU": "false",
            "VECTOR_ENABLED": "false",
            "ALLOW_IN_MEMORY_TASK_QUEUE": "false",
            "ADAPTIVE_LEARNING_ENABLED": "true",
            "ADAPTIVE_DIFFICULTY_ENABLED": "true",
            "SQL_ECHO": "false",
            "WORKER_CONCURRENCY": "1",
            "WORKER_SHUTDOWN_GRACE_SEC": "15",
            "SENTRY_DSN": "",
            "LOG_FORMAT": "json",
        }

    async def start_services(self):
        import asyncpg

        self.postgres.start()
        self.redis.start()
        deadline = time.monotonic() + 15
        while True:
            try:
                connection = await asyncpg.connect(
                    host=str(self.postgres.socket),
                    user="owned_worker",
                    database="postgres",
                    timeout=1,
                )
                try:
                    assert await connection.fetchval("SHOW listen_addresses") == ""
                    version = await connection.fetchval("SELECT version()")
                finally:
                    await connection.close()
                self.record("postgres-ready", version=version)
                break
            except (OSError, asyncpg.CannotConnectNowError):
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.05)
        await self.migrate()

    async def migrate(self):
        with (self.directory / "migration.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND / "alembic.ini"),
                "upgrade",
                "head",
                cwd=self.directory,
                env=self.environment(),
                stdout=log,
                stderr=log,
            )
            try:
                code = await asyncio.wait_for(process.wait(), timeout=45)
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
        assert code == 0, f"Migration failed; evidence: {self.directory}"
        self.record("migrated", returncode=code)

    def spawn(self):
        name = f"worker-{len(self.children) + 1}.log"
        command = [sys.executable, "-m", "app.worker_main"]
        with (self.directory / name).open("wb") as log:
            child = spawn_owned(
                command,
                log=log,
                directory=self.directory,
                environment=self.environment(),
            )
        self.children.append((child, name))
        self.record("spawn", pid=child.pid, command=command, log=name)
        return child

    async def until(self, predicate, *, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = await predicate()
            if value:
                return value
            await asyncio.sleep(0.05)
        raise AssertionError(f"Condition timed out; evidence: {self.directory}")

    async def log_contains(self, child, message):
        name = next(name for process, name in self.children if process is child)

        async def predicate():
            assert child.poll() is None, (
                f"Worker exited; evidence: {self.directory / name}"
            )
            return message in (self.directory / name).read_text(errors="replace")

        await self.until(predicate)

    async def wait_exit(self, child, expected, timeout=30):
        async def exited():
            return child.poll() is not None

        await self.until(exited, timeout=timeout)
        assert child.returncode == expected
        self.record("exit", pid=child.pid, returncode=child.returncode)

    async def stop(self):
        errors = []
        try:
            for child, _ in self.children:
                try:
                    capture_owned_children(child)
                    if child.poll() is None:
                        child.send_signal(signal.SIGTERM)
                        await self.wait_exit(child, 0)
                except BaseException as error:
                    errors.append(error)
                finally:
                    try:
                        await asyncio.to_thread(stop_owned_group, child)
                    except BaseException as error:
                        errors.append(error)
        finally:
            try:
                self.postgres.stop()
            finally:
                self.redis.stop()
                self.record("retained", directory=str(self.directory))
        if errors:
            raise BaseExceptionGroup("Private workers did not stop cleanly", errors)
