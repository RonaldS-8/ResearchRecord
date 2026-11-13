# Gate43A-R 独立复验运行记录

2026-11-13，用户配置LabServer后授权继续；CPU-only，无LLM/GPU/API调用。运行计划先前已提交于1e770ae的验收报告，本文补记实际运行及负结果。科学问题、计价、任务与评分均不变，不合并PR。

固定PR head 3efa57b42eea804115711486e7d2c985163bda53（GitHub再次核对未变），独立云端树/tmp/gate43ar-3efa57b；基准main 3a2e699a7e042e6a63fe3c692c495fc0dad604ac。临时整合树/tmp/gate43ar-integration从该main开始，用merge-base 9eb2890到PR head的源码diff执行git apply，不创建合并提交或移动main。未将PR分支缺失的Gate42A误当删除。正式来源锁为PR SHA、main SHA及归档patch/源码哈希，而非临时树HEAD伪装成整合提交。

开始端云状态：本地1e770ae，有五份既有未跟踪Review；云端3a2e699a、干净。Python3.10.12。首次自动审批Bad Request后通过同一审批流程重试成功；云端GitHub SSH主机密钥校验失败，未关闭校验，改用本地固定源码Git bundle上传并在云端verify。云端模型/数据/原始轨迹不下载。

## 核验协议

新证据目录 `results/043a-r-final-independent-01/`（云端）。不覆盖旧结果；scripts保存全部调度/独立审计脚本；environment-source.json保存Python/平台、PR来源与逐文件SHA256。PR树仅链接云端data和旧results夹具；临时整合树保留已应用patch及源码差异，不当成干净PR树。d1调度8个CPU进程，按提交的25个cell/seed分段、同一训练池/预算/300次EM/初值条件运行；PYTHONHASHSEED=0。040九轮、041七轮在整合树重新运行，其中B2/B3/B4在B1结束后运行。seed与配置不因输出改变。

- PR原树ToolMaze153项、防泄漏5项通过。
- 整合树ToolMaze168项、防泄漏5项通过（包括Gate42A）。
- 整合树全仓CPU首轮206项中4个错误：缺旧005结果夹具；首轮日志integration-all-cpu.log保留。链接云端既有results后重跑206项通过，日志integration-all-cpu-02.log。未修改测试/评分解决错误。
- 独立数学脚本以显式隐状态轨迹穷举验证最终参数似然/期望计数，在静态与动态模型、1/2/10次迭代上通过；独立前向算法复核M3、N30、seed6000的10种模型×2初值的最终似然和BIC。
- 对比云端上一轮独立原始c4与PR原始证据：七文件14叶子，仅正负零；其他字段严格一致。382个既有冻结归档SHA256全部未变。

最终d1/旧16轮对账及Go结论见[最终验收报告](../reviews/043a-r-final-independent-acceptance.md)，以结果实际齐备后追加为准。全局损失界仅在同一可行策略集合、有限预算、0≤费用≤F、λ=δ/F、准确最大化模型内线性目标时成立，不是Agent可靠性或统计置信保证。完整BTM没有在本轮CPU代理中受测。

## 最终结果

25份d1全部正常结束，与提交result严格逐字段/规范JSON哈希一致且无负零；2640场合结构与状态选择0变，26400初值选择241变。040/041全部16轮结果与旧独立云端证据字段和哈希一致。PR原树全仓191/191、整合树全仓206/206通过；382冻结归档未变，执行器及评分源码无差异。工程Go、HMM方法研究No-Go。未合并PR、未调用真实模型；Gate44A继续只登记。数学误差与证据索引见报告；负结果及首轮缺夹具日志均保留。
