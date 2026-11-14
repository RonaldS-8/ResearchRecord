# Gate46 · 独立工程验收与合同澄清结果

2026-11-15（Asia/Singapore归档，真实运行11月14日23:45–23:51）。Gate47授权执行既有24条件；源分支`gate46-semantic-variants` head `9324eff`，执行代码`d6b5db4`。未合并PR，未改变旧M3/M4或独立评分。此处“独立验收”指重新检查提交及实际重放，不是第二位人类编码者。

**工程Go；本次C1语义澄清没有带来完成改善。C0=0/12、C1=0/12，全部在首请求停止，无真实后缀工具调用。** 不把CPU假SDK成功称作模型成功，也不把零后缀费用称作效率。

## 工程和冻结核验

原8项Gate46测试、3项Gate47日志/预算测试及既有回归、防泄漏合计216项云端通过。首轮隔离工作区缺云端数据夹具，且新假客户端测试未对齐冻结采样，失败日志完整保留；仅补云端原数据软链接、修测试配置和错误记录后复验，不涉及模型补跑。旧gate34a/gate34b/gate42a及原生Agent实现相对main f4b2bbf差异为空。

24条件精确提示/工具逐字内容留云端`results/047-cpu-acceptance-02/freeze/payloads.json`，SHA256 `1da99a849dfa217826d3cb33358813a30349c2febec2099836ae4b859356d51d`。每条件原始prompt/public哈希及token数见[freeze.json](../evidence/047/freeze.json)，全部24个prompt哈希不同；剩3次调用；token范围1895–1965；AW0N0-C0与Gate44A/45 M4-R0冻结锚点相同。冻结文件SHA256 `b84c4ccf918102812ab43cf5884b84ec67c32781b86d5e14d2dc6951d9ff0bfe`。这里哈希使用既有JSON序列化规范，不声称不同序列化字节等同。

记录/内容双向替换、N1仅去掉alternate、W1只改任务句，C1只追加预登记prepare/confirm两处澄清。通过原始实参拒绝、未见canonical值拒绝、真实引用链、原预算收费及独立scorer复放测试；底层故障/业务义务/评分未改。无自动绑参/修复/续程，无tool_choice。24条真实调用最后均未发工具，故真实模型的参数绑定率为NA；CPU测试不能填这个分母。

使用原Qwen3-4B-Thinking-2507及revision、温度0、max_tokens6144、120秒、每回合12请求上限，固定schedule(460001)和seed，无warmup/补跑。实际仅24次请求，均stop结束，无length、SDK错误或OOM。独立tmux监管服务API pid3044016、EngineCore3044261，启动日志明确`enable_prefix_caching=False`；退出的SIGTERM及EngineCore强制清理警告发生于正常监管清理，不能当作OOM。原始`reasoning`字段完整保留，API实验使用`reasoning_content`，两者没有因字段差异丢失。

## 逐回合失败证据

全部24行的共同观察：B首请求停止；E引用原发布未提交的反馈（不等于理解全部恢复合同）；B起点有3调用的CPU实际可行备用续程；B停止不能完成；与同变体C1配对均无成功，因此没有观察到此次简单澄清避免损失。原错误工具关系的内部动机未知。下表“注意”仅指推理是否点名prepare，E不等于已识别合法性；“任务适用性”在A行有明确排除/误读文本，unknown行没有足够证据。全部真实非法调用0，参数语义/纯格式失败0；没有一行满足“已正确理解全部相关合同后选错”的C类主因证据要求。

首次阅读遮蔽C0/C1标签，记录/工具名仍可见，不能称完全盲审。17行A、7行unknown的[首次编码](../evidence/047/blind-coding.json)先以`7af3d55`固定，再关联条件。C0为A6/unknown6，C1为A11/unknown1；文本更常点名路径不等于语义因果误读概率上升。括号内为Q1推理的0起始字符位置，精确结束偏移及完整推理哈希见[failure-evidence.json](../evidence/047/failure-evidence.json)。

| Condition | Blind ID | strict/obligations | Primary | Prepare noticed | Registered subtype | Q1 evidence (character start) |
| --- | --- | --- | --- | --- | --- | --- |
| 01-BW0N1-C0 | K08 | 0/0 | A | E | unknown | 3879: the user's task is to publish, not prepare. |
| 02-BW0N1-C1 | K18 | 0/0 | A | E | T2 | 4375: prepare_publication is for preparing but not publishing. |
| 03-AW1N0-C1 | K20 | 0/0 | A | E | T2 | 2016: But the user wants a single publication, and the publish_verified_record is the main way. |
| 04-AW1N0-C0 | K10 | 0/0 | A | E | T1+T2 | 3654: But the user wants to publish the current record, not an alternate. |
| 05-CW1N1-C0 | K22 | 0/0 | A | E | T2 | 2137: But the user's task is to publish, not prepare. |
| 06-CW1N1-C1 | K01 | 0/0 | A | E | T2 | 2269: So the intended path is publish_verified_record. |
| 07-AW1N1-C1 | K24 | 0/0 | A | E | T2 | 5064: the task requires publishing via publish_verified_record. |
| 08-AW1N1-C0 | K05 | 0/0 | unknown | U | T2 | 3489: there's no alternative path to get a publication |
| 09-BW1N0-C0 | K16 | 0/0 | unknown | U | unknown | 1691: Since the publish failed, there's no publication to read. |
| 10-BW1N0-C1 | K12 | 0/0 | A | E | T1+T2 | 2633: but those are for alternate publications. |
| 11-AW0N0-C1 | K09 | 0/0 | A | E | T2 | 2962: But the user wants exactly one copy |
| 12-AW0N0-C0 | K17 | 0/0 | A | E | T1+T2 | 2421: but the user wants to publish the current record, not an alternate. |
| 13-BW1N1-C0 | K14 | 0/0 | A | E | unknown | 3722: But the user's task says "publish a single copy", so maybe they want to use publish_verified_record directly |
| 14-BW1N1-C1 | K21 | 0/0 | A | E | T2 | 2677: But the user wants to publish via publish_verified_record, not prepare_publication. |
| 15-AW0N1-C1 | K13 | 0/0 | A | E | T2 | 3150: the other tools like prepare_publication and confirm_publication might not be applicable here |
| 16-AW0N1-C0 | K04 | 0/0 | unknown | U | T2 | 3773: There's no other tool to handle this. |
| 17-CW0N1-C0 | K23 | 0/0 | unknown | U | T2 | 1898: There's no alternative tool to fix this. |
| 18-CW0N1-C1 | K02 | 0/0 | unknown | U | T2 | 3851: there's no other tool to do it. |
| 19-CW0N0-C1 | K19 | 0/0 | A | E | T2 | 5049: the other tools are for alternate publications, which might not be the right path here |
| 20-CW0N0-C0 | K03 | 0/0 | unknown | U | T2 | 3836: There's no other tool to publish the record. |
| 21-BW0N0-C0 | K15 | 0/0 | A | E | T1+T2 | 3619: but the task is to publish the record, not an alternate. |
| 22-BW0N0-C1 | K07 | 0/0 | A | E | T2 | 3831: So the intended path is through publish_verified_record |
| 23-CW1N0-C1 | K11 | 0/0 | A | E | T2 | 2705: But the user wants a single publication, so maybe the publish_verified_record is the right path |
| 24-CW1N0-C0 | K06 | 0/0 | unknown | U | T2 | 2093: the tools available don't have a retry mechanism mentioned. |

## 预登记判据与解释边界

表中T1为原注册类型一（把alternate排除为非当前任务），T2为明确声称没有替代发布路径，unknown为这两种细分证据不足；宽口径A与T1/T2不是同一个编码。

没有任何成对纠正（0/12），C1完成0/12；非法调用/重复发布/错误发布均0，安全条件未恶化，但“有作用”和“足够”判据均未满足。C0中明确的类型一相关失败至少包含AW1N0（current record, not an alternate）、AW0N0（current record, not an alternate）、BW0N0（record, not an alternate），加上明确声称无替代工具的CW0N0，已达到≥4/12前提（表中保守C0相关9/12，另3行细分unknown）；不必把全部unknown硬编码为类型一/二才能作这个判断。其余“publish而非prepare”的A类属于更宽的任务适用性误读，不能自动冒称为“以为第二份发布”的同一细分机制。无成功使纠正计数恒0。

C1同时澄清同一份发布和未提交不占额；无改善不能确定哪句话是否被注意。不能把澄清失败解释为原合同完全清楚，或排除停止模板、工具显著性、任务框架及4B能力限制。无关系/数值信息组，无方法有效性结论。12变体属于同一恢复实现和固定shared故障，只是措辞/命名/内容敏感性检查；动作轨迹均为一个STOP，不是24个独立故障场景。

## 资源与归档

C0输入/输出22850/11684 Token，C1为23486/13306；推理已含输出，分别11407/12957。C0模型请求累计158.380秒、C1累计183.260秒，均值13.198/15.272秒；端到端累计158.488/183.381秒。前缀模拟工具费各48，后缀均0；本地GPU无API账单，GPU租赁费未知，不能记作真实经济成本为0。

**共享GPU限制：**另一用户训练进程3046473于2026-11-14 23:50:07.160+08启动，与条件21-BW0N0-C0、22-BW0N0-C1、23-CW1N0-C1、24-CW1N0-C0的请求重叠。本轮请求无错误/截断，仍保留该非独占事实及不可排除的运行影响；不能据上述延迟推断合同效率差异。不停外部进程、不删除这四回合、不补跑。

原始`results/046-real-agent-01/`，服务`results/046-service-01/`，CPU`results/047-cpu-acceptance-{01,02}/`均留云端。逐文件SHA见[raw-index](../evidence/047/raw-index.json)，运行支持日志及GPU混杂见[verification](../evidence/047/verification.json)。最终Q2判断见[Gate47报告](047-failure-nature-and-q2-decision.md)。
