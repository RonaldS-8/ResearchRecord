# Gate44A-Obs 首轮真实Agent行为观察（预登记）

2026-11-13。用户仅授权准备，**真实运行等待明确批准**。本轮不开发恢复算法、不新增数学模型、不改任务/合同/scorer，不合并PR。独立于实验044四组smoke；R2/R3原设计保留，本轮禁用。前次暂停要求由本次明确授权在此准备范围内恢复，其他方法及Benchmark扩展仍暂停。

## 来源与范围

已读AGENTS、044、044A-0及PR17公平性审查，PR固定head d382bb3239e6a86bf292cd8dd1e9d911e21b9194，仅读取未合并。R2/R3无适配训练源；R1为M3/M4知情静态提醒，不能称已验证最强基线，R0/R1差异含提示增量，不能作算法因果结论。两个已见开发检查点、单一基础任务，不支持跨任务泛化或显著性声明。

科学问题：实际损失是否来自反馈理解、动作选择、参数/引用绑定、续程或开销？竞争解释包括静态提醒改变注意力、采样偶然性、基础设施故障、非法调用使严格失败不可逆。不存在预设正结果；四条轨迹都必须保留。

## 固定4回合与预算

运行ID `044a-obs-01`，CPU准备另为`044a-obs-preparation-01`。顺序固定M3-R0、M3-R1、M4-R1、M4-R0，各1回合；所有请求SDK seed444001（两组配对，相同seed不保证相同输出）。调用条件/快照/引用流与044A-0相同，R0/R1提示字节逐哈希核对；不改四组预登记、不据首轮结果改模型或提示。

Qwen3-4B-Thinking-2507，revision768f209d9ea81521153ed38c47d515654e938aea；Python3.10.12、vLLM0.31.0、OpenAI3.42.0；温度0、输出6144、timeout120秒、transport retry0。原Agent内部重试保留并逐请求计数。qwen3 reasoning、hermes工具解析；max_model_len32768、max_num_seqs2、显存.85、enforce_eager，沿既有serve脚本，无自定义聊天模板覆盖。

每回合≤12次实际SDK请求，全批≤48；输出Token保守界294912，输入窗口保守界1572864。M3每回合剩6调用、M4剩3，共最多18次工具调用；模拟后缀费用保守界42（M3每轮≤18、M4≤3），前缀沉没费另列共14。请求串行最大96分钟（不含工具/启动），全批端到端上限2小时，超出暂停待批准，不补回合。无货币价格映射，不把工具费、Token、时间相加。

上下文须逐请求按本地冻结tokenizer渲染，输入+6144≤32768，否则不发送请求。12请求上限、连续3个SDK错误或执行异常时停批次；失败保留，不自动替补、追加或转入160回合。原生解析失败/无效终答保留为实际结果，不事后修输出。服务启动后须确认独占endpoint、模型名和启动日志对应冻结参数；漂移则停，不换模型。

## 实现、准备证据与运行命令

新增gate44obs.py，复用gate44a.AdviceAgent/restored/treatment、gate34b原生loop、Gate42A独立scorer。只开放R0/R1；初始化/首提示与既有manifest逐字哈希匹配。SDK原请求/响应/usage/error、渲染文本、每请求前公开view/剩余预算、每工具前后view/真实实参/副作用/发布状态全部保存；不强制工具、不绑定实参、不代办确认或回读。保留模型原终答及scorer业务/严格结果。推理Token从原usage取可得字段，缺失标unknown，不重复加到output。

CPU专项覆盖四组角色/日志/usage/预算、实参错误不修复、上下文超限不发送、SDK错误保留及内部请求12次上限；使用真实本地tokenizer离线渲染四个首请求。首次错误把BatchEncoding字段数当Token数的记录保留，修正后重验。准备证据云端results/044a-obs-preparation-01，冻结原manifest为docs/evidence/044a-0/manifest.json。真实服务尚未启动；CPU协议通过不等于模型有效执行。

获用户批准后才可在LabServer /home/ubuntu/Song/Agent执行以下两终端命令（本轮未执行）：

```sh
bash benchmarks/ToolMaze/evaluation/scripts/serve_local_vllm.sh
PYTHONPATH=benchmarks/ToolMaze:tests:. .venv/bin/python -m extensions.toolmaze_recovery.gate44obs --output results/044a-obs-01 --model-path /home/ubuntu/Song/Agent/models/Qwen3-4B-Thinking-2507 --approved-run 044a-obs-01
```

--approved-run只记录用户已作的批准，不构成批准本身。启动前归档实际命令/版本、tokenizer/chat_template哈希、模型revision缓存、服务启动日志、源码提交和全目录哈希；启动后只跑这4回合。

## 逐轨迹人工审计与判断标准

批准后每轮整理事件时间线：起始剩余义务与公开反馈→首次实际恢复动作→逐调用原始实参/回执/预算/费用/副作用→首次执行错误→最终义务/严格完成/答复。首动作是否正确仅依据公开可行性，未知记unknown；不得用隐藏故障或CPU最优路径补模型决策。

逐项标A反馈理解遗漏，B恢复动作选择，C实参/引用/合同违反，D续程/确认/回读/终答失败，E无效重复/提前停止/成本浪费，F SDK/解析/基础设施。每个标签必须附事件编号、公开信息证据、可避免性和竞争解释；可多标签但按最早导致不可恢复损失标主因，不确定就unknown。不把执行错误归于估值，不把工具少当总成本低。分别报输入/输出/可得推理Token、请求/工具数、模拟费、模型时间、端到端延迟及可核算货币费（没有则NA）。

4回合只作观察与可行性筛查。R0/R1逐轨迹并排，不用15pp阈值作此样本的统计门槛，不宣称显著性；不同轨迹≤2时尤其不作路线判决。若主要为C/D，建议优先执行可靠性验证；若绑定正确但B/E明显且R1仍有可避免损失，建议另登记恢复决策观察；若反馈理解/保留存在可定位缺口，才建议上下文/记忆方向验证；若提醒已覆盖或无清晰余量，保留负结果，建议在真实业务语义下扩充故障类型，不能定制任务追求方法收益。最终路线建议须等真实证据，当前unknown。

## 准备验收

全仓199项CPU通过（含防泄漏）；最终入口专项5项通过。真实tokenizer渲染首请求Token：M3 R0/R1=1551/1665，M4 R0/R1=1911/2025；均可预留6144输出。模型与tokenizer缓存revision一致。首轮错误计数记录保留，修正版见template-summary-02.json。配置与源码哈希见[准备manifest](../evidence/044a-obs/preparation.json)。准备状态：可请求批准这4回合，服务尚未启动；实际请求/响应/usage与行为归因必须等批准后获得，不预填结果。
