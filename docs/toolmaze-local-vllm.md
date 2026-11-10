# ToolMaze 本地权重服务配置（在云端运行）

这里的“本地权重”指 LabServer 磁盘上的权重，不是 Mac 上的文件。

## 本次修改

以下路径相对于 `benchmarks/ToolMaze/`：

| 文件 | 修改及原因 |
| --- | --- |
| `evaluation/configs/openai_eval_config_c1.yaml` | 默认 Agent 改为 `vllm`，模型名改为 `Qwen3-4B-Thinking-2507`，地址改为 `http://127.0.0.1:8000/v1`，占位密钥为 `EMPTY`，请求超时为 300 秒。 |
| `evaluation/scripts/serve_local_vllm.sh` | 新增启动脚本，定位云端 `models` 下的权重，设置虚拟环境 PATH、Qwen3 推理解析和 Hermes 工具调用解析。单卡上下文上限为 32768 token，并发上限为 2。 |
| `evaluation/agents/openai_agent.py` | 将写死的 45 秒请求超时改为构造参数 `request_timeout`，默认值仍为 45 秒。 |
| `evaluation/agents/vllm_agent.py` | 接收并传递请求超时参数。 |
| `evaluation/scripts/run_eval.py` | 创建 vLLM Agent 时读取 YAML 中的 `request_timeout`。 |

原命令默认读取的就是 `openai_eval_config_c1.yaml`，所以本次修改该文件。另一个 `eval_config.yaml` 未修改，若通过 `--config` 显式选择它，需要单独配置。

## 启动和运行

在 LabServer 第一个终端运行；若 8000 端口已有该服务，无需重复启动：

```bash
cd /home/ubuntu/Song/Agent/benchmarks/ToolMaze
bash evaluation/scripts/serve_local_vllm.sh
```

在 LabServer 第二个终端运行：

```bash
source /home/ubuntu/Song/Agent/.venv/bin/activate
cd /home/ubuntu/Song/Agent/benchmarks/ToolMaze
curl http://127.0.0.1:8000/v1/models
python evaluation/scripts/run_eval.py --task-id C1_task_001_P0 --inference-only
python evaluation/scripts/run_eval.py --task-id C1_task_001_P1 --inference-only
```

首次请求可能触发 CUDA 组件编译。启动脚本将 `.venv/bin` 加入 PATH，确保能找到已安装的 `ninja`。Thinking 模型生成推理内容需要时间，因此当前请求超时设为 300 秒。

## 以后切换权重

`MODEL_PATH` 是云端磁盘目录；`MODEL_NAME` 是服务对外的名称，需要与 YAML 的 `agent.model` 一致。对兼容当前解析器的模型，可以在重启服务时指定：

```bash
MODEL_PATH=/home/ubuntu/Song/Agent/models/另一个模型目录 \
MODEL_NAME=另一个模型名 \
bash evaluation/scripts/serve_local_vllm.sh
```

再将 YAML 的 `agent.model` 改为相同名称。若换到其他模型家族，需要根据该模型核实推理解析器、工具解析器和聊天模板，不能直接假设当前参数适用。

## 已验证范围

2026-11-02 在 RTX 4090 上验证：模型权重加载成功，P0 完成四次工具调用并输出最终答案；P1 成功调用工具，但收到模拟的 `Service Temporarily Unavailable` 后终止，没有重试。这说明接口和工具调用流程已连通，不代表 P1 任务通过。

当前只运行 `--inference-only`，Judge 未配置。该脚本仍会输出空的指标汇总，不应将其当作已判分结果。

结果位于云端 `evaluation/results/Qwen3-4B-Thinking-2507/fc/c1/inferences/`。脚本发现同名已有结果时会复用缓存；要重新生成，应先将对应推理结果移动到备份位置。当前后台服务日志为 `/home/ubuntu/Song/Agent/logs/toolmaze-vllm.log`。
