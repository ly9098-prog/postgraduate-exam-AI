"""Private AOF Redis child for destructive recovery tests; retains all evidence."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import redis


class OwnedRedis:
    """Never accepts a URL or directory belonging to another Redis instance."""

    def __init__(self):
        binary = shutil.which("redis-server")
        if binary is None:
            raise RuntimeError(
                "redis-server must be installed for owned recovery tests"
            )
        self.binary = binary
        self.directory = Path(tempfile.mkdtemp(prefix="queue-recovery-"))
        self.socket = self.directory / "redis.sock"
        self.url = f"unix://{self.socket}?db=0"
        self.process = None
        self.events = []

    def record(self, action, **details):
        self.events.append({"action": action, "time": time.time(), **details})
        (self.directory / "evidence.json").write_text(
            json.dumps(self.events, indent=2) + "\n",
            encoding="utf-8",
        )

    def start(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("owned Redis is already running")
        command = [
            self.binary,
            "--port",
            "0",
            "--unixsocket",
            str(self.socket),
            "--unixsocketperm",
            "700",
            "--dir",
            str(self.directory),
            "--appendonly",
            "yes",
            "--appendfsync",
            "always",
            "--save",
            "",
            "--daemonize",
            "no",
        ]
        with (self.directory / "redis.log").open("ab") as log:
            self.process = subprocess.Popen(command, stdout=log, stderr=log)
        with redis.Redis.from_url(self.url, socket_timeout=0.2) as client:
            info = self._wait_ready(client)
            assert client.config_get("port")["port"] == "0"
            assert client.config_get("appendfsync")["appendfsync"] == "always"
        assert info["process_id"] == self.process.pid
        self.record(
            "start",
            pid=self.process.pid,
            run_id=info["run_id"],
            version=info["redis_version"],
            command=command,
        )
        return info

    def _wait_ready(self, client):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Redis exited; evidence: {self.directory}")
            try:
                return client.info("server")
            except (redis.ConnectionError, redis.TimeoutError):
                time.sleep(0.02)
        raise RuntimeError(f"Redis readiness timeout; evidence: {self.directory}")

    def crash(self):
        assert self.process is not None and self.process.poll() is None
        self.process.kill()
        result = self.process.wait(timeout=5)
        assert result == -signal.SIGKILL
        self.record("crash", pid=self.process.pid, returncode=result)

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                result = self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                result = self.process.wait(timeout=5)
            self.record("stop", pid=self.process.pid, returncode=result)
        self.record(
            "retained",
            directory=str(self.directory),
            files=sorted(
                str(path.relative_to(self.directory))
                for path in self.directory.rglob("*")
                if path.is_file()
            ),
        )

    async def restart(self, minimum_downtime=0):
        import asyncio

        await asyncio.sleep(minimum_downtime)
        before = next(
            event for event in reversed(self.events) if event["action"] == "start"
        )
        after = self.start()
        assert after["run_id"] != before["run_id"]
        assert self.directory.stat().st_mode & 0o077 == 0
        assert os.getpid() != after["process_id"]
        return after
