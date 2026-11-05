# 目录管理

两端根目录名称可以不同，内部目录结构相同。以下模型和数据等目录只在云端存在：

```text
Agent/                         # 本地对应 Master_thesis/
├── AGENTS.md                  # 协作约定
├── README.md                  # 项目入口
├── .gitignore                 # 根目录统一排除规则
├── benchmarks/
│   ├── ToolMaze/              # 保留上游源码结构
│   │   ├── evaluation/        # Agent、配置、评测入口
│   │   ├── toolmaze/
│   │   ├── tools/
│   │   ├── data/              # 仅云端，忽略
│   │   ├── git-data/          # 既有数据副本，仅云端，忽略
│   │   └── evaluation/results/# 仅云端，忽略
│   └── CostBench/             # 保留上游源码结构
│       └── env/               # 源码，纳入 Git
│           └── data/          # 仅云端，忽略
├── scripts/                   # 跨 benchmark 或项目级维护脚本
├── extensions/                # 独立实验扩展，不修改 benchmark 原实现
│   └── toolmaze_diagnostic_mvp/ # Gate 3 受控恢复决策环境
├── tests/                     # 项目扩展的必要验证与隔离测试
├── docs/
│   ├── adr/                   # 架构决策记录
│   ├── version-control.md     # 同步步骤
│   └── toolmaze-local-vllm.md  # 模型配置和验证说明
├── models/                    # 仅云端，忽略
├── .venv/                     # 仅云端，忽略
└── logs/                      # 仅云端，忽略
```

## 放置规则

- benchmark 专属代码、配置和启动脚本留在对应 benchmark 内，避免无关重构。
- 项目级维护脚本放 `scripts/`，使用描述用途的名称，不新增 `tmp.py` 一类含糊文件名。
- 说明文档放 `docs/`，长期有效的设计取舍写入 `docs/adr/`，不将每次运行日志写成 ADR。
- 实验结果留在 benchmark 自身已有结果目录；项目级运行日志放 `logs/`。需要分享结论时，在文档中写精简摘要与云端路径。
- 不在根目录堆积结果、临时下载或权重，不给每个子目录单独初始化 Git。
- 数据和模型的下载说明可以进 Git，下载内容不能进 Git；密钥通过环境或未跟踪配置提供。

现有 `toolmaze_audit_report.json` 保留在云端并忽略，未迁移或删除既有运行产物。原根目录 `audit.py`、`tmp.py` 已分别整理为 `scripts/audit_toolmaze.py`、`scripts/download_toolmaze_data.py`；相对路径仍以项目根目录为工作目录，下载脚本只在明确需要下载数据时手动运行。
