# Agent Tools Research and Benchmark

Agent 底层 Tool、Backend、结果处理与运行形态的可复现评测工程。

## 当前状态

项目仍在进行中，当前不存在“最终唯一方案”。已完成的主要阶段包括：

- 固定 `ripgrep` Backend 的 Tool Surface Pilot；
- Windows/WSL 文件、文本和 SQLite FTS5 搜索；
- ripgrep、ast-grep、Python AST 结构查询；
- WebFetch、HTML 抽取、Playwright 浏览器渲染；
- API 分页、gzip、redirect、429、500、连接池和并发。

文档入口：

- [`docs/research/README.md`](docs/research/README.md)
- [`docs/research/全面评测计划.md`](docs/research/全面评测计划.md)
- [`docs/research/扩展评测阶段结果.md`](docs/research/扩展评测阶段结果.md)

历史 Phase 0 数据在修正 regex 判题后为：

| Tool Surface | 成功率 |
|---|---:|
| Dedicated `glob/grep/read_file` | 87.5% |
| Shell Only | 70.8% |
| Minimal Router | 50.0% |

这只说明 Tool Surface 是重要变量，不代表完整 Tool 方案排名。

## 目录

```text
benchmark/
  config.json
  data/                 # 固定测试集和 ground truth
  results/              # 本轮原始结果与汇总
  scripts/              # 数据生成、跑测和分析
docs/research/          # 调研与最终报告
```

## 复现

需要 Python 3.12、Node.js、Git 和 ripgrep。

```powershell
npm install --no-save @ast-grep/cli
python benchmark/scripts/prepare_dataset.py
python benchmark/scripts/microbench.py --repeats 12
python benchmark/scripts/agent_eval.py --repeats 2
python benchmark/scripts/analyze.py
```

Agent 跑测需要在本地 `.env` 中配置：

```text
ANTHROPIC_API_KEY=
AGENT_BASE_URL=
AGENT_MODEL_ID=
AGENT_INPUT_COST_PER_MILLION_TOKENS=
AGENT_OUTPUT_COST_PER_MILLION_TOKENS=
AGENT_MAX_COST_USD=
```

`.env`、依赖目录和克隆的被测仓库不会提交到 Git。
