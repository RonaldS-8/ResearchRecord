# 当前进度（2026-11-05）

Gate 1/2 审计已归档；Gate 3 独立受控诊断 MVP 已完成环境、隔离/评分测试、单任务运行和 10 任务规则策略对照。

- 设计与授权范围：[ADR-0003](adr/0003-controlled-diagnostic-mvp.md)。代码：`extensions/toolmaze_diagnostic_mvp/`；未改原始 Benchmark。
- 18 项必要测试通过，含 `tests/test_no_leakage.py`；一次错误的换序反例构造失败记录已保留，后改为真实依赖负例及独立换序正例。
- 300 条全量轨迹：`/home/ubuntu/Song/Agent/results/005-gate3-full-20261105-01/`；运行提交 `c127428`。低价诊断净省 0.25、高价净亏 0.25，均为固定请求单位和配对状态均值。
- 完整证据、阶段路径、成本与限制：[实验 005](experiments/005-diagnostic-mvp.md)。这是环境验收，没有语言模型或 GPU 推理。
- MVP 请求成本已按用户授权预登记；[全局指标草案](metrics.md)仍待确认，未自动生效。
- 后续模型接入或范围扩展需另行确认和登记；当前不自动推进。继续工作前仍须核对两端状态，保留全部结果。

## Gate 4：用户已批准的后台分阶段任务

- 设计：[实验 006](experiments/006-qwen-minimal-decisions.md)、[ADR-0004](adr/0004-qwen-decision-adapter.md)。新增适配器/运行器，不改 Gate 3 环境或成本。
- 启动器：`scripts/run_gate4_background.sh`。目录约定 `/home/ubuntu/Song/Agent/results/006-gate4-20261105-01/`；实际状态以 `stages.log`、`tests.log`、各阶段日志和 `evaluation.json` 为准，不能仅凭本文认定已完成。
- 顺序：必要测试→明确标记的真实诊断接口自检→018 四情况自主测试→40 情况完整自主对照，任一交互/泄漏/评分失败自动停止。无请求自动重试，不修提示或条件。
- vLLM 0.31.0，Qwen3-4B-Thinking-2507（768f209d…），temperature=1、max_tokens=16000、timeout=300s、seed=0+步号。
- 用户要求跑起来后暂停对话，等其再次呼叫再查；不主动轮询或发进度通知。结果尚未在本交接中认定。
