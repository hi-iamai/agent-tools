# Agent 底层热点 Tool 潜在方案补充调研

## 1. 核心修正：不能只比较四个 Tool 名称

`glob`、`grep`、`webfetch`、`websearch` 只是 Agent 暴露给模型的接口名称，不等于底层技术方案。

同一个 `grep` 可能实际使用：

* `rg` 子进程；
* `ugrep` 子进程；
* Shell 组合命令；
* 进程内正则库；
* 常驻索引服务；
* Zoekt；
* AST 搜索；
* LSP；
* 语义检索；
* 多种 Backend 的自动路由。

因此完整调研对象应拆成六层：

```text
Tool Surface
    ↓
Query Planner / Router
    ↓
Search or Fetch Engine
    ↓
Execution Runtime / Transport
    ↓
Result Processing
    ↓
Agent Tool-Use Strategy
```

真正需要回答的是：

1. Agent 应暴露哪些 Tool。
2. 每个 Tool 应使用什么底层引擎。
3. 是否应该建立索引。
4. 是否应该使用结构化代码查询。
5. 是否需要统一路由器自动选择 Backend。
6. Tool 结果应如何截断、去重、排序和分页。
7. Tool 应运行在子进程、进程内、常驻服务还是远程服务中。

---

# 2. Tool 类型需要扩展

## 2.1 P0：基础高频 Tool

第一轮必须纳入：

| Tool         | 主要用途        |
| ------------ | ----------- |
| `list`       | 查看目录直接子项    |
| `glob`       | 按路径模式搜索     |
| `grep`       | 文本与正则搜索     |
| `read`       | 读取单个文件      |
| `batch_read` | 批量读取多个文件或区间 |
| `shell`      | 执行任意本地命令    |
| `web_fetch`  | 获取指定 URL    |
| `web_search` | 搜索互联网       |

不能只测 Glob/Grep，因为真实 Agent 搜索通常是：

```text
Glob/Grep → Read → 再次 Grep → BatchRead
```

结果数量、Read 能力和上下文组织方式，会直接影响 Agent 的总耗时和 Token。

## 2.2 P1：代码智能 Tool

建议作为本轮重点候选，而不是后续附属功能：

| Tool                | 能力          |
| ------------------- | ----------- |
| `symbol_search`     | 按符号名搜索      |
| `go_to_definition`  | 找定义         |
| `find_references`   | 找引用         |
| `workspace_symbols` | 工作区符号索引     |
| `ast_search`        | 按语法结构搜索     |
| `dependency_search` | 模块或包依赖      |
| `call_graph`        | 调用关系        |
| `type_hierarchy`    | 类型继承关系      |
| `repo_map`          | 提取仓库核心符号和结构 |
| `diagnostics`       | 编译器或 LSP 诊断 |

LSP 本身已经定义了 Workspace Symbol 等能力；语言服务器通常还能提供定义、引用、文档符号和代码操作。SCIP 则提供语言无关的代码索引协议，可用于定义、引用和跨仓库导航。

## 2.3 P1：版本控制 Tool

Coding Agent 实际使用频率很高：

* `git_status`
* `git_diff`
* `git_log`
* `git_show`
* `git_blame`
* `git_list_files`
* `git_changed_files`
* `git_search_history`

Git 自身已经维护了文件清单和历史信息。对于受 Git 管理的项目，很多查询没有必要重新遍历整个目录。

## 2.4 P1：网页和文档 Tool

除 WebFetch/WebSearch 外，还应考虑：

| Tool             | 用途                     |
| ---------------- | ---------------------- |
| `browser`        | 访问动态页面和执行交互            |
| `crawl`          | 抓取一个网站或文档站             |
| `site_map`       | 快速获得网站 URL 结构          |
| `extract`        | 从网页提取结构化字段             |
| `pdf_read`       | 读取 PDF                 |
| `document_parse` | DOCX、PPTX、XLSX 等       |
| `api_fetch`      | 调用结构化 REST/GraphQL API |
| `download`       | 下载二进制或附件               |

## 2.5 P2：高级检索 Tool

* `semantic_code_search`
* `hybrid_search`
* `code_graph_query`
* `codeql_query`
* `issue_search`
* `commit_search`
* `package_search`
* `documentation_search`
* `research`
* `subagent_search`

这些 Tool 不一定默认开放给模型，但值得作为复杂任务 Backend 或高级 Tool 使用。

---

# 3. Glob 的潜在方案

## 3.1 方案 G1：语言 Runtime 自带 Glob

候选：

* Node.js/Bun 原生或第三方 Glob；
* Rust `globset`＋目录遍历；
* Go `filepath.WalkDir`；
* 自研 Native Walker。

Bun 当前提供 Native Glob，并支持异步迭代扫描；Rust 的 `globset` 可同时匹配多个 Glob Pattern。

### 优点

* 无子进程；
* 易于取消；
* 可直接流式返回；
* 易于集成权限和工作区边界；
* 可共享 Agent Runtime 的线程池。

### 缺点

* 需要自行处理 `.gitignore`；
* 隐藏文件、符号链接、大小写规则复杂；
* 不同平台语义容易不一致；
* 自己实现通常很难超过成熟工具。

## 3.2 方案 G2：`fd` 或 `bfs`

`fd` 是面向用户体验和速度设计的 `find` 替代工具；`bfs` 是兼容 `find` 表达式、采用广度优先遍历的文件查找实现。

适合测试：

* 文件名查找；
* 路径 Glob；
* 大目录；
* Time to First Result；
* 结果达到上限后的提前退出。

## 3.3 方案 G3：`rg --files`

ripgrep 不仅能搜索文本，也能使用其目录遍历、Ignore 和 Glob 设施列出文件。它默认尊重 Git Ignore，并跳过隐藏文件和二进制文件。

优势是 Glob 和 Grep 可共享：

* Ignore 语义；
* 文件类型；
* 路径过滤；
* 二进制分发；
* 跨平台行为。

## 3.4 方案 G4：VCS 文件清单

候选：

* `git ls-files`
* Git Index 直接读取
* SVN Working Copy Metadata
* Perforce Workspace Metadata

适合：

* 搜索受版本控制的源码；
* 排除 Build、Cache、Generated 等未跟踪目录；
* 快速获得稳定文件集合。

不足是：

* 无法发现未跟踪但对任务重要的文件；
* Submodule、Sparse Checkout 和多仓库场景复杂；
* 不能作为完整文件系统搜索的唯一 Backend。

## 3.5 方案 G5：操作系统文件索引

候选：

* Windows USN Journal＋自建索引；
* Everything Service；
* macOS Spotlight；
* Linux inotify/fanotify＋自建索引。

Windows USN Journal 是 NTFS 的持久文件变化日志，Everything 也基于 NTFS/USN 维护文件名索引；macOS Spotlight 支持索引元数据查询，FSEvents 可监听目录层级变化；Linux 则提供 inotify 和 fanotify 文件系统事件机制。

这类方案适合：

* 超大工程；
* 多工作区；
* 高频文件名查询；
* 文件修改后的增量更新。

但跨平台实现成本较高，应作为独立实验路线。

## 3.6 方案 G6：项目级增量文件索引

维护：

```text
path
extension
size
mtime
language
VCS status
ignore status
module
generated flag
```

更新来源：

* 文件系统 Watcher；
* Git Status；
* 定期一致性扫描；
* 构建系统事件。

这是较有潜力的 Agent 专用方案，因为它可以在文件名查询之外同时支持过滤：

```text
找最近修改的、属于 renderer 模块、不是 generated 的 C++ 文件
```

---

# 4. Grep 的潜在方案

## 4.1 方案 R1：ripgrep

ripgrep 应继续作为无索引文本搜索的核心基线：

* 字面量搜索；
* 正则；
* Ignore；
* 文件类型；
* 上下文；
* JSON 输出；
* 多线程目录搜索。

但必须拆分测量：

```text
rg 本体
+ 子进程启动
+ JSON 生成
+ JSON 解析
+ 上下文整理
+ 结果截断
```

## 4.2 方案 R2：ugrep

ugrep 支持普通、布尔、模糊和多模式搜索，还提供压缩文件、归档和部分文档格式搜索；其 `ugrep-indexer` 可通过索引目录树改善较慢文件系统上的搜索。

值得单独测试的能力：

* 多 Pattern；
* Boolean Query；
* 模糊搜索；
* Archive；
* 大型日志；
* 索引模式；
* 与 Claude Code 类似的使用方式。

## 4.3 方案 R3：`git grep`

适合：

* 已跟踪源码；
* Git 仓库内搜索；
* 基于 Revision 搜索；
* 搜索历史版本；
* 避免扫描无关 Build/Cache。

应重点比较：

* 小型仓库；
* 大型 Monorepo；
* Working Tree；
* 指定 Commit；
* 未跟踪文件存在时的正确性。

## 4.4 方案 R4：进程内正则搜索

可组合：

```text
Directory Walker
+ Ignore Engine
+ Regex Engine
+ Result Stream
```

正则引擎候选：

* Rust `regex` / `regex-automata`
* RE2
* Hyperscan

RE2 面向不可信正则，保证渐近线性匹配时间并允许限制内存；Hyperscan 更适合同时匹配大量正则和流式数据。

适用差异：

| 引擎         | 更适合               |
| ---------- | ----------------- |
| Rust regex | 通用 Agent 文本搜索     |
| RE2        | 用户或模型可提供不可信正则     |
| Hyperscan  | 同时运行大量规则、日志流或安全扫描 |

Hyperscan 不一定适合普通的一次单 Pattern Grep，因此应作为专门实验组，而不是直接替代 ripgrep。

## 4.5 方案 R5：Zoekt 索引搜索

Zoekt 是针对源码设计的 Trigram 索引搜索引擎，支持子串、正则、Boolean Query、多仓库搜索，并利用符号等代码信号排序结果。

重点价值：

* 大型仓库反复搜索；
* 跨仓库搜索；
* 低延迟正则；
* 更好的代码结果排序；
* 常驻服务。

需要测量：

* 首次建索引时间；
* 索引大小；
* 增量更新时间；
* 索引陈旧窗口；
* 查询延迟；
* 未保存文件；
* Generated 文件；
* 查询准确性。

## 4.6 方案 R6：倒排索引或 Trigram 自研索引

可以针对 Agent 场景只维护：

* Identifier；
* Token；
* Trigram；
* 文件路径；
* 行偏移；
* 语言；
* 模块；
* VCS 状态。

优势是可与其他元数据深度融合，缺点是索引正确性、增量更新和资源治理成本很高。

## 4.7 方案 R7：Grep＋结果重排

不修改搜索引擎，只增强结果处理：

```text
rg candidates
    ↓
identifier weighting
    ↓
path relevance
    ↓
symbol relevance
    ↓
context deduplication
    ↓
token-budget truncation
```

近期 GrepRAG 工作表明，简单 Grep 检索仍具有竞争力，但高频标识符噪声、固定截断和重复上下文会影响效果；标识符加权、结构去重和结果重排是值得单独验证的方向。

这可能是投入产出比最高的优化之一，因为它不要求替换成熟搜索引擎。

---

# 5. 结构化代码搜索方案

纯文本 Grep 无法可靠表达：

* 查找某函数的所有调用；
* 找到继承某个接口的类型；
* 找到所有没有 `await` 的特定调用；
* 查找参数顺序满足某结构的函数；
* 查找语义相同但格式不同的代码。

## 5.1 ast-grep

ast-grep 使用 Tree-sitter 将源码解析为 AST，然后按代码结构而不是表面文本匹配，也支持结构化替换和 JSON 输出。

适合作为独立的 `ast_search` Tool：

```json
{
  "language": "typescript",
  "pattern": "console.log($A)",
  "paths": ["src"]
}
```

## 5.2 Tree-sitter Query

Tree-sitter 是增量解析器，可在存在语法错误时继续生成语法树；其 Query 使用 S-expression 模式匹配节点，也可提取定义和引用标签。

潜在实现：

* 每次查询临时解析；
* 文件变化时增量解析；
* AST 缓存；
* 预提取符号；
* 预构建结构索引。

## 5.3 LSP

复用语言服务器能力：

* Definition；
* References；
* Workspace Symbol；
* Type Hierarchy；
* Call Hierarchy；
* Diagnostics。

优势：

* 更接近语言语义；
* 不需要自行实现所有语言；
* 可以利用现有 IDE 生态。

问题：

* 不同语言服务器质量差异大；
* 初始化可能慢；
* 大型工程需要完整编译配置；
* 未正确加载 Workspace 时结果可能为空；
* 多语言项目生命周期管理复杂。

## 5.4 SCIP

SCIP 适合将不同语言的代码导航数据统一成稳定索引：

```text
Compiler / Indexer
        ↓
SCIP Index
        ↓
Definition / Reference / Symbol Query
```

它更适合稳定代码库、CI 构建后索引和跨仓库查询，不一定适合每次按键后的最新 Working Tree。

## 5.5 Repo Map

Aider 的 Repo Map 使用 Tree-sitter 提取符号和引用，再构建图并按 Token Budget 选择最重要的仓库内容。

这种 Tool 的目标不是返回所有匹配，而是快速回答：

* 仓库有哪些核心模块；
* 哪些符号最重要；
* 某个文件与哪些部分关联；
* 哪些文件最值得先读。

可设计为：

```text
repo_map
related_files
important_symbols
context_pack
```

## 5.6 CodeQL 或代码数据库

CodeQL 将代码转换为可查询数据，查询可用于安全性、正确性、可维护性和代码质量分析。

它适合：

* 深层数据流；
* 污点分析；
* 安全审计；
* 跨函数关系；
* 复杂静态分析。

但不适合作为普通 Agent 每轮都调用的轻量搜索工具，应放入“重型分析 Tool”类别。

---

# 6. 语义代码搜索方案

## 6.1 文件级 Embedding

为每个文件生成：

* 文件摘要；
* 模块职责；
* 主要符号；
* 文本 Embedding。

优点是索引小，缺点是定位不够精确。

## 6.2 Chunk 级 Embedding

按：

* 固定行数；
* 函数；
* 类型；
* AST 节点；
* 语义段落；

进行切分。

需要重点研究：

* Chunk 边界；
* 重叠；
* 代码和注释权重；
* 路径信息；
* 符号信息；
* 增量更新。

## 6.3 Symbol 级 Embedding

索引对象：

```text
symbol name
qualified name
signature
documentation
body summary
file path
callers
callees
```

通常比固定行 Chunk 更适合 Coding Agent，但构建复杂度更高。

## 6.4 Hybrid Retrieval

推荐测试：

```text
BM25 / Trigram
+ Path Match
+ Symbol Match
+ Embedding
+ Graph Proximity
+ Reranker
```

语义搜索不应和 Grep 使用相同任务进行简单排名：

* 精确字符串和错误码：Grep；
* 自然语言概念和职责：Semantic；
* 调用关系：Symbol/Graph；
* 代码形态：AST。

正确的实验目标是判断 Router 是否能选择正确 Backend。

---

# 7. WebFetch 的潜在方案

## 7.1 F1：直接 HTTP Fetch

实现候选：

* curl/libcurl；
* Rust reqwest；
* Node/Bun fetch；
* 语言 Runtime HTTP Client。

返回：

* Raw Bytes；
* HTML；
* Text；
* JSON；
* Header 和状态码。

适用于：

* API；
* 静态页面；
* Markdown；
* 原始 GitHub 文件；
* 已知结构数据。

这是速度和保真度基线。

## 7.2 F2：正文抽取

候选：

* Mozilla Readability；
* Trafilatura；
* 自定义 DOM 清理。

Readability 是 Firefox Reader View 使用的独立正文抽取库；Trafilatura 支持网页下载、正文、元数据和评论抽取，并提供偏 Precision 或 Recall 的配置。

需要比较：

* 正文召回；
* 导航噪声；
* 代码块；
* 表格；
* 链接；
* 标题层级；
* Token 压缩率。

## 7.3 F3：浏览器渲染

候选：

* Playwright；
* Chromium DevTools Protocol；
* Browserless；
* Remote Browser Service。

Playwright 支持 Chromium、Firefox 和 WebKit；Playwright MCP 可以通过结构化 Accessibility Snapshot 向 Agent 提供页面结构，而不必完全依赖截图视觉。

适用于：

* SPA；
* JavaScript 渲染；
* 登录页面；
* 分页；
* 展开区域；
* 点击后加载；
* 表单；
* 动态文档站。

缺点：

* 冷启动慢；
* 内存高；
* 安全边界更复杂；
* 页面 Prompt Injection 风险更高；
* 需要管理 Browser Context。

## 7.4 F4：远程网页提取服务

候选：

* Jina Reader；
* Firecrawl；
* Browserless；
* 其他托管 Reader/Scraper。

Jina Reader 将 URL 转换成适合模型使用的文本，并包含浏览器渲染和正文提取；Firecrawl 提供 Search、Scrape、Crawl 和 Map 等接口，并可以在搜索后直接返回页面内容。

需要测量：

* 延迟；
* 内容保真度；
* 动态页面成功率；
* 缓存；
* 数据隐私；
* 限流；
* 单次成本；
* 页面新鲜度。

## 7.5 F5：模型驱动抽取

流程：

```text
HTML/Markdown
    ↓
Small Model
    ↓
Question-focused Result
```

优点：

* 显著减少上下文；
* 能根据问题提取局部信息；
* 可处理复杂页面结构。

缺点：

* 增加模型延迟和费用；
* 抽取可能遗漏；
* 无法保证逐字保真；
* 不适合作为唯一证据来源。

## 7.6 推荐测试的 Fetch Waterfall

这是一个待验证的架构假设：

```text
1. Structured API
2. Direct HTTP
3. Static Main-Content Extraction
4. Headless Browser
5. Model-Based Extraction
6. Site-Specific Connector
```

只有前一级失败或质量不足时，才进入更昂贵的后一级。

---

# 8. WebSearch 的潜在方案

## 8.1 S1：模型厂商原生搜索

特点：

* 与模型推理深度集成；
* 可能自动选择查询、搜索和引用；
* Harness 开发量低。

问题：

* 可观测性有限；
* Provider 锁定；
* 难以单独控制 Search 和 Fetch；
* 缓存和排序策略可能不透明。

## 8.2 S2：传统 SERP API

将主流搜索引擎结果封装为结构化 API。

重点是：

* 官方来源排名；
* 地域和语言；
* 新鲜度；
* 搜索结果稳定性；
* Query 参数能力；
* 反爬和限流。

## 8.3 S3：面向 Agent 的神经搜索 API

例如 Exa 提供多种延迟和质量档位，并可在搜索后获取页面内容；Tavily 提供 Search、Extract、Crawl、Map 和 Research 类接口。

适合测试：

* 自然语言问题；
* 技术调研；
* 相似页面；
* 直接内容返回；
* 深度搜索。

## 8.4 S4：Search＋Scrape 一体化

Firecrawl、Browserless 等方案可将搜索和页面抓取组合，减少 Agent 自行选择 URL 后再次调用 Fetch 的流程。

需要判断：

* 是否真的降低总延迟；
* 是否抓取了错误结果；
* Top K 抓取带来的费用；
* 内容重复；
* 是否丢失搜索结果元数据。

## 8.5 S5：SearXNG 聚合

SearXNG 支持聚合多个搜索引擎，并可在启用后通过 HTTP 返回 JSON、CSV 或 RSS。

价值：

* 自部署；
* Provider 可组合；
* 可建立缓存；
* 可加入公司内部搜索；
* 降低单一 Provider 依赖。

问题：

* 上游搜索引擎稳定性；
* 反爬；
* 结果质量不稳定；
* 自维护成本；
* 不一定适合高并发商用。

## 8.6 S6：私有搜索索引

适合企业或垂直 Agent：

* 官方技术文档；
* GitHub 仓库；
* Issue；
* 内部 Wiki；
* API Reference；
* 已验证来源。

可组合：

```text
Public Search
+ Curated Source Index
+ Internal Search
+ Recency Filter
+ Source Authority Ranking
```

这类方案往往比只换一个公共搜索 Provider 更值得研究。

---

# 9. Tool 的运行形态

同一个 Engine 需要在不同运行形态下测试。

## 9.1 每次启动子进程

```text
Agent → Spawn rg → Result → Exit
```

优点：

* 实现简单；
* 崩溃隔离；
* 复用成熟 CLI。

缺点：

* 高频短查询受到 Spawn 影响；
* Windows 开销可能更明显；
* 取消和子进程树清理复杂。

## 9.2 持久 Shell

```text
Agent → Persistent Bash/PowerShell → Commands
```

适合 Shell 中心型 Agent。

需要研究：

* 状态污染；
* 当前目录；
* 环境变量；
* 长期运行内存；
* 命令并发；
* 命令边界；
* Shell Injection。

## 9.3 进程内 Library

```text
Agent Runtime → Search Library
```

优点：

* 低调用成本；
* 直接流式返回；
* 取消、Deadline 和内存预算容易控制。

缺点：

* Crash 隔离弱；
* 语言绑定成本；
* 第三方库升级影响 Runtime；
* 长查询可能阻塞执行器。

## 9.4 常驻本地 Daemon

```text
Agent → IPC → Tool Daemon
```

适合：

* Zoekt；
* LSP；
* Browser；
* 文件索引；
* Embedding；
* 多 Agent 共享。

需要比较：

* Unix Socket；
* Named Pipe；
* Local HTTP；
* gRPC；
* 自定义二进制协议。

## 9.5 MCP STDIO

MCP STDIO 由客户端启动 Tool Server 子进程，并通过标准输入输出交换 JSON-RPC 消息。

适合：

* 第三方 Tool 插件；
* 跨 Agent 复用；
* 本地权限隔离；
* 独立升级。

但 MCP 协议不会自动解决：

* Tool 本身性能；
* 结果过大；
* 取消不及时；
* Tool Schema 设计错误；
* 索引陈旧。

## 9.6 MCP Streamable HTTP

Streamable HTTP 将 Tool Server 作为独立服务，通过 POST/GET 通信，并可使用 SSE 进行流式消息和通知。

适合：

* 远程 Tool；
* 团队共享索引；
* 集中式 Web Search；
* 企业内部数据服务。

## 9.7 Wasm Plugin

可将 Tool 编译为受约束的 Wasm Component 或 Plugin：

* 跨语言；
* 能力授权；
* 资源限制；
* 易于分发。

Wasmtime 可作为 CLI 或嵌入式 Library 使用，WASI 使用能力式权限模型，默认没有环境权限，只有显式授予的 Capability。

需要验证：

* 文件系统遍历性能；
* Regex SIMD；
* 网络访问；
* 启动开销；
* Host Call 数量；
* 大结果传输。

## 9.8 托管 SaaS Tool

适合：

* Web Search；
* Browser；
* Crawl；
* OCR；
* Document Parse；
* Deep Research。

重点不是单次延迟，而是：

* 数据安全；
* 可用性；
* 成本；
* 限流；
* Provider 锁定；
* 是否能回退。

---

# 10. Tool Surface 的四种设计方案

## 10.1 方案 A：Shell Only

模型只有：

```text
shell
read
write
edit
```

Glob/Grep 由模型生成 Shell 命令完成。

### 优势

* Tool 数少；
* 组合能力最强；
* 新命令不需要增加 Schema。

### 问题

* 模型需要知道平台和 CLI；
* 参数和转义错误；
* 权限粒度粗；
* 输出难以统一；
* 跨平台行为不同；
* 不容易稳定截断和分页。

## 10.2 方案 B：窄而专用的 Tool

```text
glob
grep
read
symbol_search
ast_search
web_fetch
web_search
browser
```

### 优势

* Schema 清晰；
* 权限细粒度；
* 结果结构稳定；
* 更容易采集指标；
* 更容易更换 Backend。

### 问题

* Tool 数量较多；
* 模型要选择正确 Tool；
* Tool 说明可能占据较多 Prompt；
* 复杂组合需要多轮调用。

## 10.3 方案 C：统一搜索 Tool

```json
{
  "query": "...",
  "scope": "code",
  "mode": "auto"
}
```

内部 Router 选择：

* Glob；
* Grep；
* Symbol；
* AST；
* Semantic；
* Index。

### 优势

* 模型侧接口简单；
* Backend 可以持续演进；
* 可以自动进行混合召回。

### 问题

* 内部行为不透明；
* Router 错误难以纠正；
* 权限和成本难预测；
* Benchmark 不容易解释；
* 模型无法明确表达必须使用哪类检索。

## 10.4 方案 D：专用 Tool＋自动 Router 混合

同时提供：

```text
glob
grep
symbol_search
ast_search
search_code(mode=auto)
```

简单任务由专用 Tool 完成；自然语言或不确定查询交给 Router。

这是目前最值得作为目标方案验证的一种 Tool Surface，但仍需要通过实验确认 Tool 数量是否增加模型选择错误。

---

# 11. 建议纳入 Benchmark 的候选组合

## 11.1 文件路径组

* Runtime Native Glob
* `rg --files`
* `fd`
* `bfs`
* `git ls-files`
* OS Native Index
* 自建增量文件索引

## 11.2 文本搜索组

* `rg`
* `ugrep`
* `git grep`
* Rust Regex In-process
* RE2 In-process
* Hyperscan 多 Pattern
* Zoekt
* 自建 Trigram Index

## 11.3 代码结构组

* ast-grep
* Tree-sitter Query
* LSP
* SCIP
* Repo Map
* CodeQL

## 11.4 语义检索组

* File Embedding
* Chunk Embedding
* Symbol Embedding
* Lexical＋Embedding
* Lexical＋Embedding＋Graph
* Hybrid＋Reranker

## 11.5 WebFetch 组

* Raw HTTP
* HTTP＋Readability
* HTTP＋Trafilatura
* Playwright
* Playwright MCP
* Jina Reader
* Firecrawl
* Browserless
* Model Extraction

## 11.6 WebSearch 组

* 模型原生搜索
* 传统 SERP API
* Exa
* Tavily
* Firecrawl Search
* Browserless Search
* SearXNG
* 私有文档搜索
* Public＋Private Hybrid Search

## 11.7 运行形态组

* Per-call Process
* Persistent Shell
* In-process Library
* Local Daemon
* MCP STDIO
* MCP Streamable HTTP
* Wasm Plugin
* Hosted SaaS

---

# 12. 新增的关键性能指标

原方案中的延迟、CPU、内存和正确性仍然保留，但索引与高级搜索方案需要增加以下指标。

## 12.1 索引指标

* 首次构建时间；
* 索引体积；
* 增量更新时间；
* 从文件修改到可搜索的延迟；
* 重启恢复时间；
* 索引损坏恢复；
* 索引版本兼容；
* 每 GB 源码索引成本；
* 多工作区共享率；
* 陈旧结果率。

## 12.2 Router 指标

* Backend 选择准确率；
* 不必要的昂贵查询比例；
* Fallback 次数；
* Router 自身延迟；
* Router Token 消耗；
* 自动模式与模型显式选择的差异；
* 错误 Backend 导致的任务失败率。

## 12.3 结果处理指标

* 原始命中数；
* 去重后结果数；
* 返回 Token；
* Relevant Result Recall；
* Top 10 有效结果数；
* 首条有效证据延迟；
* 重复上下文比例；
* 截断造成的关键证据丢失率；
* Continuation 使用率。

## 12.4 Tool Surface 指标

* Tool 选择正确率；
* 参数错误率；
* 无效调用率；
* Shell 转义错误率；
* Tool Schema Token；
* 为完成任务所需调用轮次；
* 模型是否能意识到结果被截断；
* 模型是否会主动切换搜索方法。

---

# 13. 建议优先验证的八条路线

## 路线 1：Shell 基线

```text
shell + rg + fd + curl
```

代表 Codex/终端 Agent 式自由组合能力。

## 路线 2：专用 CLI Tool

```text
glob(fd/rg)
grep(rg/ugrep)
web_fetch(curl + extractor)
web_search(provider)
```

代表 Claude Code、Pi、OpenCode 等专用 Tool 思路。

## 路线 3：进程内基础 Tool

```text
native walker
ignore engine
regex engine
HTTP client
HTML extractor
```

用于测量消除子进程后的收益。

## 路线 4：常驻搜索服务

```text
file index
Zoekt
LSP
AST cache
```

用于大型代码库和连续任务。

## 路线 5：代码智能组合

```text
grep
+ ast-grep
+ LSP/SCIP
+ repo map
```

判断结构化 Tool 是否降低 Grep 和 Read 次数。

## 路线 6：混合搜索 Router

```text
exact query    → grep
path query     → glob/index
symbol query   → LSP/SCIP
structure      → AST
natural text   → semantic
```

主要评估 Router 准确率和端到端收益。

## 路线 7：Web Fetch Waterfall

```text
HTTP
→ Extractor
→ Browser
→ Model Extraction
```

避免所有 URL 都直接启动浏览器。

## 路线 8：Search＋Fetch 一体化

比较：

```text
Search → Agent 选 URL → Fetch
```

与：

```text
Search Provider 直接返回页面正文
```

观察总耗时、证据质量、Token 和抓错页面的比例。

---

# 14. 当前最重要的待验证假设

## H1：`rg` 不一定是整体瓶颈

在普通代码库中，真正占成本的可能是：

* Process Spawn；
* 大量结果序列化；
* 重复 Read；
* 上下文拼接；
* Token 截断；
* Agent 重复搜索。

因此必须同时测 Engine 和完整 Tool Adapter。

## H2：结果重排可能比更换 Grep 引擎更有价值

路径、符号、标识符频率和上下文去重，可能显著提高 Top K 质量，减少后续 Read。

## H3：索引方案只在一定查询密度后有收益

必须计算：

```text
索引构建成本
+ 增量维护成本
+ 查询节省
```

不能只比较 Warm Query 延迟。

## H4：不同搜索能力不是互相替代关系

* Glob 解决路径；
* Grep 解决文本；
* AST 解决结构；
* LSP/SCIP 解决语言语义；
* Semantic Search 解决自然语言；
* CodeQL 解决重型程序分析。

最终更可能是分层组合，而不是单引擎统一替换。

## H5：WebFetch 应按成本递进

绝大多数静态技术文档不需要浏览器；动态页面则不能只靠 HTTP＋HTML 清理。

## H6：Agent 最终表现取决于 Tool Surface

即便 Backend 相同：

* Shell；
* 专用 Tool；
* Unified Search；
* Auto Router；

也可能产生不同的调用次数、参数错误和任务成功率。

---

# 15. 对原调研方案的最终调整

原有调研不应只形成：

```text
Codex Glob vs Claude Glob vs Pi Glob vs OpenCode Glob
```

而应形成以下三组正交实验。

## 实验组 A：同一 Engine，不同 Tool Surface

例如全部使用 ripgrep：

* Shell 调 `rg`；
* 专用 `grep` Tool；
* 统一 `search_code`；
* 自动 Router。

回答 Tool Schema 和 Agent 行为问题。

## 实验组 B：同一 Tool Schema，不同 Engine

例如统一 Grep Contract：

* ripgrep；
* ugrep；
* git grep；
* In-process Regex；
* Zoekt。

回答底层实现问题。

## 实验组 C：不同检索层级完成同一真实任务

例如“找出所有注册某类 Tool 的位置”：

* Grep；
* AST；
* LSP；
* SCIP；
* Semantic；
* Hybrid。

回答哪种能力能真正提高 Agent 完成任务的效果。

最终报告应分别给出：

1. **最佳无索引 Backend**
2. **最佳索引 Backend**
3. **最佳结构化代码 Tool**
4. **最佳 WebFetch 路径**
5. **最佳 WebSearch Provider 类型**
6. **最佳 Tool 运行形态**
7. **最佳 Tool Surface**
8. **最佳混合路由策略**

不能再只给出一个笼统的“最快 Tool”排名。
