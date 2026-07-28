from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from common import RESULTS, jsonl_write


SOURCE = """def calculate_total(values):
    total = 0
    for value in values:
        total += value
    return total
"""


def run_case(name: str, repeat: int, root: Path) -> dict:
    target = root / f"{name}_{repeat}.py"
    target.write_text(SOURCE, encoding="utf-8")
    started = time.perf_counter()
    error = None
    try:
        if name == "python_replace":
            text = target.read_text(encoding="utf-8")
            target.write_text(text.replace("return total", "return total + 1", 1), encoding="utf-8")
        elif name == "git_apply":
            patch = root / f"{name}_{repeat}.patch"
            patch.write_text(
                f"""diff --git a/{target.name} b/{target.name}
--- a/{target.name}
+++ b/{target.name}
@@ -1,5 +1,5 @@
 def calculate_total(values):
     total = 0
     for value in values:
         total += value
-    return total
+    return total + 1
""",
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", str(patch)],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
            )
            if proc.returncode:
                raise RuntimeError(proc.stderr)
        elif name == "patch_conflict":
            patch = root / f"{name}_{repeat}.patch"
            patch.write_text(
                f"""diff --git a/{target.name} b/{target.name}
--- a/{target.name}
+++ b/{target.name}
@@ -1,5 +1,5 @@
 def calculate_total(values):
     total = 0
     for value in values:
         total = total + value
-    return total
+    return total + 1
""",
                encoding="utf-8",
            )
            proc = subprocess.run(
                ["git", "apply", "--check", str(patch)],
                cwd=root, capture_output=True, text=True, encoding="utf-8",
            )
            correct = proc.returncode != 0 and target.read_text(encoding="utf-8") == SOURCE
            return {
                "tool": name, "repeat": repeat,
                "duration_ms": (time.perf_counter() - started) * 1000,
                "correct": correct, "error": None if correct else proc.stderr,
            }
        result = target.read_text(encoding="utf-8")
        correct = "return total + 1" in result and result.count("return total + 1") == 1
    except Exception as exc:
        correct, error = False, repr(exc)
    return {
        "tool": name, "repeat": repeat,
        "duration_ms": (time.perf_counter() - started) * 1000,
        "correct": correct, "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    rows = []
    with tempfile.TemporaryDirectory(prefix="agent-patch-") as temp:
        root = Path(temp)
        subprocess.run(["git", "init", "-q"], cwd=root)
        for repeat in range(args.repeats):
            for name in ("python_replace", "git_apply", "patch_conflict"):
                rows.append(run_case(name, repeat, root))
    jsonl_write(output / "patch_tools_windows.jsonl", rows)
    print(json.dumps({"rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
