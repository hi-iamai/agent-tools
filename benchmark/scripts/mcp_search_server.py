from __future__ import annotations

import argparse
import anyio
from pathlib import Path

from mcp.server.mcpserver import MCPServer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    server = MCPServer("search-benchmark")

    @server.tool()
    def search_text(query: str) -> dict:
        values = []
        for path in repo.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            try:
                raw = path.read_bytes()
                if b"\0" in raw[:4096]:
                    continue
                text = raw.decode("utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if query in line:
                    values.append(f"{path.relative_to(repo).as_posix()}:{line_no}:{line}")
        return {"count": len(values), "matches": values}

    anyio.run(server.run_stdio_async)


if __name__ == "__main__":
    main()
