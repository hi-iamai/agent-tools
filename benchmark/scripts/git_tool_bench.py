from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from common import RESULTS, jsonl_write, load_config


COMMANDS = {
    "status": ["git", "status", "--porcelain"],
    "diff": ["git", "diff", "--", "django/db/models/query.py"],
    "log_20": ["git", "log", "-20", "--oneline"],
    "show_head": ["git", "show", "--stat", "--oneline", "HEAD"],
    "blame_range": ["git", "blame", "-L", "330,350", "--", "django/db/models/query.py"],
    "changed_files": ["git", "diff", "--name-only", "HEAD"],
    "history_search": ["git", "log", "-S", "get_user_model", "--oneline", "--all"],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    repo = Path(load_config()["repo_path_abs"])
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    rows = []
    for repeat in range(args.repeats):
        for name, command in COMMANDS.items():
            started = time.perf_counter()
            proc = subprocess.run(
                command, cwd=repo, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180,
            )
            rows.append({
                "environment": args.environment, "tool": name, "repeat": repeat,
                "duration_ms": (time.perf_counter() - started) * 1000,
                "returncode": proc.returncode,
                "output_bytes": len(proc.stdout.encode()),
                "line_count": len(proc.stdout.splitlines()),
                "error": proc.stderr if proc.returncode else None,
            })
    jsonl_write(output / f"git_tools_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows), "tools": list(COMMANDS)}, indent=2))


if __name__ == "__main__":
    main()
