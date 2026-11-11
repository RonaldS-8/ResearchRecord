# 实验 035 · Gate 33 建议与强制分离、首动作分配

2026-11-11。探索性开发实验，见 [ADR-0032](../adr/0032-advice-enforcement-and-first-action-assignment.md)，承接 [实验 034](034-sequential-recovery-decision.md)。Q2、诊断与 $Q^\pi(h,a)$ 沿用 AGENTS.md。登记时 main 为 `f832f84`，`Dependence` 为 main 加 6 个只改 `CLAUDE.md` 的提交。本机不运行模型；模型回合由云端终端按本文执行。

## 预登记

**问题。** 写入超时、查询确认无记录之后：

1. 如果“重新预留”确实被执行，模型能否绑定合法参数，并在之后自主完成复核和答复。
2. 不删工具、只把规则的建议写进提示，模型是否照做。
3. 规则选中的工具被强制执行时，简单规则能否完成两种隐藏情形。

**假设与可证伪标准。**

- H1：在 `confirmed_absent` 检查点强制 `reserve_stock` 后，模型给出被执行器接受的调用，之后自主调用状态复核并作答，回合严格完成。若调用被拒绝，瓶颈在参数绑定；若写入成功但未复核或提前作答，瓶颈在续程。两种情况都判 H1 不成立并分别记录。
- H2：`advice_only` 在 `not_found` 后仍与 `react` 一样停止，在 `found` 后完成。若 `not_found` 后模型照建议重新预留并完成，则 H2 不成立，说明在这条谱系上一句建议就够。
- H3：强制执行的 `simple_feedback` 在两种隐藏情形下都严格完成。若任一未完成，记录失败发生在绑参还是续程。

**竞争解释。** 强制请求下模型不经推理直接生成参数，可能填错证据引用；建议文字本身改变了模型行为，与建议内容无关；模型停止是因为把“无记录”理解为任务不可完成，与工具选择无关；强制成功只是因为这条谱系的正确路径唯一。

**范围。** 只用已多次使用的 `stock-write-recovery`，隐藏情形 `write_not_committed` 与 `write_response_lost`。全部回合属于同一基础任务 stock-reservation、同一实现 depot-physical-stock-v1、同一故障谱系 ambiguous-write，并共享同一段脚本前缀和同一次强制的首次查询。它们是同一组开发观察，不构成独立样本；不报告比率、区间或显著性，也不据此估计任何动作的成功概率。发布家族只做 CPU 验证，不跑模型。不含 BTM、动作记忆或估值方法。

**固定条件。** Qwen3-4B-Thinking-2507，修订 `768f209d9ea81521153ed38c47d515654e938aea`，vLLM 现有服务配置，temperature 0，seed 3301，每请求最多 6144 输出 Token，每回合最多 12 次 SDK 请求，工具预算 16（含前缀 2 次）。每回合都从“库存读取成功、预留请求超时”的前缀恢复，首次模型请求用 `tool_choice` 限定 `lookup_reservations_by_request`，与 Gate 32 相同。

**回合表，固定顺序，共 8 回合，上限 96 次 SDK 请求。**

| 序号 | 做法 | 隐藏情形 | 分配 |
| ---: | --- | --- | --- |
| 1 | `react` | `write_not_committed` | 无 |
| 2 | `react` | `write_response_lost` | 无 |
| 3 | `advice_only` | `write_not_committed` | 无 |
| 4 | `advice_only` | `write_response_lost` | 无 |
| 5 | `simple_feedback` | `write_not_committed` | 无 |
| 6 | `simple_feedback` | `write_response_lost` | 无 |
| 7 | `react` | `write_not_committed` | `confirmed_absent` → `reserve_stock` |
| 8 | `react` | `write_not_committed` | `confirmed_absent` → `lookup_reservations_by_request` |

第 1、2 回合重跑 `react`，是为了让三种做法在同一提交、同一种子下对照；Gate 32 的回合不并入本轮。第 5、6 回合的 `simple_feedback` 自本轮起带 `tool_choice` 强制执行，与 Gate 32 中“删工具但不强制”的同名回合是不同条件，同样不合并。

第 7、8 回合是同一检查点上逐一列举的两个分支，分配概率按设计为 1。第 8 回合检验“再诊断一次”是否改变后续动作；诊断费另计。分配为停止没有信息量，不安排。第 5 与第 7 回合在重新预留这一步相同，之后分别由规则强制和模型自主续程，用来对照同一动作在两种续程下的结果，各一次观察。

不按结果补跑、改提示、改任务或换种子。任一回合异常退出时保留失败归档，后续回合照常进行。

**记录与分析。** 每个检查点归档公开历史、阶段、证据允许的动作、未知估值与支持度 0、规则选择与规则方式、是否照规则、分配的阶段与工具与概率、模型实际工具与参数、是否照分配、调用是否被接受、沉没费与实得后续费。回合层面沿用原评分，分列严格完成、非法调用、执行费、诊断费、输入与输出 Token、模型秒、盲重试和重复预留。四类错误分别描述：未选该动作、选了但参数被拒、执行成功但续程未完成、重复副作用。带 `tool_choice` 的请求逐条在 `requests.jsonl` 中核对。

**Go / No-Go。** 工程 Go 的条件：云端全部 CPU 测试与 `test_no_leakage.py` 通过；强制请求确实带 `tool_choice` 且只出现在登记的位置；分配与实际动作如实归档；没有隐藏真值进入上下文或提示。出现泄漏、执行器代办义务、评分或合同被改动则 No-Go。

阶段判断按下表，不改条件追求正结果：

| 观察 | 含义 | 之后 |
| --- | --- | --- |
| H1 成立 | 重新预留可执行，模型缺的是选择这一步 | 可在更多检查点登记分配采样 |
| H1 因绑参不成立 | 强制请求下的参数生成是瓶颈 | 先解决绑参，再谈动作选择 |
| H2 成立且 H3 成立 | 建议不被采纳，强制才有效 | 与用户讨论估值信息的传递形式 |
| H2 不成立 | 一句建议就够 | 这条谱系上简单建议已足够，如实报告 |
| H3 成立 | 强制简单规则解决本谱系 | 如实报告；本谱系对估值方法没有完成率余量 |

## 运行入口

用户 2026-11-11 确认上述回合方案。仅云端，PR 合入 main 后在 `/home/ubuntu/Song/Agent` 执行，先 CPU 后模型。模型步骤要求当前提交与 CPU 通过时的提交相同；vLLM 服务与 Gate 32 一样在脚本外启动和停止，服务日志另存。输出目录已存在时脚本拒绝覆盖。

```bash
bash scripts/run_gate33.sh cpu
```

```bash
bash scripts/run_gate33.sh agent
```

预期：CPU 步骤的 ToolMaze 测试与防泄漏测试全部通过，日志在 `results/035-gate33-cpu-01/`；模型步骤在 `results/035-gate33-agent-01/` 下产生 8 个回合目录，每个含 `config.json`、`requests.jsonl`、`episode.json`。异常退出的回合名记入该目录的 `failed.txt`，其目录保留 `failure.json`，其余回合照常运行。

运行后需核对并写入“结果”一节：

- `requests.jsonl` 中带 `tool_choice` 的请求只出现在三处：每回合的首次查询、`simple_feedback` 规则选中工具的各步、第 7 和第 8 回合进入 `confirmed_absent` 的那一步。
- 每个检查点的规则选择、是否照做、分配、实际调用、调用是否被接受。
- 各回合的严格完成、非法调用、执行费、诊断费、Token、模型秒、盲重试和重复预留。

另有一项不依赖本轮代码、可先行完成：把 Gate 29 与 Gate 32 中三个“查询无记录后停止”回合的模型推理原文摘入对应实验记录，不改原归档。

## 本机验收

预登记提交 `19fea67`，实现提交 `c3a4726`，分支 `gate33-advice-assignment`（`Dependence` 含相同提交），基于 main `f832f84`。本机为 Windows、Python 3.14，无 vLLM、无云端数据，没有模型请求。以下全部是脚本化假客户端的接口见证，不是真实模型的行为或效果样本。

改动：`methods.py` 的上下文重建与简单规则；`run.py` 的合同、`advice_only`、强制请求、首动作分配与归档字段；`tests/test_toolmaze_sequential_recovery.py`；新增 `scripts/run_gate33.sh`。没有改公开工具合同、执行器、计价、评分、原生 Agent 或任何归档。

| 测试文件 | 结果 |
| --- | --- |
| `test_toolmaze_sequential_recovery.py` | 12 项通过（原 8 项，新增 4 项，改 2 项） |
| `test_toolmaze_recovery_mvp.py` | 17 项通过 |
| `test_toolmaze_write_agent.py` | 3 项通过 |
| `test_toolmaze_family_expansion.py` | 12 项中 11 项通过；剩下 1 项是既有的入口测试，本机缺 vLLM 包而报错，改动前同样如此 |

本机未运行、须由云端运行：`test_toolmaze_agent_recovery.py`、`test_toolmaze_recovery_integration.py`、`test_no_leakage.py`。

逐项见证：

- **三种做法的请求。** `react` 的每次请求保留 6 个工具、无 `tool_choice`、系统提示不变。`advice_only` 保留 6 个工具、无 `tool_choice`，系统提示多一句建议。`simple_feedback` 只留规则选中的工具，且请求带指向该工具的 `tool_choice`。三种做法的首次请求逐字段相同。
- **建议未被采纳。** 模型在 `not_found` 后直接作答时，归档记录规则建议 `reserve_stock`、模型实际停止、未照做；没有代办调用，没有实际效果，回合未完成。
- **分配。** `confirmed_absent` 分配 `reserve_stock`：只有该次请求带 `tool_choice`，工具列表和提示不变，之后的请求不带；归档含阶段、工具、`enumerated`、概率 1、已施加、已照做、调用被接受。分配再次查询：第二次进入同一阶段时不再施加，诊断费为 2。
- **未执行的分配不算已执行。** 模型不调用分配的工具时记为未照做；调用了但证据引用是编造的，记为照做但被拒绝，非法调用 1 次、无实际效果；分配的工具不在证据允许集合内时不施加任何约束；阶段未出现时没有任何分配记录。分配与规则组叠加、分配为停止或未知阶段均报错。
- **估值不变。** 所有检查点、所有动作的估值仍为未知、支持度 0、完成率为空，分配回合也是如此。
- **规则。** 查询失败一次后规则选择再查，连续两次失败才停；中途查询恢复则计数清零并继续。
- **发布家族。** 用真实执行器走完两种隐藏情形：超时后为 `commit_unknown`，空列表后为 `confirmed_absent` 并允许重新发布，查到或发布成功后为 `verify_existing` 且不再允许发布，回读吻合后义务解除并严格完成。写法不同的版本号被拒绝，不算无记录的证据。回读的摘要或状态不符时义务不解除。
- **库存判定未变。** 用 4000 条随机调用序列共 20115 个公开历史，对比 main 的原实现与本轮实现，除新增的 `lookup_failures` 字段外输出逐项相同；其中 1252 个历史处于未解决义务，覆盖 7 种不同情形。
- **反向验证。** 去掉 `tool_choice`、把规则改回失败一次就停、把发布回读改用库存字段，对应的断言分别失败。

未验证：真实模型在强制请求下能否写出被接受的参数、之后能否完成复核与答复；`run.py` 的启动入口本机无法执行；`scripts/run_gate33.sh` 只做了语法检查。

## 结果

待云端运行后填写。
