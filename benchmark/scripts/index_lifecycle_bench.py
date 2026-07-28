from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from common import RESULTS, json_dump, load_config
from extended_search_bench import build_fts, fts_query


def replace_file(con: sqlite3.Connection, repo: Path, path: Path) -> None:
    rel = path.relative_to(repo).as_posix()
    con.execute("delete from lines where path = ?", (rel,))
    text = path.read_text(encoding="utf-8", errors="replace")
    con.executemany(
        "insert into lines(path,line_no,text) values(?,?,?)",
        [(rel, line_no, line) for line_no, line in enumerate(text.splitlines(), 1)],
    )
    con.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    source = Path(load_config()["repo_path_abs"])
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    with tempfile.TemporaryDirectory(prefix="agent-index-") as temp:
        repo = Path(temp) / "django"
        shutil.copytree(source, repo, ignore=shutil.ignore_patterns(".git"))
        db = Path(temp) / "index.sqlite"
        build = build_fts(repo, db)
        target = repo / "django" / "utils" / "_benchmark_index_fixture.py"
        target.write_text('VALUE = "INDEX-LIFECYCLE-001"\n', encoding="utf-8")
        con = sqlite3.connect(db)
        started = time.perf_counter()
        replace_file(con, repo, target)
        add_ms = (time.perf_counter() - started) * 1000
        add_visible = fts_query(db, "INDEX-LIFECYCLE-001")["returncode"] == 0

        target.write_text('VALUE = "INDEX-LIFECYCLE-002"\n', encoding="utf-8")
        started = time.perf_counter()
        replace_file(con, repo, target)
        update_ms = (time.perf_counter() - started) * 1000
        old_visible = fts_query(db, "INDEX-LIFECYCLE-001")["returncode"] == 0
        new_visible = fts_query(db, "INDEX-LIFECYCLE-002")["returncode"] == 0

        started = time.perf_counter()
        rel = target.relative_to(repo).as_posix()
        target.unlink()
        con.execute("delete from lines where path = ?", (rel,))
        con.commit()
        delete_ms = (time.perf_counter() - started) * 1000
        deleted_visible = fts_query(db, "INDEX-LIFECYCLE-002")["returncode"] == 0
        con.close()

        started = time.perf_counter()
        reopened = sqlite3.connect(db)
        reopened.execute("select count(*) from lines").fetchone()
        reopened.close()
        reopen_ms = (time.perf_counter() - started) * 1000

        result = {
            "build": build,
            "add_ms": add_ms,
            "add_visible": add_visible,
            "update_ms": update_ms,
            "old_visible_after_update": old_visible,
            "new_visible_after_update": new_visible,
            "delete_ms": delete_ms,
            "deleted_visible_after_delete": deleted_visible,
            "reopen_ms": reopen_ms,
        }
    json_dump(output / "index_lifecycle_windows.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
