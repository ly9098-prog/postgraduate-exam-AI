"""Isolated configuration, cache and process ports for cloud boundary tests."""

import builtins
import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from app.core import ocr_runtime_config
from app.core.config import settings
from app.core.ocr_profile import get_ocr_profile


def _local_sdk(name):
    return name in {"paddle", "paddleocr"} or name.startswith(("paddle.", "paddleocr."))


@pytest.fixture(autouse=True)
def isolated_cloud_settings(monkeypatch, tmp_path):
    fields = {
        "APP_ENV": "test", "DEPLOYMENT_PROFILE": "", "DEPLOY_PROFILE": "",
        "OCR_ENABLED": False, "OCR_USE_GPU": False, "OCR_EXECUTION_BACKEND": "local_process",
        "OCR_REMOTE_URL": "", "OCR_REMOTE_TOKEN": "", "STAGING_STORAGE_DIR": str(tmp_path),
    }
    for name, value in fields.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.delenv("DEPLOYMENT_PROFILE", raising=False)
    for name in ["OCR_REMOTE_FALLBACK_ENABLED", "OCR_UNSAFE_THREAD_FALLBACK_ENABLED"]:
        monkeypatch.setenv(name, "0")
    monkeypatch.setattr(ocr_runtime_config, "_runtime_config", None)
    for name in list(sys.modules):
        if _local_sdk(name):
            monkeypatch.delitem(sys.modules, name)
    attempts = []

    def forbid_connect(*args, **kwargs):
        attempts.append("socket.connect")
        raise AssertionError("cloud boundary tests must not connect to external services")

    monkeypatch.setattr(socket.socket, "connect", forbid_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid_connect)
    get_ocr_profile.cache_clear()
    try:
        yield
    finally:
        get_ocr_profile.cache_clear()
        assert not attempts, "a network attempt was swallowed by a production boundary"


@pytest.fixture
def production_app_env(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")


@pytest.fixture
def cloud_settings(monkeypatch):
    fields = {
        "APP_ENV": "production", "DEPLOYMENT_PROFILE": "cloud_api",
        "OCR_ENABLED": True, "OCR_USE_GPU": False, "OCR_EXECUTION_BACKEND": "paddlex_http",
        "OCR_REMOTE_URL": "https://ocr.example.com/api", "OCR_REMOTE_TOKEN": "synthetic-ocr-token",
    }
    for name, value in fields.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
    return settings


@pytest.fixture
def forbid_local_ocr(monkeypatch):
    attempts = []
    original = builtins.__import__
    forbidden = {"app.services.ocr_executor_service", "app.core.ocr_process_pool", "app.core.ocr_engine"}

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):
        candidates = [name, *[f"{name}.{item}" for item in fromlist or () if item != "*"]]
        if any(_local_sdk(item) or item in forbidden for item in candidates):
            attempts.append(name)
            raise AssertionError(f"cloud path tried a local OCR import: {name}")
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded)
    yield attempts
    assert not attempts


def install_paddle_probe(monkeypatch, *, available=False, forbidden=False):
    calls = []
    original = importlib.util.find_spec

    def find_spec(name, *args, **kwargs):
        if name == "paddleocr":
            calls.append(name)
            if forbidden:
                raise AssertionError("cloud path must not probe the local PaddleOCR installation")
            return SimpleNamespace(name=name) if available else None
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    return calls


def run_script(script, tmp_path):
    (tmp_path / "scratch").mkdir()
    environment = os.environ | {
        "ISOLATION_TEST_ROOT": str(tmp_path),
        "WORKER_SCRATCH_DIR": str(tmp_path / "scratch"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        "AI_CONFIG_ENCRYPT_KEY": Fernet.generate_key().decode(),
        "SENTRY_DSN": "",
        "DEPLOY_PROFILE": "",
    }
    guard = """
import socket
def forbidden_connect(*args, **kwargs):
    raise AssertionError('cloud profile probe must not connect to external services')
socket.socket.connect = forbidden_connect
socket.socket.connect_ex = forbidden_connect
"""
    result = subprocess.run(
        [sys.executable, "-c", guard + script], env=environment, cwd=tmp_path,
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    return result.stdout
