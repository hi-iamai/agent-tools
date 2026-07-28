# Phase 0：Tool Surface Pilot

本文件用于标记首轮固定 `ripgrep` Backend 的 Agent Tool Surface 消融实验。

完整原始报告保留在：

- [`agent_tool最终报告.md`](agent_tool最终报告.md)

但该报告不再代表项目的最终结论。其有效范围仅为：

- 单一 Django 仓库；
- 单一模型；
- 12 个本地只读任务；
- Shell、Dedicated Tools、最小 Router；
- 三组主要共享 ripgrep Backend。

在修正 regex 判题器后，阶段结果为：

| Surface | 成功率 |
|---|---:|
| Dedicated `glob/grep/read_file` | 87.5% |
| Shell Only | 70.8% |
| Minimal Router | 50.0% |

该实验支持“Tool Surface 会显著影响 Agent 行为”，但不能据此确定完整底层 Tool
组合，也不能外推到 WebFetch、WebSearch、索引、LSP、语义检索或其他模型。

