from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup


QUERIES = [
    ("RemovedInDjango71Warning", 20),
    ("get_user_model", 53),
    ("QuantumCacheTeleport", 0),
    ("get_user_model|RemovedInDjango71Warning", 73),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:6070")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = []
    for repeat in range(args.repeats):
        for query, expected_count in QUERIES:
            started = time.perf_counter()
            with urllib.request.urlopen(
                args.base_url + "/search?q=" + urllib.parse.quote(query) + "&num=1000",
                timeout=60,
            ) as response:
                raw = response.read()
            soup = BeautifulSoup(raw, "html.parser")
            result_anchors = soup.select("a.result")
            line_links = [
                link for link in soup.select("a[href*='#L']")
                if link.get_text(strip=True).isdigit()
            ]
            rows.append({
                "query": query,
                "repeat": repeat,
                "duration_ms": (time.perf_counter() - started) * 1000,
                "raw_bytes": len(raw),
                "file_count": len(result_anchors),
                "match_count": len(line_links),
                "expected_count": expected_count,
                "count_match": len(line_links) == expected_count,
            })
    Path(args.output).write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
