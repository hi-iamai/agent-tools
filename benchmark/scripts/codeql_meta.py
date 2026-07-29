from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


def parse_time(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    elapsed = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*(.+)", text)
    rss = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", text)
    return {
        "elapsed": elapsed.group(1).strip() if elapsed else None,
        "max_rss_kb": int(rss.group(1)) if rss else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-time", required=True)
    parser.add_argument("--query-time", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--suite-time")
    parser.add_argument("--sarif")
    args = parser.parse_args()
    database = Path(args.database)
    size = sum(path.stat().st_size for path in database.rglob("*") if path.is_file())
    with Path(args.csv).open(encoding="utf-8") as handle:
        rows = sum(1 for _ in csv.reader(handle)) - 1
    result = {
        "database_create": {**parse_time(Path(args.create_time)), "database_bytes": size},
        "function_query": {**parse_time(Path(args.query_time)), "result_rows": rows},
    }
    if args.suite_time and args.sarif:
        sarif = json.loads(Path(args.sarif).read_text(encoding="utf-8"))
        findings = sum(
            len(run.get("results", []))
            for run in sarif.get("runs", [])
        )
        result["security_and_quality_suite"] = {
            **parse_time(Path(args.suite_time)),
            "sarif_bytes": Path(args.sarif).stat().st_size,
            "findings": findings,
        }
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
