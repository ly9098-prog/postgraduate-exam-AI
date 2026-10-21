"""HTTP OCR startup preserves resource ownership through partial failures."""

import asyncio

import pytest

from tests.core.runtime_ocr_startup_ports import ports as ports

IMPORTS = [
    "httpx", "app.core.ocr_runtime_config", "app.features.ocr_gateway",
    "app.services.ocr_worker_client", "app.core.deployment_profile", "app.services.ocr_service",
]
OPERATIONS = ["config", "timeout", "limits", "client", "worker", "profile", "gateway", "publish"]


def test_gateway_assembly_keeps_timeout_limits_configuration_and_resource_identity(ports):
    assert ports.initialize(ports.resources, "web") is None
    assert ports.imports == IMPORTS
    assert ports.events == [
        ("config", (), {}),
        ("timeout", (), {"connect": 3, "read": 17, "write": 3, "pool": 3}),
        ("limits", (), {"max_keepalive_connections": 4, "max_connections": 4}),
        ("client", (), {"timeout": "synthetic-timeout", "limits": "synthetic-limits"}),
        ("worker", (ports.cfg,), {"http_client": ports.client}),
        ("profile", (), {}),
        ("gateway", (), {"mode": "gateway", "profile": "synthetic-profile", "worker_client": ports.worker}),
        ("publish", (ports.gateway,), {}),
    ]
    assert ports.resources.gateway is ports.gateway
    assert ports.resources.shared_http_client is ports.client
    assert ports.resources.worker_client is None
    ports.logger.info.assert_called_once_with(
        "OCR Gateway initialized (role=%s mode=gateway exec_backend=%s profile=%s env=%s)",
        "web", "synthetic-remote", "cloud_api", "production",
    )


def test_disabled_gateway_still_imports_original_dependencies_but_creates_no_resources(ports):
    ports.cfg.enabled = False
    ports.initialize(ports.resources, "all")
    assert ports.imports == IMPORTS[:4]
    assert [event[0] for event in ports.events] == ["config"]
    assert ports.resources.gateway is ports.resources.shared_http_client is None
    ports.logger.info.assert_called_once_with("OCR not enabled, skipping Gateway initialization")


@pytest.mark.parametrize("failed", OPERATIONS)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
def test_partial_assembly_preserves_only_previously_created_resources(ports, failed, error_type):
    error = error_type("synthetic OCR startup error")
    ports.failures[failed] = error
    with pytest.raises(error_type) as caught:
        ports.initialize(ports.resources, "web")
    assert caught.value is error
    index = OPERATIONS.index(failed)
    assert [event[0] for event in ports.events] == OPERATIONS[:index + 1]
    assert ports.resources.shared_http_client is (ports.client if index > OPERATIONS.index("client") else None)
    assert ports.resources.gateway is (ports.gateway if index > OPERATIONS.index("gateway") else None)
    retained = OPERATIONS.index("worker") < index <= OPERATIONS.index("gateway")
    assert ports.resources.worker_client is (ports.worker if retained else None)
    ports.logger.info.assert_not_called()
    ports.logger.warning.assert_not_called()


@pytest.mark.parametrize("failed", IMPORTS)
@pytest.mark.parametrize("error_type", [ImportError, asyncio.CancelledError])
def test_import_failure_propagates_with_original_partial_resource_state(ports, failed, error_type):
    error = error_type("synthetic OCR import error")
    ports.failures[failed] = error
    with pytest.raises(error_type) as caught:
        ports.initialize(ports.resources, "web")
    assert caught.value is error
    assert ports.imports == IMPORTS[:IMPORTS.index(failed) + 1]
    assert ports.resources.shared_http_client is (
        ports.client if failed in IMPORTS[4:] else None
    )
    assert ports.resources.gateway is (ports.gateway if failed == IMPORTS[-1] else None)
    assert ports.resources.worker_client is (
        ports.worker if failed == "app.core.deployment_profile" else None
    )
    ports.logger.info.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_startup_log_failure_propagates_after_original_resource_publication(ports, enabled):
    ports.cfg.enabled = enabled
    error = RuntimeError("synthetic log failure")
    ports.logger.info.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        ports.initialize(ports.resources, "web")
    assert caught.value is error
    assert ports.resources.gateway is (ports.gateway if enabled else None)
    assert ports.resources.shared_http_client is (ports.client if enabled else None)
    assert [event[0] for event in ports.events] == (OPERATIONS if enabled else ["config"])
