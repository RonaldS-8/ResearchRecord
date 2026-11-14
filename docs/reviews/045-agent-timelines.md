# Gate45 全部74回合行为时间线

独立重放原始实参与评分；无自动纠错、无反事实重评分。完整参数、引用和终答留云端原始文件。

## 045-real-agent-01/450001-M3-R0

起点已用3次、剩6次；信息组/建议：R0。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1551/861/831（推理已含输出）；模型/端到端秒=11.761/11.765。
证据：云端results/045-real-agent-01/450001-M3-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450001-M3-R1

起点已用3次、剩6次；信息组/建议：R1。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [非法：正文少末尾句点] → 原始终答。
严格/义务=False/False；主因=format_exact_match；E6选路/真实引用正确，正文少末尾句点被拒；其后停止，未继续业务义务。
首建议遵从=True（R2/R4无单一建议NA）；绑定=2/3；非法=1；后缀费=5。
SDK=4；输入/输出/推理Token=11365/4762/4567（推理已含输出）；模型/端到端秒=64.463/64.484。
证据：云端results/045-real-agent-01/450001-M3-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450001-M4-R0

起点已用4次、剩3次；信息组/建议：R0。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1911/686/655（推理已含输出）；模型/端到端秒=9.255/9.261。
证据：云端results/045-real-agent-01/450001-M4-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450001-M4-R1

起点已用4次、剩3次；信息组/建议：R1。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=2025/2070/2042（推理已含输出）；模型/端到端秒=27.708/27.713。
证据：云端results/045-real-agent-01/450001-M4-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450002-M3-R0

起点已用3次、剩6次；信息组/建议：R0。
E4 read_primary_record [合法服务失败] → E5 read_archive_record [接受] → E6 validate_record_granularity [接受] → E7 publish_verified_record [接受] → E8 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=5/5；非法=0；后缀费=7。
SDK=6；输入/输出/推理Token=18904/2895/2598（推理已含输出）；模型/端到端秒=40.266/40.298。
证据：云端results/045-real-agent-01/450002-M3-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450002-M3-R1

起点已用3次、剩6次；信息组/建议：R1。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=16026/2928/2697（推理已含输出）；模型/端到端秒=40.994/41.020。
证据：云端results/045-real-agent-01/450002-M3-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450002-M4-R0

起点已用4次、剩3次；信息组/建议：R0。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1911/971/944（推理已含输出）；模型/端到端秒=13.652/13.656。
证据：云端results/045-real-agent-01/450002-M4-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450002-M4-R1

起点已用4次、剩3次；信息组/建议：R1。
E5 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=5739/3002/2372（推理已含输出）；模型/端到端秒=41.098/41.110。
证据：云端results/045-real-agent-01/450002-M4-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450003-M3-R0

起点已用3次、剩6次；信息组/建议：R0。
E4 read_primary_record [合法服务失败] → E5 read_archive_record [接受] → E6 validate_record_granularity [接受] → E7 publish_verified_record [接受] → E8 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=5/5；非法=0；后缀费=7。
SDK=6；输入/输出/推理Token=20129/3553/3293（推理已含输出）；模型/端到端秒=50.236/50.278。
证据：云端results/045-real-agent-01/450003-M3-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450003-M3-R1

起点已用3次、剩6次；信息组/建议：R1。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=15236/2397/2130（推理已含输出）；模型/端到端秒=34.679/34.713。
证据：云端results/045-real-agent-01/450003-M3-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450003-M4-R0

起点已用4次、剩3次；信息组/建议：R0。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1911/971/944（推理已含输出）；模型/端到端秒=13.689/13.694。
证据：云端results/045-real-agent-01/450003-M4-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450003-M4-R1

起点已用4次、剩3次；信息组/建议：R1。
E5 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=5739/2779/2148（推理已含输出）；模型/端到端秒=39.549/39.564。
证据：云端results/045-real-agent-01/450003-M4-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450004-M3-R0

起点已用3次、剩6次；信息组/建议：R0。
E4 read_primary_record [合法服务失败] → E5 read_archive_record [接受] → E6 validate_record_granularity [接受] → E7 publish_verified_record [接受] → E8 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=5/5；非法=0；后缀费=7。
SDK=6；输入/输出/推理Token=19054/2997/2737（推理已含输出）；模型/端到端秒=42.976/43.011。
证据：云端results/045-real-agent-01/450004-M3-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450004-M3-R1

起点已用3次、剩6次；信息组/建议：R1。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=15925/2983/2752（推理已含输出）；模型/端到端秒=41.983/42.023。
证据：云端results/045-real-agent-01/450004-M3-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450004-M4-R0

起点已用4次、剩3次；信息组/建议：R0。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1911/971/944（推理已含输出）；模型/端到端秒=13.558/13.565。
证据：云端results/045-real-agent-01/450004-M4-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450004-M4-R1

起点已用4次、剩3次；信息组/建议：R1。
E5 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=5739/2779/2148（推理已含输出）；模型/端到端秒=38.952/38.967。
证据：云端results/045-real-agent-01/450004-M4-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450005-M3-R0

起点已用3次、剩6次；信息组/建议：R0。
E4 read_primary_record [合法服务失败] → E5 read_archive_record [接受] → E6 validate_record_granularity [接受] → E7 publish_verified_record [接受] → E8 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=5/5；非法=0；后缀费=7。
SDK=6；输入/输出/推理Token=19144/2978/2682（推理已含输出）；模型/端到端秒=41.589/41.629。
证据：云端results/045-real-agent-01/450005-M3-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450005-M3-R1

起点已用3次、剩6次；信息组/建议：R1。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=16019/2869/2603（推理已含输出）；模型/端到端秒=40.050/40.086。
证据：云端results/045-real-agent-01/450005-M3-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450005-M4-R0

起点已用4次、剩3次；信息组/建议：R0。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1911/971/944（推理已含输出）；模型/端到端秒=13.052/13.059。
证据：云端results/045-real-agent-01/450005-M4-R0/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-real-agent-01/450005-M4-R1

起点已用4次、剩3次；信息组/建议：R1。
E5 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=5739/2779/2148（推理已含输出）；模型/端到端秒=37.697/37.713。
证据：云端results/045-real-agent-01/450005-M4-R1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/1-M3-1

起点已用3次、剩6次；信息组/建议：read_archive_record。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=13889/2396/2157（推理已含输出）；模型/端到端秒=34.188/34.224。
证据：云端results/045c-training-01/1-M3-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/1-M3-2

起点已用3次、剩6次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1595/453/420（推理已含输出）；模型/端到端秒=6.612/6.618。
证据：云端results/045c-training-01/1-M3-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/1-M3-3

起点已用3次、剩6次；信息组/建议：read_primary_record。
E4 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=3593/1259/1200（推理已含输出）；模型/端到端秒=17.580/17.591。
证据：云端results/045c-training-01/1-M3-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/1-M4-1

起点已用4次、剩3次；信息组/建议：prepare_alternate_publication。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=11630/1759/1517（推理已含输出）；模型/端到端秒=24.705/24.727。
证据：云端results/045c-training-01/1-M4-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/1-M4-2

起点已用4次、剩3次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1949/966/950（推理已含输出）；模型/端到端秒=13.682/13.687。
证据：云端results/045c-training-01/1-M4-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/1-M4-3

起点已用4次、剩3次；信息组/建议：publish_verified_record。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1965/1021/990（推理已含输出）；模型/端到端秒=14.333/14.337。
证据：云端results/045c-training-01/1-M4-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/2-M3-1

起点已用3次、剩6次；信息组/建议：read_primary_record。
E4 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=3576/1413/1360（推理已含输出）；模型/端到端秒=20.069/20.081。
证据：云端results/045c-training-01/2-M3-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/2-M3-2

起点已用3次、剩6次；信息组/建议：read_archive_record。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=13112/2930/2692（推理已含输出）；模型/端到端秒=43.021/43.046。
证据：云端results/045c-training-01/2-M3-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/2-M3-3

起点已用3次、剩6次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1593/382/352（推理已含输出）；模型/端到端秒=5.630/5.634。
证据：云端results/045c-training-01/2-M3-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/2-M4-1

起点已用4次、剩3次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1951/698/671（推理已含输出）；模型/端到端秒=9.902/9.907。
证据：云端results/045c-training-01/2-M4-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/2-M4-2

起点已用4次、剩3次；信息组/建议：prepare_alternate_publication。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14368/2638/2420（推理已含输出）；模型/端到端秒=37.150/37.184。
证据：云端results/045c-training-01/2-M4-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/2-M4-3

起点已用4次、剩3次；信息组/建议：publish_verified_record。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1959/934/917（推理已含输出）；模型/端到端秒=13.490/13.494。
证据：云端results/045c-training-01/2-M4-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/3-M3-1

起点已用3次、剩6次；信息组/建议：read_archive_record。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=14845/2525/2271（推理已含输出）；模型/端到端秒=36.551/36.584。
证据：云端results/045c-training-01/3-M3-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/3-M3-2

起点已用3次、剩6次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1599/483/457（推理已含输出）；模型/端到端秒=6.877/6.883。
证据：云端results/045c-training-01/3-M3-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/3-M3-3

起点已用3次、剩6次；信息组/建议：read_primary_record。
E4 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=3585/779/719（推理已含输出）；模型/端到端秒=11.299/11.308。
证据：云端results/045c-training-01/3-M3-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/3-M4-1

起点已用4次、剩3次；信息组/建议：prepare_alternate_publication。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=13743/2704/2485（推理已含输出）；模型/端到端秒=40.097/40.120。
证据：云端results/045c-training-01/3-M4-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/3-M4-2

起点已用4次、剩3次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1953/887/867（推理已含输出）；模型/端到端秒=13.476/13.483。
证据：云端results/045c-training-01/3-M4-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/3-M4-3

起点已用4次、剩3次；信息组/建议：publish_verified_record。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1957/662/632（推理已含输出）；模型/端到端秒=10.066/10.073。
证据：云端results/045c-training-01/3-M4-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/4-M3-1

起点已用3次、剩6次；信息组/建议：read_primary_record。
E4 read_primary_record [合法服务失败] → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=1/1；非法=0；后缀费=1。
SDK=2；输入/输出/推理Token=3599/1196/1135（推理已含输出）；模型/端到端秒=17.235/17.245。
证据：云端results/045c-training-01/4-M3-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/4-M3-2

起点已用3次、剩6次；信息组/建议：read_archive_record。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=16479/3570/3310（推理已含输出）；模型/端到端秒=51.878/51.904。
证据：云端results/045c-training-01/4-M3-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/4-M3-3

起点已用3次、剩6次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1597/389/359（推理已含输出）；模型/端到端秒=5.641/5.645。
证据：云端results/045c-training-01/4-M3-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/4-M4-1

起点已用4次、剩3次；信息组/建议：stop。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=True（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1959/775/752（推理已含输出）；模型/端到端秒=11.047/11.054。
证据：云端results/045c-training-01/4-M4-1/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/4-M4-2

起点已用4次、剩3次；信息组/建议：prepare_alternate_publication。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=12871/2393/2149（推理已含输出）；模型/端到端秒=34.535/34.568。
证据：云端results/045c-training-01/4-M4-2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045c-training-01/4-M4-3

起点已用4次、剩3次；信息组/建议：publish_verified_record。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=False（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=1957/1309/1283（推理已含输出）；模型/端到端秒=19.109/19.114。
证据：云端results/045c-training-01/4-M4-3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452001-M3-R2

起点已用3次、剩6次；信息组/建议：R2。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=18557/3511/2971（推理已含输出）；模型/端到端秒=45.296/45.352。
证据：云端results/045-stat-01/452001-M3-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452001-M3-R3

起点已用3次、剩6次；信息组/建议：R3。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=14124/2010/1743（推理已含输出）；模型/端到端秒=26.068/26.108。
证据：云端results/045-stat-01/452001-M3-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452001-M3-R4

起点已用3次、剩6次；信息组/建议：R4。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=18819/3096/2865（推理已含输出）；模型/端到端秒=41.380/41.415。
证据：云端results/045-stat-01/452001-M3-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452001-M4-R2

起点已用4次、剩3次；信息组/建议：R2。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14103/2508/2297（推理已含输出）；模型/端到端秒=32.978/33.008。
证据：云端results/045-stat-01/452001-M4-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452001-M4-R3

起点已用4次、剩3次；信息组/建议：R3。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=13117/2002/1756（推理已含输出）；模型/端到端秒=26.839/26.871。
证据：云端results/045-stat-01/452001-M4-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452001-M4-R4

起点已用4次、剩3次；信息组/建议：R4。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=2559/1547/1519（推理已含输出）；模型/端到端秒=20.178/20.183。
证据：云端results/045-stat-01/452001-M4-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452002-M3-R2

起点已用3次、剩6次；信息组/建议：R2。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=17671/2754/2523（推理已含输出）；模型/端到端秒=35.472/35.501。
证据：云端results/045-stat-01/452002-M3-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452002-M3-R3

起点已用3次、剩6次；信息组/建议：R3。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=15472/2369/2131（推理已含输出）；模型/端到端秒=31.136/31.170。
证据：云端results/045-stat-01/452002-M3-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452002-M3-R4

起点已用3次、剩6次；信息组/建议：R4。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=18053/2407/2176（推理已含输出）；模型/端到端秒=31.552/31.587。
证据：云端results/045-stat-01/452002-M3-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452002-M4-R2

起点已用4次、剩3次；信息组/建议：R2。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14689/2272/2043（推理已含输出）；模型/端到端秒=30.061/30.098。
证据：云端results/045-stat-01/452002-M4-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452002-M4-R3

起点已用4次、剩3次；信息组/建议：R3。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14722/2642/2419（推理已含输出）；模型/端到端秒=35.769/35.801。
证据：云端results/045-stat-01/452002-M4-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452002-M4-R4

起点已用4次、剩3次；信息组/建议：R4。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=2559/1218/1185（推理已含输出）；模型/端到端秒=15.483/15.491。
证据：云端results/045-stat-01/452002-M4-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452003-M3-R2

起点已用3次、剩6次；信息组/建议：R2。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=17583/2507/2244（推理已含输出）；模型/端到端秒=33.793/33.822。
证据：云端results/045-stat-01/452003-M3-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452003-M3-R3

起点已用3次、剩6次；信息组/建议：R3。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=15270/2327/2096（推理已含输出）；模型/端到端秒=31.365/31.397。
证据：云端results/045-stat-01/452003-M3-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452003-M3-R4

起点已用3次、剩6次；信息组/建议：R4。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → 原始终答。
严格/义务=False/False；主因=continuation_missing_readback；E6发布成功，未执行E7回读即给终答。
首建议遵从=None（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=5。
SDK=4；输入/输出/推理Token=13557/2615/2428（推理已含输出）；模型/端到端秒=33.632/33.659。
证据：云端results/045-stat-01/452003-M3-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452003-M4-R2

起点已用4次、剩3次；信息组/建议：R2。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14662/2160/1914（推理已含输出）；模型/端到端秒=29.427/29.461。
证据：云端results/045-stat-01/452003-M4-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452003-M4-R3

起点已用4次、剩3次；信息组/建议：R3。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14763/2583/2354（推理已含输出）；模型/端到端秒=35.582/35.613。
证据：云端results/045-stat-01/452003-M4-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452003-M4-R4

起点已用4次、剩3次；信息组/建议：R4。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=2559/1218/1185（推理已含输出）；模型/端到端秒=16.730/16.738。
证据：云端results/045-stat-01/452003-M4-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452004-M3-R2

起点已用3次、剩6次；信息组/建议：R2。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=17153/2569/2338（推理已含输出）；模型/端到端秒=33.877/33.919。
证据：云端results/045-stat-01/452004-M3-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452004-M3-R3

起点已用3次、剩6次；信息组/建议：R3。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=14673/2027/1759（推理已含输出）；模型/端到端秒=27.407/27.447。
证据：云端results/045-stat-01/452004-M3-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452004-M3-R4

起点已用3次、剩6次；信息组/建议：R4。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=18459/2623/2355（推理已含输出）；模型/端到端秒=37.236/37.281。
证据：云端results/045-stat-01/452004-M3-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452004-M4-R2

起点已用4次、剩3次；信息组/建议：R2。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14611/2136/1890（推理已含输出）；模型/端到端秒=28.188/28.223。
证据：云端results/045-stat-01/452004-M4-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452004-M4-R3

起点已用4次、剩3次；信息组/建议：R3。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14765/2561/2315（推理已含输出）；模型/端到端秒=34.193/34.229。
证据：云端results/045-stat-01/452004-M4-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452004-M4-R4

起点已用4次、剩3次；信息组/建议：R4。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=2559/1218/1185（推理已含输出）；模型/端到端秒=16.307/16.315。
证据：云端results/045-stat-01/452004-M4-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452005-M3-R2

起点已用3次、剩6次；信息组/建议：R2。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=17259/2303/2060（推理已含输出）；模型/端到端秒=30.835/30.878。
证据：云端results/045-stat-01/452005-M3-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452005-M3-R3

起点已用3次、剩6次；信息组/建议：R3。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=14725/2091/1848（推理已含输出）；模型/端到端秒=27.801/27.837。
证据：云端results/045-stat-01/452005-M3-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452005-M3-R4

起点已用3次、剩6次；信息组/建议：R4。
E4 read_archive_record [接受] → E5 validate_record_granularity [接受] → E6 publish_verified_record [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=4/4；非法=0；后缀费=6。
SDK=5；输入/输出/推理Token=18459/2623/2355（推理已含输出）；模型/端到端秒=35.603/35.644。
证据：云端results/045-stat-01/452005-M3-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452005-M4-R2

起点已用4次、剩3次；信息组/建议：R2。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=None（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14611/2076/1830（推理已含输出）；模型/端到端秒=27.205/27.243。
证据：云端results/045-stat-01/452005-M4-R2/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452005-M4-R3

起点已用4次、剩3次；信息组/建议：R3。
E5 prepare_alternate_publication [接受] → E6 confirm_alternate_publication [接受] → E7 read_published_record [接受] → 原始终答。
严格/义务=True/True；主因=success；完整发布及回读通过。
首建议遵从=True（R2/R4无单一建议NA）；绑定=3/3；非法=0；后缀费=3。
SDK=4；输入/输出/推理Token=14765/2626/2380（推理已含输出）；模型/端到端秒=35.558/35.593。
证据：云端results/045-stat-01/452005-M4-R3/result.json、requests.jsonl；参数及回执按E编号逐条可查。

## 045-stat-01/452005-M4-R4

起点已用4次、剩3次；信息组/建议：R4。
直接终答，无后缀调用 → 原始终答。
严格/义务=False/False；主因=recovery_decision；有公开可行路径时停止，或先消耗恢复关键预算再停止。
首建议遵从=None（R2/R4无单一建议NA）；绑定=0/0；非法=0；后缀费=0。
SDK=1；输入/输出/推理Token=2559/1218/1185（推理已含输出）；模型/端到端秒=15.723/15.731。
证据：云端results/045-stat-01/452005-M4-R4/result.json、requests.jsonl；参数及回执按E编号逐条可查。
