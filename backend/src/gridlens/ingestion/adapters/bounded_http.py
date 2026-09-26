"""HTTP response limits shared by the public-source readers."""

from __future__ import annotations

import httpx


class ResponseTooLarge(ValueError):
    pass


def read_bounded_response(
    client: httpx.Client,
    url: str,
    max_bytes: int,
    params: dict[str, str | int] | None = None,
) -> tuple[httpx.Headers, bytes]:
    with client.stream("GET", url, params=params) as response:
        response.raise_for_status()
        declared = response.headers.get("content-length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError as exc:
                raise ResponseTooLarge("Response Content-Length is malformed") from exc
            if declared_size > max_bytes:
                raise ResponseTooLarge(f"Response Content-Length exceeds {max_bytes} bytes")
        parts: list[bytes] = []
        size = 0
        for part in response.iter_bytes():
            size += len(part)
            if size > max_bytes:
                raise ResponseTooLarge(f"Response exceeds {max_bytes} bytes")
            parts.append(part)
        return response.headers, b"".join(parts)
