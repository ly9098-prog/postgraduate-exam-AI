"""Contracts for OCR backend selection and import background wrappers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.ocr_types import WorkerResult
from app.services import import_pipeline_service as pipeline


class Ports:
    def __init__(self):
        self.binds: list[dict] = []
        self.logs: list[tuple] = []
        self.logger_obj = None
        self.events: list[tuple] = []
        self.tags: list[tuple] = []
        self.releases: list[dict] = []
        self.reservations: dict = {"pipe-1": ("tok", "ocr", "owner", 3)}
        self.exists = True
        self.unlinks: list[str] = []
        self.unlink_error: Exception | None = None
        self.execute_calls: list = []
        self.execute_error: Exception | None = None
        self.failures: list[dict] = []
        self.lifecycle_calls: list[tuple] = []
        self.lifecycle = SimpleNamespace(ensure_record="ENSURE-RECORD-SENTINEL")
        self.checkpoints: list = []
        self.import_runs: list = []
        self.import_error: Exception | None = None
        self.image_failures: list[tuple] = []
        self.persisted_failures: list[tuple] = []
        self.run_background = None
        self.gateway = None
        self.clients: list = []
        self.client_factory_calls: list = []
        self.cfg = None
        self.sanitized: list[str] = []


@pytest.fixture
def ports(monkeypatch):
    ports = Ports()

    def record_log(kind):
        def fn(*args, **kwargs):
            ports.logs.append((kind, args, kwargs))

        return fn

    ports.logger_obj = SimpleNamespace(
        info=record_log("info"),
        warning=record_log("warning"),
        error=record_log("error"),
    )
    monkeypatch.setattr(pipeline, "logger", ports.logger_obj)

    monkeypatch.setattr(
        pipeline, "bind_log_context", lambda **kwargs: ports.binds.append(kwargs)
    )
    monkeypatch.setattr(
        pipeline,
        "log_event",
        lambda logger_obj, event, **kwargs: ports.events.append(
            (getattr(logger_obj, "name", None), event, kwargs)
        ),
    )
    monkeypatch.setattr(pipeline, "set_tag", lambda *args: ports.tags.append(args))

    class Guard:
        async def release_reservation(self, **kwargs):
            ports.releases.append(kwargs)

    monkeypatch.setattr(pipeline, "resource_guard", Guard())
    monkeypatch.setattr(pipeline, "_pipeline_reservations", ports.reservations)

    def unlink(path):
        ports.unlinks.append(path)
        if ports.unlink_error is not None:
            raise ports.unlink_error

    monkeypatch.setattr(
        pipeline,
        "os",
        SimpleNamespace(
            path=SimpleNamespace(exists=lambda path: ports.exists),
            unlink=unlink,
        ),
    )

    async def fake_execute(request):
        ports.execute_calls.append(request)
        if ports.execute_error is not None:
            raise ports.execute_error

    monkeypatch.setattr(pipeline, "execute_import_background", fake_execute)
    monkeypatch.setattr(pipeline, "async_session", "SESSION-SENTINEL")

    def fake_run_background(*args, **kwargs):
        return "RUN-BACKGROUND-SENTINEL"

    ports.run_background = fake_run_background
    monkeypatch.setattr(pipeline, "run_pipeline_background", fake_run_background)

    async def fake_record_failure(**kwargs):
        ports.failures.append(kwargs)

    monkeypatch.setattr(
        pipeline, "record_background_pipeline_failure", fake_record_failure
    )
    monkeypatch.setattr(pipeline, "_set_pipeline_store", "STORE-SENTINEL")
    monkeypatch.setattr(pipeline, "capture_exception", "CAPTURE-SENTINEL")

    def fake_lifecycle_request(*args, **kwargs):
        ports.lifecycle_calls.append((args, kwargs))
        return ports.lifecycle

    monkeypatch.setattr(pipeline, "_image_lifecycle_request", fake_lifecycle_request)

    async def fake_ensure_checkpoint(request):
        ports.checkpoints.append(request)

    monkeypatch.setattr(pipeline, "ensure_image_checkpoint", fake_ensure_checkpoint)

    async def fake_run_lifecycle(lifecycle):
        ports.import_runs.append(lifecycle)
        if ports.import_error is not None:
            raise ports.import_error

    monkeypatch.setattr(pipeline, "run_image_import_lifecycle", fake_run_lifecycle)
    monkeypatch.setattr(
        pipeline,
        "_record_image_failure",
        lambda lifecycle, exc: ports.image_failures.append((lifecycle, exc)),
    )

    async def fake_persist_failure(lifecycle, exc):
        ports.persisted_failures.append((lifecycle, exc))

    monkeypatch.setattr(pipeline, "persist_image_import_failure", fake_persist_failure)
    return ports


@pytest.fixture
def ocr_ports(monkeypatch):
    ports = Ports()

    def record_log(kind):
        def fn(*args, **kwargs):
            ports.logs.append((kind, args, kwargs))

        return fn

    monkeypatch.setattr(
        pipeline,
        "logger",
        SimpleNamespace(
            info=record_log("info"),
            warning=record_log("warning"),
            error=record_log("error"),
        ),
    )

    from app.core import ocr_runtime_config
    from app.services import ocr_service, ocr_worker_client

    monkeypatch.setattr(ocr_runtime_config, "get_runtime_config", lambda: ports.cfg)
    monkeypatch.setattr(
        ocr_runtime_config,
        "sanitize_url",
        lambda url: ports.sanitized.append(url) or "sanitized-url",
    )
    monkeypatch.setattr(ocr_service, "get_gateway", lambda: ports.gateway)

    def fake_create_client(cfg):
        ports.client_factory_calls.append(cfg)
        return ports.clients.pop(0) if ports.clients else None

    monkeypatch.setattr(
        ocr_worker_client, "create_ocr_worker_client", fake_create_client
    )
    return ports


def make_config(**overrides):
    data = {
        "enabled": True,
        "execution_backend": "paddlex_http",
        "remote_url": "http://user:pass@host:8000/ocr",
        "use_gpu": False,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_client(results=(), error=None, shutdown_error=None):
    async def recognize_batch(pages):
        if error is not None:
            raise error
        return list(results)

    async def shutdown():
        if shutdown_error is not None:
            raise shutdown_error

    return SimpleNamespace(
        recognize_batch=recognize_batch,
        shutdown=shutdown,
        recognized_pages=None,
    )


@pytest.mark.asyncio
async def test_ocr_disabled_backend_fails_before_any_backend_use(ocr_ports):
    ocr_ports.cfg = make_config(enabled=False)

    with pytest.raises(RuntimeError, match="OCR 功能未启用"):
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert ocr_ports.client_factory_calls == []
    assert ocr_ports.logs == []


@pytest.mark.asyncio
async def test_ocr_disabled_execution_backend_fails_before_any_backend_use(ocr_ports):
    ocr_ports.cfg = make_config(execution_backend="disabled")

    with pytest.raises(RuntimeError, match="OCR 执行后端已禁用"):
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert ocr_ports.client_factory_calls == []


@pytest.mark.asyncio
async def test_gateway_backend_returns_result_without_writing_worker_client(ocr_ports):
    result = {"text": "网关识别文本", "lines": []}
    worker_result = WorkerResult(status="success", result=result)
    calls = []

    class Gateway:
        is_gateway = True

        async def recognize_pages(self, pages):
            calls.append(pages)
            return [worker_result]

    ocr_ports.cfg = make_config()
    ocr_ports.gateway = Gateway()

    returned = await pipeline._run_ocr_via_configured_backend(b"image-bytes")

    assert returned is result
    assert calls == [[(1, b"image-bytes")]]
    assert ocr_ports.client_factory_calls == []
    assert ocr_ports.logs == [
        (
            "info",
            (
                "image OCR backend selected: backend=%s remote_url=%s use_gpu=%s",
                "paddlex_http",
                "sanitized-url",
                False,
            ),
            {},
        )
    ]
    assert ocr_ports.sanitized == ["http://user:pass@host:8000/ocr"]


@pytest.mark.asyncio
async def test_non_gateway_object_falls_back_to_owned_worker_client(ocr_ports):
    result = {"text": "worker 文本"}
    ocr_ports.cfg = make_config()
    ocr_ports.gateway = SimpleNamespace(is_gateway=False)
    client = make_client([WorkerResult(status="success", result=result)])
    ocr_ports.clients = [client]

    recognize_calls = []

    async def recognize_batch(pages):
        recognize_calls.append(pages)
        return [WorkerResult(status="success", result=result)]

    client.recognize_batch = recognize_batch

    returned = await pipeline._run_ocr_via_configured_backend(b"image-bytes")

    assert returned is result
    assert ocr_ports.client_factory_calls == [ocr_ports.cfg]
    assert recognize_calls == [[(1, b"image-bytes")]]


@pytest.mark.asyncio
async def test_owned_worker_client_is_shut_down_after_success(ocr_ports):
    result = {"text": "worker 文本"}
    ocr_ports.cfg = make_config()
    shutdowns = []

    async def recognize_batch(pages):
        return [WorkerResult(status="success", result=result)]

    async def shutdown():
        shutdowns.append(True)

    ocr_ports.clients = [
        SimpleNamespace(recognize_batch=recognize_batch, shutdown=shutdown)
    ]

    assert await pipeline._run_ocr_via_configured_backend(b"image") is result
    assert shutdowns == [True]


@pytest.mark.asyncio
async def test_empty_backend_results_raise_after_owned_shutdown(ocr_ports):
    ocr_ports.cfg = make_config()
    shutdowns = []

    async def recognize_batch(pages):
        return []

    async def shutdown():
        shutdowns.append(True)

    ocr_ports.clients = [
        SimpleNamespace(recognize_batch=recognize_batch, shutdown=shutdown)
    ]

    with pytest.raises(RuntimeError) as caught:
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert str(caught.value) == "OCR 后端未返回识别结果"

    assert shutdowns == [True]


@pytest.mark.asyncio
async def test_failed_status_uses_stable_code_and_detail(ocr_ports):
    ocr_ports.cfg = make_config()
    ocr_ports.clients = [
        make_client(
            [
                WorkerResult(
                    status="failed",
                    result={"error": "engine exploded"},
                    stable_error_code="ocr.engine_error",
                )
            ]
        )
    ]

    with pytest.raises(RuntimeError) as caught:
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert str(caught.value) == "OCR 后端调用失败: ocr.engine_error: engine exploded"


@pytest.mark.asyncio
async def test_failed_result_flag_defaults_error_code_and_detail(ocr_ports):
    ocr_ports.cfg = make_config()
    ocr_ports.clients = [
        make_client([WorkerResult(status="success", result={"failed": True})])
    ]

    with pytest.raises(RuntimeError) as caught:
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert str(caught.value) == "OCR 后端调用失败: ocr.backend_failed: unknown"


@pytest.mark.asyncio
async def test_blank_text_raises_after_success_status(ocr_ports):
    ocr_ports.cfg = make_config()
    ocr_ports.clients = [
        make_client([WorkerResult(status="success", result={"text": "   "})])
    ]

    with pytest.raises(RuntimeError) as caught:
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert str(caught.value) == "OCR 后端返回成功，但未识别到文本"


@pytest.mark.asyncio
async def test_non_dict_result_is_treated_as_blank_text(ocr_ports):
    ocr_ports.cfg = make_config()
    ocr_ports.clients = [make_client([WorkerResult(status="success", result=None)])]

    with pytest.raises(RuntimeError) as caught:
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert str(caught.value) == "OCR 后端返回成功，但未识别到文本"


@pytest.mark.asyncio
async def test_backend_exception_propagates_identity_and_still_shuts_down(ocr_ports):
    error = ValueError("backend blew up")
    ocr_ports.cfg = make_config()
    ocr_ports.clients = [make_client(error=error)]

    with pytest.raises(ValueError) as caught:
        await pipeline._run_ocr_via_configured_backend(b"image")

    assert caught.value is error
    assert ocr_ports.logs[-1][0] == "error"
    assert ocr_ports.logs[-1][1] == ("OCR failed: %s", error)


@pytest.mark.asyncio
async def test_shutdown_failure_is_logged_not_raised(ocr_ports):
    result = {"text": "worker 文本"}
    shutdown_error = RuntimeError("shutdown boom")
    ocr_ports.cfg = make_config()
    ocr_ports.clients = [
        make_client(
            [WorkerResult(status="success", result=result)],
            shutdown_error=shutdown_error,
        )
    ]

    assert await pipeline._run_ocr_via_configured_backend(b"image") is result
    assert ocr_ports.logs[-1] == (
        "warning",
        ("Temporary OCR worker client shutdown failed: %s", shutdown_error),
        {},
    )


@pytest.mark.asyncio
async def test_missing_remote_url_keeps_dash_placeholder(ocr_ports):
    ocr_ports.cfg = make_config(remote_url=None)
    ocr_ports.gateway = SimpleNamespace(is_gateway=False)
    ocr_ports.clients = [
        make_client([WorkerResult(status="success", result={"text": "ok"})])
    ]

    await pipeline._run_ocr_via_configured_backend(b"image")

    assert ocr_ports.sanitized == []
    assert ocr_ports.logs[0][1][2] == "-"


@pytest.mark.asyncio
async def test_pipeline_wrapper_skips_cleanup_without_file_path(ports):
    await pipeline._run_pipeline_with_db(
        pipeline_id="pipe-1",
        file_path="",
        source_type="pdf",
        source_file="book.pdf",
        subject=None,
        subject_id=None,
        options={},
    )

    assert ports.unlinks == []
    assert ports.logs == []
    assert ports.releases != []


@pytest.mark.asyncio
async def test_pipeline_wrapper_binds_context_and_cleans_temp_file(ports):
    await pipeline._run_pipeline_with_db(
        pipeline_id="pipe-1",
        file_path="/tmp/file.pdf",
        source_type="pdf",
        source_file="book.pdf",
        subject="数据结构",
        subject_id=3,
        options={"_trace_id": "t-1", "_request_id": "r-1"},
        created_by="admin",
        source_sha256="a" * 64,
    )

    assert ports.binds == [
        {
            "trace_id": "t-1",
            "request_id": "r-1",
            "pipeline_id": "pipe-1",
            "source_type": "pdf",
            "source_file": "book.pdf",
        }
    ]
    assert len(ports.execute_calls) == 1
    request = ports.execute_calls[0]
    assert request.pipeline_id == "pipe-1"
    assert request.file_path == "/tmp/file.pdf"
    assert request.source_type == "pdf"
    assert request.source_file == "book.pdf"
    assert request.subject == "数据结构"
    assert request.subject_id == 3
    assert request.options == {"_trace_id": "t-1", "_request_id": "r-1"}
    assert request.created_by == "admin"
    assert request.source_sha256 == "a" * 64
    assert request.async_session == "SESSION-SENTINEL"
    assert request.run_background is ports.run_background
    assert request.logger is ports.logger_obj
    assert ports.releases == [
        {
            "token": "tok",
            "resource_type": "ocr",
            "owner_token": "owner",
            "generation": 3,
        }
    ]
    assert ports.reservations == {}
    assert ports.unlinks == ["/tmp/file.pdf"]
    assert ports.failures == []


@pytest.mark.asyncio
async def test_pipeline_wrapper_skips_unlink_when_temp_file_missing(ports):
    ports.exists = False

    await pipeline._run_pipeline_with_db(
        pipeline_id="pipe-1",
        file_path="/tmp/file.pdf",
        source_type="pdf",
        source_file="book.pdf",
        subject=None,
        subject_id=None,
        options={},
    )

    assert ports.unlinks == []
    assert [log for log in ports.logs if log[0] == "warning"] == []
    assert ports.releases != []


@pytest.mark.asyncio
async def test_pipeline_wrapper_logs_unlink_failure_without_raising(ports):
    ports.unlink_error = OSError("busy")

    await pipeline._run_pipeline_with_db(
        pipeline_id="pipe-1",
        file_path="/tmp/file.pdf",
        source_type="pdf",
        source_file="book.pdf",
        subject=None,
        subject_id=None,
        options={},
    )

    assert ports.logs[-1][0] == "warning"
    assert ports.logs[-1][1][0] == "Failed to delete pipeline tmp file %s: %s"
    assert ports.logs[-1][1][1] == "/tmp/file.pdf"


@pytest.mark.asyncio
async def test_pipeline_wrapper_records_crash_and_reraises_then_cleans(ports):
    error = RuntimeError("crash boom")
    ports.execute_error = error

    with pytest.raises(RuntimeError) as caught:
        await pipeline._run_pipeline_with_db(
            pipeline_id="pipe-1",
            file_path="/tmp/file.pdf",
            source_type="pdf",
            source_file="book.pdf",
            subject=None,
            subject_id=None,
            options={},
        )

    assert caught.value is error
    assert ports.logs[0][0] == "error"
    assert ports.logs[0][1][0] == "Background task for pipeline %s crashed: %s\n%s"
    assert ports.logs[0][1][1] == "pipe-1"
    assert ports.logs[0][1][2] is error
    assert ports.logs[0][1][3].startswith("Traceback (most recent call last):")
    assert ports.events == [
        (
            "postgraduate-ai",
            "import.background.error",
            {
                "level": "error",
                "pipeline_id": "pipe-1",
                "source_type": "pdf",
                "source_file": "book.pdf",
                "error_type": "RuntimeError",
                "error_message": "crash boom",
            },
        )
    ]
    assert len(ports.failures) == 1
    failure = ports.failures[0]
    assert failure["pipeline_id"] == "pipe-1"
    assert failure["source_type"] == "pdf"
    assert failure["source_file"] == "book.pdf"
    assert failure["exc"] is error
    assert failure["async_session"] == "SESSION-SENTINEL"
    assert failure["set_pipeline_store"] == "STORE-SENTINEL"
    assert failure["capture_exception"] == "CAPTURE-SENTINEL"
    assert ports.releases != []
    assert ports.unlinks == ["/tmp/file.pdf"]


@pytest.mark.asyncio
async def test_pipeline_wrapper_truncates_error_message_to_300_chars(ports):
    ports.execute_error = RuntimeError("x" * 500)

    with pytest.raises(RuntimeError):
        await pipeline._run_pipeline_with_db(
            pipeline_id="pipe-1",
            file_path="/tmp/file.pdf",
            source_type="pdf",
            source_file="book.pdf",
            subject=None,
            subject_id=None,
            options={},
        )

    assert len(ports.events[0][2]["error_message"]) == 300


@pytest.mark.asyncio
async def test_image_wrapper_builds_lifecycle_checkpoint_and_cleans(ports):
    await pipeline._run_image_pipeline_with_db(
        pipeline_id="pipe-1",
        image_path="/tmp/image.png",
        source_file="scan.png",
        subject="数据结构",
        subject_id=3,
        options={"_trace_id": "t-2", "_request_id": "r-2"},
        created_by="admin",
    )

    assert ports.binds == [
        {
            "trace_id": "t-2",
            "request_id": "r-2",
            "pipeline_id": "pipe-1",
            "source_type": "image",
            "source_file": "scan.png",
        }
    ]
    assert ports.events == [
        (
            None,
            "import.background.start",
            {
                "pipeline_id": "pipe-1",
                "source_type": "image",
                "source_file": "scan.png",
            },
        )
    ]
    assert ports.tags == [
        ("stage", "upload"),
        ("upload.filename", "scan.png"),
        ("upload.type", "image"),
    ]
    assert ports.lifecycle_calls == [
        (
            (
                "pipe-1",
                "/tmp/image.png",
                "scan.png",
                "数据结构",
                3,
                {"_trace_id": "t-2", "_request_id": "r-2"},
                "admin",
            ),
            {},
        )
    ]
    assert len(ports.checkpoints) == 1
    checkpoint = ports.checkpoints[0]
    assert checkpoint.pipeline_id == "pipe-1"
    assert checkpoint.source_file == "scan.png"
    assert checkpoint.created_by == "admin"
    assert checkpoint.async_session == "SESSION-SENTINEL"
    assert checkpoint.ensure_record == "ENSURE-RECORD-SENTINEL"
    assert ports.import_runs == [ports.lifecycle]
    assert ports.image_failures == []
    assert ports.persisted_failures == []
    assert ports.releases != []
    assert ports.unlinks == ["/tmp/image.png"]


@pytest.mark.asyncio
async def test_image_wrapper_records_failure_and_reraises_then_cleans(ports):
    error = RuntimeError("image boom")
    ports.import_error = error

    with pytest.raises(RuntimeError) as caught:
        await pipeline._run_image_pipeline_with_db(
            pipeline_id="pipe-1",
            image_path="/tmp/image.png",
            source_file="scan.png",
            subject=None,
            subject_id=None,
            options={},
        )

    assert caught.value is error
    assert ports.image_failures == [(ports.lifecycle, error)]
    assert ports.persisted_failures == [(ports.lifecycle, error)]
    assert ports.releases != []
    assert ports.unlinks == ["/tmp/image.png"]


@pytest.mark.asyncio
async def test_image_wrapper_logs_unlink_failure_without_raising(ports):
    ports.unlink_error = OSError("busy")

    await pipeline._run_image_pipeline_with_db(
        pipeline_id="pipe-1",
        image_path="/tmp/image.png",
        source_file="scan.png",
        subject=None,
        subject_id=None,
        options={},
    )

    assert ports.logs[-1][0] == "warning"
    assert ports.logs[-1][1][0] == "Failed to delete image tmp file %s: %s"
    assert ports.logs[-1][1][1] == "/tmp/image.png"
