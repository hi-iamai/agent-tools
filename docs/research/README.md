# Agent Tool 研究文档索引

## 当前状态

项目目标是全面验证 Agent 底层 Tool、Backend、结果处理和运行形态，而不是提前选择一个
默认组合。

当前完成：

- Phase 0：固定 Backend 的 Tool Surface Pilot；
- Phase 1：文件/文本/索引/结构搜索扩展；
- Phase 1：WebFetch、浏览器和 API Fetch 固定 fixture；
- Phase 1：本地 BM25、FTS5、Embedding 和无答案 WebSearch fixture；
- Phase 1：Jedi、Tree-sitter、Ctags 与 regex definition 定位；
- Phase 1：Django、pytest、Black 多仓库检索和 Patch 冲突检测；
- Windows 与 Ubuntu 24.04 WSL1 对照。

仍在进行：

- 公网 WebSearch Provider；
- LSP/Tree-sitter/Ctags/SCIP/Zoekt；
- 索引增量生命周期；
- MCP/daemon/persistent process 运行形态；
- Git/Read/Edit/Patch/Test Tool；
- 语义与 Hybrid Retrieval；
- 多仓库、多语言和修改任务。

## 阅读顺序

1. [`agent_tool全景评测报告.md`](agent_tool全景评测报告.md)
2. [`全面评测计划.md`](全面评测计划.md)
3. [`扩展评测阶段结果.md`](扩展评测阶段结果.md)
4. [`phase0_tool_surface_pilot.md`](phase0_tool_surface_pilot.md)
5. [`tool调研2.md`](tool调研2.md)
6. [`tool调研.md`](tool调研.md)

`agent_tool最终报告.md` 是历史命名，内容属于 Phase 0，不应作为当前最终报告引用。
