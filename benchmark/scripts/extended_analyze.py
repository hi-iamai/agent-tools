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
            "median_ms": statistics.median(times),
            "p95_ms": percentile(times, 0.95),
            "median_output_chars": statistics.median(x["output_chars"] for x in values),
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
    summary = {
        "search": summarize_search(search_rows),
        "webfetch": summarize_web(web_rows),
        "api_fetch": summarize_api(api_rows),
        "structure": summarize_structure(structure_rows),
    }
    json_dump(base / "extended_summary.json", summary)
    write_csv(base / "search_summary.csv", summary["search"])
    write_csv(base / "webfetch_summary.csv", summary["webfetch"])
    write_csv(base / "api_fetch_summary.csv", summary["api_fetch"])
    write_csv(base / "structure_summary.csv", summary["structure"])
    print(json.dumps({key: len(value) for key, value in summary.items()}, indent=2))


if __name__ == "__main__":
    main()
