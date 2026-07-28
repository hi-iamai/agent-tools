from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from common import RESULTS, ROOT, jsonl_write, load_config


CASES = {
    "rg_literal": ["rg", "-n", "-F", "get_user_model", "."],
    "git_grep_literal": ["git", "grep", "-n", "-F", "-e", "get_user_model"],
    "python_scan": [
        sys.executable, str(ROOT / "benchmark" / "scripts" / "runtime_worker.py"),
        "--repo", "{repo}", "--query", "get_user_model",
    ],
    "ast_grep": [
        str(ROOT / "node_modules" / "@ast-grep" / "cli" / "ast-grep.exe"),
        "run", "-l", "python", "-p", "get_user_model()", "--json=stream", ".",
    ],
}


def measure(command: list[str], repo: Path) -> dict:
    command = [str(repo) if value == "{repo}" else value for value in command]
    started = time.perf_counter()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(command, cwd=repo, stdout=stdout_file, stderr=stderr_file)
        process = psutil.Process(proc.pid)
        peak_rss = 0
        cpu_seconds = 0.0
        timed_out = False
        while proc.poll() is None:
            try:
                family = [process] + process.children(recursive=True)
                rss = 0
                cpu = 0.0
                for child in family:
                    try:
                        rss += child.memory_info().rss
                        times = child.cpu_times()
                        cpu += times.user + times.system
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                peak_rss = max(peak_rss, rss)
                cpu_seconds = max(cpu_seconds, cpu)
            except psutil.NoSuchProcess:
                pass
            if time.perf_counter() - started > 120:
                timed_out = True
                proc.kill()
                break
            time.sleep(0.02)
        proc.wait()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
    return {
        "duration_ms": (time.perf_counter() - started) * 1000,
        "cpu_ms": cpu_seconds * 1000,
        "peak_rss_bytes": peak_rss,
        "output_bytes": len(stdout),
        "returncode": proc.returncode,
        "error": "timeout" if timed_out else stderr.decode(errors="replace") if proc.returncode not in (0, 1) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    repo = Path(load_config()["repo_path_abs"])
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    rows = []
    for repeat in range(args.repeats):
        for name, command in CASES.items():
            rows.append({"backend": name, "repeat": repeat, **measure(command, repo)})
    jsonl_write(output / "resource_windows.jsonl", rows)
    print(json.dumps({"rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
