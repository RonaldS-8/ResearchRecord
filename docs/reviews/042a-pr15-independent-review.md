# Gate 42A · PR #15 独立 CPU 验收

2026-11-13。科研问题仍为 Decision-aware Diagnosis for Efficient Agent Recovery。本报告只验收 CPU 数学模型、复现和工程隔离；不把参照值当作真实 Agent 价值，不新增隐藏状态学习方法。

## 固定版本与边界

GitHub PR #15：`research/decision-recovery-autoresearch`，审查 head **9eb2890c6cf303bbe4ec9a5ab55e5df7aacaa062**；base/main **86a42e16dcc23020c2a9b2f49ba623364a2d6cf5**。开始时 GitHub open、mergeable=true；端云 tracked 干净，本地既有5份未跟踪Review保留。云端独立detached worktree `/home/ubuntu/Song/Agent-gate42a-review` 固定head，原main不切换；只读链接现有ToolMaze数据，复用 `.venv`，没有安装依赖或启动模型。

已阅读AGENTS、ADR-0033、实验037–041、038/039失败报告及PR全部新增模型/轮次/测试。PR共11个新增文件、3608行，无删除和旧文件修改。冻结037–039、Gate34/35夹具、原Session/ContractExecutor、评分、提示、benchmarks代码差异均为空，证据 `frozen-core.diff`。新模型的合法性是进度图和预算上的宏观合法性；参数绑定、真实凭据、终答等执行风险仍属于未来Agent验证。

## 云端完整测试与全部登记轮次

固定head上 **134项test_toolmaze*.py + 5项test_no_leakage.py =139项全部通过**，含Gate40的16项和Gate41的15项，旧测试未修改。全部轮次使用登记入口与默认参数，只把输出目录换成本次独立目录：

```bash
/home/ubuntu/Song/Agent/.venv/bin/python -m unittest discover -s tests -p 'test_toolmaze*.py'
/home/ubuntu/Song/Agent/.venv/bin/python -m unittest discover -s tests -p test_no_leakage.py
/home/ubuntu/Song/Agent/.venv/bin/python -m extensions.toolmaze_recovery.autoresearch_rounds --out /home/ubuntu/Song/Agent/results/042a-pr15-independent-review-01/040-rounds
/home/ubuntu/Song/Agent/.venv/bin/python -m extensions.toolmaze_recovery.multipath_rounds --out /home/ubuntu/Song/Agent/results/042a-pr15-independent-review-01/041-rounds
```

| 040轮次 | result SHA-256前16位 | 041轮次 | result SHA-256前16位 |
| --- | --- | --- | --- |
| R0 | a7684f354d00a966 | A1 | 4648ff2ce2501b59 |
| R1 | 35cebcf3d8f74b0f | A2 | 6a8d61c5e90e2c0f |
| R2 | 77623d2eac9dd7ae | A3 | 877834dd888f3de8 |
| R3 | 1cb3213a5f59a4f1 | B1 | 642f954bc480bec7 |
| R4 | 93a7be07c622d0fa | B2 | 6108430517d7015d |
| R5 | 9ef326c6f7dc0f5f | B3 | 834a4e66e74d7109 |
| R6 | 07e80b14671615a6 | B4 | 9f6c676d3e6d3471 |
| R7 | 8c10c2cb530d765b | | |
| R8 | 8ddb26d6b7e7dea6 | | |

哈希仅覆盖按登记方式序列化的result字段，不含提交元数据；每个原始JSON另保存实际审查SHA及dirty=false。目录中的文件独占创建，没有覆盖或改参数追平结果。CPU环境Python3.10.12；日志、输出、进程/命令、校验表均留云端。

## 独立数学与评分核验

除重跑提交方代码外，另写 `independent-values.py`：手工从登记定义构造M3/M4的状态、费用和进度转换，以独立缓存有理数递归计算public/blind/oracle及指定规则；递归不调用PR的solve/value。完成后才调用被审接口逐项对照。另枚举互斥路径所有排列计算81格，并用独立递归重算两种预算各630对先验。

| 格 | 公共最优(完成率,费) | 盲目最优 | Oracle | 先重试一次的登记顺序 |
| --- | --- | --- | --- | --- |
| M3，余量8 | (1,53/10) | (1,169/30) | (1,14/3) | (1,61/10) |
| M3，余量6 | (1,16/3) | (1,169/30) | (1,14/3) | (23/30,47/10) |
| M4，余量6 | (1,68/15) | (1,23/5) | (1,119/30) | (7/10,121/30) |

费用是从首错后开始的无条件期望，包括失败和停止分支；不是只在成功回合中平均。先重试顺序明确为M3 primary→backup→validate→archive、M4 primary→backup→writer→altwriter；不能混用PR中另一条按工具排列产生的命名顺序。M3/M4中重复确定失败工具被严格支配，工具失败上限0/1/2的优先顺序足以覆盖相应固定顺序最优；不把这个有限候选集称为任意LLM策略空间。

**百分比分母。** 041表中“盲目策略比公共最优多花”是差额÷公共最优，M3-8=10/159=6.2893%，M3-6=9/160=5.625%，M4=1/68=1.4706%。A3中“相对盲目的节省”则差额÷盲目费用，同三格为10/169=5.9172%、9/169=5.3254%、1/69=1.4493%。Oracle相对盲目的节省同样用盲目费用作分母，分别29/169、29/169、19/138。百分比和完成率百分点分开，不把不同分母都写成同一“收益”。

互斥路径闭式来自先验加权的失败调用浪费：W=FΣ(i−1)π_(i)，盲目费R+W，Oracle费R，相对节省W/(R+W)。独立81格逐排列与闭式/被审求解一致；单位价、尾部2、均匀先验的K=2/3/4为1/7、1/4、1/3；无尾部K=4上限3/5。25%上界仅适用于此前两路径且可靠备用等假设，不能直接推广。两个630对先验扫描的上下文节省中位数均1/48，最大1/6；≥5%的对数为214（预算8）及215（预算6），Oracle最大5/24，盲目/公共完成率差的对数均0。

另写 `independent-learned.py`，复用合法随机日志和学习器，但不调用PR的value/at_root/solve评分。用登记的确定状态逐条回放策略实际动作，并按私有先验在评价侧加权。全部200个留出种子、3格、N=100/3000、5种规则的60个完成率/费用汇总指标与B2逐字段一致。示例：

| 格 / N | 严格规则 完成率 / 费 | 区间z=1保护 完成率 / 费 |
| --- | --- | --- |
| M3-8 / 100 | .86517 / 5.3402 | .84233 / 5.2188 |
| M3-8 / 3000 | .99117 / 5.3135 | .98567 / 5.2965 |
| M3-6 / 100 | .86417 / 5.0772 | .81900 / 4.8125 |
| M3-6 / 3000 | .99567 / 5.3230 | .98983 / 5.2913 |
| M4 / 100 | .94083 / 4.5218 | .91450 / 4.4043 |
| M4 / 3000 | 1.00000 / 4.5333 | 1.00000 / 4.5333 |

这些完成率是200个CPU学习策略在登记测试分布上的精确完成概率的平均，不是200个真实Agent回合的经验完成率。较低费用若伴随完成率损失，不能称为效率优势。

## 信息隔离与科研解释边界

普通策略接收View：上下文、报价、公开动作反馈、预算及041的公开工具进度图。Planner只保留图/公开结果字母表/合法日志计数，不保存私有状态先验或Oracle表。故意知情的insider日志仅用于显式标记的混杂负对照，状态不写入学习日志，不能混作合法随机分配历史。公开最优知道登记生成律但不知道本回合Z；Oracle额外知道Z而不知未来随机数；真实Agent价值仍unknown。

“无需历史的最强顺序”仍由真实生成律离线挑选，属于理论类参照，不能当作已经冻结、未经调优的实际简单规则。宏观模型把必成尾部折叠计费；它不验证真实参数、凭据、额外核验、非幂等写入或最终答复。因此CPU匹配不能代替真实执行器验收，更不能填充Q^π_Agent。

固定容差、区间、非劣及未试工具回退的负结果保留；没有因独立核验改动参数或结果。有限样本的未收敛不能单独证明所有估计器都不可能收敛，“需要隐藏状态估计”仅是候选方向，不是由这些实验唯一推出的必要方法。本轮不授权该方法。Bench2Robust拆解中的论文事实和代码可得性是合作者注明来源的材料；本轮核查其CPU重建与ToolMaze本地代码，并未重新开展文献检索或声称复现原论文Benchmark。

## 验收结论

**PR工程验收Go。** 139项测试、16轮全部登记哈希、独立上界/精确值与60个学习评分汇总指标全部通过，没有修改任何参数或结果。一次只读SSH连接中断，后台B4正常完成，没有重启轮次。全部原始日志、独立脚本与结果在 `/home/ubuntu/Song/Agent/results/042a-pr15-independent-review-01/`。按用户“先验收再决定是否合并”的授权，决定合并该已审head；随后仅推进两个真实执行器开发检查点，模型比较仍未批准。合并SHA及执行器准备证据后补记。
