from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    Path(args.output).write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps({
        "documents": stats.get("documents"),
        "occurrences": stats.get("occurrences"),
        "definitions": stats.get("definitions"),
    }, indent=2))


if __name__ == "__main__":
    main()
