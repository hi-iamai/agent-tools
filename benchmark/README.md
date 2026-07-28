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

