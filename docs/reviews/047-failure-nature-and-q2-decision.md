# Gate47 · 失败性质与Q2选题判断

2026-11-15（Asia/Singapore归档）。**最终判断：Inconclusive；当前优先寻找新的真实Agent恢复场景，暂不据M3/M4开发恢复决策算法。** 保留Q2问题，不将本轮解释成Q2不存在，也不把强API失败解释成新算法空间。小模型可靠恢复可作收缩备选，但当前证据不足以认定失败只来自小模型，或主要只来自合同文字。

## 实际完成范围

预登记`6d9b744`，最小运行/验收锁`d6b5db4`，首次遮蔽标签编码`7af3d55`，只读复算脚本`61a2dad`。工作分支gate47-audit，基于Gate46 head9324eff和main f4b2bbf；未经批准不合并PR。API原始M3/M4共13回合/55请求；Gate46既有24条件/24请求；总37回合/79请求。无变体追加、失败补跑、LLM换型或新算法。逐回合及分组计量见[metrics](../evidence/047/metrics.json)，请求时间/哈希/usage见[request-index](../evidence/047/request-index.json)。

全部37回合用原实际参数独立复放，原strict scorer一致；无参数修复、自动绑参或续程、无tool_choice。216项CPU通过；旧Gate45的375个原始索引条目SHA未变。旧报告/结论、冻结任务/评分/费用未修改；Gate46 C1为独立登记合同条件，不覆盖原合同。

## 能力上界检查的配置与结果

Alibaba Cloud Model Studio / CN北京，用户端点`https://cn-beijing.maas.qianwenaiapi.com/compatible-mode/v1`；请求和响应均为固定`qwen3.7-flash-2026-07-15`。OpenAI Chat Completions非流式，原ReAct提示/工具/检查点；temperature0、top_p1、seed470001、max_tokens6144、thinking_budget6144、enable_thinking=true、timeout120秒，parallel_tool_calls=false，SDK重试关闭，异常不换协议。配置无密钥归档云端`results/047-api-01/config.json`；密钥仅env注入，云端临时副本已删除，本地model.env保留。

官方CN价格与用户批准一致：≤32K输入0.2元/百万、输出0.8、自动缓存输入0.04；未使用Batch、搜索或显式缓存。usage推算合计**0.01341224 CNY**，不是发票实收，低于15元上限。每请求事前保守预留1.249152元，成功后按真实usage结算，未知账目保留预留并停止；没有未结算请求。[模型/价格](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)及[参数语义](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/)于2026-11-14核对。API的max_tokens不含思考，按最多12288输出Token预留；4B是6144总输出上限，不能声称完全等推理预算或纯规模效应。

“强API”是本轮指定的能力参照，不代表所有强模型或已经独立证明的能力上界。服务内部权重/量化/缓存控制不可观测。此API实际有自动缓存命中104576输入Token，和Gate46关闭本地prefix caching分开报告。

| 模型/条件 | strict=义务 | 实际后缀工具调用/接受 | 前缀/后缀模拟费 | SDK | 输入/输出Token | 请求累计秒 | usage成本CNY |
| --- | --- | --- | --- | ---: | --- | ---: | ---: |
| API M3原始 | 3/3 | 12/12 | 9/18 | 15 | 30795/1605 | 20.656 | 0.00359276 |
| API M4原始 | 0/10 | 30/30 | 40/30 | 40 | 92331/5294 | 63.507 | 0.00981948 |
| 4B Gate46 C0变体 | 0/12 | 0/0（绑定NA） | 48/0 | 12 | 22850/11684 | 158.380 | 不适用 |
| 4B Gate46 C1变体 | 0/12 | 0/0（绑定NA） | 48/0 | 12 | 23486/13306 | 183.260 | 不适用 |

原始检查点与变体结果不混合。API M3各回合归档→核验→发布→回读→终答，模型独立绑定真实引用；输入/输出/缓存/推理分别归档（推理625已含1605输出）。API M4全部实际writer重试→主读→writer重试，均未发布；推理2084已含5294输出。失败产生的低工具费用不是效率收益，成功率不可比时不比较成本优势。4B未尝试任何后缀工具，既不能检验绑定能力，也没有纯格式造成的完成损失。

API M3前三次同一动作后缀，按预登记停在3；M4前三次有“预算耗尽后仍提出第四调用”和“主动终止”的两种轨迹，故运行至10上限。其实际执行工具序列始终只有1种；两种终止行为不提供新故障任务。没有为凑20–40继续采样。M3/M4首次请求各只有1种，首次assistant消息分别3/7种；原始响应ID/created不同不能制造独立性。Gate46 24个不同请求和24个不同首响应，跨所有条件仍只有STOP一种动作。不能把13或24当独立任务数、据此作稳健组间检验或算精确有效样本量。

API实际2026-11-14 23:44:55.515–23:46:19.976+08；Gate46为23:45:18.238–23:51:00.205+08，串行请求，无预热。两实验服务/模型/合同不同，不做时延模型优劣结论。Gate46末4请求与外部GPU训练进程重叠，详见Gate46报告；无OOM、截断或SDK错误，不隐去混杂。

## 失败归因：表现与原因分开

E=输出明确陈述，B=真实行为支持，U=证据不足；推理不是内部因果证明。本轮34次失败：4B的17次有路径/用户约束误读文本（A），4B另7次和API10次主因unknown。B类实参语义错误0、纯格式0；确认的C类主因0。**这不等于无错误恢复动作**：全部失败均有停止或耗尽预算的表现，只是未证明它们在正确理解完整相关合同后仍选错。A占4B失败17/24，合并全部失败仅17/34，不能宣称全模型主因超过一半。基础设施错误0；8次预算外提议由既有执行器拒绝，不执行/收费/增加事件，单列不冒充非法参数调用。

Gate46全部24条失败、E/B/U和精确Q1字符锚点见[逐条件证据表](046-contract-clarity-acceptance-and-results.md)，原推理哈希及边界见[failure-evidence](../evidence/047/failure-evidence.json)。17次点名prepare却排除任务适用性；7次未定位prepare命名，不能推断“没有注意”。没有C1成对成功。注册C1澄清既未避免损失，也没有证据说明原合同完全清楚；工具显著性、system停止范式、4B能力与更深任务框架误读仍竞争。

API全部10个M4失败逐行如下。共同事实：Q1明确知道失败未提交（E）；Q1–Q4未定位prepare命名（U注意/合法性/满足用户目标）；实际三次调用全参数合法（B）；初始备用三步可行由CPU/合同复核（B，不给Agent隐藏真值）。若原writer恢复，重试→回读在起点预算内有完成可能，因此不能仅凭固定shared隐藏状态，宣布首次重试在公开信息下必然非理性。**首次重试失败后再主读→原writer→回读需3次，但只余2次**；观察到的计划没有为完整核验留预算。它是预算/续程规划问题的证据，仍不是已完整理解替代合同的C类主因证明。

| API M4 episode | Actual suffix | Q4 actual proposal | Primary / secondary | Evidence |
| --- | --- | --- | --- | --- |
| 01-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 01-M4 |
| 02-M4 | writer-read-writer; strict=obligations=0 | Blocked final | unknown / B exhausted budget | Q1-Q4 reasoning_content; see failure-evidence.json: 02-M4 |
| 03-M4 | writer-read-writer; strict=obligations=0 | Blocked final | unknown / B exhausted budget | Q1-Q4 reasoning_content; see failure-evidence.json: 03-M4 |
| 04-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 04-M4 |
| 05-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 05-M4 |
| 06-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 06-M4 |
| 07-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 07-M4 |
| 08-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 08-M4 |
| 09-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 09-M4 |
| 10-M4 | writer-read-writer; strict=obligations=0 | writer: budget rejected, no final | unknown / E budget miscount, B rejected proposal | Q1-Q4 reasoning_content; see failure-evidence.json: 10-M4 |

API Q2的主读具有B级执行性信息获取功能，但明示计划主要是看主读是否可用/取得主来源后重发；10-M4 Q3明确推断共享provider也可能失败，仍重试。不能据此宣称已测到净信息价值；尤其此时余2，主读后无法完成发布加回读。反馈理解局部正确不等于路径合同理解正确。

## Gate46消融和选题判据

Gate46既定3记录×2措辞×2命名×C0/C1完整执行，分层均为0严格完成：每记录C0/C1各0/4，每措辞各0/6，每命名各0/6；所有成对纠正0，安全计数均0。C1新增文字不是新的工具路径指令；结果**不支持“这两处简单语义澄清足以消除失败”**，也不证明文字无关。完整条件表、精确提示冻结和工程限界见[合同报告](046-contract-clarity-acceptance-and-results.md)。

| 预登记筛选 | 本轮证据 | 判断 |
| --- | --- | --- |
| A：强API在足够差异任务≥90% | M3 3/3，M4 0/10；仅两固定机制，无独立家族 | 不满足；不能泛称强Agent恢复瓶颈普遍存在或不存在 |
| B：语义/执行占主因过半或澄清消除主失败 | 4B A17/24；全部模型A17/34；执行/格式0；C1纠正0 | 4B语义能力/合同理解优先；并非已证“主要是合同写法”，暂不开发决策算法 |
| C：清楚合同下强模型明确且可复现C类错误 | API有错误重试/预算损失，但备用路径理解U；强简单规则未在该API同期验证 | 不满足Go的证据要求；不能直接宣布估值/隐状态方法必要 |
| D：混合或不足 | 上述理解、模型覆盖、任务独立性和运行混杂均有限 | **Inconclusive** |

三项独立判断：**Q2恢复决策算法当前No-Go（继续收集合法场景证据可Go）；转小模型可靠恢复是可行备选、尚非唯一选题结论；“当前主要是Benchmark合同问题”未被本次C1验证。** 最终推荐为“现有证据不足，需寻找新的真实Agent场景”，而非重写现有题目制造难度。优先寻找自然存在的状态不确定、合法查询、重试安全/回执缺失等实际工作流；先只读检查公开合同、真实失败与强规则余量，再另行提交最小登记。任何新任务/故障/模型比较、说明文字、关系提示或Harness消融均需另登记，不自动运行。暂不实现HMM/ACV/BTM优化或新Harness修复。

原始轨迹留云端`/home/ubuntu/Song/Agent/results/{047-api-01,046-real-agent-01}/`；源、服务、CPU与派生审计路径见[核验清单](../evidence/047/verification.json)。本轮所有失败、非独占段、首轮CPU失败及自动审批/SSH问题均保留，不以成功率或费用挑选归档。
