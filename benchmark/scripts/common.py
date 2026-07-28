from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmark"
RESULTS = BENCH / "results"
DATA = BENCH / "data"


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def load_config() -> dict[str, Any]:
    cfg = json.loads((BENCH / "config.json").read_text(encoding="utf-8"))
    cfg["repo_path_abs"] = str((ROOT / cfg["repo_path"]).resolve())
    return cfg


def run(
    args: list[str],
    cwd: Path,
    timeout: int = 120,
    check: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    proc = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    result = {
        "args": args,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "duration_ms": (time.perf_counter() - started) * 1000,
    }
    if check and proc.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def jsonl_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def environment_metadata(repo: Path) -> dict[str, Any]:
    commands = {
        "git": ["git", "--version"],
        "rg": ["rg", "--version"],
        "python": ["python", "--version"],
        "node": ["node", "--version"],
        "ast_grep": [str(ROOT / "node_modules" / "@ast-grep" / "cli" / "ast-grep.exe"), "--version"],
    }
    versions = {}
    for name, command in commands.items():
        try:
            r = run(command, ROOT, timeout=30)
            versions[name] = (r["stdout"] or r["stderr"]).splitlines()[0]
        except Exception as exc:
            versions[name] = f"unavailable: {exc}"
    commit = run(["git", "rev-parse", "HEAD"], repo, check=True)["stdout"].strip()
    tracked = run(["git", "ls-files"], repo, check=True)["stdout"].splitlines()
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "versions": versions,
        "repo_commit": commit,
        "tracked_files": len(tracked),
    }
