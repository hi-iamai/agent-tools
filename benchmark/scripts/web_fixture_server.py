from __future__ import annotations

import argparse
import gzip
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


ARTICLE = """
<article>
  <h1>Agent Tool Evaluation</h1>
  <p id="lead">The canonical answer is ORCHID-7429.</p>
  <p>Structured tools reduce ambiguity while preserving evidence.</p>
  <h2>Metrics</h2>
  <table><tr><th>metric</th><th>value</th></tr><tr><td>recall</td><td>0.93</td></tr></table>
  <pre><code>grep(query="ORCHID-7429")</code></pre>
</article>
"""


class Handler(BaseHTTPRequestHandler):
    counters: dict[str, int] = {}

    def log_message(self, *_args) -> None:
        pass

    def send_body(self, body: bytes, status: int = 200, content_type: str = "text/html; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/static":
            html = f"<html><body><nav>{'menu ' * 100}</nav>{ARTICLE}<footer>{'legal ' * 100}</footer></body></html>"
            return self.send_body(html.encode())
        if path == "/malformed":
            return self.send_body(f"<html><body><nav>noise<div>{ARTICLE}<p>unfinished".encode())
        if path == "/unicode":
            return self.send_body(f"<html><body><article><h1>工具评测</h1><p>关键答案：兰花-7429。</p>{ARTICLE}</article></body></html>".encode())
        if path == "/large":
            return self.send_body((f"<html><body>{'<aside>noise</aside>' * 2000}{ARTICLE}{'<p>tail</p>' * 5000}</body></html>").encode())
        if path == "/dynamic":
            html = """<html><body><div id='app'>Loading...</div>
            <script>document.getElementById('app').innerHTML='<article><h1>Dynamic</h1><p>The dynamic answer is COBALT-318.</p></article>';</script>
            </body></html>"""
            return self.send_body(html.encode())
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/static")
            self.end_headers()
            return
        if path == "/gzip":
            body = gzip.compress(f"<html><body>{ARTICLE}</body></html>".encode())
            return self.send_body(body, headers={"Content-Encoding": "gzip"})
        if path == "/slow":
            time.sleep(float(parse_qs(parsed.query).get("seconds", ["1"])[0]))
            return self.send_body(f"<html><body>{ARTICLE}</body></html>".encode())
        if path == "/status/500":
            return self.send_body(b"server error", 500, "text/plain")
        if path == "/api/page":
            page = int(parse_qs(parsed.query).get("page", ["1"])[0])
            payload = {"page": page, "items": [{"id": page * 10 + i, "amount": i + 0.5} for i in range(3)],
                       "next": f"/api/page?page={page + 1}" if page < 3 else None}
            return self.send_body(json.dumps(payload).encode(), content_type="application/json")
        if path == "/api/rate-limit":
            key = self.client_address[0]
            self.counters[key] = self.counters.get(key, 0) + 1
            if self.counters[key] <= 2:
                return self.send_body(b'{"error":"rate limited"}', 429, "application/json", {"Retry-After": "1"})
            return self.send_body(b'{"ok":true}', content_type="application/json")
        if path == "/api/gzip":
            payload = json.dumps({"answer": "ORCHID-7429", "compressed": True}).encode()
            return self.send_body(
                gzip.compress(payload),
                content_type="application/json",
                headers={"Content-Encoding": "gzip"},
            )
        if path == "/api/redirect":
            self.send_response(302)
            self.send_header("Location", "/api/page?page=1")
            self.end_headers()
            return
        if path == "/api/slow":
            time.sleep(float(parse_qs(parsed.query).get("seconds", ["1"])[0]))
            return self.send_body(b'{"ok":true}', content_type="application/json")
        return self.send_body(b"not found", 404, "text/plain")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
