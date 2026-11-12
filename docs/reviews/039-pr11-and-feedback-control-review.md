# Gate 35 · PR #11 独立验收与反馈控制 Review

## 独立 PR 验收（2026-11-12）

审查 GitHub 最新 PR head `b9f4fb23aabeb24f178e3a63b35313576864048c`，base/main `06270a0e1343dbf837e2884971c74805cb28b72e`。GitHub open、mergeable=true；独立云端 detached worktree 审查，不依赖合作者本地测试。云端 tracked 干净；本地仅既有未跟踪 Review，保留。PR 仅4文件：夹具反馈开关、两项测试、038追加说明；原038文本和归档不覆盖。

独立99项ToolMaze+5项防泄漏=104全通过；逐调用复放038全部20回合，真实回执、事件账本、费用与原评分逐字段一致，均使用默认original。旧任务、工具合同、执行器、提示、CPU枚举、既有Agent适配器及评分函数的代码差异为零。证据：云端 `results/039-pr11-cloud-review-01/` 的 toolmaze.log、no-leakage.log、legacy-038-replay.json/log、unchanged-core.diff（空）。云端GitHub fetch因host key失败，随后从本地已验证GitHub对象经SSH同步临时审查ref；未更改云端信任配置。

`specific`仅将写入已被同一条件拒绝后的文字细分，不改变接受谓词、错误码、非法标志、费用、调用预算或副作用。类别：本任务未签发引用、未核验backup pending_ref、记录不符、内容不符；不会输出正确内容、私有Z、噪声准确率、生成律或未来反馈。内容比较只用此前真实回执来源。任务外record_id先由既有范围检查拒绝，因此内部record mismatch分支在正常单记录任务不可达，测试通过内部状态扰动覆盖，不应称为现实新路径。原生工具定义和诊断回执不变。默认条件逐字保持。

PR适配器测试只证明run_episode消费已配置Session；正式episode/CLI未能显式选择并记录write_feedback。这是用户允许的最小补充点，非接受/评分缺陷。PR本身工程Merge Go，已按授权合并为 `f36d094`，推送端云main。

## 控制实验的不可逆评分边界

P05第一次错误写入后已经非法1次，原严格评分要求零非法。因此两组即使修复并完成义务也严格失败；不能重置非法计数、抹掉历史或创造新的“严格成功”。实验039预登记保留此评分，将参数修复/业务义务与完整严格结果分列。控制实验仅移除历史规则在后续SDK上的强制WRITE，两组都变为原生续程；原历史消息和ID直接来自归档。specific仅作用于该第一次拒绝，未来反馈相同。该检查点的结果不能证明早先恢复选路改变或额外付费诊断净价值。
