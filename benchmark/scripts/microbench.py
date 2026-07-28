from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from common import DATA, RESULTS, ROOT, environment_metadata, json_dump, jsonl_write, load_config, run


def normalize_lines(text: str) -> list[str]:
    return sorted(x.replace("\\", "/").strip() for x in text.splitlines() if x.strip())


def command_for(backend: str, query: dict) -> list[str]:
    kind = query["kind"]
    if backend == "rg":
        if kind == "files":
            return ["rg", "--files", "-g", query["pattern"]]
        args = ["rg", "-n", "--no-heading", "--color", "never"]
        if kind == "text":
            args.append("-F")
        args.append(query["query"])
        return args
    if backend == "git":
        if kind == "files":
            return ["git", "ls-files"]
        args = ["git", "grep", "-n", "--no-color"]
        if kind == "text":
            args.append("-F")
        else:
            args.append("-P")
        args += ["-e", query["query"]]
        return args
    raise ValueError(backend)


def postprocess(backend: str, query: dict, result: dict) -> list[str]:
    lines = normalize_lines(result["stdout"])
    if backend == "git" and query["kind"] == "files":
        pattern = query["pattern"].replace("**/", "")
        if "/" not in pattern:
            lines = [x for x in lines if Path(x).match(pattern)]
        else:
            lines = [x for x in lines if Path(x).match(query["pattern"]) or Path(x).match(pattern)]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=12)
    args = parser.parse_args()
    cfg = load_config()
    repo = Path(cfg["repo_path_abs"])
    queries = json.loads((DATA / "micro_queries.json").read_text(encoding="utf-8"))
    ast_queries = json.loads((DATA / "ast_queries.json").read_text(encoding="utf-8"))
    jobs = [(q, b, i) for q in queries for b in ("rg", "git") for i in range(args.repeats)]
    random.Random(cfg["assignment_seed"]).shuffle(jobs)
    rows = []
    for query, backend, repeat in jobs:
        r = run(command_for(backend, query), repo, timeout=60)
        output = postprocess(backend, query, r)
        rows.append({
            "query_id": query["id"], "kind": query["kind"], "backend": backend,
            "repeat": repeat, "duration_ms": r["duration_ms"], "returncode": r["returncode"],
            "result_count": len(output), "output_bytes": len(r["stdout"].encode("utf-8")),
            "result_hash": hash(tuple(output)),
        })

    # Structural search comparison. Both commands traverse Python source; result
    # counts are descriptive because textual and AST semantics are not identical.
    for query in ast_queries:
        for repeat in range(args.repeats):
            ast = run(
                [str(ROOT / "node_modules" / "@ast-grep" / "cli" / "ast-grep.exe"),
                 "run", "-l", query["language"], "-p", query["pattern"], "--json=stream", "."],
                repo, timeout=120,
            )
            literal_seed = {
                "ast_async_methods": "async def ",
                "ast_classes": "class ",
                "ast_get_user_calls": "get_user_model()",
            }[query["id"]]
            rg = run(["rg", "-n", "-F", literal_seed, "-g", "*.py"], repo, timeout=60)
            for backend, result in (("ast_grep", ast), ("rg_seed", rg)):
                rows.append({
                    "query_id": query["id"], "kind": "structural", "backend": backend,
                    "repeat": repeat, "duration_ms": result["duration_ms"], "returncode": result["returncode"],
                    "result_count": len(normalize_lines(result["stdout"])),
                    "output_bytes": len(result["stdout"].encode("utf-8")),
                    "result_hash": hash(tuple(normalize_lines(result["stdout"]))),
                })

    jsonl_write(RESULTS / "microbench_raw.jsonl", rows)
    json_dump(RESULTS / "environment.json", environment_metadata(repo))
    print(f"wrote {len(rows)} rows")


if __name__ == "__main__":
    main()
