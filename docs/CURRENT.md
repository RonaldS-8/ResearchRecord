# 当前研究 · 工具故障后的路径恢复

**2_010 续跑已完成。** 公开样例无图 15/20、发布自动图和金图各 19/20。已见 M4 原生停止，强规则、人工路线、自动图及带验证自动图均严格通过。规则与自动图提示相同。详见 2_010 方法复现审查和 resumed.json。以下暂停说明保留为历史。

## 暂定科研问题

工具调用失败后，Agent 能否根据公开工具合同和已完成步骤自动找到多步替代路径，用实际执行证据核验路径是否满足剩余用户义务，并在适用条件成立时复用经验？优先借鉴 ToolAtlas 的执行经验复用与 GOAT 的依赖验证，在故障恢复场景中检验其适用性。研究定义待确认。

## 新方向索引

新方向从 `2_001` 编号。原 Gate 编号保留在实验登记、源码、结果和引用中，便于按原记录追溯。

| 新编号 | 原 Gate | 证据与局限 |
| --- | --- | --- |
| `2_001` | 053 | 近邻对照提出义务等价、故障下的有效性与写入安全。057–058 进一步核对了执行筛选和经验复用的先例。 [近邻报告](reviews/053-route-discovery-neighbours.md) |
| `2_002` | 054 | 原生工具池是有效路径的并集，集合差找回 400/400。C3 加入同领域干扰工具后，规则 Recall@3 约为 0.37–0.40。 [登记与结果](experiments/054-route-discovery-recall.md) · [原生任务核对](evidence/054/native-tasks.json) |
| `2_003` | 055 | 测试 Recall@3 为规则 B1 38.24%、4B 重排 L 47.06%、4B 直接提案 P 40.20%。L 有 45/200 次截断。冻结判定不确定，端到端恢复尚待验证。 [登记与结果](experiments/055-route-judge-4b.md) · [GPU 验收](reviews/055-route-judge-gpu-acceptance.md) |
| `2_004` | 056 | 选题草案提出恢复时的多步路线发现与选择。 [选题草案](reviews/056-topic-proposal-draft.md) |
| `2_005` | 057 | 在已见的 200 条查询中，54 条缺候选，25 条候选覆盖但回答被截断，31 条有效回答漏选，90 条命中。合并 P 候选再按合同重排的探针为负结果。部分候选仍需执行才能判定义务等价。 [登记](experiments/057-route-audit.md) · [决策报告](reviews/057-route-discovery-decision.md) |
| `2_006` | 058 | 14 个候选中，局部义务检查接收 2 个、拒绝 8 个、保留 4 个未知。单次复用调用从 8 次降至 2 次，但对照有冗余，且复用限于相同接口和商品。组合预留与直接预留的可见状态不一致，订单和发票缺少持久状态证据。 [登记与结果](experiments/058-execution-memory.md) · [审查](reviews/058-execution-memory-review.md) |
| `2_007` | 059 | 106 次顶层工具调用、0 次模型请求。实际反馈使两条预留路线从未知转为可确认。证据记忆与同样重查库存的普通缓存持平。证据限于会话内预留。运行 `820fd9a`，结果 `bc796e4`。 [登记与结果](experiments/059-dynamic-execution-evidence.md) · [审查](reviews/059-dynamic-evidence-results.md) · [摘要](evidence/059/summary.json) |
| `2_008` | 060 | 八回合真实 Agent 自检中，局部业务验收 7/8、严格验收 1/8。发现组与规则组持平，发现增量仍不确定。独立复核见原分支 `gate059-dynamic-evidence` 的 `b3a226c`，登记 `docs/experiments/060-agent-route-smoke.md`，审查 `docs/reviews/060-agent-route-smoke-review.md`。 |

## 复用入口

- 候选搜索与离线排序见 [route_discovery.py](../extensions/toolmaze_recovery/route_discovery.py) 和 [route_judge.py](../extensions/toolmaze_recovery/route_judge.py)。审计与执行证据原型见 [057 源码](../extensions/route_audit_057) 、[058 运行器](../extensions/execution_memory_058/run.py)和 [059 库存查询适配器](../extensions/execution_memory_059/adapter.py)。
- ToolMaze 已有 [Agent 接口](../benchmarks/ToolMaze/evaluation/agents)、[ToolExecutor](../benchmarks/ToolMaze/toolmaze/core/executor.py)、[InferenceContext](../benchmarks/ToolMaze/evaluation/core/sandbox.py) 和 [JudgeSystem](../benchmarks/ToolMaze/evaluation/core/judge.py)。严格评分适配及隔离测试入口见[资产分类表](archive/README.md#代码资产)。
- 新模块实际需要时建在 `extensions/route_recovery/`，直接导入或最小复用成熟实现。实验、审查、证据沿用 `docs/experiments/`、`docs/reviews/`、`docs/evidence/`，运行产物写入 Git 忽略的 `results/`。

## 旧研究

旧 Q2 使用 `1_001`～`1_052`，对应原 Gate 001–052。原 Gate 与部分登记文件编号曾错位，按原记录查找。结论、证据和代码入口见 [Q2 归档索引](archive/README.md)。
