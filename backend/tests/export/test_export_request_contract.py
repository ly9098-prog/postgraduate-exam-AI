"""Direct API contracts using fake sessions/storage; no external file mutation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.v1 import exports as api
from app.schemas.export_task import CreateExportTaskRequest

NOW = datetime(2026, 10, 29, 12)


def task(**overrides):
    values = dict(
        id=8,
        user_id=3,
        status="completed",
        file_format="pdf",
        file_name="test.pdf",
        file_key="8/test.pdf",
        file_size=10,
        title="test",
        range_type="all",
        filters=None,
        selected_ids=None,
        show_date=True,
        export_date="",
        sort_by="newest",
        group_by="none",
        answer_position="none",
        analysis_position="none",
        space_style="standard",
        total_count=5,
        success_count=5,
        skip_count=0,
        error_message=None,
        error_code=None,
        created_at=NOW,
        completed_at=NOW,
        expires_at=NOW + timedelta(days=1),
        snapshot_id=None,
        source_task_id=None,
        retry_count=0,
        version=1,
        generator_version="old",
        idempotency_key="old",
        processing_started_at=NOW,
        started_at=NOW,
        heartbeat_at=NOW,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def ports(monkeypatch):
    from app.services.export import processor

    db = SimpleNamespace(
        **{
            name: AsyncMock()
            for name in ("execute", "commit", "refresh", "rollback", "delete")
        }
    )
    user = SimpleNamespace(id=3)
    monkeypatch.setattr(api, "utcnow", lambda: NOW)
    monkeypatch.setattr(api, "_preview_count", AsyncMock(return_value=5))
    monkeypatch.setattr(api, "validate_export_range", Mock())
    monkeypatch.setattr(api, "ensure_format_allowed", Mock())
    monkeypatch.setattr(api, "_get_user_task", AsyncMock(return_value=task()))
    monkeypatch.setattr(api, "_task_to_response", lambda value: value)
    monkeypatch.setattr(api, "_find_existing_task", AsyncMock(return_value=None))
    monkeypatch.setattr(
        api, "_create_export_task", AsyncMock(return_value=task(status="pending"))
    )
    monkeypatch.setattr(api, "_wake_local_export_processor", Mock())
    monkeypatch.setattr(processor, "_MAX_PER_USER", 2)
    monkeypatch.setattr(processor, "get_user_pending_count", AsyncMock(return_value=0))
    return SimpleNamespace(db=db, user=user, processor=processor)


@pytest.mark.asyncio
async def test_preview_translates_only_value_error(ports):
    api._preview_count.side_effect = ValueError("invalid range")
    with pytest.raises(HTTPException) as caught:
        await api.preview_export_count(
            CreateExportTaskRequest(range_type="all"), ports.db, ports.user
        )
    assert caught.value.status_code == 400
    assert caught.value.detail == "invalid range"
    api._preview_count.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await api.preview_export_count(
            CreateExportTaskRequest(range_type="all"), ports.db, ports.user
        )


@pytest.mark.asyncio
async def test_create_idempotent_return_does_not_check_limit_or_commit(ports):
    existing = task(status="pending")
    api._find_existing_task.return_value = existing
    result = await api.create_export(
        CreateExportTaskRequest(range_type="all"), ports.db, ports.user
    )
    assert result is existing
    api._wake_local_export_processor.assert_called_once_with()
    ports.processor.get_user_pending_count.assert_not_awaited()
    ports.db.commit.assert_not_awaited()
    api._preview_count.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_limit_locks_before_count_and_stops(ports):
    ports.processor.get_user_pending_count.return_value = 2
    with pytest.raises(HTTPException) as caught:
        await api.create_export(
            CreateExportTaskRequest(range_type="all"), ports.db, ports.user
        )
    assert caught.value.status_code == 429
    query = str(ports.db.execute.call_args.args[0])
    assert "FOR UPDATE" in query and "LIMIT" in query and "user_id" in query
    api._create_export_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [False, True])
async def test_create_integrity_recovery_uses_captured_user_id(
    ports, monkeypatch, fallback
):
    from app.services.export import service

    existing = task()
    api._create_export_task.side_effect = IntegrityError(
        "insert", {}, Exception("duplicate")
    )
    api._find_existing_task.side_effect = [None, None if fallback else existing]
    last_lookup = AsyncMock(return_value=existing)
    monkeypatch.setattr(service, "find_task_by_idempotency_key", last_lookup)

    async def rollback():
        ports.user.id = 999

    ports.db.rollback.side_effect = rollback
    result = await api.create_export(
        CreateExportTaskRequest(range_type="all"), ports.db, ports.user
    )
    assert result is existing
    assert api._find_existing_task.call_args.args[1] == 3
    if fallback:
        assert last_lookup.call_args.args[1] == 3
    ports.db.commit.assert_not_awaited()
    api._wake_local_export_processor.assert_not_called()


@pytest.mark.asyncio
async def test_create_integrity_without_existing_task_is_structured_conflict(
    ports, monkeypatch
):
    from app.services.export import service

    api._create_export_task.side_effect = IntegrityError("insert", {}, Exception())
    monkeypatch.setattr(
        service, "find_task_by_idempotency_key", AsyncMock(return_value=None)
    )
    with pytest.raises(HTTPException) as caught:
        await api.create_export(
            CreateExportTaskRequest(range_type="all"), ports.db, ports.user
        )
    assert caught.value.status_code == 409
    ports.db.rollback.assert_awaited_once()
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_commits_refreshes_before_live_projection(ports, monkeypatch):
    trace = []
    marker = object()

    async def commit():
        trace.append("commit")
        monkeypatch.setattr(api, "_task_to_response", lambda value: marker)

    async def refresh(value):
        trace.append(("refresh", value.id))

    ports.db.commit.side_effect = commit
    ports.db.refresh.side_effect = refresh
    api._wake_local_export_processor.side_effect = lambda: trace.append("wake")
    result = await api.create_export(
        CreateExportTaskRequest(range_type="all"), ports.db, ports.user
    )
    assert result is marker
    assert trace == ["commit", ("refresh", 8), "wake"]
    assert api._create_export_task.return_value.total_count == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "processing"])
async def test_delete_active_task_stops_before_snapshot_and_storage(ports, status):
    api._get_user_task.return_value = task(status=status)
    with pytest.raises(HTTPException) as caught:
        await api.delete_export(8, ports.db, ports.user)
    assert caught.value.status_code == 400
    assert api._get_user_task.call_args.kwargs == {"for_update": True}
    ports.db.delete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("shared", [False, True])
async def test_delete_orders_snapshot_file_and_record_mutation(
    ports, monkeypatch, shared
):
    trace = []
    value = task(snapshot_id="snapshot")
    api._get_user_task.return_value = value
    ports.db.execute.return_value = SimpleNamespace(
        scalar_one_or_none=lambda: 9 if shared else None
    )

    async def snapshot(*args):
        trace.append("snapshot")

    async def stored_file(key):
        trace.append(("file", key))
        return True

    monkeypatch.setattr(api, "delete_snapshot", snapshot)
    monkeypatch.setattr(
        api, "get_export_storage", lambda: SimpleNamespace(delete=stored_file)
    )
    ports.db.delete.side_effect = lambda value: trace.append(("record", value.id))
    ports.db.commit.side_effect = lambda: trace.append("commit")
    assert await api.delete_export(8, ports.db, ports.user) == {"success": True}
    assert trace == ([] if shared else ["snapshot"]) + [
        ("file", "8/test.pdf"),
        ("record", 8),
        "commit",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["snapshot", "false", "exception", "cancel"])
async def test_delete_failure_and_cancellation_boundaries(ports, monkeypatch, failure):
    api._get_user_task.return_value = task(
        snapshot_id="snapshot" if failure == "snapshot" else None
    )
    if failure == "snapshot":
        ports.db.execute.side_effect = RuntimeError("snapshot query")
    storage = SimpleNamespace(delete=AsyncMock(return_value=False))
    if failure in {"exception", "cancel"}:
        storage.delete.side_effect = (
            asyncio.CancelledError() if failure == "cancel" else RuntimeError("storage")
        )
    monkeypatch.setattr(api, "get_export_storage", lambda: storage)
    expected = asyncio.CancelledError if failure == "cancel" else HTTPException
    with pytest.raises(expected):
        await api.delete_export(8, ports.db, ports.user)
    assert ports.db.rollback.await_count == (0 if failure == "cancel" else 1)
    ports.db.delete.assert_not_awaited()
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "pending", "processing", "failed"])
async def test_download_preserves_old_file_in_all_previewable_states(
    ports, monkeypatch, status
):
    api._get_user_task.return_value = task(status=status)
    storage = object.__new__(api.LocalFileStorage)
    monkeypatch.setattr(api, "get_export_storage", lambda: storage)
    monkeypatch.setattr(api, "_resolve_local_path", lambda key: "/fake/file")
    monkeypatch.setattr(api.os.path, "exists", lambda path: True)
    response = await api.download_export(8, ports.db, ports.user)
    assert response.method == "stream" and response.file_size == 10
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("url,fallback", [("signed", False), ("", True), ("", False)])
async def test_download_cos_and_explicit_local_fallback(
    ports, monkeypatch, url, fallback
):
    storage = SimpleNamespace(get_download_url=AsyncMock(return_value=url))
    monkeypatch.setattr(api, "get_export_storage", lambda: storage)
    monkeypatch.setattr(
        api, "settings", SimpleNamespace(COS_ALLOW_LOCAL_FALLBACK=fallback)
    )
    monkeypatch.setattr(api, "_resolve_local_path", lambda key: "/fake/file")
    monkeypatch.setattr(api.os.path, "exists", lambda path: True)
    if not url and not fallback:
        with pytest.raises(HTTPException) as caught:
            await api.download_export(8, ports.db, ports.user)
        assert caught.value.status_code == 500
    else:
        response = await api.download_export(8, ports.db, ports.user)
        assert response.method == ("signed_url" if url else "stream")
    storage.get_download_url.assert_awaited_once_with("8/test.pdf", expiry_sec=3600)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["download_export", "stream_export_file"])
async def test_download_expiry_equality_and_headers(ports, monkeypatch, endpoint):
    api._get_user_task.return_value = task(expires_at=NOW)
    monkeypatch.setattr(api, "_resolve_local_path", lambda key: "/fake/file")
    monkeypatch.setattr(api.os.path, "exists", lambda path: True)
    monkeypatch.setattr(
        api, "get_export_storage", lambda: object.__new__(api.LocalFileStorage)
    )
    response = await getattr(api, endpoint)(8, ports.db, ports.user)
    if endpoint == "stream_export_file":
        assert response.headers["cache-control"] == "private, no-store, max-age=0"
        assert response.headers["content-disposition"].startswith("inline;")
    api._get_user_task.return_value.expires_at = NOW - timedelta(seconds=1)
    with pytest.raises(HTTPException) as caught:
        await getattr(api, endpoint)(8, ports.db, ports.user)
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_retry_reads_config_twice_and_preserves_source(ports):
    original = task(status="failed", retry_count=2)
    api._get_user_task.return_value = original
    new = api._create_export_task.return_value

    async def pending(db, user_id):
        original.title = "changed during await"
        return 0

    ports.processor.get_user_pending_count.side_effect = pending
    result = await api.retry_export(8, ports.db, ports.user)
    assert result is new and new.source_task_id == 8 and new.retry_count == 3
    assert api._create_export_task.call_args.args[2]["title"] == "changed during await"
    assert new.total_count == 5
    ports.db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [None, "missing", "present"])
@pytest.mark.parametrize("valid_file", [False, True])
async def test_reexport_reuses_record_snapshot_and_valid_previous_file(
    ports,
    monkeypatch,
    snapshot,
    valid_file,
):
    original = task(
        snapshot_id=snapshot,
        expires_at=NOW + timedelta(seconds=1) if valid_file else NOW,
    )
    api._get_user_task.return_value = original
    loader = AsyncMock(return_value={} if snapshot == "present" else None)
    monkeypatch.setattr(api, "load_snapshot", loader)
    monkeypatch.setattr(api, "settings", SimpleNamespace(GENERATOR_VERSION="new"))
    result = await api.re_export(8, ports.db, ports.user)
    assert result is original and original.id == 8 and original.status == "pending"
    assert original.idempotency_key is None and original.generator_version == "new"
    assert original.version == 2 and original.retry_count == 1
    assert original.snapshot_id == ("present" if snapshot == "present" else None)
    assert original.file_key == ("8/test.pdf" if valid_file else None)
    assert original.error_code == (api.REEXPORTING_ERROR_CODE if valid_file else None)
    assert api._preview_count.await_count == (0 if snapshot == "present" else 1)
    api._create_export_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_reexport_validation_failure_preserves_snapshot_and_file(
    ports, monkeypatch
):
    original = task(snapshot_id="missing")
    api._get_user_task.return_value = original
    monkeypatch.setattr(api, "load_snapshot", AsyncMock(return_value=None))
    api.validate_export_range.side_effect = ValueError("no questions")
    with pytest.raises(ValueError):
        await api.re_export(8, ports.db, ports.user)
    assert original.snapshot_id == "missing" and original.file_key == "8/test.pdf"
    ports.db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled,protocol,token",
    [
        (False, "", "legacy"),
        (True, "", ""),
        (True, "bearer", ""),
    ],
)
async def test_websocket_disabled_or_missing_token_closes_without_auth(
    monkeypatch,
    enabled,
    protocol,
    token,
):
    from app.core import config

    monkeypatch.setattr(
        config,
        "settings",
        SimpleNamespace(
            EXPORT_WEBSOCKET_ENABLED=enabled,
            APP_ENV="production",
            ALLOW_LEGACY_WEBSOCKET_QUERY_TOKEN=False,
        ),
    )
    ws = SimpleNamespace(
        headers={"sec-websocket-protocol": protocol},
        query_params={"token": token},
        close=AsyncMock(),
    )
    await api.export_status_ws(ws)
    assert ws.close.call_args.kwargs["code"] == 4001


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_error,push_error", [(False, False), (True, False), (False, True)]
)
async def test_websocket_auth_context_and_push_cancellation(
    monkeypatch, auth_error, push_error
):
    from app.core import config, database, log_context, security
    from app.services.export import push_service

    trace = []
    monkeypatch.setattr(
        config,
        "settings",
        SimpleNamespace(
            EXPORT_WEBSOCKET_ENABLED=True,
            APP_ENV="production",
            ALLOW_LEGACY_WEBSOCKET_QUERY_TOKEN=False,
        ),
    )
    session = AsyncMock()
    monkeypatch.setattr(database, "async_session", lambda: session)
    auth = AsyncMock(return_value=(SimpleNamespace(id=3), {}))
    if auth_error:
        auth.side_effect = RuntimeError("bad token")
    monkeypatch.setattr(security, "authenticate_user_token", auth)
    push = AsyncMock(side_effect=asyncio.CancelledError() if push_error else None)
    monkeypatch.setattr(push_service, "handle_export_ws", push)
    monkeypatch.setattr(
        log_context, "bind_log_context", lambda **kwargs: [tuple(kwargs)]
    )
    monkeypatch.setattr(
        log_context, "reset_log_context", lambda tokens: trace.append(tokens)
    )
    ws = SimpleNamespace(
        headers={"sec-websocket-protocol": "other, bearer, jwt"},
        query_params={"token": "ignored"},
        close=AsyncMock(),
    )
    if push_error:
        with pytest.raises(asyncio.CancelledError):
            await api.export_status_ws(ws)
    else:
        await api.export_status_ws(ws)
    assert len(trace) == 1
    assert len(trace[0]) == (1 if auth_error else 2)
    if auth_error:
        ws.close.assert_awaited_once_with(code=4001, reason="Invalid token")
        push.assert_not_awaited()
    else:
        push.assert_awaited_once_with(ws, 3, auth_token="jwt", subprotocol="bearer")


@pytest.mark.asyncio
async def test_user_task_query_preserves_user_scope_and_lock():
    db = SimpleNamespace(execute=AsyncMock())
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    with pytest.raises(HTTPException) as caught:
        await api._get_user_task(db, 8, 3, for_update=True)
    query = str(db.execute.call_args.args[0])
    assert "user_id" in query and "id" in query and "FOR UPDATE" in query
    assert caught.value.status_code == 404


@pytest.mark.parametrize(
    "status,expired",
    [
        ("pending", False),
        ("processing", False),
        ("completed", False),
        ("completed", True),
        ("failed", True),
        ("expired", False),
    ],
)
def test_projection_preserves_expiry_and_old_file_status(monkeypatch, status, expired):
    monkeypatch.setattr(api, "utcnow", lambda: NOW)
    value = task(
        status=status, expires_at=NOW if expired else NOW + timedelta(seconds=1)
    )
    response = api._task_to_response(value).model_dump()
    assert response["status"] == (
        "expired" if status == "completed" and expired else status
    )
    assert response["has_file"] is (not expired)
    assert response["created_at"] == "2026-10-29T12:00:00Z"
    assert list(response)[:5] == [
        "id",
        "status",
        "file_format",
        "file_name",
        "file_size",
    ]


@pytest.mark.parametrize(
    "running,seconds,reason",
    [
        (True, 10, None),
        (True, 31, "pending_timeout"),
        (False, 10, "processor_unavailable"),
        (False, 31, "processor_unavailable"),
    ],
)
def test_pending_projection_keeps_warning_precedence(
    monkeypatch, running, seconds, reason
):
    from app.core import config, time_utils
    from app.services.export import processor

    monkeypatch.setattr(api, "utcnow", lambda: NOW)
    monkeypatch.setattr(time_utils, "utcnow", lambda: NOW)
    monkeypatch.setattr(
        config, "settings", SimpleNamespace(EXPORT_PENDING_WARNING_SECONDS=30)
    )
    monkeypatch.setattr(processor, "get_processor_health", lambda: {"running": running})
    response = api._task_to_response(
        task(
            status="pending",
            created_at=NOW - timedelta(seconds=seconds),
        )
    )
    assert response.status_reason == reason
    if not running and seconds > 30:
        assert response.status_message.endswith("联系管理员")


@pytest.mark.asyncio
async def test_list_uses_two_scoped_queries_and_live_per_item_projection(
    ports, monkeypatch
):
    first, second = task(id=1), task(id=2)
    ports.db.execute.side_effect = [
        SimpleNamespace(fetchall=lambda: [(1,), (2,), (3,)]),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [first, second])),
    ]
    trace = []

    def project(value):
        trace.append(value.id)
        if value.id == 1:
            monkeypatch.setattr(
                api,
                "_task_to_response",
                lambda current: SimpleNamespace(model_dump=lambda: {"new": current.id}),
            )
        return SimpleNamespace(model_dump=lambda: {"old": value.id})

    monkeypatch.setattr(api, "_task_to_response", project)
    result = await api.list_exports(2, 2, ports.db, ports.user)
    assert result["items"] == [{"old": 1}, {"new": 2}]
    assert result["total"] == 3 and trace == [1]
    queries = [str(call.args[0]) for call in ports.db.execute.call_args_list]
    assert all("user_id" in query for query in queries)
    assert "ORDER BY" in queries[1] and "OFFSET" in queries[1] and "LIMIT" in queries[1]
