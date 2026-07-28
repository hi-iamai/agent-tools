# Agent Tools Research and Benchmark

Agent 底层 Tool 方案调研、可复现测试集、Backend 微基准，以及固定模型下的 Tool Surface 对比实验。

## 核心结果

在同一模型和同一 `ripgrep` backend 下，本轮 Windows 本机实验结果为：

| Tool Surface | 成功率 | 中位时延 | 中位工具调用 |
|---|---:|---:|---:|
| Dedicated `glob/grep/read_file` | **91.7%** | **12.52s** | **2.5** |
| Shell Only | 75.0% | 14.01s | 3.0 |
| Minimal Router | 50.0% | 18.43s | 5.5 |

详细方法、限制和建议参见：

- [`docs/research/agent_tool最终报告.md`](docs/research/agent_tool最终报告.md)
- [`docs/research/tool调研.md`](docs/research/tool调研.md)
- [`docs/research/tool调研2.md`](docs/research/tool调研2.md)

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

