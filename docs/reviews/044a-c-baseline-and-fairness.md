# Gate 44A-C · 历史基线准备与四组公平性独立审查

2026-11-13。基于 main `1a5b0d1`，独立分支 `review/gate44a-c-baselines`。**仅阅读 Git 内记录与代码，未调用 LLM/GPU/API，未登录云端，未打开任何原始轨迹。** 未修改 main、Gate42A 执行器、原评分、Agent loop 或已登记实验。附件：[R2/R3 冻结规格](044a-c/r2-r3-frozen-spec.json)、[训练历史缺口报告](044a-c/history-gap.json)。

## 结论摘要

1. **没有可合法用于 R2/R3 的已授权真实训练历史，本轮不产出冻结统计，只交缺口报告。** 唯一工具名重合的真实来源是实验 038（Gate 34-B）的 8 个自然 ReAct 回合，未获训练授权，原始文件只在云端。
2. **即使授权 038，决定性键的支持度仍为 0。** 由代码可证：Gate 34 夹具只会让主读超时，validate 与 publish 只会返回非法拒绝，没有 archive/prepare/confirm。M3 当前错误（validate 授权覆盖失败）与 M4 当前错误（writer 端点不可用）在任何 038 池中 n=0。R3 在两检查点都退化为“BTM 静态文本＋均匀信念 0.5”，R2 则报告 validate/publish 历史成功 8/8，与刚发生的失败相反。
3. **M4 有可预先算出的结构性陷阱。** 剩 3 次调用；再试一次原 writer 合法但必然失败（共享故障），剩 2 次，不足 prepare→confirm→readback。R2 的“publish 8/8”与 R3 的 BTM_RETRY（至少重试一次）都指向这一步。R2/R3 在 M4 的结果主要由历史分布错配与静态重试条款决定，不能读成“历史信息无用”或“BTM 方法差”。
4. **四组是两个因素的非析因组合，无法把方法效果与静态提示增量分开。** R1 是针对 M3/M4 机制写的静态提醒，R3 是 BTM 静态约束加（几乎无信息的）记忆，R2 只有统计没有静态提醒。实验 044 的路线 D（历史信息信号）在现有四组下无法识别。
5. **独立建议：R2/R3 No-Go；R0/R1 在补齐既有运行阻断项后可有条件 Go。** 是否把 Gate 44A 收缩为 R0/R1，或保留四组但预先改名并登记“预期方向”，由用户决定。本文不增加实验组。

## 任务一：R2/R3 历史基线准备

### 1. 真实 Agent 历史审计

| 来源 | 性质 | 回合 | 与 M3/M4 工具重合 | 能否作训练历史 |
| --- | --- | --- | --- | --- |
| 038 自然 ReAct：S01、S02、P01–P06 react | 真实 Qwen，温度 0，无 tool_choice | 8 | 5 个基础工具；无 archive/prepare/confirm | **候选**：同一开发基础任务 REC-3401；038 第 132 行写明“不自动进入训练历史”；需用户授权并在云端补原始文件哈希 |
| 038 首动作强制：S03–S08 | 真实 Qwen，首个请求 tool_choice | 6 | 同上，另有 inspect_read_channel | 排除：行为策略被干预，与 BTM 原文“基础模型自然轨迹”不符（ADR-0033 第 58 行已记此类偏差） |
| 038 simple_feedback | 真实 Qwen，每个检查点强制工具 | 6 | 同上 | 排除：策略由规则决定 |
| 039 P05 续程 | 真实 Qwen，修改反馈条件 | 2（3 请求） | 基础工具 | 排除：事后开发对照，复用 038 前缀 |
| 042A 假 SDK | CPU 假 SDK | 4 请求 | M4 | 排除：不是模型 |
| 040、041、042B、043A-R、037 等 | CPU 规则/宏轨迹 | — | — | 排除：CPU 合成轨迹不能冒充 Agent 历史 |
| 006/007/015/020/021/025/028–031/034–036 | 真实 Qwen | 各异 | 工具集不同 | 排除：跨工具映射是新设计，未获批 |
| Gate 44A 自身 smoke/开发回合 | — | — | — | 永远排除 |

结构性支持度（由 `gate34a.py` 与 `toolmaze_agent_recovery/session.py` 的 `fault_result` 推出，不依赖数据）：Gate 34 的 MechanismSession 只令 `read_tools[0]`（主读）超时，备用读从不失败；validate 与 publish 只会返回 `code=invalid` 的非法拒绝。因此任何 038 池对下列键的支持都是 0：M3/M4 两个当前错误键、archive/prepare/confirm 的全部调用、backup→archive、primary→archive、publish→prepare 三个切换对。

另一个依赖关系：042 的 M3/M4 机制是在看过 038 之后、专门放在“直接备用路径失败”处设计的。038 历史在这两格无信息是设计使然，这一点必须写进结论边界。

### 2. R2 定义（最简逐工具成功频率）

| 项 | 冻结口径 |
| --- | --- |
| 计数单位 | 训练池中每一个已执行的工具调用事件，含登记的外生前缀调用（与 gate18 `recovery_keys` 读取前缀＋后缀的范围一致） |
| 分子 s | `illegal == false` 且回执无 `error`，即回执满足该工具合同后置条件 |
| 分母 n | `illegal == false` 的调用（合法成功＋合法服务/核验失败） |
| 拒绝 r | `illegal == true`（实参/引用/协议拒绝）单列，不进分母，避免把绑参错误当后端故障 |
| 不计 | 预算守卫拒绝、未执行的调用 |
| 错误类型 | R2 不按错误分组；任何合法失败都算失败。只逐字引用检查点最后一个回执，不重新贴标签 |
| 缺样本 | n=0 写 “unknown (no legal calls in the training pool)”，不给默认值、不平滑 |
| 明确不含 | 先验、episode 结局标签、source→target、动作价值、规划、HMM/信念、按上下文或检查点条件分组 |

提示模板见规格文件 `R2.template`。按 038 记录文字推算（**仅示意，未从原始文件计算，不得用于运行**）：read_primary_record 0/8（全为外生前缀超时）、backup/validate/publish/readback 均 8/8、archive/prepare/confirm unknown。

### 3. R3 定义（复用完整 BTM 口径，不简化为 R2）

| 部件 | 来源与口径 |
| --- | --- |
| 恢复键 | gate18 `recovery_keys`：每回合内合法失败的 (tool, 逐字 error) 集合，回合内去重，含前缀 |
| 标签 | 训练回合在其自身评分器下的 strict_success（038 用 gate34a evaluate），是任务最终恢复，不是单次调用成功 |
| 后验 | Beta(1,1)，均值 (s+1)/(n+2)，按 gate18 格式 `0.500 (n=0; no observations)` 显示 n |
| 切换关系 | 静态替代映射中的 (source, target)：M3 为 primary→backup、primary→archive、backup→archive；M4 为 primary→backup、publish→prepare(+confirm)。映射只取自公开工具描述 |
| 切换键 | 回合内 target 的合法调用发生在 (a) source 合法失败之后，或 (b) 由 source 签发的 pending_ref 的 validate 合法失败之后。(b) 是为 M3（读成功、核验失败）所做的适配，**需联合批准** |
| 静态部分 | gate18 `BTM_GUIDANCE`、`BTM_RETRY`、`BTM_CONSTRAINTS` 逐字；映射行沿用 gate18 “same … and required fields” 句式；methods.py `btm_full` 的 “Never retry a tool explicitly reported unavailable for this session.” 作为本项目偏差保留并标注 |
| 列出范围 | 训练池中出现的所有可见工具恢复键＋检查点当前键＋全部静态切换对。一次性渲染的静态块，与论文“一个块列出全部工具/错误信念”一致，不随后续失败重渲染 |
| 记忆版本 | 固定版；Gate 44A 结局永不更新；每回合前后核对产物哈希 |

已知与既有复现的差异：两份既有实现本身不一致。gate18 有映射行，并且只列当前错误；methods.btm_full 无映射行，带“unavailable”例外，并按检查点重渲染到 system。本规格取 gate18 的统计与文本，加 methods 的例外句和 target 说明句。放置位置按 044a 放在前缀之后，而不是论文与两份旧实现所用的 system 提示，属复现偏差，已在规格中记录。

### 4. 冻结产物、来源清单与哈希

本轮不产出 R2/R3 统计文件（无合法训练源）。冻结的是规格与缺口报告；运行前仍须补：授权的训练池清单、每个原始 result.json/requests.jsonl 的云端 SHA-256、按规格计算出的统计 JSON 及其哈希。

来源清单（`git show 1a5b0d1:<path> | sha256sum`，即 LF 规范化的 Git blob 内容；Windows 工作区为 CRLF，整文件哈希会不同）：

| SHA-256 | 文件 |
| --- | --- |
| 6c7cffc7d430c16124ca0a45247b8de6dbb77df3c45638bb5fcc043a9734ac3a | AGENTS.md |
| 4eac38be04236f6b2789bcd344716d4a36ed6b066fecc92860227783fd30b6f3 | docs/experiments/044-gate44a-real-agent-bottleneck.md |
| ef5c1c86e2c4c97a19500878bd6eed933d9b3cee2c340e4145ceb616b2f61b57 | docs/reviews/044a-information-contract-and-budget.md |
| be62c05117a7be8c0a7e5e5a626e78e638da286b1a8e00f9f0703fa760536647 | docs/experiments/042-gate42a-real-executor-preparation.md |
| 808078cb9693e3f852198da92617635c17609ce8f763b6a31fba66653384d80a | docs/experiments/038-gate34b-agent-development.md |
| 6d6f70b0cc76e774adf8121ae84bc893f17c985fc70faa19b684acff4ef956d7 | docs/experiments/039-write-rejection-feedback-control.md |
| 4e404ca5aa13e60bad0e782330af1c6704415e924c7ebb3325d9915b82e4f5b0 | docs/reviews/041-bench2robust-teardown.md |
| eab4d0496a0939e92763d733e08ffe4d89205e0e1845e07e615cd57a966a3c3d | docs/adr/0011-action-value-and-btm-comparability.md |
| 1c0493c36564668e324a9d85db7714f682df2d2ddd2b1fce9006461dfec15c20 | extensions/action_conditioned_recovery/gate18.py |
| 2875d91762751f0139704e876a049cb326bc3c4ac55bccdcdc939c5ae4b07483 | extensions/toolmaze_agent_recovery/methods.py |
| fd0ad2c0903d1063a04528ed2b48e4ec2ce91e42c1f3815c56203d7d4ea26306 | extensions/toolmaze_agent_recovery/session.py |
| 0b5c8e3bba205f46a1c6ffffd797923f5a0b571fbaa3e734b0ccf139ee1055e2 | extensions/toolmaze_recovery/gate34a.py |
| 64fc04a39d7e147dd7e33c7b23df44141294bfcf996e14ac06f174a50fbf4903 | extensions/toolmaze_recovery/gate34b.py |
| 859a974bd67c2b08ad6f3f181658ca8ae734ec2f6bc1d0ad3e2a48b9292784cc | extensions/toolmaze_recovery/gate42a.py |

两份附件的哈希见文末。

## 任务二：四组公平性外审

### R0–R3 信息合同差异表

| 维度 | R0 | R1 | R2 | R3 |
| --- | --- | --- | --- | --- |
| 原 system、任务、工具定义、报价、预算、检查点前缀、在线回执、scorer | 相同 | 相同 | 相同 | 相同 |
| 新增恢复块 | 无 | 有 | 有 | 有 |
| 块位置/角色 | — | **未冻结** | **未冻结** | **未冻结**（论文为 system） |
| 已试/未试工具优先于停止 | 无 | 有（明文） | 无 | 间接：“仅在重试与替代均用尽后升级” |
| 失败后至少重试一次 | 无 | 相反：“不无意义地重复失败调用” | 无 | 有（BTM_RETRY） |
| 替代来源须核验权限/粒度 | 合同内 | 明文重述 | 无 | 明文（BTM_CONSTRAINTS） |
| 准备≠提交、须确认与回读 | 合同内 | 明文重述 | 无 | 仅“写后检查结果” |
| 显式替代映射行 | 合同描述 | 无 | 无 | 有 |
| 逐工具频率 s/n | 无 | 无 | 有 | 无 |
| (tool,error) 回合恢复 Beta | 无 | 无 | 无 | 有（决定性键 n=0） |
| source→target 切换 Beta | 无 | 无 | 无 | 有（决定性对 n=0） |
| 当前错误再引用 | 仅原回执 | 无 | 逐字 | 作为键 |
| 训练池 | — | — | 同一冻结池 | 同一冻结池 |
| 隐藏状态/生成律/Oracle | 禁止 | 禁止 | 禁止 | 禁止 |
| 强制工具/自动实参/自动续程 | 禁止 | 禁止 | 禁止 | 禁止 |
| 额外输入 Token | 0 | 短 | 中 | 最长 |

### 逐项回答

**相同任务、工具、预算与公开检查点？** 设计上相同：同一检查点快照克隆、同 scorer、同 12 请求上限、无 tool_choice。未冻结的是块的消息角色与位置，它对 R1–R3 共同起作用，但会影响遵从率。Qwen3 模板对中途 system 消息的处理须在云端用服务实际模板渲染核验，本地无法确认。

**R1 是否包含“合法未试工具优先于提前停止”？** 包含（044a R1 第二句）。另需注意：R1 同时重述“替代来源核验”“准备不等于提交、须确认与回读”，这几句正好对应 M3/M4 的两种机制，是看过 038/042 后写的检查点知情提醒。它不具名正确工具、不读私有信息，合规，但不能称作通用“最强简单规则”。英文精确字节仍未提交。

**R2 是否严格限于逐工具频率与当前错误、未暗含 ACV/HMM？** 044a 文字与本规格均满足：无先验、无条件表、无结局标签、无转移。须守住两条实现边界：频率按全池逐调用计，不按上下文、检查点或步次切分；成功只看回执本身，不用隐藏覆盖范围等私有字段判断“读到的是否可用”。

**R3 是否完整保留 BTM 原始恢复记忆与静态约束？** 统计口径、Beta 先验、切换关系、静态映射与六条约束均可保留（见上表）。三处必须如实标注为偏差：块位置不在 system；“unavailable for this session”例外是本项目添加的；M3 切换键的 (b) 条款是适配。更根本的是，没有合法训练池时“记忆”部分不存在；有了 038 池，决定性键仍为 0。此时 R3 实际上就是论文消融里的“静态结构＋均匀信念”。

**训练测试混用、隐藏状态泄漏、提示信息不对等？**
- 混用：训练候选与测试检查点是同一基础任务 REC-3401，不是论文那样的任务级划分；只能作开发诊断，不能支持跨任务结论。Gate 44A 自身回合不得入池（044a 已写）。
- 泄漏：未发现直接泄漏。标签用训练回合自身评分器的 strict_success，是合法的训练侧标签。风险在于实现时若把 CPU 规则日志、042A 假 SDK 或 Gate 42B/43A-R 的 CPU 轮次放进池，就会把已知生成律带入。规格已列为排除项。
- 训练标签口径：训练回合用 gate34a 评分，测试用 gate42a 评分，两者义务不同（后者含归档/备用发布链），需在报告中注明。
- 不对等：R1 与 R3 在“是否重试失败调用”上给出相反指令；R2 不含任何静态提醒；R0 无块。见下节。

**能否区分方法效果与静态提示内容增加的效果？** 不能。四组相当于在“静态提示（无/R1式/BTM式）”和“历史统计（无/频率/BTM 记忆）”两个因素上各取一点，不是析因设计。决定性键支持度为 0 时，R3 与 R1 的差几乎全是两段静态文本之差，R2 与 R0 的差是“误导性频率表＋多一段文字”之差。044a 已承认四组不足以识别纯算法效应；这里进一步说明，在现有训练源下，**连“历史信息信号”这一较弱结论也无法识别**。

### 可能导致错误科研结论的因素与最小修复（不增组）

| # | 风险 | 可能的错误结论 | 最小修复 |
| --- | --- | --- | --- |
| 1 | 决定性键 n=0，R3 退化为静态＋均匀信念 | “BTM 历史记忆无效/有效” | 运行前按冻结产物公布每个检查点的键支持度表；n=0 时分析中把 R3 记作“BTM 静态＋无信息信念”，路线 D 对 R3 记 unknown |
| 2 | 038 与 M3/M4 故障世界错配，R2 报 validate/publish 8/8 | “历史频率误导恢复”被泛化 | 预登记“依据冻结产物的预期引导方向”表（M3 倾向重试 validate、M4 倾向重试 writer），结果只与该预期比较，并明确为同任务分布迁移失效 |
| 3 | M4 剩 3 调用，重试 writer 后不可完成；BTM_RETRY 与 R2 均指向重试 | R3/R2 在 M4 的失败被归因于记忆或历史 | 单列“是否遵从重试条款”和“重试后预算可行性”；由重试导致的失败归因为静态条款，不归因于统计 |
| 4 | “unavailable for this session”例外对 M4 回执是否适用存在歧义（回执文字是 “Publication endpoint unavailable; no publication was committed.”） | R3 M4 结果取决于模型如何理解一句歧义文本 | 冻结前写明：字面不匹配，预期不触发；遵从与否单独记录，不在运行后解释 |
| 5 | R1 是检查点知情提醒 | “简单规则胜过 BTM”被泛化 | 报告中称“M3/M4 知情静态提醒”，不称“最强简单规则”；提交英文字节与哈希 |
| 6 | 块角色/位置未定，且偏离论文 system 放置 | 遵从差异被当成方法差异 | 冻结统一角色与位置，在云端用服务模板渲染完整请求核对；R3 偏差写入报告 |
| 7 | 温度 0、同 seed，20 次重复可能高度相同 | 一条分叉轨迹即造成 ≥15 个百分点“信号” | 沿 044 报告不同轨迹数；预登记“不同轨迹数 ≤2 的格只报告、不作路线判断” |
| 8 | 训练与测试同基础任务，M3/M4 机制在看过 038 后设计 | 把同任务开发观察当作跨任务证据 | 结论限于“同一开发任务、移位故障世界”，不进入 H-D 的一般化表述 |

## 对 Gate 44A 的独立 Go/No-Go 建议

- **R2/R3：No-Go。** 无已授权训练池；即使授权 038 自然 ReAct 8 回合，决定性键支持度为 0，结果可由冻结产物事先推出，主要反映分布错配与静态重试条款。在“新增合规训练采集”获批之前，跑 R2/R3 的 100 个回合（smoke 20＋开发 80）回答不了 H-D。
- **R0/R1：有条件 Go（仅指设计层面）。** 条件是补齐 044 第 55 行的既有阻断项（检查点哈希、R1 英文字节、SDK 计数核验等）并修复第 5、6、7 项。这部分可以回答 H-A/H-B/H-C。
- **需要用户决定的两条路：**
  - A（建议）：把 Gate 44A 收缩为 R0/R1，R2/R3 推迟到另行登记、经批准的训练采集之后。总回合与 GPU 时间减半。
  - B：保留四组，但按第 1–4 项修复改名，并预登记预期方向。代价是多 100 个回合换取基本可预知的结果。
- 不论选哪条路，本审查都不授权运行、合并或采集。

## 附件哈希

按 Git LF blob 内容计算（本文不含自身哈希）：

| SHA-256 | 文件 |
| --- | --- |
| 695c8c4c35ade684a10b2c786a43406027cd9c676947eaca79213deaeec3fbb1 | docs/reviews/044a-c/r2-r3-frozen-spec.json（规格 `044a-c-spec-v1`） |
| eda716f7747cdd800ec198c5abc93feb57ead8785ef05a081107f8acefc78875 | docs/reviews/044a-c/history-gap.json（缺口 `044a-c-gap-v1`） |

## 限制

未打开云端原始轨迹，038 的推算数字只来自报告文字；Qwen3 聊天模板行为未核验；切换键 (b) 条款与静态映射是本审查的建议，需联合确认。
