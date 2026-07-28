from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import sqlite3
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from common import RESULTS, ROOT, json_dump, jsonl_write, load_config


QUERIES = [
    {"id": "literal_rare", "kind": "literal", "query": "RemovedInDjango71Warning"},
    {"id": "literal_symbol", "kind": "literal", "query": "get_user_model"},
    {"id": "literal_broad", "kind": "literal", "query": "from django."},
    {"id": "regex_classes", "kind": "regex", "query": r"^class (HttpResponse|URLResolver|QuerySet|Model|BaseCache)\b"},
    {"id": "regex_async", "kind": "regex", "query": r"^\s+async def a\w+\("},
    {"id": "no_hit", "kind": "literal", "query": "QuantumCacheTeleport"},
]

FILE_QUERIES = [
    {"id": "all_python", "pattern": "*.py"},
    {"id": "cache_backends", "pattern": "django/core/cache/backends/*.py"},
    {"id": "test_urls", "pattern": "tests/**/urls.py"},
]


def run_cmd(args: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
    start = time.perf_counter()
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return {
        "duration_ms": (time.perf_counter() - start) * 1000,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "max_rss_kb": None,
    }


def python_scan(repo: Path, query: dict[str, str]) -> dict[str, Any]:
    start = time.perf_counter()
    results = []
    regex = re.compile(query["query"]) if query["kind"] == "regex" else None
    for path in repo.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            if b"\0" in path.read_bytes()[:4096]:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, 1):
            matched = regex.search(line) if regex else query["query"] in line
            if matched:
                results.append(f"{path.relative_to(repo).as_posix()}:{line_no}:{line}")
    return {
        "duration_ms": (time.perf_counter() - start) * 1000,
        "returncode": 0 if results else 1,
        "stdout": "\n".join(results),
        "stderr": "",
        "max_rss_kb": None,
    }


def python_files(repo: Path, pattern: str, scandir: bool) -> dict[str, Any]:
    start = time.perf_counter()
    values: list[str] = []
    if scandir:
        stack = [repo]
        while stack:
            base = stack.pop()
            try:
                entries = list(os.scandir(base))
            except OSError:
                continue
            for entry in entries:
                if entry.name == ".git":
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    rel = Path(entry.path).relative_to(repo)
                    if rel.match(pattern) or rel.match(pattern.replace("**/", "")):
                        values.append(rel.as_posix())
    else:
        values = [
            p.relative_to(repo).as_posix() for p in repo.rglob("*")
            if p.is_file() and ".git" not in p.parts
            and (p.relative_to(repo).match(pattern) or p.relative_to(repo).match(pattern.replace("**/", "")))
        ]
    return {
        "duration_ms": (time.perf_counter() - start) * 1000,
        "returncode": 0 if values else 1,
        "stdout": "\n".join(sorted(values)),
        "stderr": "",
        "max_rss_kb": None,
    }


def command_for(backend: str, query: dict[str, str]) -> list[str]:
    q = query["query"]
    if backend == "rg":
        return ["rg", "-n", "--no-heading", "--color", "never"] + (["-F"] if query["kind"] == "literal" else []) + [q, "."]
    if backend == "git_grep":
        return ["git", "grep", "-n", "--no-color"] + (["-F"] if query["kind"] == "literal" else ["-P"]) + ["-e", q]
    if backend == "ugrep":
        return ["ugrep", "-n", "-r", "--exclude-dir=.git"] + (["-F"] if query["kind"] == "literal" else ["-P"]) + [q, "."]
    if backend == "grep":
        return ["grep", "-R", "-n", "-I", "--exclude-dir=.git"] + (["-F"] if query["kind"] == "literal" else ["-P"]) + [q, "."]
    if backend == "ag":
        return ["ag", "--nocolor", "--nogroup"] + (["-Q"] if query["kind"] == "literal" else []) + [q, "."]
    raise KeyError(backend)


def file_command(backend: str, pattern: str) -> list[str]:
    if backend == "rg_files":
        return ["rg", "--files", "-g", pattern]
    if backend == "fd":
        prefix = re.split(r"[*?[]", pattern, maxsplit=1)[0]
        base = str(Path(prefix).parent) if prefix else "."
        return ["fdfind", "--type", "f", "--glob", Path(pattern).name, base or "."]
    if backend == "find":
        prefix = re.split(r"[*?[]", pattern, maxsplit=1)[0]
        base = str(Path(prefix).parent) if prefix else "."
        return ["find", base or ".", "-type", "f", "-name", Path(pattern).name]
    if backend == "git_files":
        return ["git", "ls-files"]
    raise KeyError(backend)


def normalize(text: str) -> list[str]:
    return sorted(x.replace("\\", "/").lstrip("./") for x in text.splitlines() if x.strip())


def normalize_file_output(text: str, repo: Path) -> list[str]:
    values = []
    repo_posix = repo.as_posix().rstrip("/") + "/"
    for raw in text.splitlines():
        value = raw.replace("\\", "/").strip()
        if not value:
            continue
        if value.startswith(repo_posix):
            value = value[len(repo_posix):]
        values.append(value.lstrip("./"))
    return sorted(values)


def result_digest(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def build_fts(repo: Path, db: Path) -> dict[str, Any]:
    if db.exists():
        db.unlink()
    start = time.perf_counter()
    con = sqlite3.connect(db)
    con.execute("pragma journal_mode=off")
    con.execute("pragma synchronous=off")
    con.execute("create virtual table lines using fts5(path UNINDEXED, line_no UNINDEXED, text, tokenize='unicode61')")
    rows = []
    files = 0
    for path in repo.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            raw = path.read_bytes()
            if b"\0" in raw[:4096]:
                continue
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        files += 1
        rel = path.relative_to(repo).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            rows.append((rel, line_no, line))
            if len(rows) >= 20_000:
                con.executemany("insert into lines(path,line_no,text) values(?,?,?)", rows)
                rows.clear()
    if rows:
        con.executemany("insert into lines(path,line_no,text) values(?,?,?)", rows)
    con.commit()
    count = con.execute("select count(*) from lines").fetchone()[0]
    con.close()
    return {
        "build_ms": (time.perf_counter() - start) * 1000,
        "size_bytes": db.stat().st_size,
        "files": files,
        "lines": count,
    }


def fts_query(db: Path, query: str) -> dict[str, Any]:
    start = time.perf_counter()
    con = sqlite3.connect(db)
    escaped = '"' + query.replace('"', '""') + '"'
    rows = con.execute(
        "select path,line_no,text from lines where lines match ? limit 100000", (escaped,)
    ).fetchall()
    con.close()
    return {
        "duration_ms": (time.perf_counter() - start) * 1000,
        "returncode": 0 if rows else 1,
        "stdout": "\n".join(f"{p}:{n}:{t}" for p, n, t in rows),
        "stderr": "",
        "max_rss_kb": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--repo")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    cfg = load_config()
    repo = Path(args.repo).resolve() if args.repo else Path(cfg["repo_path_abs"])
    output_dir = Path(args.output_dir).resolve() if args.output_dir else RESULTS
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    oracle_text: dict[str, list[str]] = {q["id"]: normalize(python_scan(repo, q)["stdout"]) for q in QUERIES}
    oracle_files: dict[str, list[str]] = {
        q["id"]: normalize(python_files(repo, q["pattern"], True)["stdout"]) for q in FILE_QUERIES
    }
    available = {name for name in ("rg", "git", "ugrep", "grep", "ag", "fdfind", "find") if shutil.which(name)}
    text_backends = ["rg", "git_grep"]
    if "ugrep" in available:
        text_backends.append("ugrep")
    if "grep" in available:
        text_backends.append("grep")
    if "ag" in available:
        text_backends.append("ag")

    for repeat in range(args.repeats):
        for query in QUERIES:
            for backend in text_backends + ["python_re"]:
                result = python_scan(repo, query) if backend == "python_re" else run_cmd(command_for(backend, query), repo)
                output = normalize(result["stdout"])
                expected = set(oracle_text[query["id"]])
                actual = set(output)
                rows.append({
                    "environment": args.environment, "suite": "text", "query_id": query["id"],
                    "kind": query["kind"], "backend": backend, "repeat": repeat,
                    "duration_ms": result["duration_ms"], "returncode": result["returncode"],
                    "result_count": len(output), "output_bytes": len(result["stdout"].encode()),
                    "result_hash": result_digest(output),
                    "precision": len(expected & actual) / len(actual) if actual else (1.0 if not expected else 0.0),
                    "recall": len(expected & actual) / len(expected) if expected else (1.0 if not actual else 0.0),
                })
        for query in FILE_QUERIES:
            backends = ["rg_files", "git_files", "python_rglob", "python_scandir"]
            if "fdfind" in available:
                backends.append("fd")
            if "find" in available:
                backends.append("find")
            for backend in backends:
                if backend == "python_rglob":
                    result = python_files(repo, query["pattern"], False)
                elif backend == "python_scandir":
                    result = python_files(repo, query["pattern"], True)
                else:
                    result = run_cmd(file_command(backend, query["pattern"]), repo)
                output = normalize_file_output(result["stdout"], repo)
                if backend == "git_files":
                    p = query["pattern"]
                    output = [x for x in output if Path(x).match(p) or Path(x).match(p.replace("**/", ""))]
                expected = set(oracle_files[query["id"]])
                actual = set(output)
                rows.append({
                    "environment": args.environment, "suite": "files", "query_id": query["id"],
                    "kind": "files", "backend": backend, "repeat": repeat,
                    "duration_ms": result["duration_ms"], "returncode": result["returncode"],
                    "result_count": len(output), "output_bytes": len(result["stdout"].encode()),
                    "result_hash": result_digest(output),
                    "precision": len(expected & actual) / len(actual) if actual else (1.0 if not expected else 0.0),
                    "recall": len(expected & actual) / len(expected) if expected else (1.0 if not actual else 0.0),
                })

    db = output_dir / f"search_index_{args.environment}.sqlite"
    index_meta = build_fts(repo, db)
    for repeat in range(args.repeats):
        for query in [q for q in QUERIES if q["kind"] == "literal"]:
            result = fts_query(db, query["query"])
            output = normalize(result["stdout"])
            expected = set(oracle_text[query["id"]])
            actual = set(output)
            rows.append({
                "environment": args.environment, "suite": "text", "query_id": query["id"],
                "kind": "literal", "backend": "sqlite_fts5", "repeat": repeat,
                "duration_ms": result["duration_ms"], "returncode": result["returncode"],
                "result_count": len(output), "output_bytes": len(result["stdout"].encode()),
                "result_hash": result_digest(output),
                "precision": len(expected & actual) / len(actual) if actual else (1.0 if not expected else 0.0),
                "recall": len(expected & actual) / len(expected) if expected else (1.0 if not actual else 0.0),
            })

    jsonl_write(output_dir / f"extended_search_{args.environment}.jsonl", rows)
    json_dump(output_dir / f"search_index_{args.environment}.json", index_meta)
    print(json.dumps({"rows": len(rows), "index": index_meta, "backends": sorted({x["backend"] for x in rows})}, indent=2))


if __name__ == "__main__":
    main()
