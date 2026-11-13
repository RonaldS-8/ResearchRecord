# Gate44A-0 首轮真实LLM运行准备

2026-11-13，用户授权仅CPU准备，不运行真实模型、不合并PR、不改冻结合同。实现基准1a5b0d1，PR16仍未合并。运行计划沿实验044和信息合同：40 smoke、480实际SDK请求上限、输出≤2949120 Token、工具费保守界420，串行请求时间≤16小时；不自动扩大160开发回合。模拟费用、Token、模型时间/端到端时延分别记录。

## 结果：Smoke Not Ready

已锁定M3/M4检查点、前缀真实引用流和私有构造记录；R0/R1可用提示与R2/R3缺数据协议占位版本均已生成字节哈希。**R2/R3不是最终可运行冻结基线**，缺已授权同源真实Agent历史、统计适配与拟合记忆。缺数据产物有哈希只为防止偷偷替换，不表示完成训练。未申请启动smoke。

证据云端 `results/044a-0-preparation-01/`，本地[manifest](../evidence/044a-0/manifest.json)仅复制哈希/预算元数据，原始快照和轨迹留云端。freeze/M3、M4分别保存public.json、private-construction.json、reference-stream.json、R0–R3-prompt.json，全部SHA256见manifest。namespace为gate44a-0-M3/M4，仅在执行侧；同一固定检查点每组重建，原预算M3已用3剩6、M4已用4剩3，不重置、不复制活状态跨组使用。public()和view()分别用于合同/历史，私有状态不入提示。

## 最小实现与CPU证据

新增 `extensions/toolmaze_recovery/gate44a.py`、`tests/test_toolmaze_gate44a.py`；沿用gate34b.initialize/run_episode、原生VLLMAgent、gate42a.checkpoint/evaluate。没有改旧文件、工具合同、价格、评分。AdviceAgent只在真实前缀后加一条处理消息；R0没有处理消息。所有组工具列表和去掉处理后的消息逐字段相等。R3复用既有BTM三段指导及btm_full的session不可用例外，不加未来路径或参数。

7个专项覆盖：两格四组消息/工具公平性，独立重建与副作用隔离，真实SDK请求计数/内部请求12次硬上限，usage/请求/响应逐条落盘，错误实参原样被拒，两条完整假模型续程的八组严格验收，以及缺历史不伪装成记忆。八组CPU停止轨迹保存在protocol/；完整续程由测试假模型给参数，运行器不含参数绑定器、不强制工具或代办尾部。假SDK成功不能作真实LLM能力证据。

全仓194项CPU测试通过（all-tests.log，包含防泄漏）；SDK客户端恢复修复后7项专项再次核验。失败请求保留error和时间；可得usage原文包含推理字段则保留，不可得记空，避免推理Token重复相加。每轮保存events、prefix_calls、模型请求数、训练与检查点哈希、总wall_seconds及原loop的model_seconds。没有实现可启动真实网络的CLI；run_protocol仅供注入假SDK检查。真实transport retry=0、版本/上下文窗口/服务错误批次暂停等启动前检查仍需在训练合同补齐后接入并验收，当前不具备真实启动条件。

## 独立训练审计与停止原因

云端现有results/**/config.json中91份含model字段，M3/M4配置为0；详training-source-audit.json。这个盘点不证明所有可能来源不存在，但没有已获授权、可追溯的Gate42A同源训练清单。Gate42A已有native-protocol-fake-sdk明确是假SDK；040–043 CPU规则/宏历史不属于真实Agent历史。旧Gate18/21/22或其他业务轨迹不能未经批准改标为本任务训练集，也不能用本批smoke结局更新记忆。

原复现合同：methods.History要求source_task==TRAIN_TASK且continuation==CONTINUATION；每episode对发生过的工具/原始错误键去重，source→target取相邻读取动作中失败后切换键并按episode去重，以最终strict_success计数。Beta(1,1)，后验(s+1)/(n+2)；n0的.5是先验，不是经验成功率。R2目标是单次工具合同后置条件成功，R3目标是最终恢复，不能互填。原实现限读取工具，不能静默扩展到M4写入/确认或用CPU状态推算这些工具统计。尚缺显式任务/工具映射、episode名单/采集策略/授权/排除评测集证明及产物，故不训练、不声称完整冻结BTM已适配。

解除阻断需要确认合法的既有真实训练来源及跨任务适配合同，或另行登记并批准采集；本轮禁止真实模型，因此没有自动新增采集。之后才能产出R2/R3最终摘要与提示哈希、真实网络配置预检和最终manifest，再申请40 smoke。维持既定组/阈值/预算，不以空训练版本偷跑。

## 复现命令

在云端完整数据环境、PYTHONPATH=benchmarks/ToolMaze:tests:.：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_toolmaze_gate44a.py' -v
.venv/bin/python -m unittest discover -s tests
```

freeze使用 `gate44a.prepare(new_output_directory, lambda: test_toolmaze_gate34b.client_agent([])[0])`；每组协议使用 `gate44a.run_protocol(fake_agent, mechanism, arm, new_directory)`，默认SDK seed440001，其他smoke seed440002–440005合法。没有真实smoke启动命令，本轮状态Not Ready。
