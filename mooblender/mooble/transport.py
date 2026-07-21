"""Minimal HTTPS transport with bounded responses and injectable behavior."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class TransportError(RuntimeError):
    pass


class HttpTransport:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        user_agent: str = "Mooblender/0.1 (+https://github.com/dantedex/mooblender)",
        allowed_hosts: tuple[str, ...] = ("catalog.mooble.com", "cdn.mooble.com"),
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.allowed_hosts = allowed_hosts

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise TransportError("only HTTPS Mooble resources are allowed")
        hostname = (parsed.hostname or "").lower()
        if hostname not in self.allowed_hosts:
            raise TransportError(f"resource host is not allowed: {hostname or '<empty>'}")
        if parsed.username or parsed.password:
            raise TransportError("credentials in resource URLs are not allowed")

    def get_bytes(self, url: str, *, max_bytes: int) -> bytes:
        self.validate_url(url)
        request = Request(
            url,
            headers={"Accept": "*/*", "User-Agent": self.user_agent},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > max_bytes:
                    raise TransportError("response exceeds configured size limit")
                data = response.read(max_bytes + 1)
        except HTTPError as error:
            raise TransportError(f"Mooble returned HTTP {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            raise TransportError(f"could not reach Mooble: {error}") from error
        if len(data) > max_bytes:
            raise TransportError("response exceeds configured size limit")
        return data

    def get_json(self, url: str, *, max_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
        data = self.get_bytes(url, max_bytes=max_bytes)
        try:
            value = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TransportError(f"Mooble returned invalid JSON: {error}") from error
        if not isinstance(value, dict):
            raise TransportError("Mooble JSON root is not an object")
        return value
