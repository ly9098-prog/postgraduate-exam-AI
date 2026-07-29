"""Small SSRF-resistant downloader for server-side remote assets.

The implementation resolves and validates every redirect target, rejects all
non-global addresses, and connects to the validated IP while preserving the
original hostname for TLS SNI and the Host header. This prevents the usual
DNS-rebinding gap between validation and connection.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlsplit

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class UnsafeRemoteURLError(ValueError):
    """Raised when a remote URL is unsafe or cannot be fetched safely."""


@dataclass(frozen=True)
class RemoteResponse:
    status: int
    data: bytes
    content_type: str
    final_url: str


def _resolve_public_addresses(hostname: str, port: int) -> list[str]:
    try:
        rows = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeRemoteURLError("remote host cannot be resolved") from exc

    addresses: list[str] = []
    for row in rows:
        raw_ip = str(row[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(raw_ip)
        except ValueError as exc:
            raise UnsafeRemoteURLError("invalid resolved address") from exc
        # is_global excludes loopback, private, link-local, multicast,
        # unspecified, reserved and documentation ranges.
        if not ip.is_global:
            raise UnsafeRemoteURLError("remote host resolves to a non-public address")
        normalized = str(ip)
        if normalized not in addresses:
            addresses.append(normalized)

    if not addresses:
        raise UnsafeRemoteURLError("remote host has no usable public address")
    return addresses


def validate_remote_url(
    url: str,
    *,
    allow_http: bool = False,
) -> tuple[SplitResult, list[str]]:
    parsed = urlsplit(str(url).strip())
    if parsed.scheme not in ({"https", "http"} if allow_http else {"https"}):
        raise UnsafeRemoteURLError("only HTTPS remote URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeRemoteURLError("URL credentials are not allowed")
    if not parsed.hostname:
        raise UnsafeRemoteURLError("remote URL has no hostname")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeRemoteURLError("invalid remote URL port") from exc
    if port < 1 or port > 65535:
        raise UnsafeRemoteURLError("invalid remote URL port")
    return parsed, _resolve_public_addresses(parsed.hostname, port)


def is_safe_remote_url(url: str, *, allow_http: bool = False) -> bool:
    try:
        validate_remote_url(url, allow_http=allow_http)
        return True
    except UnsafeRemoteURLError:
        return False


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, resolved_ip: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout)
        self._resolved_ip = resolved_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._resolved_ip, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, resolved_ip: str, port: int, timeout: float):
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._resolved_ip = resolved_ip

    def connect(self) -> None:
        raw_sock = socket.create_connection(
            (self._resolved_ip, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)


def _host_header(parsed: SplitResult, port: int) -> str:
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = 443 if parsed.scheme == "https" else 80
    return hostname if port == default_port else f"{hostname}:{port}"


def _validate_headers(headers: dict[str, str] | None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for name, value in (headers or {}).items():
        if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
            raise UnsafeRemoteURLError("invalid request header")
        if name.lower() in {"host", "connection", "content-length", "transfer-encoding"}:
            continue
        cleaned[str(name)] = str(value)
    return cleaned


def request_remote_bytes(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    max_bytes: int,
    timeout: float = 15.0,
    allow_http: bool = False,
    follow_redirects: bool = False,
    max_redirects: int = 0,
    require_2xx: bool = False,
    headers: dict[str, str] | None = None,
) -> RemoteResponse:
    """Perform a bounded request while pinning every validated destination IP.

    Redirect following is disabled by default, which is important for requests
    carrying API credentials. Callers that enable redirects should not include
    sensitive headers.
    """
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    method = method.strip().upper()
    if method not in {"GET", "HEAD", "POST"}:
        raise ValueError("unsupported HTTP method")
    if body is not None and len(body) > 10 * 1024 * 1024:
        raise UnsafeRemoteURLError("request body is too large")

    request_headers = _validate_headers(headers)
    current_url = str(url).strip()
    current_method = method
    current_body = body

    for redirect_count in range(max_redirects + 1):
        parsed, addresses = validate_remote_url(current_url, allow_http=allow_http)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        connection_cls = (
            _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
        )
        connection = connection_cls(
            parsed.hostname or "",
            addresses[0],
            port,
            timeout,
        )
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        outgoing_headers = {
            "Host": _host_header(parsed, port),
            "Connection": "close",
            **request_headers,
        }

        try:
            connection.request(
                current_method,
                path,
                body=current_body,
                headers=outgoing_headers,
            )
            response = connection.getresponse()

            if response.status in _REDIRECT_STATUSES:
                if not follow_redirects:
                    return RemoteResponse(
                        status=response.status,
                        data=response.read(min(max_bytes, 64 * 1024)),
                        content_type=response.getheader("Content-Type", ""),
                        final_url=current_url,
                    )
                location = response.getheader("Location")
                response.read(1024)
                if not location:
                    raise UnsafeRemoteURLError("redirect has no Location header")
                if redirect_count >= max_redirects:
                    raise UnsafeRemoteURLError("too many redirects")
                current_url = urljoin(current_url, location)
                if response.status == 303 or (
                    response.status in {301, 302} and current_method == "POST"
                ):
                    current_method = "GET"
                    current_body = None
                continue

            if require_2xx and not 200 <= response.status < 300:
                raise UnsafeRemoteURLError(
                    f"remote server returned HTTP {response.status}"
                )

            content_length = response.getheader("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise UnsafeRemoteURLError("remote resource is too large")
                except ValueError as exc:
                    raise UnsafeRemoteURLError("invalid Content-Length header") from exc

            chunks: list[bytes] = []
            total = 0
            while current_method != "HEAD":
                remaining = max_bytes + 1 - total
                if remaining <= 0:
                    raise UnsafeRemoteURLError("remote resource is too large")
                chunk = response.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise UnsafeRemoteURLError("remote resource is too large")

            return RemoteResponse(
                status=response.status,
                data=b"".join(chunks),
                content_type=response.getheader("Content-Type", ""),
                final_url=current_url,
            )
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise UnsafeRemoteURLError("remote resource fetch failed") from exc
        finally:
            connection.close()

    raise UnsafeRemoteURLError("too many redirects")


def fetch_remote_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 15.0,
    allow_http: bool = False,
    max_redirects: int = 3,
    headers: dict[str, str] | None = None,
) -> RemoteResponse:
    """Fetch a bounded public resource with safe redirect handling."""
    merged_headers = {
        "Accept": "image/*,application/octet-stream;q=0.5",
        **(headers or {}),
    }
    return request_remote_bytes(
        url,
        method="GET",
        max_bytes=max_bytes,
        timeout=timeout,
        allow_http=allow_http,
        follow_redirects=True,
        max_redirects=max_redirects,
        require_2xx=True,
        headers=merged_headers,
    )

