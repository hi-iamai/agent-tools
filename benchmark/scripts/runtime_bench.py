from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from common import RESULTS, ROOT, jsonl_write, load_config


QUERIES = ["RemovedInDjango71Warning", "get_user_model", "QuantumCacheTeleport"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    repo = Path(load_config()["repo_path_abs"])
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    worker = ROOT / "benchmark" / "scripts" / "runtime_worker.py"
    server = ROOT / "benchmark" / "scripts" / "runtime_http_server.py"
    rows: list[dict[str, Any]] = []

    stdio = subprocess.Popen(
        [sys.executable, str(worker), "--repo", str(repo), "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
    )
    http = subprocess.Popen(
        [sys.executable, str(server), "--repo", str(repo), "--port", "8766"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    try:
        for repeat in range(args.repeats):
            for query in QUERIES:
                cases = []
                started = time.perf_counter()
                proc = subprocess.run(
                    [sys.executable, str(worker), "--repo", str(repo), "--query", query],
                    capture_output=True, text=True, encoding="utf-8", timeout=120,
                )
                cases.append(("per_call_python", (time.perf_counter() - started) * 1000, proc.stdout))

                started = time.perf_counter()
                rg = subprocess.run(
                    ["rg", "-n", "-F", query, "."], cwd=repo,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                )
                cases.append(("per_call_rg", (time.perf_counter() - started) * 1000, rg.stdout))

                started = time.perf_counter()
                request = json.dumps({"id": f"{repeat}-{query}", "query": query}, ensure_ascii=False)
                assert stdio.stdin and stdio.stdout
                stdio.stdin.write(request + "\n")
                stdio.stdin.flush()
                stdio_result = stdio.stdout.readline()
                cases.append(("persistent_stdio", (time.perf_counter() - started) * 1000, stdio_result))

                started = time.perf_counter()
                with urllib.request.urlopen(
                    "http://127.0.0.1:8766/search?q=" + urllib.parse.quote(query), timeout=120
                ) as response:
                    http_result = response.read().decode()
                cases.append(("persistent_http", (time.perf_counter() - started) * 1000, http_result))

                for runtime, duration, result in cases:
                    rows.append({
                        "environment": args.environment, "runtime": runtime, "query": query,
                        "repeat": repeat, "duration_ms": duration,
                        "output_bytes": len(result.encode("utf-8")),
                        "success": (
                            json.loads(result).get("count", 0) == 0
                            if query == "QuantumCacheTeleport" and runtime != "per_call_rg"
                            else (not result.strip() if query == "QuantumCacheTeleport" else bool(result.strip()))
                        ),
                    })
    finally:
        stdio.terminate()
        http.terminate()
        stdio.wait(timeout=10)
        http.wait(timeout=10)
    jsonl_write(output / f"runtime_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
