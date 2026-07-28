from __future__ import annotations

import json

from agent_eval import grade
from common import DATA, RESULTS, jsonl_write


def main() -> None:
    tasks = {
        task["task_id"]: task
        for task in json.loads((DATA / "agent_tasks.json").read_text(encoding="utf-8"))
    }
    path = RESULTS / "agent_eval_raw.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    changed = 0
    for row in rows:
        task = tasks[row["task_id"]]
        new_grade = grade(task, row.get("final"), row.get("trace", []))
        if new_grade != row.get("grade"):
            changed += 1
        row["grade"] = new_grade
        row["grader_version"] = "deterministic-v2"
    jsonl_write(path, rows)
    print(json.dumps({"rows": len(rows), "changed": changed}, indent=2))


if __name__ == "__main__":
    main()
