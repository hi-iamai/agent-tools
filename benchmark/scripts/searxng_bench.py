from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


QUERIES = [
    ("python official programming language homepage", {"python.org"}),
    ("Django official documentation", {"docs.djangoproject.com", "djangoproject.com"}),
    ("pytest official documentation", {"docs.pytest.org", "pytest.org"}),
    ("ripgrep official GitHub repository", {"github.com"}),
    ("Model Context Protocol official specification", {"modelcontextprotocol.io", "github.com"}),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8888")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = []
    for repeat in range(args.repeats):
        for query, expected_domains in QUERIES:
            started = time.perf_counter()
            response = requests.get(
                args.base_url + "/search",
                params={"q": query, "format": "json"},
                headers={"X-Forwarded-For": "127.0.0.1"},
                timeout=90,
            )
            duration_ms = (time.perf_counter() - started) * 1000
            payload = response.json()
            domains = [
                (urlparse(item.get("url", "")).hostname or "").removeprefix("www.")
                for item in payload.get("results", [])
            ]
            ranks = [
                index + 1 for index, domain in enumerate(domains)
                if any(domain == expected or domain.endswith("." + expected) for expected in expected_domains)
            ]
            rows.append({
                "query": query, "repeat": repeat, "duration_ms": duration_ms,
                "status": response.status_code, "result_count": len(domains),
                "official_rank": min(ranks) if ranks else None,
                "official_at_5": any(rank <= 5 for rank in ranks),
                "official_at_10": any(rank <= 10 for rank in ranks),
                "unresponsive_engines": payload.get("unresponsive_engines", []),
            })
    Path(args.output).write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
