"""Doctor — system health check for all critical components.

Usage:
    python -m app.cli.doctor

Exits 0 if all checks pass, non-zero otherwise.
"""

from __future__ import annotations

import asyncio
import os
import sys


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = _green("PASS") if ok else _red("FAIL")
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


async def _main() -> int:
    from app.core.config import settings

    print("=== 2240AI Doctor ===\n")

    failures = 0

    # ── Environment ──
    print("─ Environment")
    ok = _check("APP_ENV", True, settings.APP_ENV)
    if not ok:
        failures += 1
    ok = _check("PROCESS_ROLE", settings.PROCESS_ROLE in ("web", "worker", "scheduler", "all"),
                 settings.PROCESS_ROLE)
    if not ok:
        failures += 1

    # Deployment profile
    try:
        from app.core.deployment_profile import detect_deployment_profile
        profile = detect_deployment_profile()
        ok = _check("Deployment Profile", True, str(profile))
    except Exception as e:
        ok = _check("Deployment Profile", False, str(e))
    if not ok:
        failures += 1

    # ── PostgreSQL ──
    print("\n─ PostgreSQL")
    try:
        from sqlalchemy import text

        from app.core.database import async_session
        async with async_session() as db:
            result = await db.execute(text("SELECT 1"))
            row = result.one()
            if row._mapping[0] == 1:
                _check("PostgreSQL connectivity", True, settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else settings.DATABASE_URL[:50])
            else:
                _check("PostgreSQL connectivity", False)
                failures += 1
    except Exception as e:
        _check("PostgreSQL connectivity", False, str(e)[:80])
        failures += 1

    # ── Alembic ──
    print("\n─ Alembic")
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import text as sa_text

        # Resolve alembic.ini path relative to backend/
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        alembic_ini = os.path.join(backend_dir, "alembic.ini")

        heads: list[str] = []
        current_rev: str = ""

        if os.path.exists(alembic_ini):
            cfg = Config(alembic_ini)
            script = ScriptDirectory.from_config(cfg)
            heads = list(script.get_heads())

            async with async_session() as db:
                conn = await db.connection()
                await conn.execute(sa_text("SET lock_timeout = '2s'"))
                _mc = MigrationContext.configure(conn)
                rows = await conn.execute(sa_text("SELECT version_num FROM alembic_version"))
                row = rows.one_or_none()
                current_rev = row._mapping["version_num"] if row else "(none)"
                head_rev = heads[0] if heads else "(none)"
                at_head = current_rev == head_rev

            _check("Alembic current", bool(current_rev and current_rev != "(none)"), current_rev[:12] if current_rev else "(none)")
            _check("Alembic head", bool(heads), heads[0][:12] if heads else "(none)")
            ok = _check("Alembic current=head", at_head,
                        f"current={current_rev[:12]} head={head_rev[:12]}")
            if not ok:
                failures += 1
        else:
            _check("Alembic config", False, f"not found: {alembic_ini}")
            failures += 1
    except Exception as e:
        _check("Alembic", False, str(e)[:80])
        failures += 1

    # ── Redis ──
    print("\n─ Redis")
    if settings.REDIS_URL:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await r.ping()
            await r.aclose()
            _check("Redis connectivity", True, settings.REDIS_URL.split("@")[-1] if "@" in settings.REDIS_URL else settings.REDIS_URL)

            # Queue namespace check
            try:
                from app.services.task_queue_service import task_queue
                ns_client = await task_queue._get_client()
                if ns_client is not None:
                    keys = await ns_client.keys("taskq:v2:*")
                    ns_count = len(keys)
                    _check("Queue namespace", True, f"{ns_count} keys in taskq:v2:*")
                else:
                    _check("Queue namespace", True, "no client (no Redis URL?)")
            except Exception as e2:
                _check("Queue namespace", False, str(e2)[:60])
                failures += 1
        except Exception as e:
            _check("Redis connectivity", False, str(e)[:80])
            failures += 1
    else:
        _check("Redis", False, "REDIS_URL not configured")
        failures += 1

    # ── Staging ──
    print("\n─ Staging")
    try:
        from app.services.staging_storage import _STAGING_DIR
        ok = _check("Staging dir exists", _STAGING_DIR.exists(), str(_STAGING_DIR))
        if not ok:
            failures += 1
        ok = _check("Staging dir writable", os.access(str(_STAGING_DIR), os.W_OK))
        if not ok:
            failures += 1

        # Disk space
        import shutil
        usage = shutil.disk_usage(str(_STAGING_DIR))
        free_gb = usage.free / (1024 ** 3)
        ok = _check("Staging disk free", free_gb > 1.0, f"{free_gb:.1f} GB free")
        if not ok:
            failures += 1
    except Exception as e:
        _check("Staging", False, str(e)[:80])
        failures += 1

    # ── OCR config ──
    print("\n─ OCR")
    try:
        _check("OCR_ENABLED", True, str(settings.OCR_ENABLED))
        _check("OCR_EXECUTION_BACKEND", True, settings.OCR_EXECUTION_BACKEND)

        # Check paddle not loaded (cloud safety)
        import sys as _sys
        paddle_in_modules = "paddleocr" in _sys.modules or "paddle" in _sys.modules
        if paddle_in_modules:
            from app.core.deployment_profile import detect_deployment_profile as _dp
            prof = _dp()
            if hasattr(prof, 'value'):
                prof_val = str(prof)
            else:
                prof_val = str(prof)
            is_cloud = "cloud" in prof_val.lower()
            if is_cloud:
                _check("PaddleOCR not loaded in cloud", False,
                       "PaddleOCR module loaded in cloud profile — potential memory issue")
                failures += 1
            else:
                _check("PaddleOCR loaded", True, "local profile, paddle expected")
        else:
            _check("PaddleOCR not loaded", True, "clean")

        # OCR remote connectivity check
        if settings.OCR_ENABLED and settings.OCR_EXECUTION_BACKEND == "paddlex_http":
            from app.main import _check_ocr_remote_connectivity
            remote_ok = await _check_ocr_remote_connectivity()
            _check("OCR remote connectivity", remote_ok,
                   "reachable" if remote_ok else "unreachable")
            if not remote_ok:
                failures += 1
    except Exception as e:
        _check("OCR config", False, str(e)[:80])
        failures += 1

    # ── Storage / scratch ──
    print("\n─ Storage")
    try:
        scratch = settings.WORKER_SCRATCH_DIR
        if scratch:
            ok = _check("Worker scratch dir exists", os.path.isdir(scratch), scratch)
            if ok:
                ok = _check("Worker scratch writable", os.access(scratch, os.W_OK))
            if not ok:
                failures += 1
        else:
            _check("Worker scratch dir", False, "WORKER_SCRATCH_DIR not set")
            failures += 1
    except Exception as e:
        _check("Storage", False, str(e)[:80])
        failures += 1

    # ── DB connection budget ──
    print("\n─ DB Connection Budget")
    try:
        from app.core.database import engine
        pool = engine.pool
        if hasattr(pool, 'size'):
            _check("Pool size", True, str(pool.size()))
        else:
            _check("Pool size", True, "using default")
    except Exception as e:
        _check("DB pool", False, str(e)[:60])
        failures += 1

    # ── Summary ──
    print(f"\n{'='*30}")
    if failures == 0:
        print(_green("All checks passed."))
        return 0
    else:
        print(_red(f"{failures} check(s) failed."))
        return 1


def main() -> None:
    code = asyncio.run(_main())
    sys.exit(code)


if __name__ == "__main__":
    main()
