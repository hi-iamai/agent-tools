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
python benchmark/scripts/code_intelligence_bench.py --repeats 2 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/lsp_bench.py --repeats 3 --output-dir benchmark/results/extended
# Zoekt, SCIP Python, and CodeQL are exercised from WSL; see the panoramic
# report for installation commands, build costs, and environment limitations.
python benchmark/scripts/index_lifecycle_bench.py --output-dir benchmark/results/extended
python benchmark/scripts/runtime_bench.py --repeats 3 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/git_tool_bench.py --repeats 5 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/io_tool_bench.py --repeats 5 --environment windows --output-dir benchmark/results/extended
python benchmark/scripts/websearch_bench.py --repeats 5 --output-dir benchmark/results/extended
python benchmark/scripts/provider_capability_probe.py
python benchmark/scripts/multirepo_search_bench.py --repeats 3 --output-dir benchmark/results/extended
python benchmark/scripts/patch_tool_bench.py --repeats 20 --output-dir benchmark/results/extended
# MCP 2.0 SDK is currently exercised in WSL:
python benchmark/scripts/mcp_runtime_bench.py --repo /path/to/repo --repeats 3 --output benchmark/results/extended/mcp_runtime_wsl.jsonl
python benchmark/scripts/mcp_http_bench.py --url http://127.0.0.1:8767/mcp --repeats 3 --output benchmark/results/extended/mcp_http_wsl.jsonl

# SearXNG and Zoekt are deployed from source in WSL:
python benchmark/scripts/searxng_bench.py --base-url http://127.0.0.1:8888 --repeats 3 --output benchmark/results/extended/searxng_wsl.jsonl
python benchmark/scripts/zoekt_bench.py --base-url http://127.0.0.1:6070 --repeats 10 --output benchmark/results/extended/zoekt_wsl.jsonl

# Strict same-engine runtime/transport ablation (run in WSL where MCP SDK works):
python benchmark/scripts/strict_runtime_bench.py --repeats 20 --throughput-requests 64 --python /path/to/python --output-dir benchmark/results/extended
python benchmark/scripts/strict_runtime_analyze.py
python benchmark/scripts/generate_manifest.py
python benchmark/scripts/extended_analyze.py
```

Linux candidates currently covered by the runner include GNU `find`/`grep`,
`fd`, `ripgrep`, `ugrep`, `ag`, `git grep`, Python scanning, and SQLite FTS5.
Keep WSL-on-NTFS and a repository copied into the Linux filesystem as separate
environments.

The strict runtime benchmark uses one preloaded in-memory engine and one
response schema across every adapter. Run it in isolation: ports `8770` and
`8771` must be free, and no other CPU-heavy benchmark should run concurrently.
