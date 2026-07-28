from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path

from common import BENCH, RESULTS, ROOT, json_dump, load_config


def command_version(command: list[str]) -> str:
    try:
        proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return (proc.stdout or proc.stderr).splitlines()[0]
    except Exception as exc:
        return f"unavailable: {exc}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    config = load_config()
    repo = Path(config["repo_path_abs"])
    manifest = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "repo_commit": command_version(["git", "-C", str(repo), "rev-parse", "HEAD"]),
        "repositories": {
            name: {
                "path": str(path.relative_to(ROOT)),
                "commit": command_version(["git", "-C", str(path), "rev-parse", "HEAD"]),
            }
            for name, path in {
                "django": ROOT / "benchmark" / "repos" / "django",
                "pytest": ROOT / "benchmark" / "repos" / "pytest",
                "black": ROOT / "benchmark" / "repos" / "black",
            }.items()
            if path.exists()
        },
        "versions": {
            "python": command_version(["python", "--version"]),
            "git": command_version(["git", "--version"]),
            "ripgrep": command_version(["rg", "--version"]),
            "node": command_version(["node", "--version"]),
            "edge": "system Microsoft Edge; exact version unavailable in headless singleton environment",
        },
        "environment_notes": {
            "windows": "Windows native",
            "wsl": "Ubuntu 24.04 WSL1; not a native Linux kernel benchmark",
        },
        "config_sha256": sha256(BENCH / "config.json"),
        "data_sha256": {
            path.name: sha256(path)
            for path in sorted((BENCH / "data").glob("*.json"))
        },
        "script_sha256": {
            path.name: sha256(path)
            for path in sorted((BENCH / "scripts").glob("*"))
            if path.is_file() and path.suffix in {".py", ".mjs"}
        },
    }
    json_dump(RESULTS / "extended" / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
