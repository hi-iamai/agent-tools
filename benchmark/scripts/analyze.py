from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from common import RESULTS, json_dump


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return math.nan
    values = sorted(values)
    pos = (len(values) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def main() -> None:
    micro = read_jsonl(RESULTS / "microbench_raw.jsonl")
    agent = read_jsonl(RESULTS / "agent_eval_raw.jsonl")
    micro_groups = defaultdict(list)
    for row in micro:
        micro_groups[(row["kind"], row["backend"])].append(row)
    micro_summary = []
    for (kind, backend), rows in sorted(micro_groups.items()):
        times = [x["duration_ms"] for x in rows]
        micro_summary.append({
            "kind": kind, "backend": backend, "runs": len(rows),
            "median_ms": statistics.median(times), "p95_ms": percentile(times, 0.95),
            "median_results": statistics.median(x["result_count"] for x in rows),
            "median_output_bytes": statistics.median(x["output_bytes"] for x in rows),
        })

    agent_groups = defaultdict(list)
    category_groups = defaultdict(list)
    for row in agent:
        agent_groups[row["surface"]].append(row)
        category_groups[(row["surface"], row["category"])].append(row)
    agent_summary = []
    for surface, rows in sorted(agent_groups.items()):
        valid = [x for x in rows if x["termination"] != "infrastructure_error"]
        agent_summary.append({
            "surface": surface, "runs": len(rows),
            "success_rate": sum(bool(x["grade"]["success"]) for x in valid) / len(valid) if valid else 0,
            "mean_score": statistics.mean(x["grade"]["score"] for x in valid) if valid else 0,
            "median_duration_ms": statistics.median(x["duration_ms"] for x in valid) if valid else math.nan,
            "p95_duration_ms": percentile([x["duration_ms"] for x in valid], 0.95),
            "median_tool_calls": statistics.median(x["tool_call_count"] for x in valid) if valid else math.nan,
            "median_input_tokens": statistics.median(x["usage"]["input_tokens"] for x in valid) if valid else math.nan,
            "median_cost_usd": statistics.median(x["estimated_cost_usd"] for x in valid) if valid else math.nan,
            "infrastructure_errors": len(rows) - len(valid),
        })
    category_summary = []
    for (surface, category), rows in sorted(category_groups.items()):
        valid = [x for x in rows if x["termination"] != "infrastructure_error"]
        category_summary.append({
            "surface": surface, "category": category, "runs": len(valid),
            "success_rate": sum(bool(x["grade"]["success"]) for x in valid) / len(valid) if valid else 0,
            "mean_score": statistics.mean(x["grade"]["score"] for x in valid) if valid else 0,
        })
    summary = {"microbench": micro_summary, "agent": agent_summary, "agent_by_category": category_summary}
    json_dump(RESULTS / "summary.json", summary)
    for name, rows in (("microbench_summary.csv", micro_summary), ("agent_summary.csv", agent_summary), ("agent_category_summary.csv", category_summary)):
        if rows:
            with (RESULTS / name).open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
