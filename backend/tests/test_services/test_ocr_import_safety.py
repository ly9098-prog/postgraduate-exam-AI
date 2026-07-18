"""Import safety verification for ``paddlex_http`` execution backend.

Runs a minimal Python subprocess that sets ``OCR_EXECUTION_BACKEND=paddlex_http``
and verifies that **no** PaddleOCR / paddle import happens during
``ocr_runtime_config`` resolution and ``create_ocr_worker_client``.

This must run in a **subprocess** so that the parent test process's
``sys.modules`` pollution does not mask real lazy-import violations.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap


def _run_import_safety_subprocess(backend: str = "paddlex_http") -> dict:
    """Run the import-safety script in a fresh Python subprocess.

    Args:
        backend: ``OCR_EXECUTION_BACKEND`` value to test.

    Returns the JSON-decoded result dict.
    """
    script = textwrap.dedent(f"""\
    import json
    import os
    import sys

    # Set env vars BEFORE any project imports so they take priority.
    os.environ["OCR_ENABLED"] = "true"
    os.environ["OCR_GATEWAY_MODE"] = "gateway"
    os.environ["OCR_EXECUTION_BACKEND"] = "{backend}"
    os.environ["OCR_REMOTE_URL"] = "http://127.0.0.1:9/ocr"
    os.environ["OCR_REMOTE_FAIL_FAST"] = "false"
    os.environ["OCR_USE_GPU"] = "false"
    os.environ["OCR_UNSAFE_THREAD_FALLBACK_ENABLED"] = "0"
    os.environ["APP_ENV"] = "development"

    # Record modules BEFORE any project imports
    before_paddle = any(m.startswith("paddle") for m in sys.modules)
    before_paddleocr = any(m.startswith("paddleocr") for m in sys.modules)

    # Resolve the runtime config (reads env vars)
    from app.core.ocr_runtime_config import get_runtime_config
    cfg = get_runtime_config()

    # Create the worker client via the factory
    from app.services.ocr_worker_client import create_ocr_worker_client
    client = create_ocr_worker_client(cfg)

    # Check modules AFTER the factory returned
    after_modules = list(sys.modules.keys())
    has_paddle = any(m.startswith("paddle") for m in after_modules)
    has_paddleocr = any(m.startswith("paddleocr") for m in after_modules)
    has_ocr_engine = "app.core.ocr_engine" in after_modules
    has_worker_pool = "app.core.ocr_worker_pool" in after_modules

    # Cleanup — shutdown may fail for LocalOcrWorkerClient if the pool
    # had no consumers started; that is acceptable for this test.
    if client is not None:
        try:
            import asyncio
            asyncio.run(client.shutdown())
        except Exception:
            pass

    result = {{
        "ok": not (has_paddle or has_paddleocr or has_ocr_engine),
        "has_paddle": has_paddle,
        "has_paddleocr": has_paddleocr,
        "has_ocr_engine": has_ocr_engine,
        "has_worker_pool": has_worker_pool,
        "client_type": type(client).__name__ if client is not None else "None",
        "execution_backend": cfg.execution_backend,
        "before_paddle": before_paddle,
        "before_paddleocr": before_paddleocr,
    }}
    print(json.dumps(result))
    """)

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
    )

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": proc.stderr[:1000] if proc.stderr else f"exit code {proc.returncode}",
            "stdout": proc.stdout[:500],
        }

    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"JSON parse error: {e}", "stdout": proc.stdout[:500]}


class TestImportSafetyPaddlexHttp:
    """Verify that paddlex_http mode does NOT import paddle/paddleocr."""

    def test_no_paddle_import(self):
        result = _run_import_safety_subprocess(backend="paddlex_http")
        assert result.get("ok"), (
            f"Import safety violation: paddle={result.get('has_paddle')} "
            f"paddleocr={result.get('has_paddleocr')} "
            f"ocr_engine={result.get('has_ocr_engine')} "
            f"worker_pool={result.get('has_worker_pool')} "
            f"client={result.get('client_type')} "
            f"error={result.get('error', 'none')}"
        )

    def test_client_type(self):
        result = _run_import_safety_subprocess(backend="paddlex_http")
        assert result.get("client_type") == "PaddleXHttpOcrWorkerClient", (
            f"Expected PaddleXHttpOcrWorkerClient, got {result.get('client_type')}"
        )

    def test_local_process_imports_worker_pool(self):
        """Verify that local_process mode DOES import OcrWorkerPool (negative control)."""
        result = _run_import_safety_subprocess(backend="local_process")
        assert result.get("has_worker_pool"), (
            "local_process should import OcrWorkerPool — "
            "if this unexpectedly fails, the import-safety test is broken"
        )

    def test_worker_pool_not_imported_in_paddlex_mode(self):
        """Verify OcrWorkerPool is NOT imported in paddlex_http mode."""
        result = _run_import_safety_subprocess(backend="paddlex_http")
        assert not result.get("has_worker_pool"), (
            "OcrWorkerPool must not be imported in paddlex_http mode"
        )
