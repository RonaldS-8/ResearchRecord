# 当前研究 · 工具故障后的路径恢复

## 暂定科研问题

工具调用失败后，Agent 能否根据公开工具合同和已完成步骤自动找到多步替代路径，用实际执行证据核验路径是否满足剩余用户义务，并在适用条件成立时复用经验？优先借鉴 ToolAtlas 的执行经验复用与 GOAT 的依赖验证，在故障恢复场景中检验其适用性。研究定义待确认。

## Gate 053–058 的证据与局限

| Gate | 已观察到的结果 | 结论边界 |
| --- | --- | --- |
| 053 / 056 | 近邻对照和选题草案提出义务等价、故障下的有效性与写入安全。057/058 进一步核对了执行筛选和经验复用的先例。 | 仍需检验故障恢复场景中的增量。 [053 近邻](reviews/053-route-discovery-neighbours.md) · [056 草案](reviews/056-topic-proposal-draft.md) |
| 054 | 原生工具池是有效路径的并集，集合差找回 400/400。C3 加入同领域干扰工具后，规则 Recall@3 约为 0.37–0.40。 | 原生工具池容易暴露候选。 [054 登记与结果](experiments/054-route-discovery-recall.md) · [原生任务核对](evidence/054/native-tasks.json) |
| 055 | 测试 Recall@3 为规则 B1 38.24%、4B 重排 L 47.06%、4B 直接提案 P 40.20%；L 有 45/200 次截断。 | 冻结判定不确定，离线召回尚未验证端到端恢复。 [055 登记与结果](experiments/055-route-judge-4b.md) · [GPU 验收](reviews/055-route-judge-gpu-acceptance.md) |
| 057 | 在已见的 200 条查询中，54 条缺候选，25 条候选覆盖但回答被截断，31 条有效回答漏选，90 条命中。合并 P 候选再按合同重排的探针为负结果。 | 归因依赖冻结的精确路径评分，部分候选需执行后才能判定义务等价。 [057 登记](experiments/057-route-audit.md) · [决策报告](reviews/057-route-discovery-decision.md) |
| 058 | 14 个候选中，执行与局部义务检查接收 2 个、拒绝 8 个、保留 4 个未知。单次选品复用将顶层调用从 8 次降至 2 次。 | 对照有冗余，且复用在相同接口和商品内。组合预留与直接预留的可见库存状态不一致，订单和发票缺少持久状态证据。 [058 登记与结果](experiments/058-execution-memory.md) · [审查](reviews/058-execution-memory-review.md) |

## 复用入口

- 候选搜索与离线排序见 [route_discovery.py](../extensions/toolmaze_recovery/route_discovery.py) 和 [route_judge.py](../extensions/toolmaze_recovery/route_judge.py)。审计与执行证据原型见 [057 源码](../extensions/route_audit_057) 和 [058 运行器](../extensions/execution_memory_058/run.py)。
- ToolMaze 已有 [Agent 接口](../benchmarks/ToolMaze/evaluation/agents)、[ToolExecutor](../benchmarks/ToolMaze/toolmaze/core/executor.py)、[InferenceContext](../benchmarks/ToolMaze/evaluation/core/sandbox.py) 和 [JudgeSystem](../benchmarks/ToolMaze/evaluation/core/judge.py)。严格评分适配及隔离测试入口见[资产分类表](archive/README.md#代码资产)。
- 新模块实际需要时建在 `extensions/route_recovery/`，直接导入或最小复用成熟实现。实验、审查、证据沿用 `docs/experiments/`、`docs/reviews/`、`docs/evidence/`，运行产物写入 Git 忽略的 `results/`。

## Gate 059 已完成

- 在限定的预留库存场景，实际工具反馈让两条路线从静态 `unknown` 转为可确认。已有公开历史足以判断库存不足时，静态规则也正确拒绝。8 个候选检查和 8 个复用单元共 106 次顶层工具调用、0 次模型请求。
- 证据记忆与同样重查库存的普通缓存决策和成本相同；正常复用也未比首次验证成功即采用的重搜省调用。原生宏和展开调用的可观察差异由独立查询适配器处理，证据限于会话内预留。
- 源码运行提交 `820fd9a`，原结果提交 `bc796e4`。接续时可直接复用 [库存查询适配器](../extensions/execution_memory_059/adapter.py)。[登记与结果](experiments/059-dynamic-execution-evidence.md) · [结果审查](reviews/059-dynamic-evidence-results.md) · [派生摘要](evidence/059/summary.json)

后续 Gate 060 的八回合真实 Agent 自检已在原分支独立归档，提交 `b3a226c`。本次接入范围为 Gate 059。

## 旧研究

Gate 001–052 的结论、证据和代码入口见 [Q2 归档索引](archive/README.md)。
