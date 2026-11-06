# Agent 项目

当前研究问题（Q2）是，工具故障的真实状态不完全可观测时，Agent 如何结合历史恢复经验、当前任务的新反馈与成本信息，选择重试、切换、诊断或停止，在保证任务质量的同时降低恢复开销？研究假设与范围见 [AGENTS.md](AGENTS.md#1-研究目标q2)，阶段进展见 [HANDOFF](docs/HANDOFF.md)。

本地目录：`/Users/ronald/Research/Learning/Agent/Master_thesis`

云端目录：`LabServer:/home/ubuntu/Song/Agent`

两者是同一个项目根目录，内部目录名与相对路径一致。代码开发和实验运行遵循 `AGENTS.md`：运行在云端，本地用于阅读、讲解、计划与版本同步。

- `benchmarks/ToolMaze/`：ToolMaze 源码、配置和模型服务启动脚本。
- `benchmarks/CostBench/`：CostBench 源码；其中 `env/` 是源码目录，不是虚拟环境。
- `scripts/`：项目级维护脚本；原 `audit.py` 整理为 `audit_toolmaze.py`，原 `tmp.py` 整理为 `download_toolmaze_data.py`。从云端项目根目录调用。
- `docs/`：同步和配置说明。

模型权重、数据、虚拟环境、缓存、实验结果和日志只保留在云端，根目录 `.gitignore` 防止它们进入版本管理。代码文件中使用的云端权重路径无需改成本地路径。

2026-11-02 按用户要求移除项目内原有 Git 元数据，改为一个覆盖整个项目的新仓库；旧提交历史不在新仓库中。两端保留同一套新提交历史，不再将两个 benchmark 当作嵌套仓库。

操作说明见 [本地与云端版本同步](docs/version-control.md)、[目录管理](docs/directory-layout.md) 和 [ADR 决策记录](docs/adr/README.md)，本次 ToolMaze 修改见 [模型配置说明](docs/toolmaze-local-vllm.md)。
