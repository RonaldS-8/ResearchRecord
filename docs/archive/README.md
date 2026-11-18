# 旧 Q2 归档索引 · Gate 001–052

以 `d916949` 为索引基线。Gate 001–052 是冻结的研究历史，登记、评审、源码及 Git 历史沿用原路径。编号按文档实际使用的实验号查找，Gate 与实验号曾错位。Gate 053–058 是新方向的冻结预研，入口见[当前研究](../CURRENT.md)。[完整历史交接](handoff-d916949.md)保留基线交接原文，归档副本按新位置调整相对链接。

## 结论与证据

| 阶段 | 结论与适用范围 | 入口 |
| --- | --- | --- |
| 早期观测与诊断 | 受控环境区分公开反馈与隐藏状态；显式诊断、重试和切换均可计费。C2-018 上一位记忆规则在全部 54 个枚举格追平理论最优，复杂信念模型缺少该任务上的增量。 | [实验 001 起](../experiments/001-observability-audit.md) · [诊断 MVP](../experiments/005-diagnostic-mvp.md) · [Belief-SSP](../experiments/010-gate7-belief-ssp-pilot.md) |
| 动作价值与信息价值 | 动作条件恢复价值、VOI（信息价值）和动态故障估计曾在受控任务上验证机制。强规则可覆盖部分收益，历史迁移和续程策略会影响估值。 | [动作条件基准](../action-conditioned-recovery-benchmark.md) · [统计估值与 BTM 可比性](../experiments/013-action-value-and-btm-comparability.md) · [历史偏移](../experiments/016-information-value-under-history-shift.md) · [随机动态环境](../experiments/019-stochastic-dynamic-recovery.md) |
| ToolMaze 真实执行与旧方法比较 | 早期执行资产支持真实调用、独立重放与严格评分。Gate 45 有具体恢复信息的行为信号，统计的独立增量未识别，多隐状态必要性在现有数据下无法检验；Gate 46/47 未由合同澄清解决 M4。 | [真实执行器](../experiments/042-gate42a-real-executor-preparation.md) · [045 结果](../reviews/045-real-agent-method-report.md) · [045-R 复核](../reviews/045r-independent-attribution-audit.md) · [047 结论及证据](../reviews/047-failure-nature-and-q2-decision.md) |
| CPU 余量、止损与 051 | 040/041 中复杂规划相对较强固定规则的节费上界有限。048 的逐格最优规则与跨场景冻结规则余量不同。051 的 CPU 收益主要来自估计故障机制后选规则，未验证真实 Agent 迁移。049 的止损提议与 052 的后续修订均保留。 | [040](../reviews/040-cpu-autoresearch-report.md) · [041](../reviews/041-gate41-report.md) · [048](../experiments/048-completion-headroom.md) · [049](../reviews/049-q2-stop-loss-decision.md) · [051](../experiments/051-history-estimated-recovery.md) · [052](../reviews/052-status-report-and-route-discovery.md) |
| 050 丢回执 | 在已提交但丢回执的固定检查点，两组 BTM 都重复发布。知情条件下可先查后写。结果限于该场景，可为新方向提供写入安全反例。 | [050 登记](../experiments/050-lost-receipt-btm-check.md) · [独立验收与结果](../reviews/050-lost-receipt-results.md) · [哈希索引](../evidence/050/sha256-index.json) |

全量位置见[实验登记](../experiments)、[ADR 索引](../adr/README.md)、[独立审查](../reviews)和[派生证据](../evidence)。旧 ADR 0003–0033 记录方法、环境和评测演进，0001–0002 主要为共享仓库及推理环境决定。云端原始产物按各登记与交接中的 `results/<run_id>/` 和哈希索引定位。基线外的历史分支线索见 [052 的分支表](../reviews/052-status-report-and-route-discovery.md#五github-分支2026-11-15-远端状态)，其中合并和删除建议仅为当时记录。

## 代码资产

| 分类 | 路径 | 边界与复用方式 |
| --- | --- | --- |
| 冻结旧方法 | [action_conditioned_recovery](../../extensions/action_conditioned_recovery)、[toolmaze_belief_ssp](../../extensions/toolmaze_belief_ssp)、[toolmaze_diagnostic_mvp](../../extensions/toolmaze_diagnostic_mvp) | 动作条件估值、动态与多步 CPU 规划、信念状态求解及显式诊断环境。旧执行与测试仍引用其中部分模块。 |
| 冻结旧方法与代理实验 | [toolmaze_recovery](../../extensions/toolmaze_recovery) 中的 `autoresearch*.py`、`multipath*.py`、`completion_headroom.py`、`history_estimation.py`、`gate*.py`；[旧运行与分析入口](../../scripts) | CPU 理论优化、历史估计、HMM、旧基线与 Gate 运行。脚本如 `run_completion_headroom.py`、`run_rule_transfer.py`、`run_history_estimation.py` 和 `run_gate45stats.sh` 留原位。 |
| 旧实验与仍可复用的适配 | [toolmaze_agent_recovery](../../extensions/toolmaze_agent_recovery)，以及 [environment.py](../../extensions/toolmaze_recovery/environment.py)、[tasks.py](../../extensions/toolmaze_recovery/tasks.py)、[families.py](../../extensions/toolmaze_recovery/families.py)、[run.py](../../extensions/toolmaze_recovery/run.py) | 历史 Session、故障夹具、执行与验证适配。按需复用已核对的执行与评分函数。 [Gate 42A 评估适配](../../extensions/toolmaze_recovery/gate42a.py)带旧故障合同依赖。 |
| 冻结新方向预研 | [route_discovery.py](../../extensions/toolmaze_recovery/route_discovery.py)、[route_judge.py](../../extensions/toolmaze_recovery/route_judge.py)、[route_audit_057](../../extensions/route_audit_057)、[execution_memory_058](../../extensions/execution_memory_058) | 公开合同搜索、离线排序、事后审计以及执行证据和局部复用原型。Gate 058 的事后评价器可读取参考路径，须与在线发现及记忆隔离。 |
| 共享执行和测试 | [ToolMaze](../../benchmarks/ToolMaze)、[Agent 评测入口](../../benchmarks/ToolMaze/evaluation/scripts/run_eval.py)、[根测试目录](../../tests) | 复用原生执行器、Agent loop、Judge 及独立严格评分适配。保留 [防泄漏](../../tests/test_no_leakage.py)、[路线发现](../../tests/test_route_discovery.py)、[排序](../../tests/test_route_judge.py)、[执行复用](../../extensions/execution_memory_058/test_checks.py)测试。 |
| 后续新模块 | `extensions/route_recovery/` | 按需建文件，优先直接导入成熟函数。避免经由旧方法运行器引入 ACV（动作条件价值）或 HMM（隐马尔可夫模型），沿用共享执行与评分设施。 |

## 目录依赖与验收

- `route_discovery` 依赖 PyYAML，`route_judge` 和 057 主要审计入口依赖 `route_discovery`。058 运行器走原生 `ToolExecutor`、`InferenceContext` 和公开合同加载，局部义务检查与事后评价分开。上述新方向入口的导入链无需旧 ACV 或 HMM。在线发现可复用 `Deriver` 和公开合同加载，离线真值构建用的 `task_queries` 与 `substitutes` 留在评测侧。
- `toolmaze_recovery/environment.py` 和 `run.py` 仍引用旧 `toolmaze_agent_recovery`；后者的若干模块和 `test_no_leakage.py` 使用旧诊断环境。旧 BTM 指导从 `action_conditioned_recovery` 复用，HMM 仍由旧实验导入。保留这些路径。
- `057/search_audit.py`、`057/secondary.py` 和 `058/evaluate.py` 是含顶层读写的事后脚本，前缀分别为 `extensions/route_audit_057/` 和 `extensions/execution_memory_058/`。后续入口应复用可安全导入的函数，避开这些脚本。

本轮在 LabServer 的独立 `d916949` 工作树用 Python 3.10.12 做 CPU 检查。73 个模块成功导入，76 份非测试 Python 源码通过语法检查，含上述三个事后脚本。路线发现与排序 16 项、执行适配 9 项、防泄漏 5 项、旧动作条件恢复与 058 检查合计 55 项均通过。根测试共 280 项，旧 048 的 `test_vote_class_never_beats_the_optimum_in_round_two` 在基线上断言失败。另有 4 项稳定性测试初次缺少 Gate 005 的云端夹具，在独立工作树补入既有夹具后，该套件 11 项全部通过。

首轮批量导入误执行了上述三个脚本的顶层代码。057 搜索审计被重跑，重写的摘要仅耗时发生变化，已用冻结副本恢复原始字节。057 录制诊断与 058 摘要重写后的内容分别与原清单和 Git 冻结证据一致，三个文件的修改时间已改变。复核通过 057 清单中的全部六项产物哈希及 058 的原始结果哈希。后续检查跳过三个脚本的导入。Gate 059 未启动。

## AGENTS.md 待确认修改

- §1 的核心问题、诊断定义及动作条件估值以 Q2 为中心。待确定新主线的剩余义务、候选路径、执行证据和经验复用边界。
- §1 的 Benchmark、竞争解释和对照仍以诊断决策为主。待确定 ToolMaze 状态语义、义务验收、适用性与失效、强静态和成熟路线方法的对照，以及严格完成和构建／在线成本口径。
- §2–3 仍引用 Q2 的 HMM、ACV、Oracle 或诊断相关实验约定。待核对新方向的冻结边界、引用历史的权限、留出单位、禁泄漏与实验准入规则。
- 根 [README.md](../../README.md) 首段仍将 Q2 称为当前问题。正式定义获确认后同步更新并链接 [CURRENT.md](../CURRENT.md)。
