"""Read-only loopback HTTP workbench for QSTE inspection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from qste.interfaces.contracts import InterfacePolicy
from qste.interfaces.service import InterfaceBroker

MAX_URL_BYTES = 4096


def create_handler(policy: InterfacePolicy) -> type[BaseHTTPRequestHandler]:
    broker = InterfaceBroker(policy)
    index_bytes = files("qste.interfaces").joinpath("workbench/index.html").read_bytes()

    class WorkbenchHandler(BaseHTTPRequestHandler):
        server_version = "QSTEWorkbench/0.1"

        def do_GET(self) -> None:
            if not self._request_allowed():
                return
            try:
                if len(self.path.encode("utf-8")) > MAX_URL_BYTES:
                    self._json(HTTPStatus.REQUEST_URI_TOO_LONG, {"error": "URL exceeds bound"})
                    return
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query, keep_blank_values=False)
                if parsed.path == "/":
                    self._send(HTTPStatus.OK, index_bytes, "text/html; charset=utf-8")
                    return
                if parsed.path == "/api/snapshot":
                    record_id = _one(query, "record_id", required=False)
                    maximum = _integer(query, "maximum_items", default=policy.maximum_items)
                    self._result(broker.snapshot(record_id=record_id, maximum_items=maximum))
                    return
                if parsed.path == "/api/record":
                    record_id = _one(query, "record_id")
                    if record_id is None:  # defensive narrowing; _one already rejects absence
                        raise ValueError("missing query parameter: record_id")
                    self._result(broker.inspect(record_id))
                    return
                if parsed.path == "/api/lineage":
                    record_id = _one(query, "record_id")
                    direction = _one(query, "direction", default="ancestors")
                    if record_id is None or direction is None:
                        raise ValueError("lineage query parameters are incomplete")
                    self._result(
                        broker.lineage(
                            record_id,
                            direction=direction,
                            maximum_depth=_integer(query, "maximum_depth", default=16),
                        )
                    )
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})
            except (TypeError, ValueError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_HEAD(self) -> None:
            if not self._request_allowed():
                return
            if urlsplit(self.path).path == "/":
                self._send(HTTPStatus.OK, b"", "text/html; charset=utf-8")
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "route not found"})

        def do_POST(self) -> None:
            if not self._request_allowed():
                return
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "workbench is read-only"})

        def do_PUT(self) -> None:
            self.do_POST()

        def do_PATCH(self) -> None:
            self.do_POST()

        def do_DELETE(self) -> None:
            self.do_POST()

        def do_OPTIONS(self) -> None:
            self.do_POST()

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _request_allowed(self) -> bool:
            port = getattr(self.server, "server_port", None)
            if not isinstance(port, int):
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "server port is invalid"})
                return False
            hosts = self.headers.get_all("Host", failobj=[])
            allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if len(hosts) != 1 or hosts[0].strip().casefold() not in allowed_hosts:
                self._json(
                    HTTPStatus.MISDIRECTED_REQUEST,
                    {"error": "Host is outside the loopback workbench origin"},
                )
                return False
            origins = self.headers.get_all("Origin", failobj=[])
            allowed_origins = {f"http://{host}" for host in allowed_hosts}
            if len(origins) > 1 or (
                origins and origins[0].strip().casefold() not in allowed_origins
            ):
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {"error": "Origin is outside the loopback workbench origin"},
                )
                return False
            return True

        def _result(self, result: dict[str, Any]) -> None:
            status = (
                HTTPStatus.OK
                if result["operation_status"] == "completed"
                else HTTPStatus.BAD_REQUEST
            )
            self._json(status, result)

        def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
            data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self._send(status, data, "application/json")

        def _send(self, status: HTTPStatus, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header(
                "Permissions-Policy",
                "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
            )
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                "img-src 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

    return WorkbenchHandler


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only QSTE inspection workbench")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--allowed-root", required=True, action="append", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--maximum-items", type=int, default=256)
    arguments = parser.parse_args(argv)
    if arguments.host != "127.0.0.1":
        raise SystemExit("P13 workbench binds only to 127.0.0.1")
    if arguments.port < 1024 or arguments.port > 65535:
        raise SystemExit("P13 workbench port must be between 1024 and 65535")
    policy = InterfacePolicy.create(
        workspace=arguments.workspace,
        allowed_roots=tuple(arguments.allowed_root),
        maximum_items=arguments.maximum_items,
    )
    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), create_handler(policy))
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        pass
    finally:
        server.server_close()
    return 0


def _one(
    query: dict[str, list[str]], key: str, *, required: bool = True, default: str | None = None
) -> str | None:
    values = query.get(key, [])
    if not values:
        if required and default is None:
            raise ValueError(f"missing query parameter: {key}")
        return default
    if len(values) != 1 or not values[0]:
        raise ValueError(f"query parameter must occur once: {key}")
    return values[0]


def _integer(query: dict[str, list[str]], key: str, *, default: int) -> int:
    value = _one(query, key, required=False)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"query parameter is not an integer: {key}") from error


if __name__ == "__main__":
    raise SystemExit(main())
