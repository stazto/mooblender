from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from mooblender.mooble.transport import (
    HttpTransport,
    TransportError,
    _retry_after_delay,
)


class _Response:
    def __init__(
        self,
        data: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        will_close: bool = False,
    ) -> None:
        self.data = data
        self.status = status
        self.headers = headers or {}
        self.will_close = will_close

    def getheader(self, name: str):
        return self.headers.get(name)

    def read(self, amount: int | None = None) -> bytes:
        return self.data if amount is None else self.data[:amount]


class HttpTransportTests(unittest.TestCase):
    @patch("mooblender.mooble.transport.HTTPSConnection")
    def test_reuses_https_connection_on_the_same_thread(self, connection_type) -> None:
        connection = connection_type.return_value
        connection.getresponse.side_effect = [_Response(b"one"), _Response(b"two")]
        transport = HttpTransport()

        first = transport.get_bytes("https://cdn.mooble.com/one.png", max_bytes=10)
        second = transport.get_bytes("https://cdn.mooble.com/two.png", max_bytes=10)

        self.assertEqual((first, second), (b"one", b"two"))
        connection_type.assert_called_once()
        self.assertEqual(connection.request.call_count, 2)
        transport.close()
        connection.close.assert_called_once()

    @patch("mooblender.mooble.transport.HTTPSConnection")
    def test_rejects_oversized_response_before_reading(self, connection_type) -> None:
        connection = connection_type.return_value
        connection.getresponse.return_value = _Response(
            b"oversized",
            headers={"Content-Length": "100"},
        )
        transport = HttpTransport()

        with self.assertRaisesRegex(TransportError, "size limit"):
            transport.get_bytes("https://cdn.mooble.com/image.png", max_bytes=10)

        connection.close.assert_called_once()

    def test_rejects_untrusted_host_before_connecting(self) -> None:
        transport = HttpTransport()

        with self.assertRaisesRegex(TransportError, "not allowed"):
            transport.get_bytes("https://example.com/image.png", max_bytes=10)

    @patch("mooblender.mooble.transport.HTTPSConnection")
    def test_retries_rate_limit_after_bounded_server_delay(self, connection_type) -> None:
        connection = connection_type.return_value
        connection.getresponse.side_effect = [
            _Response(b"busy", status=429, headers={"Retry-After": "2"}),
            _Response(b"ready"),
        ]
        delays = []
        transport = HttpTransport(sleeper=delays.append)

        data = transport.get_bytes(
            "https://catalog.mooble.com/api/explorer/v2",
            max_bytes=10,
        )

        self.assertEqual(data, b"ready")
        self.assertEqual(delays, [2.0])
        self.assertEqual(connection_type.call_count, 2)

    @patch("mooblender.mooble.transport.HTTPSConnection")
    def test_caps_retry_after_and_stops_after_configured_attempts(
        self,
        connection_type,
    ) -> None:
        connection = connection_type.return_value
        connection.getresponse.side_effect = [
            _Response(b"busy", status=503, headers={"Retry-After": "9999"}),
            _Response(b"still busy", status=503, headers={"Retry-After": "9999"}),
        ]
        delays = []
        transport = HttpTransport(
            max_retries=1,
            max_retry_after=3.0,
            sleeper=delays.append,
        )

        with self.assertRaisesRegex(TransportError, "HTTP 503"):
            transport.get_bytes(
                "https://catalog.mooble.com/api/explorer/v2",
                max_bytes=20,
            )

        self.assertEqual(delays, [3.0])
        self.assertEqual(connection_type.call_count, 2)

    def test_retry_after_accepts_http_date_and_rejects_invalid_values(self) -> None:
        now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)

        self.assertEqual(
            _retry_after_delay(
                "Wed, 22 Jul 2026 12:00:08 GMT",
                maximum=30.0,
                now=now,
            ),
            8.0,
        )
        self.assertIsNone(
            _retry_after_delay("not-a-delay", maximum=30.0, now=now)
        )
        self.assertIsNone(_retry_after_delay("-1", maximum=30.0, now=now))


if __name__ == "__main__":
    unittest.main()
