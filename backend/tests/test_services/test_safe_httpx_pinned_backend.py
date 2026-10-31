import asyncio

import pytest

from app.services import safe_httpx
from app.services.safe_remote_fetch import UnsafeRemoteURLError


class _Inner:
    def __init__(self):
        self.calls = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.calls.append((host, port))
        return "stream"

    async def sleep(self, seconds):
        return None


def _backend(monkeypatch, answers):
    queue = list(answers)

    def fake_resolve(hostname, port):
        value = queue.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(safe_httpx, "_resolve_public_addresses", fake_resolve)
    inner = _Inner()
    return safe_httpx.PublicOnlyBackend(inner), inner


def test_connects_to_the_validated_ip_not_the_hostname(monkeypatch):
    backend, inner = _backend(monkeypatch, [["93.184.216.34"]])
    assert asyncio.run(backend.connect_tcp("files.example.com", 443)) == "stream"
    assert inner.calls == [("93.184.216.34", 443)]


def test_private_resolution_is_rejected_before_any_connection(monkeypatch):
    backend, inner = _backend(monkeypatch, [UnsafeRemoteURLError("non-public")])
    with pytest.raises(UnsafeRemoteURLError):
        asyncio.run(backend.connect_tcp("rebind.example.com", 443))
    assert inner.calls == []


def test_falls_back_to_next_validated_address(monkeypatch):
    backend, inner = _backend(monkeypatch, [["93.184.216.34", "93.184.216.35"]])

    async def flaky(host, port, **_kwargs):
        inner.calls.append((host, port))
        if host == "93.184.216.34":
            raise OSError("down")
        return "stream"

    inner.connect_tcp = flaky
    assert asyncio.run(backend.connect_tcp("files.example.com", 443)) == "stream"
    assert [h for h, _ in inner.calls] == ["93.184.216.34", "93.184.216.35"]


def test_download_client_rejects_loopback_hostname():
    client = safe_httpx.build_public_only_client()

    async def run():
        try:
            await client.get("https://localhost:9/")
        finally:
            await client.aclose()

    with pytest.raises(UnsafeRemoteURLError):
        asyncio.run(run())
