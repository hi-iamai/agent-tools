from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from common import RESULTS, ROOT, jsonl_write, load_config


TASKS = [
    {
        "id": "async_a_methods",
        "ast_kind": "async_prefix",
        "ast_value": "a",
        "sg_pattern": "async def $F($$$ARGS): $$$BODY",
        "rg_pattern": r"^\s*async def a\w+\(",
    },
    {
        "id": "selected_classes",
        "ast_kind": "class_names",
        "ast_value": ["HttpResponse", "URLResolver", "QuerySet", "Model", "BaseCache"],
        "sg_pattern": "class $C($$$BASE): $$$BODY",
        "rg_pattern": r"^class (HttpResponse|URLResolver|QuerySet|Model|BaseCache)\b",
    },
    {
        "id": "get_user_model_calls",
        "ast_kind": "call_name",
        "ast_value": "get_user_model",
        "sg_pattern": "get_user_model()",
        "rg_pattern": r"\bget_user_model\s*\(",
    },
    {
        "id": "property_decorators",
        "ast_kind": "decorator_name",
        "ast_value": "property",
        "sg_pattern": "@property\ndef $F($$$ARGS):\n    $$$BODY",
        "rg_pattern": r"^\s*@property\s*$",
    },
    {
        "id": "classmethod_decorators",
        "ast_kind": "decorator_name",
        "ast_value": "classmethod",
        "sg_pattern": "@classmethod\ndef $F($$$ARGS):\n    $$$BODY",
        "rg_pattern": r"^\s*@classmethod\s*$",
    },
    {
        "id": "staticmethod_decorators",
        "ast_kind": "decorator_name",
        "ast_value": "staticmethod",
        "sg_pattern": "@staticmethod\ndef $F($$$ARGS):\n    $$$BODY",
        "rg_pattern": r"^\s*@staticmethod\s*$",
    },
    {
        "id": "warnings_warn_calls",
        "ast_kind": "attribute_call",
        "ast_value": ["warnings", "warn"],
        "sg_pattern": "warnings.warn($$$ARGS)",
        "rg_pattern": r"\bwarnings\.warn\s*\(",
    },
    {
        "id": "super_calls",
        "ast_kind": "call_name",
        "ast_value": "super",
        "sg_pattern": "super()",
        "rg_pattern": r"\bsuper\s*\(\s*\)",
    },
    {
        "id": "yield_functions",
        "ast_kind": "function_contains_yield",
        "ast_value": None,
        "sg_pattern": "def $F($$$ARGS): $$$BODY",
        "rg_pattern": r"^\s*yield\b",
    },
    {
        "id": "try_except_blocks",
        "ast_kind": "try_nodes",
        "ast_value": None,
        "sg_pattern": "try:\n    $$$BODY\nexcept $$$EXC:\n    $$$HANDLER",
        "rg_pattern": r"^\s*try:\s*$",
    },
    {
        "id": "with_blocks",
        "ast_kind": "with_nodes",
        "ast_value": None,
        "sg_pattern": "with $CTX:\n    $$$BODY",
        "rg_pattern": r"^\s*with .+:$",
    },
    {
        "id": "async_with_blocks",
        "ast_kind": "async_with_nodes",
        "ast_value": None,
        "sg_pattern": "async with $CTX:\n    $$$BODY",
        "rg_pattern": r"^\s*async with .+:$",
    },
    {
        "id": "raise_nodes",
        "ast_kind": "raise_nodes",
        "ast_value": None,
        "sg_pattern": "raise $EXC",
        "rg_pattern": r"^\s*raise\b",
    },
    {
        "id": "lambda_nodes",
        "ast_kind": "lambda_nodes",
        "ast_value": None,
        "sg_pattern": "lambda $$$ARGS: $BODY",
        "rg_pattern": r"\blambda\b",
    },
    {
        "id": "named_expressions",
        "ast_kind": "named_expr_nodes",
        "ast_value": None,
        "sg_pattern": "$A := $B",
        "rg_pattern": r":=",
    },
]


def python_ast(repo: Path, task: dict[str, Any]) -> list[str]:
    results = []
    for path in repo.rglob("*.py"):
        if ".git" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            matched = False
            if task["ast_kind"] == "async_prefix":
                matched = isinstance(node, ast.AsyncFunctionDef) and node.name.startswith(task["ast_value"])
            elif task["ast_kind"] == "class_names":
                matched = isinstance(node, ast.ClassDef) and node.name in task["ast_value"]
            elif task["ast_kind"] == "call_name":
                matched = isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == task["ast_value"]
            elif task["ast_kind"] == "attribute_call":
                matched = (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and [node.func.value.id, node.func.attr] == task["ast_value"]
                )
            elif task["ast_kind"] == "decorator_name":
                matched = (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(isinstance(decorator, ast.Name) and decorator.id == task["ast_value"] for decorator in node.decorator_list)
                )
            elif task["ast_kind"] == "function_contains_yield":
                matched = (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in ast.walk(node))
                )
            elif task["ast_kind"] == "try_nodes":
                matched = isinstance(node, ast.Try)
            elif task["ast_kind"] == "with_nodes":
                matched = isinstance(node, ast.With)
            elif task["ast_kind"] == "async_with_nodes":
                matched = isinstance(node, ast.AsyncWith)
            elif task["ast_kind"] == "raise_nodes":
                matched = isinstance(node, ast.Raise)
            elif task["ast_kind"] == "lambda_nodes":
                matched = isinstance(node, ast.Lambda)
            elif task["ast_kind"] == "named_expr_nodes":
                matched = isinstance(node, ast.NamedExpr)
            if matched:
                line_no = node.lineno
                if task["ast_kind"] == "decorator_name":
                    decorators = [
                        decorator.lineno for decorator in node.decorator_list
                        if isinstance(decorator, ast.Name) and decorator.id == task["ast_value"]
                    ]
                    line_no = min(decorators)
                results.append(f"{path.relative_to(repo).as_posix()}:{line_no}")
    return sorted(results)


def run_process(args: list[str], repo: Path) -> tuple[float, int, str, str]:
    started = time.perf_counter()
    proc = subprocess.run(args, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    return (time.perf_counter() - started) * 1000, proc.returncode, proc.stdout, proc.stderr


def parse_rg(text: str) -> list[str]:
    values = []
    for line in text.splitlines():
        match = re.match(r"(.+?):(\d+):", line.replace("\\", "/"))
        if match:
            values.append(f"{match.group(1).lstrip('./')}:{match.group(2)}")
    return sorted(set(values))


def parse_ast_grep(text: str, task: dict[str, Any]) -> list[str]:
    values = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        source = item.get("text", "")
        if task["ast_kind"] == "async_prefix":
            match = re.match(r"\s*async def\s+(\w+)", source)
            if not match or not match.group(1).startswith("a"):
                continue
        elif task["ast_kind"] == "class_names":
            match = re.match(r"\s*class\s+(\w+)", source)
            if not match or match.group(1) not in task["ast_value"]:
                continue
        elif task["ast_kind"] == "decorator_name":
            if f"@{task['ast_value']}" not in source:
                continue
        path = str(item.get("file", "")).replace("\\", "/").lstrip("./")
        line_no = int(item.get("range", {}).get("start", {}).get("line", 0)) + 1
        values.append(f"{path}:{line_no}")
    return sorted(set(values))


def normalize_decorator_locations(repo: Path, values: list[str], task: dict[str, Any]) -> list[str]:
    if task["ast_kind"] != "decorator_name":
        return values
    normalized = []
    decorator = "@" + task["ast_value"]
    for value in values:
        path_text, line_text = value.rsplit(":", 1)
        line_no = int(line_text)
        try:
            lines = (repo / path_text).read_text(encoding="utf-8", errors="replace").splitlines()
            while line_no > 1 and lines[line_no - 2].lstrip().startswith("@"):
                line_no -= 1
            if lines[line_no - 1].strip() != decorator:
                for candidate in range(max(1, line_no - 5), line_no + 1):
                    if lines[candidate - 1].strip() == decorator:
                        line_no = candidate
                        break
        except (OSError, IndexError):
            pass
        normalized.append(f"{path_text}:{line_no}")
    return sorted(set(normalized))


def score(expected: set[str], actual: set[str]) -> tuple[float, float]:
    precision = len(expected & actual) / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = len(expected & actual) / len(expected) if expected else (1.0 if not actual else 0.0)
    return precision, recall


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    repo = Path(load_config()["repo_path_abs"])
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    sg = ROOT / "node_modules" / "@ast-grep" / "cli" / "ast-grep.exe"
    rows = []
    for task in TASKS:
        expected_values = python_ast(repo, task)
        expected = set(expected_values)
        for repeat in range(args.repeats):
            started = time.perf_counter()
            ast_values = python_ast(repo, task)
            duration = (time.perf_counter() - started) * 1000
            precision, recall = score(expected, set(ast_values))
            rows.append({
                "environment": args.environment, "task": task["id"], "backend": "python_ast",
                "repeat": repeat, "duration_ms": duration, "result_count": len(ast_values),
                "precision": precision, "recall": recall, "output_bytes": len("\n".join(ast_values).encode()),
                "error": None,
            })
            duration, code, stdout, stderr = run_process(
                [str(sg), "run", "-l", "python", "-p", task["sg_pattern"], "--json=stream", "."], repo
            )
            sg_values = parse_ast_grep(stdout, task)
            sg_values = normalize_decorator_locations(repo, sg_values, task)
            precision, recall = score(expected, set(sg_values))
            rows.append({
                "environment": args.environment, "task": task["id"], "backend": "ast_grep",
                "repeat": repeat, "duration_ms": duration, "result_count": len(sg_values),
                "precision": precision, "recall": recall,
                "output_bytes": len("\n".join(sg_values).encode()),
                "raw_output_bytes": len(stdout.encode()),
                "error": stderr if code not in (0, 1) else None,
            })
            duration, code, stdout, stderr = run_process(
                ["rg", "-n", "--no-heading", "--color", "never", task["rg_pattern"], "-g", "*.py", "."], repo
            )
            rg_values = parse_rg(stdout)
            precision, recall = score(expected, set(rg_values))
            rows.append({
                "environment": args.environment, "task": task["id"], "backend": "rg_pattern",
                "repeat": repeat, "duration_ms": duration, "result_count": len(rg_values),
                "precision": precision, "recall": recall,
                "output_bytes": len("\n".join(rg_values).encode()),
                "raw_output_bytes": len(stdout.encode()),
                "error": stderr if code not in (0, 1) else None,
            })
    jsonl_write(output / f"structure_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows), "tasks": len(TASKS)}, indent=2))


if __name__ == "__main__":
    main()
