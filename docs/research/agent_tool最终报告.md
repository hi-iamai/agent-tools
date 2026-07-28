# Agent Tool 调研、跑测评估与最终建议

> 评测日期：2026-07-28  
> 环境：Windows / PowerShell，本机原生运行  
> 代码仓：Django，固定 commit `5e32c82a5a896e1d942cfc9dd9a2ebbe86741258`  
> 模型：`.env` 中的 `claude-sonnet-4-6`，经 Anthropic-compatible `/v1/messages` 接口调用  
> 原始结果：`benchmark/results/`

## 1. 执行摘要

本轮工作完成了三部分：

1. 在已有两份调研文档基础上，将过大的候选空间收敛为可复现的正交实验；
2. 构建了锁定真实开源仓库 commit 的本地测试集和评测 harness；
3. 实际完成 **312 次 backend 微基准**和 **72 次 LLM Agent Tool Surface 跑测**。

核心结果如下。

### 1.1 推荐默认方案

对于当前在研 coding agent，建议首版采用：

```text
专用 glob + grep + read_file
底层默认 ripgrep
保留受控 shell 作为兜底
结构问题按需增加 ast-grep
暂不把单一自动 Router 作为默认入口
```

原因不是单次搜索速度，而是端到端行为：

| Tool Surface | 成功率 | 中位时延 | P95 时延 | 中位工具调用 | 中位输入 Token | 中位成本 |
|---|---:|---:|---:|---:|---:|---:|
| 专用 Tools | **91.7%** | **12.52s** | **27.02s** | **2.5** | 4,875 | $0.0268 |
| Shell Only | 75.0% | 14.01s | 29.94s | 3.0 | **4,353** | **$0.0238** |
| 单一 Router | 50.0% | 18.43s | 37.10s | 5.5 | 9,665 | $0.0464 |

专用 Tool 相对 Shell：

- 成功率提高 **16.7 个百分点**；
- 中位时延下降约 **10.6%**；
- 中位调用数下降约 **16.7%**；
- 成本略高约 **12.6%**，但每个成功任务的预期成本更有优势。

本轮 Router 是确定性、无额外 LLM 的最小实现。它在路径任务上表现良好，但在 regex 和多步任务中频繁误路由或无法提供后续精确读取能力，12 个失败全部表现为工具预算耗尽或证据不足。因此结论不是“Router 路线无价值”，而是：

> **只有一个自然语言 `workspace_query`，而内部仅做简单词项/路径规则路由，不足以替代显式 `glob/grep/read`。Router 必须支持可解释 backend、精确 regex、读取/分页、fallback、结果重排和状态延续。**

### 1.2 Backend 结果

在本仓库与 Windows 环境中：

| 查询类型 | Backend | 中位时延 | P95 | 备注 |
|---|---|---:|---:|---|
| 文件路径 | `rg --files` | **56.9ms** | **71.0ms** | 直接按 glob 输出，结果体积小 |
| 文件路径 | `git ls-files` + 进程内过滤 | 61.8ms | 83.5ms | tracked-only；CLI 原始清单约 324KB |
| 精确文本 | `rg` | 181.5ms | **234.6ms** | 与 git grep 接近，尾延迟更低 |
| 精确文本 | `git grep` | **178.7ms** | 252.8ms | 中位数略快，差异很小 |
| 正则 | `rg` | 182.0ms | **249.7ms** | 结果与 git grep 相同 |
| 正则 | `git grep -P` | **180.1ms** | 303.9ms | 中位数近似，尾延迟更高 |
| 结构查询 | `rg` 候选词种子 | **105.4ms** | **131.1ms** | 只是候选召回，不提供 AST 精确语义 |
| 结构查询 | `ast-grep` | 720.3ms | 1303.9ms | 约慢 6.8 倍，JSON 结果约 1.6MB |

因此：

- `rg` 与 `git grep` 在普通 tracked 源码文本搜索上属于同一性能量级；
- `git grep` 的核心价值是 **tracked-only 语义与 Git 集成**，不是稳定的大幅提速；
- `rg` 更适合作为默认通用 backend，尤其是要覆盖未跟踪文件、工作区新增文件和统一 glob 行为时；
- `ast-grep` 不应替代 grep，应只在“函数/调用/继承/装饰器等语法结构”任务上按需调用；
- AST 输出必须做去重、字段裁剪、Top-K 和分页，否则结果序列化与上下文成本可能超过搜索本身。

## 2. 研究问题与实验边界

两份前置调研已经指出，不能直接比较“Codex Glob、Claude Glob、OpenCode Glob”这样的产品名称。完整链路至少有：

```text
Tool Surface
→ Planner / Router
→ Backend Engine
→ Runtime
→ Result Processing
→ Agent Strategy
```

本轮采用两组正交实验：

### 实验 A：同一 Agent 模型与 Backend，不同 Surface

- Shell Only：只暴露 PowerShell；
- Dedicated：暴露 `glob / grep / read_file`；
- Router：暴露 `workspace_query`；
- 三组底层词法搜索均使用同一 `ripgrep 15.2.0`。

该实验回答：**Tool Schema 会不会改变 Agent 成功率、调用轮数、Token 与失败模式？**

### 实验 B：相同查询，不同 Backend

- 路径：`rg --files`、`git ls-files`；
- 文本/正则：`rg`、`git grep`；
- 结构：`rg` 候选词搜索、`ast-grep`。

该实验回答：**Backend 本身的时延、结果体积和语义边界是什么？**

### 本轮非目标

以下方向未被声称已经完成全面横评：

- Codex、Claude Code、OpenCode 完整产品排名；
- LSP、SCIP、Zoekt、Embedding、CodeQL；
- WebSearch Provider 和浏览器自动化；
- Linux/macOS 性能；
- 写代码与隐藏测试修复成功率；
- 大规模并发和索引维护成本。

## 3. 测试集

### 3.1 为什么选择 Django

主跑测仓库为 Django：

- 7,077 个 tracked 文件；
- 检出约 47.8MB；
- Python 主导，包含源码、测试、文档、配置和大量跨文件关系；
- 在 Windows 上无需先构建即可完成检索实验；
- 能同时构造路径、精确文本、regex、定义定位和跨文件证据任务。

仓库固定到 commit，避免主分支更新造成行号和 ground truth 漂移。

### 3.2 Agent 测试集

共 12 个只读任务，每题在三个 Surface 上重复 2 次，共 72 runs。

| 类别 | 任务数 | 两次重复后的每 Surface 样本 |
|---|---:|---:|
| 路径/Glob | 2 | 4 |
| 精确文本/定义 | 4 | 8 |
| Regex | 2 | 4 |
| 多步跨文件证据 | 3 | 6 |
| 零命中边界 | 1 | 2 |

Ground truth 使用固定文件、行号、路径前缀和必要概念组合；评分以程序化规则为主，不使用 LLM-as-judge。

### 3.3 Backend 微基准

- 10 个路径/文本/regex query；
- 3 个结构 query；
- 每个 backend/query 组合重复 12 次；
- 合计 312 次。

运行顺序使用固定随机种子打散，以降低热缓存和运行顺序偏差。

## 4. Agent Surface 详细结果

### 4.1 按类别成功率

| 类别 | Shell | Dedicated | Router |
|---|---:|---:|---:|
| 路径 | 100% | 100% | 100% |
| 精确文本 | 75% | **100%** | 75% |
| Regex | 100% | **100%** | 0% |
| 多步任务 | 33.3% | **66.7%** | 0% |
| 零命中 | 100% | 100% | 100% |

### 4.2 Shell Only

优点：

- 最灵活；
- 对简单路径、regex、零命中任务表现良好；
- schema 最小，中位 token 与成本最低。

主要失败：

- 多步任务中容易进行过宽搜索和重复命令；
- 3 个多步 run 达到 9～10 次调用，两个任务直接触发 `max_tool_calls`；
- PowerShell 输出组织不稳定，模型需要自己拼装“搜索—读取—再搜索”流程；
- 两次 QuerySet 任务找到正确定义，但最终证据行号/格式未满足严格评分。

建议：

- 保留 Shell，但不作为基础检索的唯一入口；
- 设置只读/写入命令策略、输出上限和超时；
- 对 `rg`、读取文件、git status/diff 提供专用 Tool，Shell 只承担长尾组合操作。

### 4.3 Dedicated Tools

优点：

- 路径、文本、regex 全部达到 100%；
- 中位 2.5 次调用即可完成任务；
- 三组中端到端成功率最高、时延最低；
- `grep → read_file` 的工具语义清晰，失败更容易归因。

两个失败均来自同一个多步任务：定位 `JsonResponse` 实现与“直接测试该类”的测试文件。模型找到了核心实现，但测试文件证据未满足严格的路径/证据评分。

这说明 Dedicated 的下一步优化重点不是替换 grep backend，而是：

- 搜索结果排序；
- 根据定义自动扩展测试引用；
- batch read；
- 结果 continuation；
- “实现—测试—配置”关系提示或轻量 repo map。

### 4.4 Router

Router 在简单路径任务中有效，但表现明显落后。

失败分布：

- regex：4/4 失败；
- 多步：6/6 失败；
- 文本：2/8 失败；
- 12 个失败中大部分达到 8～10 次 `workspace_query`。

根因：

1. `objective + known_terms + file_hints` 无法稳定表达精确 regex；
2. Router 返回候选匹配，却没有独立读取 Tool；
3. Agent 只能反复改写自然语言目标，形成循环；
4. 简单词项抽取在多步问题中会选择错误 backend/关键词；
5. Router 没有 continuation state、结果去重和 fallback reason。

Router 要进入下一轮，至少应改造成：

```text
search_code(
  mode = auto | path | literal | regex | symbol | structure,
  query,
  path,
  file_glob,
  context_lines,
  limit,
  cursor
)

+ read_file / batch_read
+ strategy trace
+ empty-result fallback
+ broad-result narrowing
```

不要让模型只能通过不断重述自然语言来控制检索。

## 5. Backend 详细分析

### 5.1 `rg` 与 `git grep`

文本和正则中位时延差异不到几个毫秒，不能据此宣称某一个在所有场景更快。更重要的是语义：

| 维度 | `rg` | `git grep` |
|---|---|---|
| tracked 文件 | 支持 | 支持 |
| 未跟踪新文件 | 默认可搜索 | 默认不覆盖 |
| `.gitignore` | 默认遵守 | 基于 Git index/tree |
| 路径 glob | 直接、统一 | pathspec 语义不同 |
| 非 Git 目录 | 支持 | 不适用 |
| Agent 默认工具 | 更合适 | 适合 tracked-only 优化 |

推荐策略：

```text
默认 grep → rg
用户明确要求“只查已提交/被跟踪文件” → git grep
历史版本/commit/tree 搜索 → git grep 或 git show
```

### 5.2 `ast-grep`

本轮 `ast-grep` 的结构搜索显著慢于关键词候选搜索，但二者不能按“同样结果谁更快”简单替代：

- `rg` 返回的是文本候选；
- `ast-grep` 返回的是语法节点，可表达结构约束；
- 本轮宽模式产生约 1.6MB JSON，结果处理成本非常突出。

正确用法应是：

```text
rg 缩小文件/符号范围
→ ast-grep 做结构验证
→ 只返回 path + span + 精简 snippet
```

或对高价值结构问题直接调用 AST，但必须限制路径和 Top-K。

## 6. 失败模式与基础设施观察

### 6.1 API 429

首轮连续运行中，网关在第 40 个任务附近开始大量返回 HTTP 429。初次原始跑测出现 33 个基础设施失败。

Harness 后续增加：

- 429/5xx 指数退避；
- `Retry-After` 支持；
- 任务间 2 秒节流；
- `--resume` 仅补跑基础设施失败；
- 原始成功 run 不被覆盖。

最终 72 个实验 run 均有有效结果。这个过程说明 Agent benchmark 必须把：

```text
模型行为失败
≠ API 限流/基础设施失败
```

严格分开。

### 6.2 最终 JSON 不完全遵守

兼容网关上的模型有时会在 JSON 前添加解释文字或 Markdown。Harness 对最后一个合法 JSON 对象做容错提取，同时保留原始响应。

格式偏差不应直接归因于某个 Tool Surface，但需要单独统计为协议遵守率。

### 6.3 Windows 限制

本报告不能外推到 Linux：

- PowerShell quoting 与 Bash 不同；
- Windows 进程启动成本不同；
- 路径分隔符和长路径行为不同；
- 无法简单宣称是严格 OS cold cache；
- 防病毒/索引服务可能影响扫描。

## 7. 最终架构建议

### 7.1 P0 Tool Surface

推荐暴露：

```text
list
glob
grep
read_file
batch_read
apply_patch
shell
git_status
git_diff
```

其中：

- `glob/grep/read` 是主路径；
- `shell` 是受控兜底；
- 输出统一支持 `limit/cursor/truncated`；
- 所有结果使用相对路径、稳定行号和结构化错误。

### 7.2 Backend Router

Router 不应一开始替代所有 Tool，而应作为内部优化：

```text
path query       → rg --files / git ls-files
literal/regex    → rg
tracked-only     → git grep
structure        → ast-grep
definition/ref   → 后续 LSP/SCIP
natural language → 后续 hybrid retrieval
```

模型仍可显式指定 mode；`auto` 只是默认值。

### 7.3 结果处理

本轮数据支持“结果处理可能比换 grep 引擎更重要”：

- `rg` 与 `git grep` 单次差异很小；
- Dedicated 相同 backend 却显著提高成功率；
- AST 宽查询的 1.6MB 输出会放大上下文成本；
- Router 失败主要来自证据组织与控制面不足。

因此优先投入：

1. 路径和符号相关性排序；
2. 去重；
3. Top-K；
4. 分页/continuation；
5. batch read；
6. 截断显式提示；
7. 搜索策略 trace；
8. 自动从实现扩展到测试/配置。

## 8. 分阶段落地路线

### 第一阶段：立即可用

- `rg` 实现 glob/grep；
- 专用 Tool Schema；
- read/batch_read；
- Shell 只读/写入策略；
- 全量 trace、token、cost、timeout；
- 429 retry 与 resume。

### 第二阶段：代码智能

- `ast-grep` 结构搜索；
- LSP definition/references/workspace symbols；
- Git history/diff/blame tools；
- repo map；
- 对 Dedicated + Router 做新一轮消融。

### 第三阶段：索引和语义

- Zoekt/Trigram 的 break-even query density；
- Embedding + lexical hybrid；
- reranker；
- 索引构建、增量延迟、陈旧结果率和磁盘成本。

### 第四阶段：Web Tool

- HTTP Fetch → Readability/Trafilatura → Browser waterfall；
- Search → Fetch 与 Search+Content 一体化对照；
- 动态页面、PDF、提示注入和引用正确性。

## 9. 结论

本轮最有支撑的结论是：

1. **Agent 工具效果不能只看搜索引擎单次时延。**
2. **在同一模型、同一 ripgrep backend 下，专用 `glob/grep/read` 明显优于 Shell Only 和本轮最小 Router。**
3. **`rg` 与 `git grep` 普通文本搜索性能接近，默认选择应由覆盖语义与集成便利决定。**
4. **AST 是补充层，不是 grep 替代品；其输出处理必须严格受控。**
5. **当前最值得投入的是 Tool Surface 与结果处理，而不是继续寻找一个“更快一点的 grep”。**

最终推荐：

> **以 Dedicated Tools 为默认面、ripgrep 为基础 backend、受控 Shell 为兜底、ast-grep/LSP 为按需增强；Router 先放在内部做可解释路由，待具备 regex、读取、分页、fallback 和策略 trace 后再评估是否收敛成统一入口。**

## 10. 复现文件

- `benchmark/config.json`：仓库 commit 与预算；
- `benchmark/data/agent_tasks.json`：Agent 任务和 ground truth；
- `benchmark/data/micro_queries.json`：backend query；
- `benchmark/data/ast_queries.json`：结构 query；
- `benchmark/scripts/prepare_dataset.py`：数据生成；
- `benchmark/scripts/microbench.py`：微基准；
- `benchmark/scripts/agent_eval.py`：Agent loop、三种 Surface 与评分；
- `benchmark/scripts/analyze.py`：汇总；
- `benchmark/results/microbench_raw.jsonl`：312 条原始微基准；
- `benchmark/results/agent_eval_raw.jsonl`：72 条 Agent run；
- `benchmark/results/summary.json`：最终汇总。

