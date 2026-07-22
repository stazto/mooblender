"""Minimal HTTPS transport with bounded responses and reusable connections.

Every initial URL and redirect is revalidated against an explicit host list.
Connections are reused only by their owning thread, while response sizes,
redirects, stale-connection retries, and service-directed waits are bounded.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from threading import Lock, get_ident
from typing import Any
from urllib.parse import urljoin, urlparse


class TransportError(RuntimeError):
    """Raised for rejected URLs, HTTP failures, and bounded-read violations."""


def _retry_after_delay(
    value: str | None,
    *,
    maximum: float,
    now: datetime | None = None,
) -> float | None:
    """Parse Retry-After seconds or an HTTP date and cap the blocking delay."""
    if not value:
        return None
    try:
        delay = float(value.strip())
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delay = (retry_at - (now or datetime.now(UTC))).total_seconds()
    if not math.isfinite(delay) or delay < 0.0:
        return None
    return min(delay, maximum)


class HttpTransport:
    """Thread-local reusable HTTPS transport restricted to trusted hosts."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        user_agent: str = "Mooblender/0.5.1 (+https://github.com/dantedex/mooblender)",
        allowed_hosts: tuple[str, ...] = ("catalog.mooble.com", "cdn.mooble.com"),
        max_retries: int = 2,
        max_retry_after: float = 30.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Configure request bounds, trusted hosts, and thread-local connections."""
        self.timeout = timeout
        self.user_agent = user_agent
        self.allowed_hosts = allowed_hosts
        self.max_retries = min(max(max_retries, 0), 5)
        # Never let a server-provided value block a background worker for more
        # than one minute. The default is deliberately shorter so cancellation
        # and shutdown remain responsive during service throttling.
        self.max_retry_after = min(max(max_retry_after, 0.0), 60.0)
        self.sleeper = sleeper
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
        # Validation occurs on every recursive call, so an allowed endpoint
        # cannot redirect the client to an arbitrary host or credentialed URL.
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
        """Read a bounded response and honor limited server retry instructions."""
        retry_count = 0
        while True:
            response, hostname, port = self._open(url)
            try:
                if response.status < 200 or response.status >= 300:
                    retry_delay = (
                        _retry_after_delay(
                            response.getheader("Retry-After"),
                            maximum=self.max_retry_after,
                        )
                        if response.status in {429, 503}
                        else None
                    )
                    if retry_delay is not None and retry_count < self.max_retries:
                        # Do not reuse a connection whose error body was not
                        # consumed. A fresh request starts after the bounded wait.
                        self._drop_connection(hostname, port)
                        self.sleeper(retry_delay)
                        retry_count += 1
                        continue
                    raise TransportError(f"Mooble returned HTTP {response.status}")
                # Content-Length rejects known oversize responses early. The
                # limited read is authoritative for absent or dishonest headers
                # and consumes one sentinel byte to detect overflow.
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
