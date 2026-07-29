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
    args = parser.parse_args()
    database = Path(args.database)
    size = sum(path.stat().st_size for path in database.rglob("*") if path.is_file())
    with Path(args.csv).open(encoding="utf-8") as handle:
        rows = sum(1 for _ in csv.reader(handle)) - 1
    result = {
        "database_create": {**parse_time(Path(args.create_time)), "database_bytes": size},
        "function_query": {**parse_time(Path(args.query_time)), "result_rows": rows},
    }
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
