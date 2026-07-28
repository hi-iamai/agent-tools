from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from common import RESULTS, jsonl_write, load_config


class LspClient:
    def __init__(self, repo: Path):
        env = dict(os.environ)
        vendor = Path(__file__).resolve().parents[1] / "vendor"
        env["PYTHONPATH"] = str(vendor) + os.pathsep + env.get("PYTHONPATH", "")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "pylsp"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env,
        )
        self.messages: queue.Queue[dict] = queue.Queue()
        self.stderr_lines: list[str] = []
        self.next_id = 1
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._stderr_reader, daemon=True).start()
        self.repo = repo

    def _reader(self):
        assert self.proc.stdout
        while True:
            headers = {}
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    return
                if line in (b"\r\n", b"\n"):
                    break
                key, value = line.decode().split(":", 1)
                headers[key.lower()] = value.strip()
            length = int(headers["content-length"])
            self.messages.put(json.loads(self.proc.stdout.read(length)))

    def _stderr_reader(self):
        assert self.proc.stderr
        for line in self.proc.stderr:
            self.stderr_lines.append(line.decode(errors="replace").rstrip())

    def send(self, method: str, params: dict, notification: bool = False):
        request = {"jsonrpc": "2.0", "method": method, "params": params}
        request_id = None
        if not notification:
            request_id = self.next_id
            self.next_id += 1
            request["id"] = request_id
        raw = json.dumps(request).encode()
        assert self.proc.stdin
        self.proc.stdin.write(f"Content-Length: {len(raw)}\r\n\r\n".encode() + raw)
        self.proc.stdin.flush()
        if notification:
            return None
        while True:
            try:
                response = self.messages.get(timeout=30)
            except queue.Empty as exc:
                raise RuntimeError("LSP timeout; stderr=" + "\n".join(self.stderr_lines[-20:])) from exc
            if response.get("id") == request_id:
                return response

    def close(self):
        try:
            if self.proc.poll() is None:
                self.send("shutdown", {})
                self.send("exit", {}, notification=True)
        except Exception:
            pass
        finally:
            self.proc.terminate()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    repo = Path(load_config()["repo_path_abs"])
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    client = LspClient(repo)
    root_uri = repo.as_uri()
    started = time.perf_counter()
    client.send("initialize", {
        "processId": None,
        "rootUri": root_uri,
        "capabilities": {"workspace": {"symbol": {}}},
        "workspaceFolders": [{"uri": root_uri, "name": "django"}],
    })
    initialize_ms = (time.perf_counter() - started) * 1000
    client.send("initialized", {}, notification=True)
    imports = {
        "QuerySet": "django.db.models.query",
        "HttpResponse": "django.http.response",
        "URLResolver": "django.urls.resolvers",
        "BaseCache": "django.core.cache.backends.base",
        "get_user_model": "django.contrib.auth",
    }
    probe = repo / "_lsp_benchmark_probe.py"
    probe_text = "\n".join(
        f"from {module} import {symbol}\n{symbol}"
        for symbol, module in imports.items()
    )
    client.send("textDocument/didOpen", {
        "textDocument": {
            "uri": probe.as_uri(),
            "languageId": "python",
            "version": 1,
            "text": probe_text,
        }
    }, notification=True)
    time.sleep(2)
    rows = []
    try:
        for repeat in range(args.repeats):
            for index, symbol in enumerate(imports):
                line = index * 2 + 1
                started = time.perf_counter()
                response = client.send("textDocument/definition", {
                    "textDocument": {"uri": probe.as_uri()},
                    "position": {"line": line, "character": len(symbol) - 1},
                })
                result = response.get("result") or []
                if isinstance(result, dict):
                    result = [result]
                rows.append({
                    "method": "pylsp_definition", "symbol": symbol, "repeat": repeat,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "result_count": len(result),
                    "success": bool(result), "initialize_ms": initialize_ms,
                    "error": response.get("error"),
                })
    finally:
        client.close()
    jsonl_write(output / "lsp_windows.jsonl", rows)
    print(json.dumps({"rows": len(rows), "initialize_ms": initialize_ms}, indent=2))


if __name__ == "__main__":
    main()
