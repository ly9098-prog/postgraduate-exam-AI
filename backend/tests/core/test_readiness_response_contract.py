"""Readiness sampling order and original response policy before extraction."""

import json
from dataclasses import FrozenInstanceError, replace
from unittest.mock import AsyncMock, Mock

import pytest

from app import main
from app.core.readiness_response import ReadinessSnapshot, build_readiness_response

PROBES = [
    "_check_database", "_check_redis", "_check_alembic_head", "_check_staging",
    "_check_staging_space", "_check_role_deps", "_check_ocr_config", "_check_queue",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, *PROBES])
async def test_readiness_probe_order_and_early_failure(monkeypatch, failure):
    from app.services import task_queue_worker

    calls = []
    error = RuntimeError("synthetic probe failure")
    results = [True, True, True, True, {"free": 10}, True, None, None]
    for name, value in zip(PROBES, results, strict=True):
        async def probe(name=name, value=value):
            calls.append(name)
            if name == failure:
                raise error
            return value
        monkeypatch.setattr(main, name, probe)
    monkeypatch.setattr(main, "_production_mode", False)
    monkeypatch.setattr(main.settings, "REDIS_URL", "")
    monkeypatch.setattr(
        task_queue_worker, "is_draining_v2",
        lambda: calls.append("draining") or False,
    )
    monkeypatch.setattr(
        main, "_get_db_pool_metrics", lambda: calls.append("pool") or {"size": 4},
    )
    if failure:
        with pytest.raises(RuntimeError) as caught:
            await main.ready_health()
        assert caught.value is error
        assert calls == PROBES[:PROBES.index(failure) + 1]
    else:
        response = await main.ready_health()
        assert response.status_code == 200
        assert calls == [*PROBES, "draining", "pool"]
        content = json.loads(response.body)
        assert content["checks"]["staging_space"] == {"free": 10}
        assert "redis" not in content["checks"]


@pytest.mark.asyncio
@pytest.mark.parametrize("drain", [False, True, "error"])
@pytest.mark.parametrize("production", [False, True])
async def test_draining_probe_error_fallback_and_cloud_privacy(monkeypatch, drain, production):
    from app.services import task_queue_worker

    for name in PROBES:
        result = None if name in {"_check_ocr_config", "_check_queue"} else True
        if name == "_check_staging_space":
            result = {"private": "synthetic-private"}
        monkeypatch.setattr(main, name, AsyncMock(return_value=result))
    monkeypatch.setattr(main, "_production_mode", production)
    monkeypatch.setattr(main.settings, "REDIS_URL", "")
    monkeypatch.setattr(main, "_get_db_pool_metrics", lambda: {"private": "synthetic-private"})
    monkeypatch.setattr(
        task_queue_worker, "is_draining_v2",
        Mock(side_effect=RuntimeError("private")) if drain == "error" else lambda: drain,
    )
    response = await main.ready_health()
    assert response.status_code == (503 if drain is True else 200)
    content = json.loads(response.body)
    assert ("checks" in content) is (not production)
    if production:
        assert "synthetic-private" not in response.body.decode()


def snapshot(**changes):
    value = ReadinessSnapshot(
        database_ok=True, redis_ok=True, alembic_ok=True, staging_ok=True,
        staging_space={}, role_ok=True, ocr_status=None, queue_status=None,
        draining=False, db_pool={"size": 4}, event_loop_lag_ms=1.25,
    )
    return replace(value, **changes)


@pytest.mark.parametrize("production,redis_configured", [
    (False, False), (False, True), (True, False), (True, True),
])
@pytest.mark.parametrize("changes,status,degraded", [
    ({}, 200, False),
    ({"database_ok": False}, 503, False),
    ({"staging_ok": False}, 503, False),
    ({"role_ok": False}, 503, False),
    ({"ocr_status": "unavailable"}, 503, False),
    ({"ocr_status": "degraded"}, 200, True),
    ({"queue_status": "degraded"}, 200, True),
    ({"queue_status": "unavailable"}, 200, False),
    ({"alembic_ok": False}, 200, False),
    ({"draining": True}, 503, False),
    ({"database_ok": False, "queue_status": "degraded"}, 503, True),
])
def test_pure_response_decision_matrix(production, redis_configured, changes, status, degraded):
    original = snapshot(**changes)
    code, content = build_readiness_response(
        original, production_mode=production, redis_configured=redis_configured,
    )
    assert code == status
    assert content["status"] == ("ok" if status == 200 else "unavailable")
    assert content["degraded"] is degraded
    assert ("checks" in content) is (not production)
    if not production:
        assert ("redis" in content["checks"]) is redis_configured
        assert content["checks"]["db_pool"] is original.db_pool


@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("configured", [False, True])
def test_redis_is_critical_only_when_included(production, configured):
    code, _ = build_readiness_response(
        snapshot(redis_ok=False), production_mode=production, redis_configured=configured,
    )
    assert code == (503 if production or configured else 200)


def test_snapshot_and_response_keep_existing_mapping_references_without_mutation():
    space = {"free": 42}
    pool = {"size": 3}
    value = snapshot(staging_space=space, db_pool=pool, ocr_status="", queue_status="")
    code, content = build_readiness_response(
        value, production_mode=False, redis_configured=False,
    )
    assert code == 200
    assert content["checks"]["staging_space"] is space
    assert content["checks"]["db_pool"] is pool
    assert "ocr" not in content["checks"] and "queue" not in content["checks"]
    assert space == {"free": 42} and pool == {"size": 3}
    with pytest.raises(FrozenInstanceError):
        value.database_ok = False
