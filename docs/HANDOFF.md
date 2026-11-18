# 研究交接 · 路径恢复

## 2_010 · 已暂停，等待接手

2026-11-18，新加坡时间约 22:36。根据用户要求暂停，当前没有本轮 GPU 或模型执行进程。请取得用户恢复指示后再启动实验。工作分支 `codex/2_010-method-reproduction`，基线 `research/route-recovery@c0e582d`。云端工作树 `/home/ubuntu/Song/Agent-worktrees/route-recovery-2_010`。原始数据留在 LabServer。完整证据摘要和实验边界见[审计](reviews/2_010-method-reproduction-audit.md)与[预登记](experiments/2_010.md)。

| 工作包 | 当前状态 | 完成证据 |
| --- | --- | --- |
| A 历史瓶颈 | 完成 | 复核 045、046、047 及 2_009 的原始请求和动作。2_009 的 78 个原始文件哈希一致。前五候选静态覆盖 8/20，原绑定器逐条隔离执行严格通过 0/20。天气提示救回的是取数工具，模型自行改接归档。评分另有表示误拒。 |
| B 作者实现 | 暂停 | ToolAtlas 指定仓库公开 404，GOAT 核查到实际调用和训练代码，选 In-N-Out 为主复现对象。原作者的边分类 5/12，无图选择独立复算 15/20。自动图与人工金图未运行。 |
| C M4 迁移 | 暂停 | 脚手架和 CPU 接线通过。真实 Agent 0 回合，原评分与检查点保持冻结。 |

### 运行位置和恢复顺序

1. 保留 `/home/ubuntu/Song/Agent/results/2_010-repro-02`。其中 `upstream/requests.jsonl` 共 32 行，12 次边分类和 20 次无图选择。最后一次 6144 Token 全为思考，`finish_reason=length`、正文为空。作者 `select_gold_api_with_llm` 在对 `None` 检查代码块时抛出 TypeError。网络故障发生在读取产物时，原日志已恢复读取并确认 Python 错误为退出原因。
2. 用新的结果目录补好上游薄适配。对空正文作明确弃选并保留原响应与截断标签。避免重发已完成的 32 个请求。无图的排名可从同一 MiniLM 和合同复算，其 19 条已解析选择及截断可从原始文件重建。补跑固定前 8 条任务的自动图与人工金图，每组 20 目标。使用相同 4B 模型、固定次序、原作者选择提示与同一 MiniLM。第 02 批已用掉 80 次本地请求上限中的 32 次，剩余 48 次，原 30 分钟服务预算剩 15 分 58 秒。预算变更先说明。原作者补齐候选的分支依赖评测标签，忠实复核须披露，迁移禁止该依赖。
3. 待无图、自动图关键链与预登记条件满足后再启动 M4。运行器为 `extensions/route_recovery/reproduce_in_n_out_m4.py`。隔离目录 `/home/ubuntu/Song/Agent-worktrees/2_010-upstream` 有锁定作者仓库、NESTful 公开数据、`minilm/`、依赖 `deps/` 和起草的 `launch-m4.sh`。旧启动脚本绑定第 02 批，续跑后需以新的产物路径验证门槛。新阶段单卡上限 15 分钟、72 个本地请求。五组为原生、同名字段强规则、知情人工路线、自动图、同图加隔离执行证据。若规则与图输出相同，提示内容匹配并按同等结构知识解释。只允许本地模拟，一次见过的检查点仅用于开发，后续独立任务须另行登记。
4. 两个新 Python 入口及核心记录已提交。原作者依赖处于隔离目录，原执行器和评分未改。云端原始路径还包括 `results/2_010-candidate-replay-01/cases.jsonl`。在提交最终结果前同步专用分支，继续验证模型自主执行及逐实参复放。费用分列构图模型、重置和验证调用、Agent 在线模型与工具及独立重放。

## 较早交接

2026-11-18。当前暂定问题、Gate 053–058 证据和代码入口见[当前研究](CURRENT.md)。在 `research/route-recovery` 上接续，从 `gate058-execution-memory` 的 `d916949` 起步。

Gate 059 已完成。两条预留路线取得动态信息增量，证据记忆与同检查普通缓存持平。运行源码 `820fd9a`、结果 `bc796e4`，原始产物保存在 LabServer 的 `results/059-dynamic-evidence-01/`。本次接入复核了已有独立审计和两个产物的 SHA-256，摘要也与 Git 证据一致。[实验 059](experiments/059-dynamic-execution-evidence.md) · [结果审查](reviews/059-dynamic-evidence-results.md) · [库存投影 ADR](adr/0034-observable-reservation-projection.md)

Gate 001–052 已逻辑归档。原始交接与证据链接见[完整历史交接](archive/handoff-d916949.md)，研究定义的待确认差异和目录依赖见[归档索引](archive/README.md)。
