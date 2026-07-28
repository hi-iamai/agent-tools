from __future__ import annotations

import json
import re
from pathlib import Path

from common import BENCH, DATA, ROOT, json_dump, load_config, run


AGENT_TASKS = [
    {
        "task_id": "path_001",
        "category": "path",
        "prompt": "找出 django/core/cache/backends 下所有 Python 后端实现文件，返回完整相对路径列表。不要修改文件。",
        "expected_files_glob": "django/core/cache/backends/*.py",
    },
    {
        "task_id": "path_002",
        "category": "path",
        "prompt": "找出 tests/auth_tests 目录树中所有名为 urls.py 的文件，返回完整相对路径列表。不要修改文件。",
        "expected_files_glob": "tests/auth_tests/**/urls.py",
    },
    {
        "task_id": "text_001",
        "category": "text",
        "prompt": "定位 QuerySet 类的定义，返回文件和定义行，并用一句话说明其直接父类。不要修改文件。",
        "expected_hits": [{"path": "django/db/models/query.py", "line": 330}],
        "concepts": ["AltersData"],
    },
    {
        "task_id": "text_002",
        "category": "text",
        "prompt": "定位 URLResolver 类的定义，返回文件和定义行。不要修改文件。",
        "expected_hits": [{"path": "django/urls/resolvers.py", "line": 503}],
    },
    {
        "task_id": "text_003",
        "category": "text",
        "prompt": "找到 HttpResponse 类的定义，并返回它的父类名称与定义位置。不要修改文件。",
        "expected_hits": [{"path": "django/http/response.py", "line": 377}],
        "concepts": ["HttpResponseBase"],
    },
    {
        "task_id": "text_004",
        "category": "text",
        "prompt": "找到 BaseCache 类的定义，并返回其构造函数 __init__ 所在的大致行区间作为证据。不要修改文件。",
        "expected_hits": [{"path": "django/core/cache/backends/base.py", "line": 58}],
        "concepts": ["__init__"],
    },
    {
        "task_id": "multi_001",
        "category": "multi_step",
        "prompt": "说明 Django 中 get_user_model 函数定义在哪里，并找出 auth 应用中至少一个调用它的测试文件。返回定义和调用证据。不要修改文件。",
        "expected_files": ["django/contrib/auth/__init__.py"],
        "required_path_prefixes": ["tests/auth_tests/"],
        "concepts": ["get_user_model"],
    },
    {
        "task_id": "multi_002",
        "category": "multi_step",
        "prompt": "定位 JsonResponse 的实现和对应测试文件，返回实现文件、类定义位置，以及至少一个直接测试该类的测试文件。不要修改文件。",
        "expected_files": ["django/http/response.py"],
        "required_path_prefixes": ["tests/httpwrappers_tests/"],
        "concepts": ["JsonResponse"],
    },
    {
        "task_id": "multi_003",
        "category": "multi_step",
        "prompt": "找出 django.core.cache.cache 这个默认缓存代理对象是在哪里创建的，以及它代理的连接处理器类型在哪里定义。给出两处代码证据。不要修改文件。",
        "expected_files": ["django/core/cache/__init__.py"],
        "concepts": ["ConnectionProxy", "CacheHandler"],
    },
    {
        "task_id": "regex_001",
        "category": "regex",
        "prompt": "在 django/db/models/query.py 中列出所有名称以字母 a 开头的 async def 方法。只返回方法名及行号。不要修改文件。",
        "expected_regex": "^\\s+async def a\\w+\\(",
        "expected_path": "django/db/models/query.py",
    },
    {
        "task_id": "regex_002",
        "category": "regex",
        "prompt": "找出 django/http/response.py 中所有 RemovedInDjango71Warning 的实际代码引用行，排除纯注释行。返回行号和简短上下文。不要修改文件。",
        "expected_regex": "RemovedInDjango71Warning",
        "expected_path": "django/http/response.py",
    },
    {
        "task_id": "nohit_001",
        "category": "edge",
        "prompt": "确认仓库中是否存在名为 QuantumCacheTeleport 的类或函数。必须搜索后回答；若不存在，明确说明没有命中。不要修改文件。",
        "expected_no_hit": True,
        "concepts": ["QuantumCacheTeleport"],
    },
]


MICRO_QUERIES = [
    {"id": "files_py", "kind": "files", "pattern": "*.py"},
    {"id": "files_tests_urls", "kind": "files", "pattern": "tests/urls_tests/**/urls.py"},
    {"id": "files_cache", "kind": "files", "pattern": "django/core/cache/backends/*.py"},
    {"id": "text_queryset", "kind": "text", "query": "class QuerySet"},
    {"id": "text_removed", "kind": "text", "query": "RemovedInDjango71Warning"},
    {"id": "text_get_user_model", "kind": "text", "query": "get_user_model"},
    {"id": "regex_async", "kind": "regex", "query": "^\\s+async def a\\w+\\("},
    {"id": "regex_class", "kind": "regex", "query": "^class (HttpResponse|URLResolver|QuerySet|Model|BaseCache)\\b"},
    {"id": "no_hit", "kind": "text", "query": "QuantumCacheTeleport"},
    {"id": "broad_import", "kind": "text", "query": "from django."}
]


AST_QUERIES = [
    {"id": "ast_async_methods", "language": "python", "pattern": "async def $F($$$ARGS): $$$BODY"},
    {"id": "ast_classes", "language": "python", "pattern": "class $C($$$BASE): $$$BODY"},
    {"id": "ast_get_user_calls", "language": "python", "pattern": "get_user_model()"},
]


def main() -> None:
    cfg = load_config()
    repo = Path(cfg["repo_path_abs"])
    if not (repo / ".git").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", cfg["repo_url"], str(repo)], ROOT, timeout=300, check=True)
    actual = run(["git", "rev-parse", "HEAD"], repo, check=True)["stdout"].strip()
    if actual != cfg["repo_commit"]:
        raise SystemExit(f"Repository commit mismatch: expected {cfg['repo_commit']}, got {actual}")

    # Resolve deterministic path ground truth with ripgrep's file list.
    for task in AGENT_TASKS:
        pattern = task.pop("expected_files_glob", None)
        if pattern:
            r = run(["rg", "--files", "-g", pattern], repo, check=False)
            task["expected_files"] = sorted(p.replace("\\", "/") for p in r["stdout"].splitlines())
        if task.get("expected_regex"):
            target = repo / task["expected_path"]
            regex = re.compile(task["expected_regex"])
            task["expected_matches"] = [
                {
                    "path": task["expected_path"],
                    "line": line_no,
                    "text": line.strip(),
                    "symbol": (
                        re.search(r"async def\s+(\w+)", line).group(1)
                        if re.search(r"async def\s+(\w+)", line)
                        else ""
                    ),
                }
                for line_no, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1)
                if regex.search(line) and not line.lstrip().startswith("#")
            ]
    json_dump(DATA / "agent_tasks.json", AGENT_TASKS)
    json_dump(DATA / "micro_queries.json", MICRO_QUERIES)
    json_dump(DATA / "ast_queries.json", AST_QUERIES)
    print(json.dumps({"agent_tasks": len(AGENT_TASKS), "micro_queries": len(MICRO_QUERIES), "ast_queries": len(AST_QUERIES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
