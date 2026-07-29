from __future__ import annotations

import argparse
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
    parser.add_argument("--zoekt-time", required=True)
    parser.add_argument("--zoekt-index", required=True)
    parser.add_argument("--scip-time", required=True)
    parser.add_argument("--scip-index", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = {
        "zoekt": {
            **parse_time(Path(args.zoekt_time)),
            "index_bytes": sum(path.stat().st_size for path in Path(args.zoekt_index).glob("*")),
        },
        "scip_python": {
            **parse_time(Path(args.scip_time)),
            "index_bytes": Path(args.scip_index).stat().st_size,
        },
    }
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
