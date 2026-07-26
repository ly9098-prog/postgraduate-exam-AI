"""Staging storage status CLI.

Usage:
    python -m app.cli.staging status
"""

from __future__ import annotations

import asyncio
import os
import sys
import time


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


async def _cmd_status() -> int:
    """Show staging storage status."""
    from app.services.staging_storage import _STAGING_DIR, _ensure_refcount_redis

    print("=== Staging Storage Status ===\n")

    # ── Directory info ──
    print("─ Storage Directory")
    staging_dir = str(_STAGING_DIR)
    print(f"  Path:         {staging_dir}")
    print(f"  Exists:       {_green('yes') if _STAGING_DIR.exists() else _red('no')}")

    if _STAGING_DIR.exists():
        # Count objects and subdirectories
        object_count = 0
        tmp_count = 0
        total_size = 0
        lease_count = 0

        for entry in os.scandir(str(_STAGING_DIR)):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                object_count += 1
                try:
                    dir_size = 0
                    for dirpath, _dirnames, filenames in os.walk(entry.path):
                        for fn in filenames:
                            fp = os.path.join(dirpath, fn)
                            try:
                                dir_size += os.path.getsize(fp)
                            except OSError:
                                pass
                    total_size += dir_size
                except OSError:
                    pass
                # Check for leases
                lease_file = os.path.join(entry.path, ".lease")
                if os.path.exists(lease_file):
                    lease_count += 1
            elif entry.name.startswith("tmp_"):
                tmp_count += 1
                try:
                    total_size += os.path.getsize(entry.path)
                except OSError:
                    pass
            elif entry.is_file():
                try:
                    total_size += os.path.getsize(entry.path)
                except OSError:
                    pass

        print(f"  Objects:      {object_count}")
        print(f"  Temp files:   {tmp_count}")
        print(f"  Active leases:{lease_count}")
        print(f"  Total size:   {total_size / (1024*1024):.1f} MB")

        # Disk usage
        import shutil
        usage = shutil.disk_usage(str(_STAGING_DIR))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = (usage.used / usage.total) * 100
        print(f"  Disk free:    {free_gb:.1f} GB / {total_gb:.1f} GB ({used_pct:.0f}% used)")

        if free_gb < 1.0:
            print(f"  {_red('WARNING: Less than 1 GB free disk space!')}")
    else:
        print(f"  {_red('Staging directory does not exist.')}")
        return 1

    # ── Redis refcount ──
    print("\n─ Redis Refcount")
    try:
        client = await _ensure_refcount_redis()
        if client is None:
            print(f"  {_yellow('Redis not available — refcount not tracked')}")
            return 0

        # Scan for refcount keys
        refcount_keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = await client.scan(cursor=cursor, match="staging:ref:*", count=200)
            refcount_keys.extend(batch)
            if cursor == 0:
                break

        print(f"  Refcount keys: {len(refcount_keys)}")

        # Show some stats
        negative = 0
        orphan_candidates = 0
        for key in refcount_keys[:100]:  # Sample first 100
            try:
                val = await client.get(key)
                if val is not None:
                    v = int(val)
                    if v < 0:
                        negative += 1
                    elif v == 0:
                        orphan_candidates += 1
            except Exception:
                pass

        if negative > 0:
            print(f"  {_red(f'Negative refcounts: {negative}')}")
        else:
            print("  Negative refcounts: 0")

        if orphan_candidates > 0:
            print(f"  {_yellow(f'Orphan candidates (refcount=0): {orphan_candidates} (sampled)')}")

        # Active leases
        lease_keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = await client.scan(cursor=cursor, match="staging:lease:*", count=200)
            lease_keys.extend(batch)
            if cursor == 0:
                break

        now = time.time()
        active_leases = 0
        expired_leases = 0
        for key in lease_keys:
            try:
                val = await client.get(key)
                if val is not None:
                    expiry = float(val)
                    if expiry > now:
                        active_leases += 1
                    else:
                        expired_leases += 1
            except Exception:
                pass

        print(f"  Active leases:  {active_leases}")
        print(f"  Expired leases: {expired_leases}")

        if expired_leases > 10:
            print(f"  {_yellow(f'{expired_leases} expired leases may need cleanup')}")

    except Exception as e:
        print(f"  {_yellow(f'Redis error: {e}')}")

    return 0


def _usage() -> None:
    print("Usage:")
    print("  python -m app.cli.staging status")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "status":
        _usage()

    code = asyncio.run(_cmd_status())
    sys.exit(code)


if __name__ == "__main__":
    main()
