# Gate 35 · PR #11 独立验收与反馈控制 Review

## 独立 PR 验收（2026-11-12）

审查 GitHub 最新 PR head `b9f4fb23aabeb24f178e3a63b35313576864048c`，base/main `06270a0e1343dbf837e2884971c74805cb28b72e`。GitHub open、mergeable=true；独立云端 detached worktree 审查，不依赖合作者本地测试。云端 tracked 干净；本地仅既有未跟踪 Review，保留。PR 仅4文件：夹具反馈开关、两项测试、038追加说明；原038文本和归档不覆盖。

独立99项ToolMaze+5项防泄漏=104全通过；逐调用复放038全部20回合，真实回执、事件账本、费用与原评分逐字段一致，均使用默认original。旧任务、工具合同、执行器、提示、CPU枚举、既有Agent适配器及评分函数的代码差异为零。证据：云端 `results/039-pr11-cloud-review-01/` 的 toolmaze.log、no-leakage.log、legacy-038-replay.json/log、unchanged-core.diff（空）。云端GitHub fetch因host key失败，随后从本地已验证GitHub对象经SSH同步临时审查ref；未更改云端信任配置。

`specific`仅将写入已被同一条件拒绝后的文字细分，不改变接受谓词、错误码、非法标志、费用、调用预算或副作用。类别：本任务未签发引用、未核验backup pending_ref、记录不符、内容不符；不会输出正确内容、私有Z、噪声准确率、生成律或未来反馈。内容比较只用此前真实回执来源。任务外record_id先由既有范围检查拒绝，因此内部record mismatch分支在正常单记录任务不可达，测试通过内部状态扰动覆盖，不应称为现实新路径。原生工具定义和诊断回执不变。默认条件逐字保持。

PR适配器测试只证明run_episode消费已配置Session；正式episode/CLI未能显式选择并记录write_feedback。这是用户允许的最小补充点，非接受/评分缺陷。PR本身工程Merge Go，已按授权合并为 `f36d094`，推送端云main。

## 控制实验的不可逆评分边界

P05第一次错误写入后已经非法1次，原严格评分要求零非法。因此两组即使修复并完成义务也严格失败；不能重置非法计数、抹掉历史或创造新的“严格成功”。实验039预登记保留此评分，将参数修复/业务义务与完整严格结果分列。控制实验仅移除历史规则在后续SDK上的强制WRITE，两组都变为原生续程；原历史消息和ID直接来自归档。specific仅作用于该第一次拒绝，未来反馈相同。该检查点的结果不能证明早先恢复选路改变或额外付费诊断净价值。

## 最小适配补充及正式验收

用户允许必要补充，已在main提交 `35f1f36f9f1000482652d8cb094b257d2f305829`：

- gate34b.py：episode/CLI显式接收并归档write_feedback，默认original；run_episode支持原归档messages与剩余SDK上限；P05恢复函数用真实合同重放原前缀，仅在第五次拒绝使用指定文案，之后回到original。首个SDK请求在发送前对照归档完整字段，任何非登记变化均失败留档。原始业务合同、执行器、评分及底层Agent未改。
- gate35.py：短期两回合固定入口，原生续程、不补跑、目录拒绝覆盖。复用episode已有SDK记录与实际调用链，不建立新框架。
- test_toolmaze_gate34b.py：4项必要CPU测试覆盖保留真实消息/调用ID、单回执差异与未来反馈复原、预算/历史非法不重置、公共回执可修复但完整严格失败、拒绝污染前缀、条件与首请求归档及不覆盖。假客户端只是协议测试，不当作真实Agent结果。

正式main干净且端云同步，103项ToolMaze+5项防泄漏=108项全通过，passed-commit等于35f1f36。新增代码未改gate34a评分或旧任务。20个旧038回合再次逐条复放通过。开发两批日志（12项、补充完整归档后13项）均保留；未出现模型前CPU失败后删档。源文件哈希及提交锁在 `results/039-feedback-control-cpu-01/`。PR审查worktree仅临时只读数据链接，清理不影响原数据。

## 真实两回合与独立事后核验

先提交预登记 `10a97358dced58d66d68ad62c97bdf8db716a717`，后运行35f1f36；vLLM0.31.0、SDK3.42.0、Python3.10.12及五项模型文件下载修订元数据均核对768f209d9ea81521153ed38c47d515654e938aea。system哈希与038/33的55b343e13c8838cecf38d8d15c159f03429b17d8a34131468d9865c569cdad90一致。启动复用原脚本，输出不覆盖。

两回合3个SDK请求，独立audit通过：首请求只有登记error字符串不同；所有请求无tool_choice，seed3301/temperature0/max_tokens6144/timeout120一致；检查点Assigned全部null，实际动作/实参独立记录；全事件CPU重放、账本/费用/评分一致；完整历史038的141文件哈希未变。SDK无错误/截断，未追加样本。原SDK返回reasoning字段已保存，不推测内部因果。

original只返回终答，错误归因为evidence_ref，无新增调用，后续执行费0。specific最终文本识别content mismatch，实际却合法调用read_primary_record，超时后以Blocked停止，后续执行费1、没有新增诊断。两组新增非法均0，原前缀非法1；都未修复内容、实际写入0、回读0、业务义务未完成、strict=false，剩余预算2/1。specific虽然在保存推理中讨论句号，却反复考虑去掉句号；实际没有生成修复后的写入参数。只能说错误类别识别和动作有所改变，不能说已正确定位差异或修复成功。

只读CPU修复见证从同一公共历史提取content与证书，真实写入+回读两步均可完成义务，但strict仍false；额外主读后证书仍可写，剩余预算不够回读。原生失败不是合同缺少合法路径；该CPU见证不补入真实轨迹，不变成Q^π_Agent。original词面valid_answer=true而specific=false是既有格式检查，两组实质失败不依赖该差别。

本对未支持“仅澄清错误类别足以让此次P05原生续程完成”的开发假设；不能排除其他样本的反馈作用，也不能把两回合当总体因果效应估计。没有新增付费诊断，因此无诊断净价值证据。工程Go，P05文案充分解释No-Go；下一轮仅提出既有E中信息/无信息诊断与自然ReAct的最多12回合草案，尚未运行、未经新批准不启动。细表、终答、费用和下一设计见实验039。

云端目录：039-pr11-cloud-review-01（固定head审查）；039-feedback-control-cpu-dev-01/02（开发协议测试）；039-feedback-control-cpu-01（正式108项、版本/请求前验、旧20复放、CPU修复见证）；039-feedback-control-agent-01/original和specific（config/checkpoint/完整requests/result）；039-feedback-control-service-01（环境/模型、原归档哈希、预期请求、audit.py/json/log、服务日志/进程/GPU）。服务进程组2209697已退出，GPU464MiB，无新模型运行。仅派生报告同步本地，原始轨迹和数据留云端。
