from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from runtime_worker import search


class Handler(BaseHTTPRequestHandler):
    repo: Path

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/search":
            self.send_error(404)
            return
        query = parse_qs(parsed.query).get("q", [""])[0]
        result = search(self.repo, query)
        body = json.dumps({"matches": result, "count": len(result)}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    Handler.repo = Path(args.repo).resolve()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
