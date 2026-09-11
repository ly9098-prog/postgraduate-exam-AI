"""Collect stable Alembic checkpoints for the CI migration history test.

The migration graph contains merge revisions, so the complete revision graph
is not a single linear list.  Follow the first parent from the single head and
sample that valid ancestor chain.  Side branches are still exercised while
Alembic upgrades through their merge revisions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]
CHECKPOINT_STRIDE = 10


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))


def _first_parent_chain(script: ScriptDirectory) -> list[str]:
    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected one Alembic head, found {heads}")

    chain: list[str] = []
    current = script.get_revision(heads[0])
    while current is not None:
        chain.append(current.revision)
        down_revision = current.down_revision
        if isinstance(down_revision, tuple):
            down_revision = down_revision[0]
        current = script.get_revision(down_revision) if down_revision else None
    return list(reversed(chain))


def collect_checkpoints() -> list[str]:
    chain = _first_parent_chain(_script_directory())
    if not chain:
        raise RuntimeError("Alembic migration chain is empty")

    checkpoints = [
        revision
        for index, revision in enumerate(chain)
        if index % CHECKPOINT_STRIDE == 0 or index == len(chain) - 1
    ]
    return checkpoints


def main() -> int:
    json.dump(collect_checkpoints(), sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
