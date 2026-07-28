from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))
import jedi
from tree_sitter import Language, Parser, Query, QueryCursor
import tree_sitter_python

from common import RESULTS, jsonl_write, load_config


SYMBOLS = ["QuerySet", "HttpResponse", "URLResolver", "BaseCache", "get_user_model"]
IMPORTS = {
    "QuerySet": "django.db.models.query",
    "HttpResponse": "django.http.response",
    "URLResolver": "django.urls.resolvers",
    "BaseCache": "django.core.cache.backends.base",
    "get_user_model": "django.contrib.auth",
}


def ast_definitions(repo: Path) -> dict[str, list[str]]:
    result = {symbol: [] for symbol in SYMBOLS}
    for path in repo.rglob("*.py"):
        if ".git" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in result:
                result[node.name].append(f"{path.relative_to(repo).as_posix()}:{node.lineno}")
    return result


def ctags_definitions(repo: Path, symbol: str) -> list[str]:
    executable = shutil.which("ctags")
    if not executable:
        raise RuntimeError("ctags unavailable in this environment")
    proc = subprocess.run(
        [executable, "-R", "--sort=no", "--output-format=json", "--fields=+n", "--languages=Python", "-f", "-", "."],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    values = []
    for line in proc.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("name") == symbol:
            path_text = str(item["path"]).replace(chr(92), "/").lstrip("./")
            line_no = item.get("line")
            if not line_no and item.get("pattern"):
                expression = str(item["pattern"])
                expression = expression.removeprefix("/^").removesuffix("$/;\"").replace("\\/", "/")
                try:
                    source = (repo / path_text).read_text(encoding="utf-8", errors="replace").splitlines()
                    line_no = next(
                        (index for index, source_line in enumerate(source, 1) if source_line == expression),
                        0,
                    )
                except OSError:
                    line_no = 0
            values.append(f"{path_text}:{line_no or 0}")
    return sorted(set(values))


def jedi_definition(repo: Path, symbol: str) -> list[str]:
    module = IMPORTS[symbol]
    script = jedi.Script(
        code=f"from {module} import {symbol}\n{symbol}",
        path=str(repo / "_probe.py"),
        project=jedi.Project(repo, sys_path=[str(repo)]),
    )
    values = []
    for definition in script.infer(line=2, column=len(symbol)):
        if definition.module_path and str(definition.module_path).startswith(str(repo)):
            values.append(f"{Path(definition.module_path).relative_to(repo).as_posix()}:{definition.line}")
    return sorted(set(values))


def tree_sitter_definitions(repo: Path, symbol: str) -> list[str]:
    vendor_bootstrap = (
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'vendor')!r})"
        if sys.platform == "win32" else ""
    )
    code = f"""
import json, sys
from pathlib import Path
{vendor_bootstrap}
from tree_sitter import Language, Parser, Query, QueryCursor
import tree_sitter_python
repo=Path({str(repo)!r}); symbol={symbol!r}
language=Language(tree_sitter_python.language()); parser=Parser(language)
query=Query(language, '(class_definition name: (identifier) @name) @definition\\n(function_definition name: (identifier) @name) @definition')
values=[]
for path in repo.rglob('*.py'):
    if '.git' in path.parts: continue
    raw=path.read_bytes(); tree=parser.parse(raw); captures=QueryCursor(query).captures(tree.root_node)
    for name in captures.get('name', []):
        if raw[name.start_byte:name.end_byte].decode(errors='replace') == symbol:
            values.append(f"{{path.relative_to(repo).as_posix()}}:{{name.start_point[0] + 1}}")
print(json.dumps(sorted(set(values))))
"""
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr or f"tree-sitter exited {proc.returncode}")
    return json.loads(proc.stdout)


def rg_definitions(repo: Path, symbol: str) -> list[str]:
    proc = subprocess.run(
        ["rg", "-n", rf"^(class|def|async def)\s+{re.escape(symbol)}\b", "-g", "*.py", "."],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    values = []
    for line in proc.stdout.splitlines():
        match = re.match(r"(.+?):(\d+):", line.replace("\\", "/"))
        if match:
            values.append(f"{match.group(1).lstrip('./')}:{match.group(2)}")
    return sorted(set(values))


def metrics(expected: set[str], actual: set[str]) -> tuple[float, float]:
    return (
        len(expected & actual) / len(actual) if actual else 0.0,
        len(expected & actual) / len(expected) if expected else 1.0,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--repo")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    repo = Path(args.repo).resolve() if args.repo else Path(load_config()["repo_path_abs"])
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    oracle = ast_definitions(repo)
    rows = []
    methods = {
        "rg_definition": rg_definitions,
        "tree_sitter": tree_sitter_definitions,
        "ctags": ctags_definitions,
        "jedi": jedi_definition,
    }
    for repeat in range(args.repeats):
        for symbol in SYMBOLS:
            expected = set(oracle[symbol])
            for method, function in methods.items():
                started = time.perf_counter()
                error = None
                try:
                    actual = function(repo, symbol)
                except Exception as exc:
                    actual, error = [], repr(exc)
                precision, recall = metrics(expected, set(actual))
                rows.append({
                    "environment": args.environment, "symbol": symbol, "method": method,
                    "repeat": repeat, "duration_ms": (time.perf_counter() - started) * 1000,
                    "precision": precision, "recall": recall, "result_count": len(actual),
                    "error": error,
                })
    jsonl_write(output / f"code_intelligence_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows)}, indent=2))


if __name__ == "__main__":
    main()
