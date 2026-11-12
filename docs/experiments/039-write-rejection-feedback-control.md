# 实验 039 · Gate 35 写入拒绝反馈控制

2026-11-12，开发性、事后发现问题的配对控制；不是独立确认性证据。用户批准 PR #11 独立验收、合并及本次两回合实验。Q2 不变，不运行 M0–M3、BTM 或正式 F2。

## 问题与判据（模型运行前冻结）

P05 连续漏掉内容末尾句号，而回执只提 evidence_ref。H1：只明确拒绝原因可以让原生 Agent 修正 content、执行真实写入和回读。竞争解释：模型忽略反馈、不能精确绑定内容、后续执行失败或预算不足；错误文案可能并非失败原因。模型自述只作观察，不作因果证明。

两组固定实验 038 的 P05-simple_feedback 真实历史，止于第一次错误写入的拒绝。重新执行原归档前五次实参，逐条核对实际回执、费用及引用。Agent 输入直接采用其后首个归档 SDK 请求的完整 messages（含实际 tool_call ID、assistant 文本及已保存字段），不重建合成模型历史。唯一组间消息差异为最后一条 tool 消息 JSON 的 error 文本：

- original：`An actual primary or granularity-verified backup evidence_ref is required.`
- specific：`content does not exactly match the content returned with this evidence_ref.`

code=invalid_argument、错误 content、正确真实证书、全部早先回执、工具定义、价格、任务与提示保持一致。specific 不给正确内容、句号提示或隐藏状态。仅这一次拒绝采用 specific；两组未来调用均使用 original 回执。此后原生 ReAct，自行生成全部参数和终答；去掉旧强制 WRITE 的 tool_choice，不加建议。它不是原来的强制规则完整回合，也不声称重现实验 038 完整处理效果。

固定顺序 original → specific，各一次；同一 P05 环境种子 35005、E γ=9/10、d=1/10。环境参数只用于重建原状态，不入策略。模型、权重 revision、original system/user、vLLM/SDK、启动选项沿用实验 038：Qwen3-4B-Thinking-2507，revision 768f209d9ea81521153ed38c47d515654e938aea，vLLM 0.31.0、OpenAI 3.42.0、Python 3.10.12；temperature=0，SDK seed=3301，max_tokens=6144，timeout=120。每回合原上限12 SDK请求，历史已有4次，故续程最多8次实际请求；transport retry=0，原 Agent 内部处理保持并归档。总工具预算7，已用5，剩余2，不重置预算。

## 评分与费用边界

不改评分：固定前缀已有一次非法调用，因此零非法要求下两组严格完成都必为 false，即使后续义务完成。该不可逆失败是保留原评分的结果，不能放宽后报告“严格成功”。分别记录：模型是否识别 content 类别（只引实际文本）；是否修正 content；真实写入/回读、业务义务完成；合法最终答复；完整回合严格结果；新增非法调用、重复副作用、剩余预算。

检查点前实际成本=执行4+诊断1/10=41/10，其中初始失败沉没费1；该检查点前全部41/10对当前续程均为沉没成本。单列检查点后实际执行费、诊断费、Token与时延，以及原首次超时后的全后缀费用。费用逐调用精确核算，失败照收；不得把失败的低费用称为收益。

H1 的本对开发证据为 specific 修正并完成写入+回读而 original 未完成；若两者都修复或都失败，报告没有观察到这种完成差异。两组均能修复时仅报告真实动作/费用差别。两回合不估总体概率、不做显著性检验，不把参数反馈改进称为付费诊断或 Q2 方法收益。恢复选路、参数修复和付费诊断价值分别解释；本检查点已在诊断和备用核验之后，不能识别早先重试/切换/购买诊断的因果效果。

## 验证与归档

PR 固定 head b9f4fb23aabeb24f178e3a63b35313576864048c，main 合并 f36d094。云端独立104项通过，旧20回合实际调用/评分全部复放一致；见 Review。运行前再验最小适配补充和完整回归，锁通过提交，验证两组首请求除一个 error 字符串外全部相同、与旧请求除 tool_choice 和该文案外相同。CPU 用假客户端证明参数不会自动修复、严格失败保留、实际义务可完成、预算不重置、未来反馈一致。归档存在即拒绝覆盖，异常保留证据并停止，不追加模型样本。

新证据仅存云端 results/039-pr11-cloud-review-01/、039-feedback-control-cpu-01/、039-feedback-control-agent-01/、039-feedback-control-service-01/。逐回合保存来源文件哈希、固定前缀、首请求、完整SDK请求/响应/错误、实际调用、检查点、参数、终答、费用、Token及延迟。不得覆盖038。记录版本、运行提交及预登记提交；服务结束停止并验证GPU释放。详细审查写 docs/reviews/039-pr11-and-feedback-control-review.md；结果追加本文。下一最小诊断价值实验只提出设计，不执行。
