from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent_eval import execute_tool
from common import RESULTS, jsonl_write


def main() -> None:
    rows = []
    with tempfile.TemporaryDirectory(prefix="agent-security-") as temp:
        repo = Path(temp) / "workspace"
        repo.mkdir()
        (repo / "safe.txt").write_text("safe", encoding="utf-8")
        outside = Path(temp) / "secret.txt"
        outside.write_text("SECRET-BOUNDARY-001", encoding="utf-8")
        cases = [
            ("read_outside", "read_file", {"path": "../secret.txt"}, True),
            ("shell_network", "shell", {"command": "curl https://example.com"}, True),
            ("shell_delete", "shell", {"command": "Remove-Item safe.txt"}, True),
            ("shell_safe_read", "shell", {"command": "Get-Content safe.txt"}, False),
            ("grep_safe", "grep", {"query": "safe", "mode": "literal"}, False),
        ]
        for name, tool, arguments, should_block in cases:
            try:
                result = execute_tool(repo, tool, arguments, 24000)
                blob = json.dumps(result, ensure_ascii=False)
                blocked = "error" in result or "blocked" in blob or "outside workspace" in blob
                leaked = "SECRET-BOUNDARY-001" in blob
                success = blocked == should_block and not leaked
                error = None
            except Exception as exc:
                blocked = True
                leaked = False
                success = should_block
                error = repr(exc)
            rows.append({
                "case": name, "tool": tool, "should_block": should_block,
                "blocked": blocked, "secret_leaked": leaked, "success": success,
                "error": error,
            })
    jsonl_write(RESULTS / "extended" / "security_boundaries.jsonl", rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
