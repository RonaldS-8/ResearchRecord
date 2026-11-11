# ADR：架构决策记录

ADR（Architecture Decision Record）记录影响后续工作的重要决策：背景、选择、原因、代价与验证范围。它不替代代码注释、使用手册或实验日志。

| 编号 | 决策 | 状态 |
| --- | --- | --- |
| [0001](0001-single-repository-and-one-side-workflow.md) | 单仓库、云端保留数据、单端修改后同步 | 已接受 |
| [0002](0002-toolmaze-local-vllm.md) | ToolMaze 使用云端本机 vLLM 服务与可配置超时 | 已接受 |

| [0007](0007-gate6-native-recovery-audit.md) | Gate 6 原生恢复回放及分阶段验收 | C3 小样本已获批准 |
| [0008](0008-toolmaze-belief-ssp-pilot.md) | ToolMaze 独立恢复原型与两层放行 | 单任务有条件批准 |
| [0024](0024-agent-recovery-research-design.md) | 统一 Agent 工具故障恢复研究设计 | 已批准审计与最小设计，实施待审 |
| [0025](0025-toolmaze-agent-recovery.md) | ToolMaze Agent 恢复的最小执行切片 | 获准最小实现与 CPU 验收 |
| [0026](0026-toolmaze-recovery-integration.md) | ToolMaze 恢复环境与 Agent 方法接入 | 获准工程与接口验收 |
| [0027](0027-toolmaze-recovery-mvp.md) | ToolMaze-Recovery Benchmark MVP | 已批准最小实现、CPU 验收与冒烟 |
| [0028](0028-agent-write-recovery.md) | 真实 Agent 写入恢复与覆盖设计 | 已批准四回合行为验收 |
| [0029](0029-benchmark-family-expansion.md) | main 的 Benchmark 独立家族扩展 | 工程验收 Go，方法实验暂缓 |
| [0030](0030-public-contract-revision.md) | 公开工具合同修订 | 已批准修订与 CPU 验收 |
| [0031](0031-sequential-recovery-decision.md) | 新反馈后的序贯恢复检查点 | 机制 Go；规则未解决 not_found，方法比较暂缓 |
| [0032](0032-advice-enforcement-and-first-action-assignment.md) | 建议与强制分离、首动作分配 | 工程与工具级干预机制 Go；估值仍 unknown，方法比较暂缓 |
| [0033](0033-decision-tradeoff-lineage-and-strong-baselines.md) | 有决策权衡的恢复谱系与强基线冻结设计 | 提议；设计草案待用户审批，未授权实现或运行 |

新增时复制 [模板](template.md)，使用递增四位编号与描述性英文文件名，并更新此索引。已接受的决策若被替代，保留旧记录，将其状态改为“被 ADR-xxxx 替代”，再新增记录。只纠正事实和补充验证证据，不重写历史理由。

涉及研究方法或实验设计时，还应说明最近邻工作、可证伪假设、关键不确定性及 Go/No-Go 标准；纯工程配置不必扩展成科研实验。
