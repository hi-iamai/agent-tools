from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    position = (len(values) - 1) * p
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] * (upper - position) + values[upper] * (position - lower)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    base = Path(__file__).resolve().parents[1] / "results" / "extended"
    rows = [
        json.loads(line)
        for line in (base / "strict_runtime_raw.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    payload_groups = defaultdict(list)
    throughput_groups = defaultdict(list)
    for row in rows:
        if row["suite"] == "payload":
            payload_groups[(row["adapter"], row["payload"])].append(row)
        else:
            throughput_groups[(row["adapter"], row["concurrency"])].append(row)
    payload_summary = []
    for (adapter, payload), values in sorted(payload_groups.items()):
        durations = [x["duration_us"] for x in values]
        payload_summary.append({
            "adapter": adapter,
            "payload": payload,
            "runs": len(values),
            "median_us": statistics.median(durations),
            "p95_us": percentile(durations, 0.95),
            "median_response_bytes": statistics.median(x["response_bytes"] for x in values),
            "success_rate": statistics.mean(bool(x["correct"]) for x in values),
        })
    throughput_summary = []
    for (adapter, concurrency), values in sorted(throughput_groups.items()):
        throughput_summary.append({
            "adapter": adapter,
            "concurrency": concurrency,
            "runs": len(values),
            "median_rps": statistics.median(x["throughput_rps"] for x in values),
            "median_duration_ms": statistics.median(x["duration_ms"] for x in values),
            "success_rate": statistics.mean(bool(x["correct"]) for x in values),
        })
    meta = json.loads((base / "strict_runtime_meta.json").read_text(encoding="utf-8"))
    faults = json.loads((base / "strict_runtime_faults.json").read_text(encoding="utf-8"))
    summary = {
        "payload": payload_summary,
        "throughput": throughput_summary,
        "faults": faults,
        "meta": meta,
    }
    (base / "strict_runtime_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    write_csv(base / "strict_runtime_payload_summary.csv", payload_summary)
    write_csv(base / "strict_runtime_throughput_summary.csv", throughput_summary)
    print(json.dumps({
        "payload_groups": len(payload_summary),
        "throughput_groups": len(throughput_summary),
        "faults": len(faults),
    }, indent=2))


if __name__ == "__main__":
    main()
