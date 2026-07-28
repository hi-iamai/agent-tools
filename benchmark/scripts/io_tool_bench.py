from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path

from common import RESULTS, jsonl_write


def timed(name: str, repeat: int, operation) -> dict:
    started = time.perf_counter()
    error = None
    correct = False
    output_bytes = 0
    try:
        value = operation()
        if isinstance(value, tuple):
            correct, output_bytes = value
        else:
            correct = bool(value)
    except Exception as exc:
        error = repr(exc)
    return {
        "tool": name,
        "repeat": repeat,
        "duration_ms": (time.perf_counter() - started) * 1000,
        "correct": correct,
        "output_bytes": output_bytes,
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    rows = []
    with tempfile.TemporaryDirectory(prefix="agent-io-") as temp:
        root = Path(temp)
        files = []
        for index in range(100):
            path = root / f"file_{index:03}.txt"
            path.write_text(
                "\n".join(f"line {line:05} file {index:03} TOKEN-{index:03}-{line:05}" for line in range(2000)),
                encoding="utf-8",
            )
            files.append(path)
        target = files[0]
        for repeat in range(args.repeats):
            rows.append(timed("read_python_full", repeat, lambda: (
                "TOKEN-000-01999" in target.read_text(encoding="utf-8"),
                target.stat().st_size,
            )))
            rows.append(timed("read_python_range", repeat, lambda: (
                "TOKEN-000-01009" in "\n".join(target.read_text(encoding="utf-8").splitlines()[1000:1010]),
                len("\n".join(target.read_text(encoding="utf-8").splitlines()[1000:1010]).encode()),
            )))
            rows.append(timed("read_powershell_range", repeat, lambda: _powershell_range(target)))
            rows.append(timed("batch_read_python_10", repeat, lambda: _batch_read(files[:10])))
            rows.append(timed("per_file_python_10", repeat, lambda: _per_file_read(files[:10])))

            edit_path = root / f"edit_{repeat}.txt"
            edit_path.write_bytes(target.read_bytes())
            rows.append(timed("edit_python_replace", repeat, lambda: _python_replace(edit_path)))

            patch_path = root / f"patch_{repeat}.txt"
            patch_path.write_bytes(target.read_bytes())
            rows.append(timed("edit_powershell_replace", repeat, lambda: _powershell_replace(patch_path)))
    for row in rows:
        row["environment"] = args.environment
    jsonl_write(output / f"io_tools_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows)}, indent=2))


def _powershell_range(path: Path) -> tuple[bool, int]:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-Content -LiteralPath '{path}' | Select-Object -Index (1000..1009)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    return proc.returncode == 0 and "TOKEN-000-01009" in proc.stdout, len(proc.stdout.encode())


def _batch_read(paths: list[Path]) -> tuple[bool, int]:
    values = [path.read_text(encoding="utf-8") for path in paths]
    return len(values) == 10 and "TOKEN-009-01999" in values[-1], sum(len(x.encode()) for x in values)


def _per_file_read(paths: list[Path]) -> tuple[bool, int]:
    total = 0
    correct = True
    for path in paths:
        value = path.read_text(encoding="utf-8")
        total += len(value.encode())
        correct = correct and "TOKEN-" in value
    return correct, total


def _python_replace(path: Path) -> tuple[bool, int]:
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("TOKEN-000-01000", "UPDATED-000-01000", 1), encoding="utf-8")
    value = path.read_text(encoding="utf-8")
    return "UPDATED-000-01000" in value and "TOKEN-000-01000" not in value, path.stat().st_size


def _powershell_replace(path: Path) -> tuple[bool, int]:
    command = (
        f"$p='{path}'; $s=[IO.File]::ReadAllText($p); "
        "$s=$s.Replace('TOKEN-000-01000','UPDATED-000-01000'); "
        "[IO.File]::WriteAllText($p,$s)"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, timeout=60,
    )
    value = path.read_text(encoding="utf-8")
    return proc.returncode == 0 and "UPDATED-000-01000" in value, path.stat().st_size


if __name__ == "__main__":
    main()
