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

仅云端。在含本轮提交的工作树根目录，先 CPU 后模型；输出目录已存在时脚本拒绝覆盖。

```bash
bash scripts/run_gate33.sh cpu
```

```bash
bash scripts/run_gate33.sh agent
```

预期：CPU 步骤的 ToolMaze 测试与防泄漏测试全部通过；模型步骤产生 8 个回合目录，每个含 `config.json`、`requests.jsonl`、`episode.json`。

## 本机验收

待实现后填写。

## 结果

待云端运行后填写。
