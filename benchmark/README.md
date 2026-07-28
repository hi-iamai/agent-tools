# Agent Tool Benchmark

This directory contains the reproducible benchmark used by the final research
report.

## Scope

- Repository: Django, pinned in `config.json`.
- Backend microbenchmarks:
  - `rg --files` versus `git ls-files`
  - `rg` versus `git grep`
  - `rg` versus `ast-grep` for structural Python queries
- Agent Tool Surface experiment, all backed by the same `ripgrep` executable:
  - `shell`: one PowerShell tool
  - `dedicated`: `glob`, `grep`, and `read_file`
  - `router`: one deterministic `workspace_query`

The agent experiment uses the Anthropic-compatible endpoint configured in the
repository `.env`. Secrets are never written to result files.

## Run

```powershell
python benchmark/scripts/prepare_dataset.py
python benchmark/scripts/microbench.py --repeats 12
python benchmark/scripts/agent_eval.py --repeats 2
python benchmark/scripts/analyze.py
```

For a quick smoke run:

```powershell
python benchmark/scripts/agent_eval.py --repeats 1 --task-limit 3
```

Raw JSON/JSONL/CSV artifacts are written under `benchmark/results/`.

## Extended benchmark

The extended benchmark covers multiple search backends, indexed search,
WebFetch extractors, browser rendering, and API clients:

```powershell
python -m pip install -r benchmark/requirements-extended.txt
npm install --no-save playwright-core @ast-grep/cli

python benchmark/scripts/extended_search_bench.py --repeats 5 --environment windows --output-dir benchmark/results/extended

python benchmark/scripts/web_fixture_server.py --host 127.0.0.1 --port 8765
# In another terminal:
python benchmark/scripts/webfetch_bench.py --repeats 5 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/api_fetch_bench.py --repeats 3 --environment windows --output-dir benchmark/results/extended
node benchmark/scripts/browser_fetch_bench.mjs --repeats 3 --environment windows --output benchmark/results/extended/browser_fetch_windows.jsonl

python benchmark/scripts/structure_bench.py --repeats 3 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/index_lifecycle_bench.py --output-dir benchmark/results/extended
python benchmark/scripts/runtime_bench.py --repeats 3 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/git_tool_bench.py --repeats 5 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/io_tool_bench.py --repeats 5 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/websearch_bench.py --repeats 5 --output-dir benchmark/results/extended
python benchmark/scripts/generate_manifest.py
python benchmark/scripts/extended_analyze.py
```

Linux candidates currently covered by the runner include GNU `find`/`grep`,
`fd`, `ripgrep`, `ugrep`, `ag`, `git grep`, Python scanning, and SQLite FTS5.
Keep WSL-on-NTFS and a repository copied into the Linux filesystem as separate
environments.
