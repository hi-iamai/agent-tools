from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import RESULTS, json_dump


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return math.nan
    values = sorted(values)
    pos = (len(values) - 1) * p
    low, high = math.floor(pos), math.ceil(pos)
    if low == high:
        return values[low]
    return values[low] * (high - pos) + values[high] * (pos - low)


def summarize_search(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row["environment"], row["suite"], row["backend"])].append(row)
    result = []
    for (environment, suite, backend), values in sorted(groups.items()):
        times = [x["duration_ms"] for x in values]
        result.append({
            "environment": environment,
            "suite": suite,
            "backend": backend,
            "runs": len(values),
            "median_ms": statistics.median(times),
            "p95_ms": percentile(times, 0.95),
            "mean_precision": statistics.mean(x.get("precision", 0) for x in values),
            "mean_recall": statistics.mean(x.get("recall", 0) for x in values),
            "median_output_bytes": statistics.median(x["output_bytes"] for x in values),
            "median_raw_output_bytes": statistics.median(x.get("raw_output_bytes", x["output_bytes"]) for x in values),
            "error_rate": sum(x["returncode"] not in (0, 1) for x in values) / len(values),
        })
    return result


def summarize_web(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row["environment"], row["client"], row["extractor"])].append(row)
    result = []
    for (environment, client, extractor), values in sorted(groups.items()):
        times = [x["total_ms"] for x in values]
        result.append({
            "environment": environment,
            "client": client,
            "extractor": extractor,
            "runs": len(values),
            "mean_recall": statistics.mean(x["recall"] for x in values),
            "mean_content_precision": statistics.mean(x.get("content_precision", 0) for x in values),
            "mean_content_recall": statistics.mean(x.get("content_recall", 0) for x in values),
            "mean_content_f1": statistics.mean(x.get("content_f1", 0) for x in values),
            "median_ms": statistics.median(times),
            "p95_ms": percentile(times, 0.95),
            "median_output_chars": statistics.median(x["output_chars"] for x in values),
            "error_rate": sum(bool(x["error"]) for x in values) / len(values),
        })
    return result


def summarize_web_by_page(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row["environment"], row["page"], row["client"], row["extractor"])].append(row)
    result = []
    for (environment, page, client, extractor), values in sorted(groups.items()):
        result.append({
            "environment": environment,
            "page": page,
            "client": client,
            "extractor": extractor,
            "runs": len(values),
            "evidence_recall": statistics.mean(x["recall"] for x in values),
            "content_precision": statistics.mean(x.get("content_precision", 0) for x in values),
            "content_recall": statistics.mean(x.get("content_recall", 0) for x in values),
            "content_f1": statistics.mean(x.get("content_f1", 0) for x in values),
            "median_ms": statistics.median(x["total_ms"] for x in values),
            "error_rate": sum(bool(x["error"]) for x in values) / len(values),
        })
    return result


def summarize_api(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row["environment"], row["client"], row["scenario"], row.get("workers", 0))].append(row)
    result = []
    for (environment, client, scenario, workers), values in sorted(groups.items()):
        times = [x["duration_ms"] for x in values]
        result.append({
            "environment": environment,
            "client": client,
            "scenario": scenario,
            "workers": workers or "",
            "runs": len(values),
            "success_rate": statistics.mean(bool(x["correct"]) for x in values),
            "median_ms": statistics.median(times),
            "p95_ms": percentile(times, 0.95),
            "median_throughput_rps": statistics.median(x.get("throughput_rps", 0) for x in values),
            "error_rate": sum(bool(x["error"]) for x in values) / len(values),
        })
    return result


def summarize_structure(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[(row["environment"], row["backend"])].append(row)
    result = []
    for (environment, backend), values in sorted(groups.items()):
        times = [x["duration_ms"] for x in values]
        result.append({
            "environment": environment,
            "backend": backend,
            "runs": len(values),
            "mean_precision": statistics.mean(x["precision"] for x in values),
            "mean_recall": statistics.mean(x["recall"] for x in values),
            "median_ms": statistics.median(times),
            "p95_ms": percentile(times, 0.95),
            "median_output_bytes": statistics.median(x["output_bytes"] for x in values),
            "error_rate": sum(bool(x["error"]) for x in values) / len(values),
        })
    return result


def summarize_generic(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        groups[tuple(row.get(key, "") for key in keys)].append(row)
    result = []
    for group_key, values in sorted(groups.items()):
        item = {key: value for key, value in zip(keys, group_key)}
        item.update({
            "runs": len(values),
            "median_ms": statistics.median(x["duration_ms"] for x in values),
            "p95_ms": percentile([x["duration_ms"] for x in values], 0.95),
            "median_output_bytes": statistics.median(x.get("output_bytes", 0) for x in values),
            "success_rate": statistics.mean(
                bool(
                    x["success"] if "success" in x
                    else x["correct"] if "correct" in x
                    else x.get("returncode", 1) == 0
                )
                for x in values
            ),
        })
        result.append(item)
    return result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(RESULTS / "extended"))
    args = parser.parse_args()
    base = Path(args.input_dir)
    search_rows = []
    web_rows = []
    api_rows = []
    structure_rows = []
    runtime_rows = []
    git_rows = []
    io_rows = []
    websearch_rows = []
    intelligence_rows = []
    multirepo_rows = []
    patch_rows = []
    mcp_rows = []
    resource_rows = []
    security_rows = []
    lsp_rows = []
    zoekt_rows = []
    for path in base.glob("extended_search_*.jsonl"):
        search_rows.extend(read_jsonl(path))
    for path in base.glob("webfetch_*.jsonl"):
        web_rows.extend(read_jsonl(path))
    for path in base.glob("browser_fetch_*.jsonl"):
        web_rows.extend(read_jsonl(path))
    for path in base.glob("api_fetch_*.jsonl"):
        api_rows.extend(read_jsonl(path))
    for path in base.glob("structure_*.jsonl"):
        structure_rows.extend(read_jsonl(path))
    for path in base.glob("runtime_*.jsonl"):
        runtime_rows.extend(read_jsonl(path))
    for path in base.glob("git_tools_*.jsonl"):
        git_rows.extend(read_jsonl(path))
    for path in base.glob("io_tools_*.jsonl"):
        io_rows.extend(read_jsonl(path))
    for path in base.glob("websearch_*.jsonl"):
        websearch_rows.extend(read_jsonl(path))
    for path in base.glob("code_intelligence_*.jsonl"):
        intelligence_rows.extend(read_jsonl(path))
    for path in base.glob("multirepo_search*.jsonl"):
        multirepo_rows.extend(read_jsonl(path))
    for path in base.glob("patch_tools_*.jsonl"):
        patch_rows.extend(read_jsonl(path))
    for path in base.glob("mcp_runtime_*.jsonl"):
        mcp_rows.extend(read_jsonl(path))
    for path in base.glob("resource_*.jsonl"):
        resource_rows.extend(read_jsonl(path))
    for path in base.glob("security_boundaries*.jsonl"):
        security_rows.extend(read_jsonl(path))
    for path in base.glob("lsp_*.jsonl"):
        lsp_rows.extend(read_jsonl(path))
    for path in base.glob("zoekt_*.jsonl"):
        zoekt_rows.extend(read_jsonl(path))
    summary = {
        "search": summarize_search(search_rows),
        "webfetch": summarize_web(web_rows),
        "webfetch_by_page": summarize_web_by_page(web_rows),
        "api_fetch": summarize_api(api_rows),
        "structure": summarize_structure(structure_rows),
        "runtime": summarize_generic(runtime_rows, ["environment", "runtime"]),
        "git_tools": summarize_generic(git_rows, ["environment", "tool"]),
        "io_tools": summarize_generic(io_rows, ["environment", "tool"]),
        "websearch": [
            {
                "method": method,
                "runs": len(values),
                "mean_recall_at_5": statistics.mean(x["recall_at_5"] for x in values),
                "mean_mrr": statistics.mean(x["mrr"] for x in values),
                "mean_ndcg_at_5": statistics.mean(x["ndcg_at_5"] for x in values),
                "median_ms": statistics.median(x["duration_ms"] for x in values),
                "p95_ms": percentile([x["duration_ms"] for x in values], 0.95),
            }
            for method, values in sorted({
                method: [x for x in websearch_rows if x["method"] == method]
                for method in {x["method"] for x in websearch_rows}
            }.items())
        ],
        "code_intelligence": [
            {
                "method": method,
                "runs": len(values),
                "mean_precision": statistics.mean(x["precision"] for x in values),
                "mean_recall": statistics.mean(x["recall"] for x in values),
                "median_ms": statistics.median(x["duration_ms"] for x in values),
                "p95_ms": percentile([x["duration_ms"] for x in values], 0.95),
                "error_rate": statistics.mean(bool(x["error"]) for x in values),
            }
            for method, values in sorted({
                method: [x for x in intelligence_rows if x["method"] == method]
                for method in {x["method"] for x in intelligence_rows}
            }.items())
        ],
        "multirepo_search": [
            {
                "repo": repo,
                "backend": backend,
                "runs": len(values),
                "mean_precision": statistics.mean(x["precision"] for x in values),
                "mean_recall": statistics.mean(x["recall"] for x in values),
                "median_ms": statistics.median(x["duration_ms"] for x in values),
                "p95_ms": percentile([x["duration_ms"] for x in values], 0.95),
            }
            for (repo, backend), values in sorted({
                (repo, backend): [
                    x for x in multirepo_rows if x["repo"] == repo and x["backend"] == backend
                ]
                for repo, backend in {(x["repo"], x["backend"]) for x in multirepo_rows}
            }.items())
        ],
        "patch_tools": summarize_generic(patch_rows, ["tool"]),
        "mcp_runtime": [
            {
                "runtime": "mcp_stdio",
                "runs": len(mcp_rows),
                "median_ms": statistics.median(x["duration_ms"] for x in mcp_rows) if mcp_rows else math.nan,
                "p95_ms": percentile([x["duration_ms"] for x in mcp_rows], 0.95),
                "error_rate": statistics.mean(bool(x["is_error"]) for x in mcp_rows) if mcp_rows else 0,
            }
        ] if mcp_rows else [],
        "resources": [
            {
                "backend": backend,
                "runs": len(values),
                "median_wall_ms": statistics.median(x["duration_ms"] for x in values),
                "median_cpu_ms": statistics.median(x["cpu_ms"] for x in values),
                "median_peak_rss_mb": statistics.median(x["peak_rss_bytes"] for x in values) / 1024 / 1024,
                "median_output_bytes": statistics.median(x["output_bytes"] for x in values),
                "error_rate": statistics.mean(bool(x["error"]) for x in values),
            }
            for backend, values in sorted({
                backend: [x for x in resource_rows if x["backend"] == backend]
                for backend in {x["backend"] for x in resource_rows}
            }.items())
        ],
        "security": [{
            "cases": len(security_rows),
            "success_rate": statistics.mean(bool(x["success"]) for x in security_rows) if security_rows else 0,
            "secret_leaks": sum(bool(x["secret_leaked"]) for x in security_rows),
        }] if security_rows else [],
        "lsp": [{
            "method": "pylsp_definition",
            "runs": len(lsp_rows),
            "initialize_ms": statistics.median(x["initialize_ms"] for x in lsp_rows),
            "success_rate": statistics.mean(bool(x["success"]) for x in lsp_rows),
            "median_query_ms": statistics.median(x["duration_ms"] for x in lsp_rows),
            "p95_query_ms": percentile([x["duration_ms"] for x in lsp_rows], 0.95),
            "error_rate": statistics.mean(bool(x["error"]) for x in lsp_rows),
        }] if lsp_rows else [],
        "zoekt": [{
            "runs": len(zoekt_rows),
            "success_rate": statistics.mean(bool(x["count_match"]) for x in zoekt_rows),
            "median_query_ms": statistics.median(x["duration_ms"] for x in zoekt_rows),
            "p95_query_ms": percentile([x["duration_ms"] for x in zoekt_rows], 0.95),
            "median_raw_bytes": statistics.median(x["raw_bytes"] for x in zoekt_rows),
        }] if zoekt_rows else [],
        "indexers": (
            json.loads((base / "indexer_meta.json").read_text(encoding="utf-8"))
            if (base / "indexer_meta.json").exists() else {}
        ),
        "codeql": (
            json.loads((base / "codeql_meta.json").read_text(encoding="utf-8"))
            if (base / "codeql_meta.json").exists() else {}
        ),
    }
    json_dump(base / "extended_summary.json", summary)
    write_csv(base / "search_summary.csv", summary["search"])
    write_csv(base / "webfetch_summary.csv", summary["webfetch"])
    write_csv(base / "webfetch_page_summary.csv", summary["webfetch_by_page"])
    write_csv(base / "api_fetch_summary.csv", summary["api_fetch"])
    write_csv(base / "structure_summary.csv", summary["structure"])
    write_csv(base / "runtime_summary.csv", summary["runtime"])
    write_csv(base / "git_tools_summary.csv", summary["git_tools"])
    write_csv(base / "io_tools_summary.csv", summary["io_tools"])
    write_csv(base / "websearch_summary.csv", summary["websearch"])
    write_csv(base / "code_intelligence_summary.csv", summary["code_intelligence"])
    write_csv(base / "multirepo_search_summary.csv", summary["multirepo_search"])
    write_csv(base / "patch_tools_summary.csv", summary["patch_tools"])
    write_csv(base / "mcp_runtime_summary.csv", summary["mcp_runtime"])
    write_csv(base / "resource_summary.csv", summary["resources"])
    write_csv(base / "security_summary.csv", summary["security"])
    write_csv(base / "lsp_summary.csv", summary["lsp"])
    write_csv(base / "zoekt_summary.csv", summary["zoekt"])
    print(json.dumps({key: len(value) for key, value in summary.items()}, indent=2))


if __name__ == "__main__":
    main()
