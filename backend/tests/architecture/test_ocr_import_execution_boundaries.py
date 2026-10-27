"""Guard OCR import execution delegation, cleanup order and failure copy."""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
SERVICE = APP / "services/import_pipeline_service.py"
ENTRIES = (
    "_run_ocr_via_configured_backend",
    "_run_image_pipeline_with_db",
    "_run_pipeline_with_db",
)
HELPERS = (
    "_resolve_ocr_backend_ports",
    "_select_ocr_backend_result",
    "_validate_ocr_backend_result",
    "_shutdown_temporary_ocr_client",
    "_bind_image_pipeline_context",
    "_cleanup_image_pipeline_temp_file",
    "_log_pipeline_background_crash",
    "_record_pipeline_background_crash",
    "_cleanup_pipeline_temp_file",
)


def load():
    return ast.parse(SERVICE.read_text())


def function(tree, name):
    return next(node for node in tree.body if getattr(node, "name", "") == name)


def source_of(tree, name):
    return ast.unparse(function(tree, name))


def ordered(source, *items):
    for item in items:
        assert item in source, item
    indexes = [source.index(item) for item in items]
    assert indexes == sorted(indexes), items


def check_budgets(tree):
    for name in ENTRIES + HELPERS:
        node = function(tree, name)
        assert node.end_lineno - node.lineno + 1 <= 50, name


def check_ocr_resolution(tree):
    entry = source_of(tree, "_run_ocr_via_configured_backend")
    resolver = source_of(tree, "_resolve_ocr_backend_ports")
    assert "from app.core.ocr_runtime_config import" not in entry
    assert "from app.services.ocr_service import get_gateway" not in entry
    ordered(
        resolver,
        "from app.core.ocr_runtime_config import get_runtime_config, sanitize_url",
        "from app.services.ocr_service import get_gateway",
        "from app.services.ocr_worker_client import create_ocr_worker_client",
        "cfg = get_runtime_config()",
        "if not cfg.enabled:",
        "raise RuntimeError('OCR 功能未启用（OCR_ENABLED=false）')",
        "if cfg.execution_backend == 'disabled':",
        "raise RuntimeError('OCR 执行后端已禁用（OCR_EXECUTION_BACKEND=disabled）')",
        "'image OCR backend selected: backend=%s remote_url=%s use_gpu=%s'",
        "return (cfg, get_gateway, create_ocr_worker_client)",
    )
    assert "sanitize_url(cfg.remote_url) if cfg.remote_url else '-'" in resolver
    assert "await _resolve_ocr_backend_ports()" not in entry
    assert "= _resolve_ocr_backend_ports()" in entry


def check_ocr_entry(tree):
    entry = source_of(tree, "_run_ocr_via_configured_backend")
    ordered(
        entry,
        "= _resolve_ocr_backend_ports()",
        "gateway = get_gateway()",
        "worker_client = None",
        "owns_worker_client = False",
        "if gateway is not None and gateway.is_gateway:",
        "await gateway.recognize_pages([(1, image_bytes)])",
        "worker_client = create_ocr_worker_client(cfg)",
        "if worker_client is None:",
        "owns_worker_client = True",
        "await worker_client.recognize_batch([(1, image_bytes)])",
        "return _validate_ocr_backend_result(_select_ocr_backend_result(results))",
        "except Exception as e:\n        logger.error('OCR failed: %s', e)\n        raise",
        "finally:",
        "if owns_worker_client and worker_client is not None:",
        "await _shutdown_temporary_ocr_client(worker_client)",
    )


def check_ocr_result_helpers(tree):
    select = source_of(tree, "_select_ocr_backend_result")
    assert "if not results:" in select
    assert "raise RuntimeError('OCR 后端未返回识别结果')" in select
    assert select.rstrip().endswith("return results[0]")

    validate = source_of(tree, "_validate_ocr_backend_result")
    ordered(
        validate,
        "result = worker_result.result if isinstance(worker_result.result, dict) else {}",
        "if worker_result.status != 'success' or result.get('failed'):",
        "stable_code = worker_result.stable_error_code or 'ocr.backend_failed'",
        "detail = result.get('error') or worker_result.error_type or 'unknown'",
        "raise RuntimeError(f'OCR 后端调用失败: {stable_code}: {detail}')",
        "text = str(result.get('text') or '')",
        "if not text.strip():",
        "raise RuntimeError('OCR 后端返回成功，但未识别到文本')",
        "return result",
    )

    shutdown = source_of(tree, "_shutdown_temporary_ocr_client")
    assert "await worker_client.shutdown()" in shutdown
    assert "except Exception as exc:" in shutdown
    assert (
        "logger.warning('Temporary OCR worker client shutdown failed: %s', exc)"
        in shutdown
    )


def check_image_wrapper(tree):
    binder = source_of(tree, "_bind_image_pipeline_context")
    ordered(
        binder,
        "bind_log_context(",
        "source_type='image'",
        "log_event(",
        "'import.background.start'",
        "set_tag('stage', 'upload')",
        "set_tag('upload.filename', source_file)",
        "set_tag('upload.type', 'image')",
    )

    wrapper = source_of(tree, "_run_image_pipeline_with_db")
    ordered(
        wrapper,
        "_bind_image_pipeline_context(pipeline_id, source_file, options)",
        "lifecycle = _image_lifecycle_request(",
        "try:",
        "await ensure_image_checkpoint(",
        "created_by=created_by",
        "async_session=async_session",
        "ensure_record=lifecycle.ensure_record",
        "await run_image_import_lifecycle(lifecycle)",
        "except Exception as exc:",
        "_record_image_failure(lifecycle, exc)",
        "await persist_image_import_failure(lifecycle, exc)",
        "raise",
        "finally:",
        "await _cleanup_image_pipeline_temp_file(pipeline_id, image_path)",
    )
    assert "bind_log_context(" not in wrapper


def check_pipeline_wrapper(tree):
    wrapper = source_of(tree, "_run_pipeline_with_db")
    ordered(
        wrapper,
        "bind_log_context(",
        "await execute_import_background(",
        "ImportBackgroundExecutionRequest(",
        "source_sha256=source_sha256",
        "async_session=async_session",
        "run_background=run_pipeline_background",
        "logger=logger",
        "except Exception as exc:",
        "await _record_pipeline_background_crash(",
        "raise",
        "finally:",
        "await _cleanup_pipeline_temp_file(pipeline_id, file_path)",
    )

    crash_log = source_of(tree, "_log_pipeline_background_crash")
    ordered(
        crash_log,
        "import traceback",
        "'Background task for pipeline %s crashed: %s\\n%s'",
        "traceback.format_exc()",
        "log_event(",
        "logging.getLogger('postgraduate-ai')",
        "'import.background.error'",
        "level='error'",
        "error_type=type(exc).__name__",
        "error_message=str(exc)[:300]",
    )

    recorder = source_of(tree, "_record_pipeline_background_crash")
    ordered(
        recorder,
        "_log_pipeline_background_crash(pipeline_id, source_type, source_file, exc)",
        "await record_background_pipeline_failure(",
        "async_session=async_session",
        "set_pipeline_store=_set_pipeline_store",
        "capture_exception=capture_exception",
    )


def check_cleanup_helpers(tree):
    for name, path_name in (
        ("_cleanup_pipeline_temp_file", "file_path"),
        ("_cleanup_image_pipeline_temp_file", "image_path"),
    ):
        source = source_of(tree, name)
        ordered(
            source,
            "await _release_pipeline_reservation(pipeline_id)",
            f"if {path_name} and os.path.exists({path_name}):",
            f"os.unlink({path_name})",
            "except OSError as e:",
            "logger.warning('Failed to delete",
        )
        assert source.index("await _release_pipeline_reservation") < source.index(
            f"os.unlink({path_name})"
        )


def test_ocr_import_helpers_stay_within_budget():
    check_budgets(load())


def test_ocr_import_execution_structure_and_cleanup_order():
    tree = load()
    check_ocr_resolution(tree)
    check_ocr_entry(tree)
    check_ocr_result_helpers(tree)
    check_image_wrapper(tree)
    check_pipeline_wrapper(tree)
    check_cleanup_helpers(tree)


def test_gate_rejects_short_error_truncation_and_swapped_cleanup():
    tree = load()
    crash_log = function(tree, "_log_pipeline_background_crash")
    for node in ast.walk(crash_log):
        if isinstance(node, ast.Subscript) and "300" in ast.unparse(node):
            node.slice = ast.Slice(lower=None, upper=ast.Constant(value=100), step=None)
            break
    with pytest.raises(AssertionError):
        check_pipeline_wrapper(tree)

    tree = load()
    cleanup = function(tree, "_cleanup_pipeline_temp_file")
    release = next(
        statement
        for statement in cleanup.body
        if "await _release_pipeline_reservation" in ast.unparse(statement)
    )
    cleanup.body = [
        statement for statement in cleanup.body if statement is not release
    ] + [release]
    with pytest.raises(AssertionError):
        check_cleanup_helpers(tree)
