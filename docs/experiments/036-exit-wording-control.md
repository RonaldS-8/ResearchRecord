# 实验 036 · 退出措辞对照（Gate 33 补充）

2026-11-12。探索性开发实验，承接 [实验 035](035-advice-enforcement-and-assignment.md) 与 [ADR-0032](../adr/0032-advice-enforcement-and-first-action-assignment.md)，不新增 ADR。Q2、诊断与 $Q^\pi(h,a)$ 沿用 AGENTS.md。登记时 main 为 `f4a7140`。

**状态更新（2026-11-12）：用户已在云端验收后正式批准逐字提示、四回合方案及运行。** 早先的“批准文本”随后按用户要求暂记待审批；本次正式授权来自“PR #8 合并与实验 036 执行”指令。以下冻结文本、假设、参数和顺序保持原登记，不追溯修改。

## 预登记

**背景。** 到 Gate 33 为止共有十个“可恢复却停止”的回合：实验 035 审计的七个历史回合，加上 Gate 33 的第 1、3、8 回合。Gate 33 第 7 回合显示，只要“重新预留”被执行，模型能填对参数并自主完成，所以卡点在选动作。但提示里有三句话在告诉模型怎样放弃，历史回合的停止答复与其中的例句措辞相近（“no alternative approach exists”）。如果停止主要来自这三句话，后面所有基线相对 ReAct 的差距都会受它影响，所以在设计 Gate 34 之前先查一次。

这三句话，两句在 ToolMaze 原生的故障感知系统提示里（`benchmarks/ToolMaze/evaluation/agents/openai_agent.py`，本项目不改该文件），一句在我们这层加到任务消息末尾（`extensions/toolmaze_recovery/run.py`）：

1. 系统提示，FAULT HANDLING 段：`- If you determine that a required step cannot be accomplished by any available tool or approach, stop the workflow and clearly report which step failed and why, rather than proceeding with incomplete results.`
2. 系统提示，FINAL ANSWER FORMAT 段：`- If HALTED: State clearly that the task was aborted and the reason (e.g., "Task aborted: the pricing tool returned corrupted data after retry and no other alternative approaches exist"). Do not apologize excessively.`
3. 任务消息末尾：`If unable to complete the task, start your final reply with 'Blocked:' and briefly explain.`

**问题。** 在“写入超时、查询确认无记录”这个检查点，去掉这三句话，模型是否仍然停止。

**假设与可证伪标准。** H：去掉三句话后，模型在 `confirmed_absent` 仍然不调用任何恢复工具就作答结束，即这个检查点上的停止不是由退出措辞引起的。若模型改为重新预留并严格完成，H 不成立。“停止”指 `not_found` 回执之后没有任何被执行器接受的工具调用就给出最终答复。

**竞争解释。** 停止来自模型把“无记录”理解为任务失败，与提示无关；停止来自三句话中的某一句，另外两句无关；去掉措辞后模型不停止，但转为盲目重试、重复预留或耗尽预算；任何对系统提示的改动都会扰动行为，与改动内容无关。

**对照的做法：只删不加。** 对照组把上面三句话原样删除，不添加任何文字。不采用改写，因为任何改写都会带入新的倾向（例如“只有试过所有工具才可以停止”本身就是一条建议），无法与 Gate 33 的 `advice_only` 区分。删除后模型仍然可以随时作答结束，没有被禁止停止。

**两组提示的逐字文本（待审批）。**

原始组 `original`，系统提示：

```text
You are an autonomous AI assistant that executes tool-based workflows. Tools may occasionally fail or return unexpected data.

TASK COMPLETION
- The user query may describe multiple sub-tasks. You must complete ALL of them — do NOT skip any sub-tasks.
- Every fact, data retrieval, or state change must come from a tool call. Never substitute a tool result with internal knowledge, and never report a step as completed unless you actually called the corresponding tool and received its result in this conversation.
- Sub-tasks may be accomplishable through different tool combinations.

FAULT HANDLING
- When evaluating tool outputs, consider whether the returned data is coherent and usable for the next step — fields should be present, values should be semantically reasonable, and types should match what the workflow requires.
- If you determine that a required step cannot be accomplished by any available tool or approach, stop the workflow and clearly report which step failed and why, rather than proceeding with incomplete results.

FINAL ANSWER FORMAT
- Be CONCISE and DIRECT. No emojis, markdown formatting (**, ✅, etc.), or bullet points.
- If SUCCESSFUL: State only essential facts and requested results (e.g., confirmation codes). Omit internal technical details.
- If HALTED: State clearly that the task was aborted and the reason (e.g., "Task aborted: the pricing tool returned corrupted data after retry and no other alternative approaches exist"). Do not apologize excessively.
```

原始组，任务消息：

```text
At depot D4, reserve exactly 3 units of SKU P-140 from available physical stock under request reference HOLD-2702. Check that the reservation is active after creating it. Either an inventory snapshot or an authorized physical count can establish availability.

Tool prices: 1 engineering unit per advertised tool call, including diagnosis and failed calls. If unable to complete the task, start your final reply with 'Blocked:' and briefly explain.
```

对照组 `removed`，系统提示：

```text
You are an autonomous AI assistant that executes tool-based workflows. Tools may occasionally fail or return unexpected data.

TASK COMPLETION
- The user query may describe multiple sub-tasks. You must complete ALL of them — do NOT skip any sub-tasks.
- Every fact, data retrieval, or state change must come from a tool call. Never substitute a tool result with internal knowledge, and never report a step as completed unless you actually called the corresponding tool and received its result in this conversation.
- Sub-tasks may be accomplishable through different tool combinations.

FAULT HANDLING
- When evaluating tool outputs, consider whether the returned data is coherent and usable for the next step — fields should be present, values should be semantically reasonable, and types should match what the workflow requires.

FINAL ANSWER FORMAT
- Be CONCISE and DIRECT. No emojis, markdown formatting (**, ✅, etc.), or bullet points.
- If SUCCESSFUL: State only essential facts and requested results (e.g., confirmation codes). Omit internal technical details.
```

对照组，任务消息：

```text
At depot D4, reserve exactly 3 units of SKU P-140 from available physical stock under request reference HOLD-2702. Check that the reservation is active after creating it. Either an inventory snapshot or an authorized physical count can establish availability.

Tool prices: 1 engineering unit per advertised tool call, including diagnosis and failed calls.
```

两组的工具定义、脚本前缀（库存读取成功、预留请求超时）、首次请求的 `tool_choice`、模型、种子和各项上限完全相同。

**范围与限制。**

- 只用 `stock-write-recovery` 与 `react`，隐藏情形 `write_not_committed` 与 `write_response_lost`，与此前回合同属一个基础任务、一个实现、一条故障谱系。四个回合是同一组开发观察，不构成独立样本，不报告比率、区间或显著性。
- 评分器用答复开头的 `Blocked:` 识别“正确停止”。本对照的两种情形都可恢复，正确停止率不适用，严格完成的判定不受影响。对照组的提示因此不能直接用于含不可恢复情形的正式评测。
- 三句话一起删。若行为改变，本轮不能区分是哪一句起作用。
- 不含建议、强制、分配、BTM 或估值方法；入口拒绝这些组合。

**固定条件。** Qwen3-4B-Thinking-2507，修订 `768f209d9ea81521153ed38c47d515654e938aea`，vLLM 现有服务配置，temperature 0，seed 3301，每请求最多 6144 输出 Token，每回合最多 12 次 SDK 请求，工具预算 16（含前缀 2 次）。每回合首次模型请求用 `tool_choice` 限定 `lookup_reservations_by_request`，与 Gate 33 相同。

**回合表，固定顺序，共 4 回合，上限 48 次 SDK 请求。**

| 序号 | 提示 | 隐藏情形 | 用途 |
| ---: | --- | --- | --- |
| 1 | `original` | `write_not_committed` | 在同一提交下重现 Gate 33 第 1 回合 |
| 2 | `original` | `write_response_lost` | 在同一提交下重现 Gate 33 第 2 回合 |
| 3 | `removed` | `write_not_committed` | 检验 H |
| 4 | `removed` | `write_response_lost` | 副作用检查：原本能完成的情形是否被破坏 |

不按结果补跑、改提示、改任务或换种子。任一回合异常退出时保留失败归档，后续回合照常进行。

**运行后必须核对。**

- 第 1、2 回合的 `first_request_sha256` 等于 Gate 33 归档的 `e5a227c1052115acd5d03f138b7acfc3d000ce7fb5f10650ec44f611e20ea528`。不相等说明原始提示或请求被改动，本轮结果作废。
- 第 3、4 回合的首请求与第 1 回合相比，只少上面三句话，其余字段相同；之后各请求里都不含这三句话。
- 第 1、2 回合的行为与 Gate 33 第 1、2 回合一致（停止、完成）。不一致说明 temperature 0 下仍有运行间差异，配对解释不成立，如实记录。
- 每回合的严格完成、非法调用、执行费、诊断费、Token、模型秒、盲重试和重复预留；`not_found` 之后模型的实际调用与最终答复原文。

**Go / No-Go。** 工程 Go 的条件：云端全部 CPU 测试与 `test_no_leakage.py` 通过，上述哈希与文本核对通过，合同、执行器、评分与原生 Agent 文件未被改动。阶段判断按下表，不改条件追求某个结果：

| 第 3 回合的观察 | 含义 | 之后 |
| --- | --- | --- |
| 仍然停止 | 这个检查点上，去掉退出措辞不足以改变停止 | 原始提示继续作为各基线的共同提示，Gate 34 沿用 |
| 重新预留并严格完成 | 停止对退出措辞敏感，Gate 33 中“ReAct 停止”的结论依赖原始提示 | 正式比较前由用户决定共同提示；是否逐句分离另行登记，不自动运行 |
| 继续调用但未完成 | 去掉措辞把停止换成了其他失败 | 如实记录失败类型，不改提示 |

第 4 回合若未完成，说明删除措辞损害了原本能完成的情形，单独记录。每格只有一次观察，结论只对这个检查点和这组条件成立。

## 运行入口

**待用户正式确认逐字文本与回合方案、云端验收通过、PR 合入 main 之后才可执行。** 仅云端，在 `/home/ubuntu/Song/Agent`，先 CPU 后模型。模型步骤要求当前提交与 CPU 通过时的提交相同；vLLM 服务在脚本外启动和停止，服务日志另存。输出目录已存在时脚本拒绝覆盖。

```bash
bash scripts/run_exit_wording.sh cpu
```

```bash
bash scripts/run_exit_wording.sh agent
```

预期：CPU 步骤全部通过，日志在 `results/036-exit-wording-cpu-01/`；模型步骤在 `results/036-exit-wording-agent-01/` 下产生 4 个回合目录（`original-write_not_committed` 等），每个含 `config.json`、`requests.jsonl`、`episode.json`，其中 `config.json` 的 `exit_wording` 字段标明所属组。异常退出的回合名记入 `failed.txt`。

## 实现

`run.py` 新增 `--exit-wording original|removed`，默认 `original`。`original` 不经过任何新代码路径改动提示。`removed` 在原生 Agent 生成系统提示之后、发出第一个请求之前，把三句话从系统提示和任务消息中删除；任何一句在提示中不是恰好出现一次时直接报错，不会当作已删除继续运行。入口只接受 `stock-write-recovery`、`react`、无分配、从写入检查点恢复并限定首次查询的组合，其余在写入任何文件之前拒绝。`benchmarks/` 下的文件、合同、执行器、评分均未改动。

## 本机验收

2026-11-12，本机只做 CPU 检查，未运行模型。

- `test_toolmaze_sequential_recovery.py` 现为 17 项，全部通过（需 `PYTHONUTF8=1`，原因见实验 035）。MVP 17 项、写入恢复 3 项通过；家族扩展 12 项中 1 项因本机缺 vLLM 包报错，与改动前相同。改动文件按 Python 3.10 语法解析通过。
- **原始提示未变。** 测试经启动入口、用入口自己的模型名与各项上限构造请求，Gate 33 登记的八个回合的首请求哈希都等于云端归档的 `e5a227c1…`。这一条此前无法在本机核对，现在是固定断言。
- **对照只少三句话。** 四个登记回合经启动入口运行：对照组首请求等于原始组首请求删去三句话，其余字段逐项相同；之后每个请求都不含这三句话；`tool_choice` 的位置与原始组相同；`config.json` 标明所属组。三句话在测试里独立逐字写出，不引用 `run.py` 的常量。
- **未登记的组合被拒绝。** 建议组、强制组、带分配、其他任务、非检查点起点、未知措辞名，都在写入文件之前报错。
- **反向验证。** 十处改坏逐一命中：保留任务消息里的那句、保留系统提示里的两句、只删一句系统提示、改写原始提示一个词、入口放行未登记组合、回合循环放行规则或分配、容忍缺失的句子、配置字段写死、把入口或回合循环的默认值改成对照。每一处都有测试失败，还原后 17 项通过。

未验证：云端专属的三个测试文件；`scripts/run_exit_wording.sh` 只做了语法检查；命令行参数的默认值没有测试覆盖，只能在云端运行时由 `config.json` 核对；真实模型在两组提示下的行为。

## 结果

### 合并与工程验收（2026-11-12）

最终 PR #8 head 为 `233ec9e064e7855eee4472de89a9eb604c1e7649`，相比云端验收的 `8d65a8b` 只修改 ADR-0033 与实验 037；实验 036 的代码、冻结提示、测试、模型配置、执行器与评分完全相同，未重复完整 PR worktree 验收。GitHub 首次读取的 mergeable 暂为 false，复查为 true，Git 也确认 main 为 head 祖先、无冲突；随后按用户授权合并。

合并及实际运行提交：**`eb157c878a4ed507112894f863b0ad34910dec87`**。两端 main 同步后，云端工作区干净；本地用户此前要求取回的验收报告保持原样，未加入本轮提交。正式 CPU 目录此前不存在，`scripts/run_exit_wording.sh cpu` 通过 **67 项 ToolMaze 与 5 项防泄漏测试**，`passed-commit.txt` 等于合并提交。配置、Tokenizer 和三片权重的下载修订均与登记一致，没有安装依赖或变更服务参数。

### 四个真实回合

严格按登记顺序执行，模型、温度 0、种子 3301、输出上限 6144、请求上限 12 及工具预算 16 均未改。完整 SDK、配置、检查点、真实事件、账本、最终答复与审计在 `results/036-exit-wording-agent-01/`；CPU 在 `results/036-exit-wording-cpu-01/`；服务日志及停止记录在 `results/036-exit-wording-service-01/`。四回合都形成完整 episode，没有异常退出或追加请求/回合。

| 序号/组别 | 首查询实际返回 | 查询后实际恢复调用 | 严格完成 | 实际义务问题 | 执行费/诊断费 | 输入/输出 Token | 模型秒 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: |
| 1 original / 未提交 | not_found | 无，最终答复 | 否 | 缺预留及复核 | 2/1 | 3,469/1,043 | 14.99 |
| 2 original / 丢写入回执 | found、实际 ID | get_reservation_status，实参合法 | 是 | 无 | 3/1 | 6,392/1,836 | 25.49 |
| 3 removed / 未提交 | not_found | 无，最终答复 | 否 | 缺预留及复核 | 2/1 | 3,788/1,557 | 21.51 |
| 4 removed / 丢写入回执 | found、实际 ID | 无，最终答复 | 否 | 缺实际预留的状态回读 | 2/1 | 4,142/3,030 | 40.79 |

执行费包含脚本前缀的沉没执行费 2；首次诊断各费 1。首查询后完整实际后缀（执行/诊断）依次为 0/0、1/0、0/0、0/0。第 2 回合的普通状态验证计执行费，不计显式诊断费；先前诊断费不重复计入后缀。三条失败的零后缀工具费不当成成功恢复的成本优势。真实模型消耗以 Token、延迟另列，没有已确认货币报价，不臆估货币费用。

共 **9 次 SDK 请求、17,791 输入 Token、7,466 输出 Token、102.79 模型秒**。无请求错误、长度截断、空响应重试、非法调用、盲重试或重复预留。两种已提交条件的实际预留均来自超时前缀，不是执行器为模型补做；模型必须自行使用可见 ID 复核。第 4 回合虽然已有实际预留及合法查询返回的 ID，仍未调用复核工具。失败轨迹完整保留。

最终答复原文（除消息开头空行）：

1. `Task aborted: reservation creation timed out with no reservation ID returned to verify status.`
2. `Reservation created successfully with reservation ID e69eac83faec62652b5edb1f. Status: active.`
3. `Reservation request timed out; no active reservation exists for request HOLD-2702.`
4. `Reservation creation timed out; status unknown`

**格式与恢复结果分开。** 四份答复均不以 Blocked: 开头。用同一归档终态和原评分器，仅把答复在审计副本中换成中性 Finished. 后，严格完成结果仍依序为否、是、否、否；原始答复没有被修改。这排除了本批失败仅由 Blocked: 前缀否决造成的解释，不代表该评分边界一般不存在。可恢复条件的正确停止率仍记不适用，不因对照组未被要求写 Blocked: 而修改评分。

### 请求与历史不变性核验

`audit_verify.py` 与 `audit.json` 只读核对：

- 两个 original 首请求逐字段等于 Gate 33 原始 SDK 首请求，SHA-256 均为 `e5a227c1052115acd5d03f138b7acfc3d000ce7fb5f10650ec44f611e20ea528`。原始组两例的实际动作和完成结果重现 Gate 33 的“无记录后停止 / 查到后复核完成”；不要求随机签发的 ID 或措辞相同，也不据此宣称温度 0 总是确定。
- 两个 removed 首请求严格等于上述请求仅删登记三句话，其余字段均相同；后续请求也不含三句话。每回合只有首次查询带 tool_choice，后续原生 ReAct 无额外强制。
- 工具消息逐条等于事件的真实回执，原评分重算无差异，SDK usage 总和等于归档 Token；每个检查点沉没费与实际后缀费之和等于账本。
- 合同、环境执行器（含评分）及原生模型 Agent 与 main 基线 `f4a7140` 逐字节相同；Gate 33 的旧来源文件哈希保持原审计值。估值继续 unknown、支持 0，没有用本轮结果在线补估。

### 解释、Go/No-Go 与共同提示建议

**实际观察：** 第 3 回合仍在 not_found 后不调用恢复工具即作答，本批观察符合 H 的行为判据，说明删除这三句话不足以修复该检查点的停止。不能由一次观察证明退出措辞完全没有因果作用。第 4 回合从原始组的“真实复核完成”变为“有实际 ID 仍停止”，显示本次删除操作损害了另一可恢复情形；变化发生在真实动作上，不是纯答复格式。

**对 Gate 33 的边界：** 原始 ReAct 的停止在本次原样重跑中重现，删除三句并未消除 not_found 上相对强制规则的已观察缺口。但本轮没有在 removed 下重跑 advice_only 或 simple_feedback，不能量化跨提示的基线差值，也不能断言所有相对表现都不敏感。found 情形本身对提示改动敏感。三句话联合删除且没有任意文本改动对照，不能确定是哪句起作用，也不能排除一般提示扰动；不从模型自述推测内部机制。

**实验 036 工程 Go。** 合并后 CPU、原始哈希、删除边界、真实续程隔离、原评分及账本验收均通过。负结果不触发改提示、补跑、换种子或新诊断。专用 vLLM PID 2068444 已停止，GPU 回到 464 MiB。

**Gate 34 共同提示建议：** 沿用 original 作为后续候选的共同提示；本次删除未修复目标停止且破坏另一情形，没有依据将 removed 替换为共同提示。该建议不等于证明 original 最优，正式共同提示仍由用户冻结。不可把 removed 直接用于含不可恢复任务的正式比较。不实施 Gate 34 Benchmark、M0–M3、BTM 或其他诊断；实验 037 保持未冻结设计草案，内容不因本轮结果修改。
