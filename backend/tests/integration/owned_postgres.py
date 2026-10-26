"""Private PostgreSQL child for full worker tests; retains its cluster and logs."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from tests.integration.owned_process import (
    capture_owned_children,
    private_environment,
    spawn_owned,
    stop_owned_group,
)


def postgres_binaries():
    candidates = []
    pg_config = shutil.which("pg_config")
    if pg_config:
        result = subprocess.run(
            [pg_config, "--bindir"],
            check=True,
            capture_output=True,
            text=True,
            env=private_environment(),
        )
        candidates.append(Path(result.stdout.strip()))
    candidates.append(Path.home() / ".local/pgsql/bin")
    candidates.extend(sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True))
    for directory in candidates:
        if all(
            (directory / name).is_file() for name in ("initdb", "postgres", "pg_ctl")
        ):
            return directory
    raise RuntimeError("Install PostgreSQL server binaries for private worker tests")


class OwnedPostgres:
    """No external URL, data directory, socket or existing cluster is accepted."""

    def __init__(self):
        self.binaries = postgres_binaries()
        self.directory = Path(tempfile.mkdtemp(prefix="worker-postgres-"))
        self.data = self.directory / "data"
        self.socket = self.directory / "socket"
        self.socket.mkdir(mode=0o700)
        self.process = None
        self.events = []
        self.url = (
            f"postgresql+asyncpg://owned_worker@/postgres?host={self.socket}&port=5432"
        )

    def record(self, action, **details):
        self.events.append({"action": action, **details})
        (self.directory / "evidence.json").write_text(
            json.dumps(self.events, indent=2) + "\n",
            encoding="utf-8",
        )

    def start(self):
        with (self.directory / "initdb.log").open("wb") as log:
            subprocess.run(
                [
                    str(self.binaries / "initdb"),
                    "-D",
                    str(self.data),
                    "--username=owned_worker",
                    "--auth-local=trust",
                    "--auth-host=reject",
                    "--encoding=UTF8",
                    "--no-locale",
                ],
                check=True,
                stdout=log,
                stderr=log,
                timeout=30,
                env=private_environment(self.directory),
            )
        command = [
            str(self.binaries / "postgres"),
            "-D",
            str(self.data),
            "-k",
            str(self.socket),
            "-h",
            "",
            "-p",
            "5432",
            "-c",
            "unix_socket_permissions=0700",
            "-c",
            "max_connections=20",
        ]
        with (self.directory / "postgres.log").open("ab") as log:
            self.process = spawn_owned(command, log=log, directory=self.directory)
        self.record("start", pid=self.process.pid, command=command)

    def stop(self):
        if self.process is not None:
            capture_owned_children(self.process)
        if self.process is not None and self.process.poll() is None:
            try:
                with (self.directory / "stop.log").open("ab") as log:
                    subprocess.run(
                        [
                            str(self.binaries / "pg_ctl"),
                            "-D",
                            str(self.data),
                            "-m",
                            "fast",
                            "-w",
                            "-t",
                            "10",
                            "stop",
                        ],
                        check=True,
                        stdout=log,
                        stderr=log,
                        timeout=15,
                        env=private_environment(self.directory),
                    )
            finally:
                stop_owned_group(self.process)
                code = self.process.returncode
                self.record("stop", returncode=code)
        elif self.process is not None:
            stop_owned_group(self.process)
        self.record("retained", directory=str(self.directory))
