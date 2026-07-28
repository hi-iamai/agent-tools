from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def search(repo: Path, query: str) -> list[str]:
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
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--query")
    parser.add_argument("--stdio", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    if args.stdio:
        for raw in sys.stdin:
            try:
                request = json.loads(raw)
                result = search(repo, request["query"])
                response = {"id": request.get("id"), "matches": result, "count": len(result)}
            except Exception as exc:
                response = {"error": repr(exc)}
            print(json.dumps(response, ensure_ascii=False), flush=True)
    else:
        values = search(repo, args.query or "")
        print(json.dumps({"matches": values, "count": len(values)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
