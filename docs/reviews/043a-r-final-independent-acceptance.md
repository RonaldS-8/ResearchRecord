# Gate 43A-R 最终独立验收

2026-11-13。独立工作树 `/private/tmp/gate43ar-review`，detached PR #16 head **3efa57b42eea804115711486e7d2c985163bda53**；本地主线 **3a2e699a7e042e6a63fe3c692c495fc0dad604ac**。没有合并 PR、调用模型或修改任务/评分。阅读依据：AGENTS、ADR-0033、实验040/041/042A/042B/043A-R、Gate42A执行器及测试、PR新增实现及043反思。

## 两项独立判断

**最终工程验收 Go；HMM 方法研究 No-Go。** 用户配置服务器后，已补齐Python3.10.12独立复算、完整CPU/防泄漏及旧合同兼容性证据，详见文末。前次因环境不可达作出的工程No-Go已解除；下文保留初次验收观察，不覆盖负记录。工程Go不授权合并PR或真实模型比较。

## 本轮实际观察

- 初始本地只有五份无关未跟踪Review（036一份、037三份、038一份），全部保留。LabServer普通连接被沙箱阻止；授权连接与15秒超时重试均未取得云端状态（连接超时）。没有下载云端原始数据。不能声称端云同步或云端干净。
- 本机 Python3.9.6，没有发现python3.10/uv。完整ToolMaze发现11个导入错误、防泄漏1个导入错误，首先缺PyYAML；它们不是行为测试失败，也不是通过。临时venv安装PyYAML，两次分别下载超时和TLS失败。不能继续伪造缺失模块或用替代数据宣布通过。
- 独立递归比较提交中的c4与naive-c4结果（字典键、列表长度、每个叶子均检查，repr区分正负零）：十对文件中七对有差异，数量为A=3、controls=6、M3四段各1、thin-M3一段1，共14。所有差异均为浮点0/-0；其他字段一致。E、S4b、M3第一段三对零差异。这是提交证据的字段核验，不是独立运行3.10生成的证明。
- 25份d1逐一解析所有数值叶子，零值符号均为正；按运行器的sort_keys/ensure_ascii=False重新计算result SHA256，25/25与README一致。文件均声明d04415b854972579c247d5dbacd831d6d0888a2b且dirty=false。这只证明内容与自述一致，不证明程序实际在所述机器运行。
- e15d829、9703998、abf6ee6、0a3ff9e、d04415b源码提交对象存在。首次作废启动八空一完整的更正已公开；不应再描述全部为空。证据环境是提交者事后自述，旧轮没有原生环境字段；d1有环境和命令，仍不能由JSON自行认证来源。
- 旧结果保留，d1新目录、排他创建，不覆盖c1–c5。d1使用c4相同历史及开发暴露，不能称独立确认性留出。原始日志例外入Git已明示；文件字节哈希受换行影响，result哈希应按解析后规范JSON核验。

## 数学与代码审查

`fit(exact=True)`在最后M步后重新expect，返回参数的前向似然和计数；`corrected.pick`用最终似然选初值，并用相同似然算BIC；旧似然仅供审计。参数数目为上下文初态自由度+各状态发射自由度+可选转移自由度，size为非空训练episode数。带伪计数的有限步EM、隐状态奇异/不可识别情形下，BIC是工程选模启发式，不是标准渐近一致性保证；也不能把300步称为已收敛。2640/26400及241次数尚未独立复算。

`within`以最高完成质量为锚再选低费用，消除非传递的逐对比较。完全相等费用时仍按候选公开顺序决胜；`priced`完全等分时亦如此，故“顺序无关”应理解为固定公开tie-break下的数值选择，而非任意置换后动作名称必然不变。

全局界证明：若同一有限预算模型、相同可行策略集合、费用0≤f≤F、λ=δ/F且F>0，πλ确实最大化c−λf，则由最优性得c*−cλ≤λ(f*−fλ)≤δ。动态规划按未归一化概率质量相加，线性目标适用；fee_bound用调用预算乘最高公开单价，要求所有自动尾部调用都计预算且费用不超该单价。禁止将界外推到真实Agent、真实分布或另一个策略集合。ban限制、guard拒绝及未建表历史fallback可能使实际策略不等于该最优策略；保证仅限已规划模型/支持范围。节点带Hδ同样仅是有限决策深度下的模型内界，不是统计置信界。

## 同历史基线与方法结论

`compare`按同一seed/N生成一次rows/counts，corrected给ACV+untried、单状态、Belief共用；单状态来自同样拟合流程。单状态大样本guard失败后回退ACV，不能把回退成绩叫单状态模型自身成绩。untried在同一公开合法/预算集合内工作，不能推荐预算内不可能完成的路径。

现有提交结果：M3 N30/100时ACV+untried完成1，M5 N30时.900高于Belief .862；原小样本完成优势不能归因隐状态。M5仍有模型内费用空间；S4b全局界.01费用3.827差于旧ACV3.670；混杂5.100差于4.400；失配/迁移未获保护。完整BTM不是这些CPU代理；不宣称胜过完整BTM。上述数值是证据文件核验后的提交结果，未独立重跑。

## 旧合同与未完成复验

PR分叉早于main的Gate42A，端点diff中Gate42A缺失不是PR主动删除。只读`git merge-tree <merge-base> main head`未见冲突标记；没有执行合并。multipath新增moves默认None、choose默认None，旧静态分支意图保持兼容；最终必须在临时整合树跑Gate42A及040/041旧回归/哈希，静态审查不替代行为证据。

后续验收必须：取得云端status；在固定PR head的Python3.10.12完整CPU/防泄漏；按提交launch_d1的25分段独立运行并保留全部失败、逐结果/哈希对账；独立核对最终似然/BIC选择计数；在临时整合树验证Gate42A及冻结旧合同。命令用`PYTHONPATH=benchmarks/ToolMaze:tests:. python -m unittest discover -s tests -p 'test_toolmaze*.py'`及test_no_leakage.py，结果新建results/043a-r-final-independent-<批次>/。云端原始数据留云端。全部满足前工程No-Go，不请求合并批准。

本轮本地核验日志留/private/tmp/43ar-{tests,leak,artifact-audit}.log及43ar-merge-tree.txt；这些不是云端正式归档，需后续归档补齐。Gate44A仅设计见实验044和合同附件。


## 服务器恢复后的最终独立复验（2026-11-13）

运行登记与过程见[独立复验实验记录](../experiments/043a-r-independent-acceptance.md)。初始云端main为3a2e699a且干净，Python3.10.12；GitHub复核PR最新head仍为3efa57b。使用固定源码bundle创建独立工作树，不修改SSH信任设置。临时整合树只应用PR差异，不生成合并提交、不移动main。全程CPU，无真实模型/API调用，云端数据和原始结果未下载。

| 检查 | 独立结果 |
| --- | --- |
| PR原树完整仓库CPU | 191/191通过（其中ToolMaze153、防泄漏5） |
| 临时整合树完整仓库CPU | 206/206通过（其中ToolMaze168、防泄漏5，包含Gate42A） |
| 修正版d1，25个原登记分段 | 全部正常退出；全部result逐字段及规范JSON哈希一致；零负零 |
| 旧040九轮＋041七轮 | 16/16结果字段及result哈希与前次独立云端证据一致 |
| 七处c4差异，直接对云端旧独立原始JSON | 仅14个0/-0字段；其余字段一致 |
| 冻结文件/旧合同 | 382/382归档SHA256不变；原执行器、评分、gate34b及Gate42A源码diff为空 |
| 最终参数似然及期望计数 | 静态/动态、1/2/10步，隐状态轨迹穷举最大误差1.78e-15 |
| BIC独立计算 | 参数自由度及非空episode数一致；穷举例BIC误差≤7.11e-15，另以独立前向计算复核M3/N30/seed6000全部20次拟合 |

25份d1是在Linux/Python3.10.12从源码重新生成，与提交中的Windows/Python3.14记录比较；可确认本轮登记配置下跨这两个环境一致，不保证所有平台任意配置逐位相同。source commit与result哈希分别核对，环境字段允许不同。d1的2640个拟合场合结构/状态数变更均0，26400次初值选择中241次不同，与提交审计一致。d1仍复用已暴露历史，不升级为确认性研究。

全仓首轮整合回归因缺旧005结果夹具有4个错误，补只读云端results链接后206项通过；首轮日志保留。原树191项也使用同一既有夹具；未伪造数据、修改评分或忽略失败。整合树的base HEAD不是整合代码提交，以PR patch SHA256 `4640ca725631c45c408e83517737080b6d5ea6860ea68dfa8f4fc1d9dcdd20b0`及integration-source.json锁定真实源码。

证据均在云端 `results/043a-r-final-independent-01/`：d1/、040/、041/、scripts/、pr-all-cpu.log、integration-all-cpu{,-02}.log、专项与防泄漏日志、frozen-and-c4-audit.json、corrected-independent-math.json、final-result-comparison.json、old-result-hash-check.json、environment-source.json、integration-source.json、artifact-sha256.json。未修改上一轮独立证据或提交者结果。

**工程Go**：修复的似然、记录和比较规则已具独立CPU证据，旧合同兼容通过。**HMM方法研究No-Go**：完成优势被强基线解释，剩余费用优势受模型类、支持度与比较规则限制；本次复算未提供新的真实Agent证据。PR合并仍等待用户单独批准。Gate44A只设计，冻结训练源/产物、最终提示和检查点哈希及模型运行预算仍须补齐获批；不得据工程Go启动smoke或正式LLM比较。
