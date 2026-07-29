from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from strict_runtime_engine import execute_serialized, request_from_dict, search_sync


def run_once(query: str, limit: int, delay_ms: int) -> None:
    sys.stdout.buffer.write(execute_serialized(query, limit, delay_ms))


def run_stdio() -> None:
    for raw in sys.stdin.buffer:
        try:
            request = json.loads(raw)
            query, limit, delay_ms = request_from_dict(request)
            response = {
                "id": request.get("id"),
                "result": search_sync(query, limit, delay_ms),
            }
        except Exception as exc:
            response = {"id": None, "error": repr(exc)}
        sys.stdout.buffer.write(
            json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        sys.stdout.buffer.flush()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            body = b'{"ok":true}'
        elif parsed.path == "/search":
            params = parse_qs(parsed.query)
            body = execute_serialized(
                params.get("query", [""])[0],
                int(params.get("limit", ["10"])[0]),
                int(params.get("delay_ms", ["0"])[0]),
            )
        elif parsed.path == "/crash":
            body = b'{"crashing":true}'
            self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            os._exit(23)
            return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_http(port: int) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.shutdown_requested = False
    while not server.shutdown_requested:
        server.handle_request()


def run_mcp(transport: str, port: int) -> None:
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("strict-runtime")

    @server.tool()
    def search(query: str, limit: int, delay_ms: int = 0) -> dict[str, object]:
        return search_sync(query, limit, delay_ms)

    if transport == "mcp-stdio":
        server.run("stdio")
    else:
        server.run(
            "streamable-http",
            host="127.0.0.1",
            port=port,
            streamable_http_path="/mcp",
            json_response=True,
            stateless_http=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["once", "stdio", "http", "mcp-stdio", "mcp-http"])
    parser.add_argument("--query", default="needle-common")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    if args.mode == "once":
        run_once(args.query, args.limit, args.delay_ms)
    elif args.mode == "stdio":
        run_stdio()
    elif args.mode == "http":
        run_http(args.port)
    else:
        run_mcp(args.mode, args.port)


if __name__ == "__main__":
    main()
