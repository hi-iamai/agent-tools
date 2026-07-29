from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from mcp import Client


QUERIES = ["RemovedInDjango71Warning", "get_user_model", "QuantumCacheTeleport"]


async def run(url: str, repeats: int, output: Path) -> None:
    rows = []
    started = time.perf_counter()
    async with Client(url, mode="legacy") as client:
        initialize_ms = (time.perf_counter() - started) * 1000
        list_started = time.perf_counter()
        tools = await client.list_tools()
        list_ms = (time.perf_counter() - list_started) * 1000
        for repeat in range(repeats):
            for query in QUERIES:
                started = time.perf_counter()
                result = await client.call_tool("search_text", {"query": query})
                rows.append({
                    "runtime": "mcp_streamable_http", "query": query, "repeat": repeat,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "is_error": bool(result.is_error),
                })
    output.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": len(rows), "initialize_ms": initialize_ms,
        "list_tools_ms": list_ms, "tool_count": len(tools.tools),
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8767/mcp")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.repeats, Path(args.output)))


if __name__ == "__main__":
    main()
