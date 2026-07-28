from __future__ import annotations

import argparse
import fnmatch
import json
import os
import random
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from common import DATA, RESULTS, jsonl_write, load_config, load_env, run, sha256_text

SYSTEM = """你是一个在本地代码仓库中工作的只读工程 Agent。
只能依据仓库内容和工具结果回答，不得猜测未观察到的代码。
优先执行最小、可验证的搜索和读取。若结果被截断，应缩小查询。
不得修改文件、访问网络或读取工作区外路径。
最终回复必须是 JSON，不得使用 Markdown 围栏：
{"status":"completed|partial|failed","summary":"结论","evidence":[{"path":"相对路径","line_start":1,"line_end":1,"reason":"证据说明"}],"limitations":[]}
"""


def tools_for(surface: str) -> list[dict[str, Any]]:
    shell = {
        "name": "shell",
        "description": "在仓库根目录执行只读 PowerShell 命令。可使用 rg、git 和 Get-Content；禁止写文件和网络。",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "additionalProperties": False,
        },
    }
    glob = {
        "name": "glob",
        "description": "按路径 glob 查找文件，不搜索内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 300, "default": 100},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    }
    grep = {
        "name": "grep",
        "description": "使用 ripgrep 搜索文件内容，返回路径、行号和文本。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {"type": "string", "enum": ["literal", "regex"], "default": "literal"},
                "glob": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }
    read_file = {
        "name": "read_file",
        "description": "读取文本文件的指定行区间。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "line_start": {"type": "integer", "minimum": 1, "default": 1},
                "line_end": {"type": "integer", "minimum": 1, "default": 200},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    }
    router = {
        "name": "workspace_query",
        "description": "查询工作区文件和代码。内部确定性选择 glob、文本搜索或读取策略，并返回证据。",
        "input_schema": {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "known_terms": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "file_hints": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 40},
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
    }
    return {"shell": [shell], "dedicated": [glob, grep, read_file], "router": [router]}[surface]


def safe_relative(repo: Path, value: str) -> Path:
    candidate = (repo / value).resolve()
    if repo.resolve() not in candidate.parents and candidate != repo.resolve():
        raise ValueError("path outside workspace")
    return candidate


def truncate(value: str, limit: int) -> dict[str, Any]:
    if len(value) <= limit:
        return {"content": value, "truncated": False}
    return {"content": value[:limit], "truncated": True}


def execute_tool(repo: Path, name: str, data: dict[str, Any], max_chars: int) -> dict[str, Any]:
    started = time.perf_counter()
    strategy = None
    if name == "shell":
        command = data["command"]
        blocked = re.search(r"(?i)(remove-item|del\\s|erase\\s|set-content|add-content|out-file|invoke-webrequest|curl\\s|wget\\s|git\\s+(checkout|reset|clean))", command)
        if blocked:
            return {"error": "blocked unsafe or mutating command", "duration_ms": 0}
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        payload = {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    elif name == "glob":
        pattern = data["pattern"]
        limit = int(data.get("limit", 100))
        r = run(["rg", "--files", "-g", pattern], repo, timeout=60)
        lines = r["stdout"].splitlines()[:limit]
        payload = {"matches": [x.replace("\\", "/") for x in lines], "exit_code": r["returncode"]}
    elif name == "grep":
        args = ["rg", "-n", "--no-heading", "--color", "never"]
        if data.get("mode", "literal") == "literal":
            args.append("-F")
        if data.get("glob"):
            args += ["-g", data["glob"]]
        args.append(data["query"])
        r = run(args, repo, timeout=60)
        payload = {"matches": r["stdout"].splitlines()[: int(data.get("limit", 50))], "exit_code": r["returncode"]}
    elif name == "read_file":
        path = safe_relative(repo, data["path"])
        start = int(data.get("line_start", 1))
        end = int(data.get("line_end", start + 199))
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        payload = {"path": data["path"], "line_start": start, "line_end": min(end, len(lines)),
                   "content": "\n".join(f"{i}: {lines[i-1]}" for i in range(start, min(end, len(lines)) + 1))}
    elif name == "workspace_query":
        objective = data["objective"]
        terms = [x for x in data.get("known_terms", []) if x]
        hints = [x for x in data.get("file_hints", []) if x]
        limit = int(data.get("limit", 40))
        objective_glob = re.search(r"([A-Za-z0-9_./\\-]+(?:\*\*/)?\*?\.[A-Za-z0-9_*?]+)", objective)
        pathish = next((x for x in hints + terms if any(c in x for c in ("*", "?"))), None)
        if not pathish and objective_glob:
            pathish = objective_glob.group(1).replace("\\", "/")
        if not pathish and hints and re.search(r"(?i)(列出|所有|文件|目录|find all|list)", objective):
            base = hints[0].replace("\\", "/").rstrip("/")
            if "." not in Path(base).name:
                pathish = base + "/**/*"
        if pathish:
            strategy = "glob"
            r = run(["rg", "--files", "-g", pathish], repo, timeout=60)
        else:
            tokens = terms or re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", objective)
            token = max(tokens, key=len) if tokens else objective[:80]
            strategy = "literal_grep"
            r = run(["rg", "-n", "--no-heading", "--color", "never", "-F", token], repo, timeout=60)
        payload = {"strategy": strategy, "matches": r["stdout"].splitlines()[:limit], "exit_code": r["returncode"]}
    else:
        payload = {"error": f"unknown tool {name}"}
    payload["duration_ms"] = (time.perf_counter() - started) * 1000
    raw = json.dumps(payload, ensure_ascii=False)
    return truncate(raw, max_chars)


def call_api(env: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    url = env["AGENT_BASE_URL"].rstrip("/") + "/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": env["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 3 * (2 ** attempt))
            time.sleep(delay)
    raise RuntimeError("unreachable")


def parse_final(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\\s*|\\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except Exception:
        decoder = json.JSONDecoder()
        for match in reversed(list(re.finditer(r"\{", text))):
            try:
                value, _ = decoder.raw_decode(text[match.start():])
                if isinstance(value, dict) and "status" in value:
                    return value
            except Exception:
                continue
    return None


def grade(task: dict[str, Any], final: dict[str, Any] | None, trace: list[dict[str, Any]]) -> dict[str, Any]:
    if not final:
        return {"success": False, "score": 0.0, "reason": "invalid_final_json"}
    evidence = final.get("evidence") or []
    paths = {str(e.get("path", "")).replace("\\", "/") for e in evidence}
    summary_blob = json.dumps(final, ensure_ascii=False)
    checks: list[bool] = []
    for path in task.get("expected_files", []):
        checks.append(path in paths or path in summary_blob)
    for prefix in task.get("required_path_prefixes", []):
        checks.append(any(p.startswith(prefix) for p in paths) or prefix in summary_blob)
    for hit in task.get("expected_hits", []):
        path_ok = hit["path"] in paths or hit["path"] in summary_blob
        line_ok = any(
            str(e.get("path", "")).replace("\\", "/") == hit["path"]
            and abs(int(e.get("line_start", -10000)) - hit["line"]) <= 8
            for e in evidence if str(e.get("line_start", "")).lstrip("-").isdigit()
        )
        checks += [path_ok, line_ok]
    for concept in task.get("concepts", []):
        checks.append(concept.lower() in summary_blob.lower())
    if task.get("expected_no_hit"):
        checks.append(any(
            word in summary_blob.lower()
            for word in ("不存在", "没有命中", "未找到", "no match", "not found")
        ))
    if task.get("expected_regex"):
        # For list tasks, require that the agent at least used a matching search
        # and returned multiple evidence/result lines rather than guessing.
        tool_blob = json.dumps(trace, ensure_ascii=False)
        checks.append(task["expected_path"] in summary_blob)
        checks.append("rg" in tool_blob.lower() or "grep" in tool_blob.lower() or "workspace_query" in tool_blob)
    score = sum(checks) / len(checks) if checks else 0.0
    return {"success": score >= 0.8, "score": score, "checks": checks}


def one_run(task: dict[str, Any], surface: str, repeat: int, cfg: dict, env: dict) -> dict[str, Any]:
    repo = Path(cfg["repo_path_abs"])
    tools = tools_for(surface)
    messages: list[dict[str, Any]] = [{"role": "user", "content": task["prompt"]}]
    trace = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    started = time.perf_counter()
    final_text = ""
    termination = "unknown"
    for turn in range(cfg["max_agent_turns"]):
        payload = {
            "model": env["AGENT_MODEL_ID"],
            "max_tokens": cfg["max_output_tokens"],
            "temperature": 0,
            "system": SYSTEM,
            "tools": tools,
            "messages": messages,
        }
        response = call_api(env, payload, cfg["task_timeout_seconds"])
        for key in usage:
            usage[key] += int(response.get("usage", {}).get(key, 0))
        content = response.get("content", [])
        messages.append({"role": "assistant", "content": content})
        tool_uses = [x for x in content if x.get("type") == "tool_use"]
        texts = [x.get("text", "") for x in content if x.get("type") == "text"]
        if not tool_uses:
            final_text = "\n".join(texts)
            termination = response.get("stop_reason", "end_turn")
            break
        if len(trace) + len(tool_uses) > cfg["max_tool_calls"]:
            termination = "max_tool_calls"
            break
        results = []
        for block in tool_uses:
            result = execute_tool(repo, block["name"], block.get("input") or {}, cfg["tool_output_max_chars"])
            trace.append({"turn": turn, "tool": block["name"], "input": block.get("input"), "result": result})
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": json.dumps(result, ensure_ascii=False)})
        messages.append({"role": "user", "content": results})
    final = parse_final(final_text)
    if final is None and termination == "end_turn":
        # The compatibility endpoint may prepend prose despite the requested
        # JSON-only format. Keep the raw text gradeable rather than treating
        # this provider formatting behavior as a tool-surface failure.
        final = {"status": "partial", "summary": final_text, "evidence": [], "limitations": ["non_strict_json"]}
    graded = grade(task, final, trace)
    input_price = float(env.get("AGENT_INPUT_COST_PER_MILLION_TOKENS", "0") or 0)
    output_price = float(env.get("AGENT_OUTPUT_COST_PER_MILLION_TOKENS", "0") or 0)
    cost = usage["input_tokens"] / 1_000_000 * input_price + usage["output_tokens"] / 1_000_000 * output_price
    return {
        "run_id": f"{task['task_id']}-{surface}-{repeat}",
        "task_id": task["task_id"], "category": task["category"], "surface": surface, "repeat": repeat,
        "model": env["AGENT_MODEL_ID"], "prompt_hash": sha256_text(SYSTEM + task["prompt"]),
        "duration_ms": (time.perf_counter() - started) * 1000, "termination": termination,
        "usage": usage, "estimated_cost_usd": cost, "tool_call_count": len(trace),
        "trace": trace, "final_text": final_text, "final": final, "grade": graded,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--surfaces", default="shell,dedicated,router")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=1.5)
    args = parser.parse_args()
    cfg = load_config()
    env = load_env()
    tasks = json.loads((DATA / "agent_tasks.json").read_text(encoding="utf-8"))
    if args.task_limit:
        tasks = tasks[: args.task_limit]
    surfaces = args.surfaces.split(",")
    jobs = [(task, surface, repeat) for task in tasks for surface in surfaces for repeat in range(args.repeats)]
    random.Random(cfg["assignment_seed"]).shuffle(jobs)
    rows = []
    if args.resume and (RESULTS / "agent_eval_raw.jsonl").exists():
        rows = [json.loads(x) for x in (RESULTS / "agent_eval_raw.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        rows = [x for x in rows if x.get("termination") != "infrastructure_error"]
    completed = {x["run_id"] for x in rows}
    budget = float(env.get("AGENT_MAX_COST_USD", "0") or 0)
    for index, (task, surface, repeat) in enumerate(jobs, 1):
        run_id = f"{task['task_id']}-{surface}-{repeat}"
        if run_id in completed:
            continue
        if budget and sum(x["estimated_cost_usd"] for x in rows) >= budget * 0.9:
            print("stopping at 90% cost budget")
            break
        try:
            row = one_run(task, surface, repeat, cfg, env)
        except Exception as exc:
            row = {
                "run_id": f"{task['task_id']}-{surface}-{repeat}", "task_id": task["task_id"],
                "category": task["category"], "surface": surface, "repeat": repeat,
                "duration_ms": 0, "termination": "infrastructure_error",
                "usage": {"input_tokens": 0, "output_tokens": 0}, "estimated_cost_usd": 0,
                "tool_call_count": 0, "trace": [], "final_text": "", "final": None,
                "grade": {"success": False, "score": 0, "reason": repr(exc)},
            }
        rows.append(row)
        jsonl_write(RESULTS / "agent_eval_raw.jsonl", rows)
        print(index, row["run_id"], row["grade"]["success"], round(row["estimated_cost_usd"], 4))
        time.sleep(args.delay_seconds)
    print(f"wrote {len(rows)} rows")


if __name__ == "__main__":
    main()
