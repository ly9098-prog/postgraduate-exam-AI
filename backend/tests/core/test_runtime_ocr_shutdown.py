"""Exercise the real OCR shutdown block without starting external resources."""

import ast
import asyncio
import builtins
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import main
from app.core import deployment_profile, runtime_resource_shutdown
from app.services.runtime_ocr_startup import HttpOcrResources

ABSENT = object()


@pytest.fixture
def ocr_ports(monkeypatch):
    events = []
    failures = {}

    async def close(name):
        events.append(name)
        if name in failures:
            raise failures[name]

    async def executor_shutdown(*, wait):
        events.append(("executor", wait))
        await close("executor_wait")

    async def wait_for(coro, *, timeout):
        events.append(("wait_for", timeout))
        if "wait" in failures:
            coro.close()
            raise failures["wait"]
        return await coro

    async def gateway_shutdown():
        await close("gateway")

    async def client_close():
        await close("client")

    def detect():
        events.append("profile")
        if "profile" in failures:
            raise failures["profile"]
        return state.profile

    logger = SimpleNamespace(info=Mock(), warning=Mock(), exception=Mock())
    state = SimpleNamespace(
        events=events, failures=failures, logger=logger,
        profile=deployment_profile.DeploymentProfile.LOCAL_IMPORT,
        runtime=SimpleNamespace(wait_for=wait_for),
        gateway=SimpleNamespace(shutdown=gateway_shutdown),
        client=SimpleNamespace(aclose=client_close),
    )
    monkeypatch.setattr(deployment_profile, "detect_deployment_profile", detect)
    monkeypatch.setattr(runtime_resource_shutdown, "logger", logger)
    monkeypatch.setattr(runtime_resource_shutdown, "asyncio", state.runtime)
    monkeypatch.setitem(sys.modules, "app.services.ocr_executor_service", SimpleNamespace(
        ocr_executor=SimpleNamespace(shutdown=executor_shutdown),
    ))
    monkeypatch.setitem(sys.modules, "app.features.ocr_gateway", SimpleNamespace(OCRGateway=object))
    return state


@pytest.fixture
def run_ocr_shutdown(ocr_ports):
    source = Path(main.__file__).read_text()
    start = source.index("        # 6. Shutdown OCR infrastructure")
    end = source.index("        await shutdown_render_resources()", start)
    function = ast.AsyncFunctionDef(
        name="shutdown", args=ast.arguments(
            posonlyargs=[], args=[ast.arg(arg="role"), ast.arg(arg="_ocr_resources")],
            kwonlyargs=[], kw_defaults=[], defaults=[],
        ), body=ast.parse(textwrap.dedent(source[start:end])).body, decorator_list=[],
    )
    code = compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "ocr_shutdown", "exec")

    async def run(role="web", gateway=True, client=True):
        namespace = {
            "logger": ocr_ports.logger, "asyncio": ocr_ports.runtime,
            "shutdown_ocr_executor": main.shutdown_ocr_executor,
            "shutdown_http_ocr_gateway": main.shutdown_http_ocr_gateway,
        }
        exec(code, namespace)
        resources = HttpOcrResources(
            gateway=ocr_ports.gateway if gateway else None,
            shared_http_client=ocr_ports.client if client is not ABSENT and client else None,
        )
        await namespace["shutdown"](role, resources)

    return run


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["web", "all", "worker", "scheduler", "unknown"])
@pytest.mark.parametrize("cloud", [False, True])
async def test_role_and_cloud_profile_control_executor_without_reordering_gateway_and_client(run_ocr_shutdown, ocr_ports, role, cloud):
    if cloud:
        ocr_ports.profile = deployment_profile.DeploymentProfile.CLOUD_API
    await run_ocr_shutdown(role)
    expected = []
    if role in {"web", "all"}:
        expected = ["profile"]
        if not cloud:
            expected += [("wait_for", 30), ("executor", True), "executor_wait"]
        expected += ["gateway", "client"]
    assert ocr_ports.events == expected
    ocr_ports.logger.warning.assert_not_called()
    ocr_ports.logger.exception.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("gateway", [False, True])
@pytest.mark.parametrize("client", [ABSENT, False, True])
async def test_missing_client_and_gateway_are_skipped(run_ocr_shutdown, ocr_ports, gateway, client):
    await run_ocr_shutdown(gateway=gateway, client=client)
    expected = ["profile", ("wait_for", 30), ("executor", True), "executor_wait"]
    if gateway:
        expected.append("gateway")
    if client is True:
        expected.append("client")
    assert ocr_ports.events == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["profile", "wait", "executor_wait", "gateway", "client"])
@pytest.mark.parametrize("error_type", [RuntimeError, TimeoutError, asyncio.CancelledError])
async def test_original_error_cancellation_and_shared_client_propagation(run_ocr_shutdown, ocr_ports, failed, error_type):
    error = error_type("synthetic shutdown failure")
    ocr_ports.failures[failed] = error
    propagates = error_type is asyncio.CancelledError or failed == "client"
    if propagates:
        with pytest.raises(error_type) as caught:
            await run_ocr_shutdown()
        assert caught.value is error
        if failed != "client":
            assert "client" not in ocr_ports.events
        if failed in {"profile", "wait", "executor_wait"}:
            assert "gateway" not in ocr_ports.events
    else:
        await run_ocr_shutdown()
        assert ocr_ports.events[-1] == "client"
        warning = failed == "gateway" or error_type is TimeoutError
        assert ocr_ports.logger.warning.call_count == int(warning)
        assert ocr_ports.logger.exception.call_count == int(not warning)


@pytest.mark.asyncio
@pytest.mark.parametrize("module,cloud", [
    ("app.services.ocr_executor_service", True),
    ("app.services.ocr_executor_service", False),
    ("app.features.ocr_gateway", False),
    ("app.core.deployment_profile", False),
])
async def test_import_errors_stay_at_original_boundaries_and_cloud_skips_local_executor(
    run_ocr_shutdown, ocr_ports, monkeypatch, module, cloud,
):
    if cloud:
        ocr_ports.profile = deployment_profile.DeploymentProfile.CLOUD_API
    imported = []
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == module:
            imported.append(name)
            raise ImportError("synthetic unavailable shutdown module")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    await run_ocr_shutdown()
    assert ocr_ports.events[-1] == "client"
    assert imported == ([] if cloud else [module])
    assert ocr_ports.logger.warning.call_count == int(module == "app.features.ocr_gateway")
    assert ocr_ports.logger.exception.call_count == int(not cloud and module != "app.features.ocr_gateway")
