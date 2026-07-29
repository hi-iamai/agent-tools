# Agent 底层 Tool 全景评测报告

> 日期：2026-07-29  
> 仓库：Django、pytest、Black 固定快照  
> 环境：Windows Native、Ubuntu 24.04 WSL1（NTFS 与 Linux FS）  
> 数据：`benchmark/results/` 与 `benchmark/results/extended/`

## 1. 结论边界

本报告不寻找一个全局“最佳 Tool 组合”，而是给出已运行方案的：

- 延迟与吞吐；
- Precision/Recall；
- CPU、内存和输出体积；
- 索引构建和增量维护；
- 运行形态；
- 异常和安全边界；
- Agent Tool Surface 行为。

没有实际运行的候选不会填入推测数据。

## 2. 覆盖概览

| Tool 类别 | 已运行方案 |
|---|---|
| 文件发现 | `rg --files`、`git ls-files`、`fd`、GNU find、`os.scandir`、`Path.rglob` |
| 文本搜索 | ripgrep、git grep、ugrep、GNU grep、ag、Python re、SQLite FTS5 |
| 结构搜索 | regex pattern、ast-grep、Python AST |
| 定义定位 | regex、Jedi、Tree-sitter、Universal Ctags |
| 本地 WebSearch | token overlap、BM25、FTS5、BGE embedding、Hybrid RRF |
| WebFetch | requests、HTTPX、aiohttp、curl、wget、六种 HTML extractor |
| Browser | Playwright Core + Edge |
| API Fetch | one-shot/persistent/async Client、分页、gzip、redirect、429、500、并发 |
| Git | status、diff、log、show、blame、changed files、history search |
| Read/Edit/Patch | 文件/范围/batch read、精确替换、unified diff、冲突检测 |
| Runtime | 每次子进程、持久 STDIO、HTTP daemon、MCP STDIO |
| Agent Surface | Shell、Dedicated Tools、Minimal Router |
| 安全边界 | workspace 越界、Shell 网络、删除命令、敏感数据泄露 |

## 3. 文件发现

### Windows

| Backend | 中位时延 | Precision | Recall |
|---|---:|---:|---:|
| `rg --files` | 43.8ms | 98.5% | 99.99% |
| `git ls-files` | 60.4ms | 100% | 100% |
| `os.scandir` | 533.0ms | 100% | 100% |
| `Path.rglob` | 915.0ms | 100% | 100% |

`rg --files` 与全量 oracle 的差异来自 ignore 语义；`git ls-files` 是 tracked-only。
Windows `find.exe` 不是 GNU find，不作为有效候选。

### WSL1

| Backend | NTFS | Linux FS | 主要语义 |
|---|---:|---:|---|
| `git ls-files` | 9.5ms | 10.7ms | tracked-only |
| `fd` | 87.3ms | 103.0ms | ignore/hidden 规则 |
| `rg --files` | 87.5ms | 103.7ms | ripgrep ignore |
| GNU find | 140.5ms | 152.6ms | 全量遍历 |

这是 WSL1，不是原生 Linux 结果。

## 4. 文本和索引搜索

### Windows

| Backend | 中位时延 | Precision | Recall |
|---|---:|---:|---:|
| SQLite FTS5 warm query | **1.44ms** | 99.39% | 99.997% |
| git grep | 137.6ms | 100% | 100% |
| ripgrep | 165.4ms | 100% | 99.998% |
| Python re | 1414.9ms | 100% | 100% |

### Linux userspace 候选

在 WSL1 中，文本扫描整体顺序大致为：

```text
git grep / ripgrep
< ugrep / ag
< GNU grep
< Python 全量扫描
```

具体数值强依赖 WSL 文件系统和缓存。

### FTS5 生命周期

```text
首次构建：4.1s～37.7s（存储位置/缓存差异显著）
索引大小：约 135MB
新增文件可查询：286ms
更新并移除旧结果：225ms
删除并移除结果：214ms
重开数据库：151ms
```

FTS5 是 token/phrase 索引，不等价于 byte literal、regex 或结构搜索。

## 5. 结构与定义定位

### 15 类结构任务

| Backend | Precision | Recall | 中位时延 |
|---|---:|---:|---:|
| Python AST oracle | 100% | 100% | 4032ms |
| ast-grep | 93.4% | 97.8% | 641ms |
| regex pattern | 78.5% | 73.3% | **89.7ms** |

ast-grep 原始 JSON 仍较大，必须裁剪字段和分页。

### 定义定位

| 方法 | Precision | Recall | 中位时延 |
|---|---:|---:|---:|
| Jedi | 100% | 100% | 14.0ms |
| Python LSP definition | 100% | 100% | 6.4ms（初始化约 326ms） |
| regex definition | 100% | 100% | 168.7ms |
| Tree-sitter 全仓冷解析 | 100% | 100% | 3168ms |
| Ctags | WSL 有效；Windows 不可用 | WSL 100% | WSL 每次全仓约 1.8s |

当前符号唯一且定义形态简单；LSP references、workspace symbols、alias 和同名消歧仍需扩展。

### 重型代码索引器

| 方案 | 构建/提取时间 | 峰值 RSS | 产物 |
|---|---:|---:|---:|
| Zoekt | 3.0s | 402MB | 106.5MB |
| SCIP Python | 2m40s | 4.0GB | 83.3MB |
| CodeQL Python database | 1m38s | 1.9GB | 182.9MB |

Zoekt 对三类 literal query 的 Web 查询中位约 2.6～22.2ms，命中数与 oracle 一致。
CodeQL 自定义全函数查询首次编译/执行约 32.5s、峰值约 2.96GB，返回 35,718 行。
官方 Python security-and-quality suite 运行约 4m30s、峰值约 3.9GB，产出 1,336 条 SARIF
结果；分析后的数据库目录增长到约 656MB。
三者服务的层级不同：Zoekt 是高性能代码搜索，SCIP 是语言无关代码导航索引，CodeQL 是
重型程序分析数据库，不能仅按查询延迟排名。

SCIP 索引统计：

```text
documents：2,925
occurrences：770,420
definitions：166,557
```

SCIP CLI 可完成 lint/stats/snapshot，但当前版本没有通用 definition/reference 查询 CLI；
后续需要接入 SCIP 消费者或自建 SQLite/graph reader。

## 6. 本地 WebSearch / 语义检索

固定 8 文档、8 有答案和 1 无答案查询：

| 方法 | Recall@5 | MRR | nDCG@5 | 中位查询 |
|---|---:|---:|---:|---:|
| BGE embedding + 无答案阈值 | 100% | 100% | 100% | 3.58ms |
| Hybrid RRF | 100% | 100% | 100% | 0.01ms（不含子检索） |
| FTS5 | 88.9% | 88.9% | 88.9% | 0.09ms |
| BM25 | 88.9% | 83.3% | 84.8% | 0.13ms |
| Token overlap | 88.9% | 80.0% | 82.1% | 0.06ms |

数据集很小，Embedding 初始化和下载不在单查询时延内。该结果只验证检索链路。

当前配置的 Claude/Bedrock 网关已实测原生 Web Search，HTTP 400 明确表示不支持
`web_search_options`。Tavily、Exa、Brave、Bing 等因无凭证未运行。

### SearXNG 公网聚合

在 WSL1 中以源码方式部署 SearXNG，对 5 个“寻找官方站点”查询重复 3 次：

```text
官方域名 Recall@5：100%
官方域名 Recall@10：100%
中位时延：273ms
```

部分引擎出现 CAPTCHA、429 或 suspended，结果主要由仍可用的 Google CSE、Wikipedia
等引擎贡献。聚合搜索的长期可用性仍依赖上游状态。

## 7. WebFetch 与 Browser

动态页面答案通过运行时 API 加载，原始 HTML 不包含答案。

| 组合 | 平均证据 Recall | 正文 F1 | 中位时延 |
|---|---:|---:|---:|
| aiohttp + Raw | 85.7% | 29.5% | **1.93ms** |
| aiohttp + lxml | 85.7% | 47.7% | 2.02ms |
| requests Session + lxml | 85.7% | 47.7% | 11.47ms |
| HTTPX persistent + lxml | 85.7% | 47.7% | 11.97ms |
| Trafilatura | 85.7% | 51.0% | 约 4～20ms，取决于 Client |
| Playwright + Edge | **100%** | **55.6%** | 540.7ms |

纯 HTTP 对动态页 Recall 为 0，浏览器为 100%。数据支持成本递进 waterfall，但不指定固定
extractor。

## 8. API Fetch

### 分页

| 形态 | 中位时延 |
|---|---:|
| aiohttp | 4.2ms |
| requests Session | 26.4ms |
| HTTPX persistent | 28.3ms |
| requests one-shot | 29.7ms |
| curl 子进程 | 约 51ms |
| HTTPX one-shot | 455.2ms |

### Windows 并发 8 / 16 请求

| 形态 | 吞吐 |
|---|---:|
| aiohttp native async | **1561 req/s** |
| requests Session + threads | 960 req/s |
| HTTPX persistent + threads | 889 req/s |
| curl subprocess | 30 req/s |
| HTTPX one-shot | 23 req/s |

429 已按 Client/repeat 隔离，每个可用 Client 独立经历两次 429 后成功。

## 9. Git、Read、Edit、Patch

### Git

| Tool | 中位时延 |
|---|---:|
| log -20 | 45ms |
| diff | 47ms |
| blame range | 48ms |
| changed files | 61ms |
| status | 71ms |
| show HEAD + stat | 341ms |
| history `log -S` | 716ms |

### I/O

| 操作 | 中位时延 |
|---|---:|
| Python full read | 0.37ms |
| Python range read | 0.45ms |
| Python read 10 files | 1.72ms |
| Python batch read 10 files | 2.32ms |
| Python exact replace | 28.9ms |
| PowerShell replace | 197.6ms |
| PowerShell range read | 275.5ms |

### Patch

| 方式 | 中位时延 | 正确率 |
|---|---:|---:|
| Python exact replace | 2.9ms | 100% |
| git apply | 51.1ms | 100% |
| git apply conflict check | 51.9ms | 100% |

## 10. 运行形态与资源

同一个 Python 全仓 scanner：

| 形态 | 中位时延 |
|---|---:|
| per-call Python | 844ms |
| persistent STDIO | 761ms |
| persistent HTTP | 777ms |

消除启动只节省约 70～80ms，扫描 Engine 才是主要成本。

MCP SDK 2.0 STDIO：

```text
初始化：766ms
list_tools：1.5ms
Tool Call：2906ms
```

MCP 内部使用更慢的 WSL Python scanner，不能把 2.9s 全部归因于协议。

同一 Tool 通过 MCP Streamable HTTP 时：

```text
初始化：329ms
list_tools：8.2ms
Tool Call 中位：2555ms
错误率：0%
```

相同慢速 Engine 下 HTTP 与 STDIO 差异小于扫描成本；若要精确比较协议，需要换成内存或
Zoekt 等快速 Backend。

Windows 资源采样：

| Backend | Wall | CPU | Peak RSS |
|---|---:|---:|---:|
| git grep | 201ms | 414ms | 20.1MB |
| ripgrep | 232ms | 758ms | **13.2MB** |
| Python scan | 1063ms | 1047ms | 25.1MB |
| ast-grep | 1948ms | 4195ms | 35.1MB |

## 11. 多仓库泛化

| 仓库 | ripgrep Recall | git grep Recall |
|---|---:|---:|
| Black | 100% | 100% |
| pytest | 95.6% | 95.6% |
| Django | 66.7% | 66.7% |

低 Recall 来自 ignore/tracked 语义与全量 Python oracle 的差异，不是单纯引擎漏搜。

## 12. Agent Surface Pilot

修正 regex 判题器后：

| Surface | 成功率 | 中位时延 | 中位调用 |
|---|---:|---:|---:|
| Dedicated Tools | 87.5% | 12.52s | 2.5 |
| Shell | 70.8% | 14.01s | 3.0 |
| Minimal Router | 50.0% | 18.43s | 5.5 |

这只是单模型、12 题、只读任务的 Pilot。

## 13. 安全与异常

当前 Adapter 边界测试 5/5 通过：

- workspace 外读取被拒绝；
- Shell 网络访问被拒绝；
- 删除命令被拒绝；
- workspace 内只读命令允许；
- grep 允许；
- 敏感 fixture 无泄露。

这不代表完整沙箱、Prompt Injection 或浏览器安全已经验证。

## 14. 已验证假设

- **H1：rg 不一定是整体瓶颈。** Tool Surface、Client 生命周期和输出处理可产生更大差异。
- **H2：结果处理很重要。** ast-grep 原始输出、git show 和 Raw HTML 都存在大输出问题。
- **H3：索引有查询密度盈亏点。** Warm query 极快，但构建/维护成本显著。
- **H4：检索层级互补。** Grep、AST、Jedi、Embedding 解决不同语义。
- **H5：WebFetch 应按成本递进。** Browser 可补动态内容，但贵两个数量级。
- **H6：Tool Surface 会影响 Agent。** Dedicated Tool 在 Pilot 中优于 Shell 和简单 Router。

## 15. 未运行与限制

| 候选 | 状态/原因 |
|---|---|
| Tavily/Exa/Brave/Bing/SERP API | 无凭证 |
| 当前模型原生 Web Search | Provider 明确不支持 |
| SearXNG | 已完成公网聚合 smoke；上游 CAPTCHA/429 稳定性待长期观测 |
| LSP references/workspace symbols | 已完成 definition；references/workspace symbols 尚未完成 |
| SCIP | 已完成 Python 索引构建；消费/导航查询尚未实现 |
| Zoekt | 已完成索引和 literal 查询；symbol/regex 高级查询待扩展 |
| CodeQL | 已完成 Python database、自定义函数查询和 security-and-quality suite |
| SWE-bench | Docker 已安装但 WSL1 无法启动 OCI 容器 |
| 原生 Linux | 当前仅 WSL1 |
| MCP Streamable HTTP | 已完成；快速 Backend 下的纯协议消融待补 |
| Prompt Injection 红队 | 仅完成命令/路径边界 smoke |

Docker daemon 在 WSL1 中可通过关闭 bridge/iptables 后启动并响应 `docker info`，但
`runc` 启动最小 `hello-world` 容器时因 WSL1 内核 socket/OCI 限制失败。转换 WSL2 又因
宿主 Virtual Machine Platform/固件虚拟化不可用而失败。SearXNG 后续改为源码部署成功；
SWE-bench 等强依赖容器的任务仍无法在当前机器运行。

## 16. 数据使用建议

不要按一列延迟选择 Tool。至少同时查看：

```text
latency
precision / recall
coverage semantics
index lifecycle
output bytes
CPU / RSS
runtime form
failure mode
```

不同 Tool 应作为分层能力，而不是互相替代的单一排行榜。
