import ipaddress
import socket

import httpx
import pytest

from gridlens.settings import settings


@pytest.fixture(autouse=True)
def disable_real_model_keys(monkeypatch):
    """Keep test runs isolated from locally configured paid model credentials."""
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    monkeypatch.setattr(settings, "firecrawl_api_key", None)


@pytest.fixture(autouse=True)
def block_external_httpx_transport(monkeypatch):
    """Prevent accidental external HTTP requests while allowing local test servers."""

    def is_loopback(host: str) -> bool:
        normalized = host.rstrip(".").lower()
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    original_sync = httpx.HTTPTransport.handle_request
    original_async = httpx.AsyncHTTPTransport.handle_async_request
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_sync(transport, request):
        if not is_loopback(request.url.host):
            pytest.fail(f"Test attempted external HTTP request to {request.url.host}")
        return original_sync(transport, request)

    async def guarded_async(transport, request):
        if not is_loopback(request.url.host):
            pytest.fail(f"Test attempted external HTTP request to {request.url.host}")
        return await original_async(transport, request)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and not is_loopback(str(host)):
            pytest.fail(f"Test attempted external DNS lookup for {host}")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock, address):
        if sock.family not in {socket.AF_INET, socket.AF_INET6}:
            return original_connect(sock, address)
        host = address[0] if isinstance(address, tuple) and address else address
        if not is_loopback(str(host)):
            raise OSError(f"Test network guard blocked TCP connection to {host}")
        return original_connect(sock, address)

    def guarded_connect_ex(sock, address):
        if sock.family not in {socket.AF_INET, socket.AF_INET6}:
            return original_connect_ex(sock, address)
        host = address[0] if isinstance(address, tuple) and address else address
        if not is_loopback(str(host)):
            raise OSError(f"Test network guard blocked TCP connection to {host}")
        return original_connect_ex(sock, address)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
