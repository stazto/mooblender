"""Minimal HTTPS transport with bounded responses and reusable connections."""

from __future__ import annotations

import json
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from threading import Lock, get_ident
from typing import Any
from urllib.parse import urljoin, urlparse


class TransportError(RuntimeError):
    """Raised for rejected URLs, HTTP failures, and bounded-read violations."""


class HttpTransport:
    """Thread-local reusable HTTPS transport restricted to trusted hosts."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        user_agent: str = "Mooblender/0.1 (+https://github.com/dantedex/mooblender)",
        allowed_hosts: tuple[str, ...] = ("catalog.mooble.com", "cdn.mooble.com"),
    ) -> None:
        """Configure request bounds, trusted hosts, and thread-local connections."""
        self.timeout = timeout
        self.user_agent = user_agent
        self.allowed_hosts = allowed_hosts
        self._connection_lock = Lock()
        self._thread_connections: dict[
            int,
            dict[tuple[str, int], HTTPSConnection],
        ] = {}

    def validate_url(self, url: str) -> None:
        """Allow credential-free HTTPS URLs only on the configured host list."""
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise TransportError("only HTTPS Mooble resources are allowed")
        hostname = (parsed.hostname or "").lower()
        if hostname not in self.allowed_hosts:
            raise TransportError(f"resource host is not allowed: {hostname or '<empty>'}")
        if parsed.username or parsed.password:
            raise TransportError("credentials in resource URLs are not allowed")

    def _connections(self) -> dict[tuple[str, int], HTTPSConnection]:
        """Return the reusable connection map owned by the calling thread."""
        thread_id = get_ident()
        with self._connection_lock:
            return self._thread_connections.setdefault(thread_id, {})

    def _connection(self, hostname: str, port: int) -> HTTPSConnection:
        """Reuse or create the calling thread's connection to one endpoint."""
        key = (hostname, port)
        connections = self._connections()
        connection = connections.get(key)
        if connection is None:
            connection = HTTPSConnection(hostname, port=port, timeout=self.timeout)
            connections[key] = connection
        return connection

    def _drop_connection(self, hostname: str, port: int) -> None:
        """Remove and close a connection that cannot safely be reused."""
        connection = self._connections().pop((hostname, port), None)
        if connection is not None:
            connection.close()

    def close(self) -> None:
        """Atomically detach and close every thread-local connection."""
        with self._connection_lock:
            connection_groups = tuple(self._thread_connections.values())
            self._thread_connections.clear()
        for connections in connection_groups:
            for connection in connections.values():
                connection.close()

    def _open(
        self,
        url: str,
        *,
        redirects_left: int = 3,
        retry_stale: bool = True,
    ) -> tuple[HTTPResponse, str, int]:
        """Open a validated GET with bounded redirects and one stale retry."""
        self.validate_url(url)
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port or 443
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection = self._connection(hostname, port)
        try:
            connection.request(
                "GET",
                target,
                headers={"Accept": "*/*", "User-Agent": self.user_agent},
            )
            response = connection.getresponse()
        except (HTTPException, TimeoutError, OSError) as error:
            self._drop_connection(hostname, port)
            if retry_stale:
                return self._open(
                    url,
                    redirects_left=redirects_left,
                    retry_stale=False,
                )
            raise TransportError(f"could not reach Mooble: {error}") from error

        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            response.read()
            if response.will_close:
                self._drop_connection(hostname, port)
            if not location:
                raise TransportError("Mooble returned a redirect without a location")
            if redirects_left <= 0:
                raise TransportError("too many Mooble redirects")
            return self._open(
                urljoin(url, location),
                redirects_left=redirects_left - 1,
            )
        return response, hostname, port

    def get_bytes(self, url: str, *, max_bytes: int) -> bytes:
        """Read a successful response without exceeding its byte limit."""
        response, hostname, port = self._open(url)
        try:
            if response.status < 200 or response.status >= 300:
                raise TransportError(f"Mooble returned HTTP {response.status}")
            length = response.getheader("Content-Length")
            if length is not None and int(length) > max_bytes:
                raise TransportError("response exceeds configured size limit")
            data = response.read(max_bytes + 1)
        except TransportError:
            self._drop_connection(hostname, port)
            raise
        except (HTTPException, TimeoutError, OSError, ValueError) as error:
            self._drop_connection(hostname, port)
            raise TransportError(f"could not read Mooble response: {error}") from error
        finally:
            if response.will_close:
                self._drop_connection(hostname, port)
        if len(data) > max_bytes:
            raise TransportError("response exceeds configured size limit")
        return data

    def get_json(self, url: str, *, max_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
        """Decode a bounded UTF-8 JSON response whose root must be an object."""
        data = self.get_bytes(url, max_bytes=max_bytes)
        try:
            value = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TransportError(f"Mooble returned invalid JSON: {error}") from error
        if not isinstance(value, dict):
            raise TransportError("Mooble JSON root is not an object")
        return value
