from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

from common import RESULTS, ROOT, jsonl_write


REPOS = {
    "django": ROOT / "benchmark" / "repos" / "django",
    "pytest": ROOT / "benchmark" / "repos" / "pytest",
    "black": ROOT / "benchmark" / "repos" / "black",
}


def choose_queries(repo: Path) -> list[str]:
    counts: dict[str, int] = {}
    for path in repo.rglob("*.py"):
        if ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for identifier in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{9,}\b", text):
            counts[identifier] = counts.get(identifier, 0) + 1
    rare = sorted((count, identifier) for identifier, count in counts.items() if 2 <= count <= 8)
    medium = sorted((count, identifier) for identifier, count in counts.items() if 15 <= count <= 80)
    return [identifier for _, identifier in rare[:3] + medium[:3]]


def python_scan(repo: Path, query: str) -> list[str]:
    values = []
    for path in repo.rglob("*.py"):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if query in line:
                values.append(f"{path.relative_to(repo).as_posix()}:{line_no}:{line}")
    return sorted(values)


def run(command: list[str], repo: Path) -> tuple[float, list[str], int]:
    started = time.perf_counter()
    proc = subprocess.run(
        command, cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    values = [
        line.removeprefix("./")
        for line in proc.stdout.replace("\\", "/").splitlines()
        if line
    ]
    return (time.perf_counter() - started) * 1000, sorted(values), proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    rows = []
    for repo_name, repo in REPOS.items():
        if not repo.exists():
            continue
        queries = choose_queries(repo)
        for query in queries:
            expected = set(python_scan(repo, query))
            for repeat in range(args.repeats):
                for backend, command in (
                    ("rg", ["rg", "-n", "-F", query, "-g", "*.py", "."]),
                    ("git_grep", ["git", "grep", "-n", "-F", "-e", query, "--", "*.py"]),
                ):
                    duration, values, code = run(command, repo)
                    actual = set(values)
                    rows.append({
                        "repo": repo_name, "query": query, "backend": backend, "repeat": repeat,
                        "duration_ms": duration, "returncode": code,
                        "precision": len(expected & actual) / len(actual) if actual else 0,
                        "recall": len(expected & actual) / len(expected) if expected else 1,
                        "result_count": len(actual),
                    })
                started = time.perf_counter()
                values = python_scan(repo, query)
                rows.append({
                    "repo": repo_name, "query": query, "backend": "python_scan", "repeat": repeat,
                    "duration_ms": (time.perf_counter() - started) * 1000, "returncode": 0,
                    "precision": 1.0, "recall": 1.0, "result_count": len(values),
                })
    jsonl_write(output / "multirepo_search.jsonl", rows)
    print(json.dumps({"rows": len(rows), "repos": sorted({row["repo"] for row in rows})}, indent=2))


if __name__ == "__main__":
    main()
