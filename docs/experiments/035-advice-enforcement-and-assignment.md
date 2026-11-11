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

## 云端复核发现的问题与修复

云端终端在未修改的 PR head `dbb7d19` 上复现了两处缺陷，结论为合并前 No-Go，由用户于 2026-11-11 转达。复现材料是 CPU 接口证人，保存在云端（`edge_repro.py`、`edge-repro.json`），不是真实模型的效果样本。复核时模型请求为 0，未启动服务，未改 main 和 PR head。本机在同一提交上复现了两处，现象与云端描述一致。

**缺陷一：发布家族在回合循环里拿不到合同。** `sequential_contract` 对每个候选合同各调用一次 `set(tool_names)`，而回合循环传入的是生成器。库存候选先把它耗尽，发布候选看到空集，返回 `None`。结果是发布任务经 `run_episode` 运行时检查点为 0 个，而对同一公开历史直接重建上下文是 `commit_unknown`。原有发布测试只传列表，并且绕过了回合循环，所以没有发现。

**缺陷二：规则在已有有效标识时仍因查询失败而停止。** `simple_feedback_action` 把“连续两次查询失败即停”放在所有判断之前。写入超时、查询拿到单一实际标识、之后两次查询失败时，上下文仍是 `verify_existing`，复核工具仍在允许集合内，规则却选择停止；用该标识调用复核工具实际返回 active 并解除义务。两个家族都复现。

**修复，提交 `eb2d109`。**

- `sequential_contract` 入口处只读取一次工具名，各候选复用同一集合。
- 规则的判断顺序改为：预算耗尽即停；已有单一标识则复核，多个则停；确认无记录且证据齐备则重写；其余仍需查询证据的状态才适用失败止损。适用范围已写入 [ADR-0032](../adr/0032-advice-enforcement-and-first-action-assignment.md) 的修订说明。规则的输出只在“已有单一标识之后连续两次查询失败”这一种历史上与修订前不同。
- 排查同类问题时另改一处：规则包装原先在构造时固定合同，默认是库存合同，用在发布任务上会读错字段。现在由回合循环把当前任务的合同和检查点一起交给规则。

八回合的回合表、种子、提示文字、强制与分配的位置都没有改。

**新增与修改的测试。** `test_toolmaze_sequential_recovery.py` 现为 16 项，全部通过：

- 合同选择对列表和生成器给出相同结果，覆盖全部任务家族。
- 发布家族在两种隐藏情形、三种做法下经回合循环运行：每次决策都有检查点，阶段、规则选择、强制请求和工具列表与预期一致，严格完成且只有一条发布记录。
- 两个家族各两种来源的标识（查询返回、重新写入的回执）：之后查询失败 1、2、3 次，规则都选择复核，复核后义务解除并严格完成。仍需查询证据的状态下两次失败照旧停止。预算耗尽优先于已有标识。
- 两个家族共 400 条随机公开历史上的规则不变量：规则的选择总在证据允许的集合内；允许或选择重新写入时环境中确实没有已提交记录，因此不会造成重复；已知单一标识且有预算时必定选择复核；选择停止只发生在多个标识或“仍需查询且两次失败”时。两个家族都走到了规则的每个分支。
- 启动入口：八个登记回合逐一经 `smoke` 运行，核对请求日志里带 `tool_choice` 的位置。每回合首次查询都带；`react` 与 `advice_only` 之后都不带；`simple_feedback` 在规则选中工具的各步带，最终答复那一步不带；两个分配回合只在进入 `confirmed_absent` 的那一步带。未登记的组合在写入任何文件之前被拒绝。此前“启动入口本机无法执行”的说明由这项测试取代，它用假客户端替换模型并屏蔽 vLLM 版本查询。

**反向验证。** 分别把两处缺陷还原，以及让规则在发布任务上读库存合同，对应的新测试失败；还原前 16 项全部通过。库存任务上与 main 原实现的 20115 个随机历史对比仍逐项相同。

**本机情况。** 其余文件结果不变：MVP 17 项、写入恢复 3 项通过，家族扩展 12 项中 1 项因本机缺 vLLM 包报错。本机 Windows 默认编码为 cp936，启动入口写请求日志时会编码失败，新增的启动入口测试需在 `PYTHONUTF8=1` 下运行；云端为 UTF-8，不受影响。三个改动文件按 Python 3.10 语法解析通过，云端实际运行尚未进行。

**仍未验证。** 真实模型在强制请求下的参数绑定与续程；云端专属的三个测试文件；`scripts/run_gate33.sh`。H1、H2、H3 均未检验。需云端在新提交上复核后，由用户决定是否合并。

## 结果

### 合并与最终云端验收

用户批准修复验收通过后合并和运行。最新 PR head `0d33a0dc8606cb8a3c05c2b97c0671821d69403b` 在独立云端 worktree 通过 **66 项 ToolMaze CPU 和 5 项防泄漏测试**，并用上一轮未修改的 `edge_repro.py` 复核：发布生成器输入正确匹配合同，原生循环产生检查点；库存和发布均在查询两次失败后继续复核先前有效 ID，真实复核返回 active。日志及复现结果在 `results/035-gate33-pr4-review-02/`，原 No-Go 证据仍保留于批次 01。

PR #4 合并提交为 **`d0ea1090a90facbdce5bd5b7295d63c6ea91e7d9`**，GitHub 确认 merged。连接器没有合并权限，使用仓库已有 SSH 权限合并已验收 SHA 并推送。一次合并前入口探测在旧 main 报脚本不存在，未产生正式实验目录或模型请求；正式 CPU 与八回合均只在已合并、两端同步且干净的 main 上运行。合并后再次通过相同 **71 项测试**，日志在 `results/035-gate33-cpu-01/`；运行期间没有修改代码、提示、任务、预算或费用。

### Assigned、Executed 与 Outcome

`results/035-gate33-agent-01/` 保存全部八回合、原始 SDK 请求响应、配置、模型/框架版本、检查点、参数、事件、账本及审计源代码。运行提交均为上述合并提交，Qwen 修订与登记一致；Python 3.10.12、vLLM 0.31.0、OpenAI SDK 3.42.0，温度 0、种子 3301、输出上限 6144、请求上限 12。八回合逐一完成归档，没有异常退出或追加回合。

下表“分配/建议”均发生在共同首次查询之后；首次查询本身在所有回合均受相同外部限制，不称自主诊断。费用为原账本工程单位，执行费包含脚本前缀 2；最后两列是模型消耗，不与工具费合成分数。

| 序号/组别 | 实际诊断返回 | 分配/建议 | 模型随后实际调用及终态 | 严格完成 | 执行/诊断费 | 输入/输出 Token | 模型秒 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| 1 ReAct | not_found | 无 | 停止，未预留 | 否 | 2/1 | 3,469/1,043 | 15.29 |
| 2 ReAct | found | 无 | 用实际 ID 复核并答复 | 是 | 3/1 | 7,278/2,760 | 39.38 |
| 3 advice_only | not_found | 建议 reserve_stock | 未采纳，停止 | 否 | 2/1 | 3,506/1,150 | 16.88 |
| 4 advice_only | found | 建议状态复核 | 采纳，实际 ID 复核并答复 | 是 | 3/1 | 6,213/1,676 | 23.73 |
| 5 simple_feedback | not_found | 强制预留，再强制复核 | 两次调用均由模型合法绑参，完成 | 是 | 4/1 | 7,924/1,762 | 25.23 |
| 6 simple_feedback | found | 强制状态复核 | 模型合法绑定实际 ID，完成 | 是 | 3/1 | 5,692/1,688 | 23.78 |
| 7 原生续程分配 | not_found | 仅强制 reserve_stock | 预留合法，之后自主复核与答复 | 是 | 4/1 | 8,949/1,737 | 25.26 |
| 8 原生续程分配 | not_found | 仅强制再次查询 | 查询合法，仍为 not_found，随后停止 | 否 | 2/2 | 5,975/1,400 | 20.27 |

第 7 回合的 Assigned 为 `confirmed_absent → reserve_stock`、enumerated、设计概率 1；Executed 为模型实际提交 `sku=P-140, quantity=3, evidence_ref=8ad504c68b872be913cad640, request_ref=HOLD-2702`，执行器接受并产生一笔真实预留。随后 SDK 请求已无 tool_choice，模型自主用该次真实预留 ID 调状态工具，再生成答复。该检查点之前的执行/诊断沉没费为 2/1；**从分配动作开始的完整实际后缀为执行 2、诊断 0**。第 5 回合后缀也是 2/0，但后续复核仍被规则强制，二者续程不同，不能混作同一个 Q。

第 8 回合 Assigned 为再次查询，Executed 合法、applied/followed/accepted 均为 true；第二次查询没有新状态证据，模型随后停止。分配检查点实际后缀为执行 0、诊断 1，之前的诊断费未重复计入。其余回合在首次诊断后的实际后缀依序为 0/0、1/0、0/0、1/0、2/0、1/0（执行/诊断）。失败的零执行成本不解释为成功恢复的成本优势。所有条件均可恢复，正确停止率不适用。

共 **24 次 SDK 请求、49,006 输入 Token、13,216 输出 Token、189.82 模型秒**。工具预算、真实模型 Token 和延迟分项保留；未确认模型货币单价，不臆估实际货币费。无请求错误、长度截断、空响应重试、非法调用、盲重试或重复预留。失败的第 1、3、8 回合完整保留，未补跑。服务日志与停止记录在 `results/035-gate33-service-01/`，服务已退出，GPU 回到 464 MiB。

### 核验、解释与阶段结论

`audit.json` 和 `audit_verify.py` 逐 SDK 请求核验：tool_choice 只出现在每回合首查询、第 5/6 回合规则所选工具步、第 7/8 回合首个 confirmed_absent 分配步；后续原生请求未受强制。八个首请求逐字段相同，哈希为 `e5a227c1052115acd5d03f138b7acfc3d000ce7fb5f10650ec44f611e20ea528`。参数、合法性与实际事件对应，工具消息等于真实回执；原评分对归档终态重算无差异，各检查点沉没费与后缀费分账一致。合同、执行器/评分、原生 Agent 与旧防泄漏文件保持 main 基线不变；七个历史停止回合的源文件哈希也再次核对未变。所有动作估值仍 unknown、支持 0，没有将本批结果在线写入估值。

**观察：** 按预登记，本批 H1 的执行条件满足：强制预留后参数合法，原生续程可以完成；H2 所预测的现象出现：无记录后的纯建议未被采纳，found 后完成；H3 的两个登记情形均完成。失败均发生在动作选择/建议未被采纳或重查之后的停止，未观察到参数被拒、成功预留后未复核或重复副作用。第 4 回合采纳建议不能证明建议产生收益，因为同情形原生 ReAct 也会复核。

**解释边界：** 本例无需由执行器代办实参或续程即可完成；至少说明参数绑定与原生续程不是这个强制请求实例的阻断点。它没有证明模型为何自发停止，也没有证明增加估值文字会被采纳。强制请求改变工具选择及参数生成方式，只能称工具级干预 T_a；不能等同于自然选中完整参数动作的效果。第 7/8 回合提供同一公开检查点、同一原生续程下不同工具干预的真实一次分支结果与完整费用，使该观测单位可记录；不足以估计成功概率、期望成本、诊断因果收益、跨模型/任务迁移或统计优势。各次真实 ID 不同但均由本会话合法回执签发，不使用隐藏状态填补 Q。

**Go：工程与真实工具干预机制通过。** 强制简单规则已完成本谱系登记情形，不再在此例扩张估值算法或大规模方法比较。下一 Gate 优先回答一个科学问题：**在独立恢复谱系的合法多检查点上，强简单反馈规则是否仍留有完成质量与剩余成本的决策余量？** 先另行登记独立探索与规则对照，保留负结果；本轮不新建预测器或算法项目。

## 历史停止原因审计（只读，原条件不变）

### 七个历史停止回合

只读提取指定的 Gate 28 四例、Gate 29 一例和 Gate 32 两例。七例最终 SDK 响应都保存了非空 `reasoning` 字段，最终答复与 Agent 历史一致。这里的“推理”仅指实际输出并被 SDK 保存的模型自述，不能据此推测内部原因或作因果证明。完整停止前请求、最终响应、Agent 最后消息、实际回执和源文件 SHA-256 在云端 `results/035-gate33-history-audit-01/extract.json`；提取前后原始 config/requests/episode 文件哈希一致。

七例任务均为 D4、SKU P-140、3 单位、请求号 HOLD-2702。隐藏条件只作归档定位，判断合法动作不使用它。表中两种公开证据状态为：

- **A：提交未知。** 最后返回 `The reservation request timed out. Its outcome is unknown.`。合法恢复为按 HOLD-2702 调用 `lookup_reservations_by_request`；库存读取或连接状态不能证明未提交，没有可见 ID 时不能直接复核。非幂等盲重试不能保证恰好一笔。
- **B：确认无记录。** 最后返回 `request_ref=HOLD-2702, status=not_found, reservation_ids=[]`。可用任务实参和真实库存凭据调用 `reserve_stock`，取得实际 ID 后调用 `get_reservation_status`；也可重查或刷新库存证据。“当前没有 ID”不等于必须停止。

实际 SDK 工具定义证实 Gate 28/29 当时已经公开非幂等写入、超时可发生于提交前后及强一致请求查询。本表没有把后来的合同修订反向套入旧回合。

| Gate / 来源子目录 | 故障条件 | 最后返回 | 停止理由关键原文：最终答复；reasoning | 合法恢复 | 可观察错误类型与边界 |
| --- | --- | --- | --- | --- | --- |
| 28 / checkpoint-not-committed | write_not_committed | A：写入超时 | `no reservation ID available to verify status.`；`So the reservation didn't get created successfully.` | A：先查询 | 选择：未查询即停；自述把未知当未创建，与合同不符；无恢复绑参尝试，缺创建/复核 |
| 28 / checkpoint-response-lost | write_response_lost | A：写入超时 | `no reservation ID was generated to verify its status.`；`The tool response says the outcome is unknown. So the reservation wasn't created.` | A：先查询 | 选择：未查询即停；自述作出未创建断言；恢复绑参未观察，缺复核 |
| 28 / full-not-committed | write_not_committed | A：写入超时 | `no alternative path to verify reservation status.`；`The tools available don't have a way to retry or handle timeouts here.` | A：先查询 | 选择：遗漏公开查询；自述“无路径”与工具清单不符；故障前参数合法，缺创建/复核 |
| 28 / full-response-lost | write_response_lost | A：写入超时 | `no alternative approach exists to complete the task.`；`The tools don't mention retrying or alternative methods, so this is the end.` | A：先查询 | 选择：遗漏公开查询；自述“无替代”与查询能力不符；恢复绑参未观察，缺复核 |
| 29 / assisted-not-committed | write_not_committed | B：not_found | `no reservation ID available to verify status.`；`There's no way to proceed further because the reservation isn't there.` | B：重新预留、复核 | 选择：无记录后仍停；自述将无记录视为无法继续；首查询外部限制、绑参合法，重试未观察 |
| 32 / react-write_not_committed | write_not_committed | B：not_found | `no reservation ID returned to verify status.`；`The tools don't have a way to retry the reservation without another tool call` | B：重新预留、复核 | 选择：未执行可行写入；该句没有证明重试不可行；查询绑参合法，重试/续程未观察 |
| 32 / simple_feedback-write_not_committed | write_not_committed | B：not_found | `no active reservation was established for request HOLD-2702.`；`The user needs to retry the reservation or check if there's another way` | B：规则已选 reserve_stock | 选择/遵从：未调用所选工具；此请求仅保留 reserve_stock，但无 tool_choice；无重试绑参错误可供判断 |

来源：Gate 28 为提交 `25e0e87c8a6f44aed9e2fab00f166a62be05cee6`、`results/030-gate28-agent-01/`；Gate 29 为 `0750c66ff85edcb4aec3dce2ea14430edb6fd1ae`、`results/031-gate29-agent-01/`；Gate 32 为 `4efd6b007245f57bcb4415fff2bdb658c50bdfc6`、`results/034-gate32-agent-01/`。表内子目录分别对应这些原目录，不包括 Gate 29 其他失败回合。

**观察：** 四例停在查询前，三例获 not_found 后仍停止，没有执行后故障重试；“合同理解”仅指可见文本与实际合同不符，“选择”指实际停止而未调用恢复工具，两者不能据自述确定内部因果先后。没有尝试绑参不等于绑参能力通过，缺后续义务也不是已经观察到“正确恢复调用之后执行失败”。**解释边界：** 原系统提示确有“确定无任何可行工具/路径时停止”的条件，但这些文本不能证明该提示导致停止，也不能证明缺少估值是瓶颈。不据此改实验 035 的提示或条件。
