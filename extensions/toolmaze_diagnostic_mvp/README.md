# ToolMaze 受控诊断 MVP

仅在 LabServer 项目根目录运行；原始 ToolMaze、数据和模型不下载本地。本扩展不训练、不调用模型，策略选择恢复动作，实际工具流程由模板绑定展开。

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m extensions.toolmaze_diagnostic_mvp.run --smoke --out results/新的单任务目录
.venv/bin/python -m extensions.toolmaze_diagnostic_mvp.run --out results/新的十任务目录
```

输出目录必须不存在；不会覆盖已有失败或结果。`config.json` 固定任务和价格，修改需按 AGENTS.md 和实验登记要求处理。

策略只调用 `policies.choose(name, public_view)` 返回动作字符串，由运行器调用私有环境。`oracle.py` 是独立、明示的知情参照。不要把环境实例、审计记录或数据目录交给策略。诊断结果是唯一主动付费状态通道；失败重试仍合法提供信息。原始错误对照不开放诊断，单独存档。

`verification.py` 复用原生 Judge，并检查本子集的完整节点、实际参数绑定和调用重放；它不是全量通用验证器，也不验证现实世界服务的业务正确性。结果逐条保存全部公共输入、私有原始输出、成本和两种评分。完整任务成功与成本分别报告，失败的低花费不作为优胜结果。

本 MVP 的费用是预登记抽象请求单位：顶层工具尝试 1、诊断 0.25/0.75，复合工具内部工作不另计。有关设计、理论收益、限制与运行证据见 `docs/adr/0003-controlled-diagnostic-mvp.md` 和 `docs/experiments/005-diagnostic-mvp.md`；不将其当作真实货币或模型算法收益。
