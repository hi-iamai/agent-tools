from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from mcp import Client, StdioServerParameters, stdio_client


QUERIES = ["RemovedInDjango71Warning", "get_user_model", "QuantumCacheTeleport"]


async def main_async(repo: Path, repeats: int, output: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_search_server.py")), "--repo", str(repo)],
    )
    rows = []
    started = time.perf_counter()
    async with Client(stdio_client(parameters), mode="legacy") as client:
        initialize_ms = (time.perf_counter() - started) * 1000
        list_started = time.perf_counter()
        tools = await client.list_tools()
        list_tools_ms = (time.perf_counter() - list_started) * 1000
        for repeat in range(repeats):
            for query in QUERIES:
                call_started = time.perf_counter()
                result = await client.call_tool("search_text", {"query": query})
                rows.append({
                    "runtime": "mcp_stdio",
                    "query": query,
                    "repeat": repeat,
                    "duration_ms": (time.perf_counter() - call_started) * 1000,
                    "is_error": bool(result.is_error),
                    "content_blocks": len(result.content),
                })
    output.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": len(rows),
        "initialize_ms": initialize_ms,
        "list_tools_ms": list_tools_ms,
        "tool_count": len(tools.tools),
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    asyncio.run(main_async(Path(args.repo).resolve(), args.repeats, Path(args.output)))


if __name__ == "__main__":
    main()
