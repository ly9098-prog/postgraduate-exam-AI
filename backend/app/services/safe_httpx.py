"""httpx client whose connections only reach public addresses.

``PublicOnlyBackend`` resolves the host itself, rejects non-public answers and
connects to the validated IP. TLS still verifies the original hostname, since
httpcore passes it to ``start_tls`` separately from the TCP target. This closes
the gap between a DNS check and the connection that DNS rebinding relies on.
"""

from __future__ import annotations

import asyncio

import httpcore
import httpx

from app.services.safe_remote_fetch import _resolve_public_addresses


class PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, inner: httpcore.AsyncNetworkBackend | None = None):
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        addresses = await asyncio.to_thread(_resolve_public_addresses, host, port)
        last_error: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except OSError as exc:
                last_error = exc
        raise last_error or OSError("no reachable public address")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("unix sockets are not allowed")

    async def sleep(self, seconds):
        await self._inner.sleep(seconds)


def build_public_only_client(**client_kwargs) -> httpx.AsyncClient:
    """AsyncClient that ignores proxy env vars and connects to public IPs only."""
    transport = httpx.AsyncHTTPTransport()
    transport._pool._network_backend = PublicOnlyBackend()
    return httpx.AsyncClient(transport=transport, trust_env=False, **client_kwargs)
