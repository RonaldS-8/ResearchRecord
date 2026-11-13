# Gate 43A-R 原始证据

这里是实验 042（Gate 42B）与 043A-R 的原始运行文件的逐字节副本，随 PR 提交以便独立核对。项目惯例是结果不入 Git；这次是应要求做的例外，原因是运行机器当时连不上云端，文件总量约 1.7 MB。

## 运行环境

- 机器：Windows 11（`Windows-11-10.0.26200-SP0`），14 个逻辑核。
- Python：`3.14.7 | packaged by Anaconda, Inc. | [MSC v.1942 64 bit (AMD64)]`，虚拟环境 `D:/users/018574/.venvs/researchrecord`。代码只用标准库，没有 numpy。
- 运行方式：仓库根目录下，`PYTHONUTF8=1`，`PYTHONPATH` 为 `benchmarks/ToolMaze`、`tests` 和仓库根；入口 `python -B -m extensions.toolmaze_recovery.belief_rounds --out <目录> --round <轮次> --cell <格> [--seeds 起:止]`。
- 每个文件的格与种子区间就在文件名里；c4 与 d1 的整批启动脚本见 `scripts/launch_c4.sh`、`scripts/launch_d1.sh`（c4 同时跑 13 个进程，d1 同时跑 8 个）。c1–c3 是逐条用同一入口启动的，日志文件名即参数。
- 从 d1 起，结果文件里直接记录 Python 版本、平台和命令；c1–c5 的文件当时没有记录这些，以上是事后补记。

## 目录

| 目录 | 内容 |
| --- | --- |
| `042-gate42b-01/` | 首次作废的启动（提交 `0a3ff9e`）。九个结果文件里八个是空的；`roundc3-all.json` 在进程被终止前已写完，内容与后来登记的 c3 相同。实验文档第 7 节原先说“全是空文件”，不准确，已更正 |
| `042-gate42b-02/` | c1–c3，提交 `e15d829` |
| `042-gate42b-03/` | c4，提交 `9703998` |
| `042-gate42b-04/` | c5，提交 `abf6ee6` |
| `042-gate42b-repro/`、`042-gate42b-repro2/` | 改动运行器之后对已登记轮次的重跑，用来确认校验值不变 |
| `043a-r-01-digest-audit/` | 七处校验值差异的对账：`naive-c4-*.json` 是在本机把 `sum()` 换成逐项相加后重算的结果；`rerun-head/` 是用修复后的代码重跑的三个旧轮次 |
| `043a-r-02-corrected/` | 修正版 d1，提交 `d04415b`，新版本，不是 c4 的复现 |
| `scripts/` | 对账与清单用的脚本、两个启动脚本 |

## 七处差异的逐字段对账

Python 3.12 起内置 `sum()` 对浮点数使用补偿求和，3.11 及以前是逐项相加。原始运行用 3.14.7，独立验收用 3.10.12。`scripts/naive_sum.py` 在同一台机器、同一份代码上只把 `sum()` 换成逐项相加，得到的校验值与独立验收报告里的“独立复算”值逐一相同。下面是原始文件与换求和之后的文件逐字段比较（按序列化后的值比较，所以 `0.0` 与 `-0.0` 算不同）。前七个是不符的文件，后三个是原本就相符的对照。

```text
roundc4-A.json: 3 of 501 fields differ
   /by_size/1000/belief2_snap/completion_estimate_bias 0.0 -> -0.0
   /by_size/300/belief2_snap/completion_estimate_bias 0.0 -> -0.0
   /by_size/3000/belief2_snap/completion_estimate_bias -0.0 -> 0.0
roundc4-controls.json: 6 of 275 fields differ
   /confounded_insider_log/by_size/1000/belief2_snap/completion_estimate_bias -0.0 -> 0.0
   /shift_to_1/10/by_size/1000/belief2_snap/completion_estimate_bias 0.0 -> -0.0
   /shift_to_3/10/by_size/1000/belief2_snap/completion_estimate_bias 0.0 -> -0.0
   /shift_to_9/10/by_size/1000/belief2_snap/completion_estimate_bias 0.0 -> -0.0
   /uniform_log/by_size/1000/belief2_snap/completion_estimate_bias -0.0 -> 0.0
   /uniform_log/by_size/1000/belief2_snap/fee_estimate_bias -0.0 -> 0.0
roundc4-M3-8-6010-6020.json: 1 of 501 fields differ
   /by_size/1000/belief2_snap/completion_estimate_bias -0.0 -> 0.0
roundc4-M3-8-6020-6030.json: 1 of 501 fields differ
   /by_size/1000/belief2_snap/completion_estimate_bias 0.0 -> -0.0
roundc4-M3-8-6040-6050.json: 1 of 500 fields differ
   /by_size/1000/belief2_snap/completion_estimate_bias 0.0 -> -0.0
roundc4-M3-8-6050-6060.json: 1 of 499 fields differ
   /by_size/1000/belief2_snap/completion_estimate_bias -0.0 -> 0.0
roundc4-thin-M3-8-6015-6030.json: 1 of 182 fields differ
   /0.1/by_size/300/belief2_snap/completion_estimate_bias -0.0 -> 0.0
roundc4-M3-8-6000-6010.json: 0 of 501 fields differ
roundc4-E.json: 0 of 500 fields differ
roundc4-S4b-6000-6030.json: 0 of 507 fields differ
```

十四个不同的字段全部是 `0.0` 与 `-0.0` 的差别，数值相等。它们都落在 `belief2_snap` 的自估偏差上：这个量在这些格上的真值就是零，舍入前是正负 1e-17 量级的浮点噪声，符号随求和方式变。没有任何完成率、费用、种子计数或模型选择字段不同。

## 文件清单

校验值是 `result` 字段按键排序序列化后的 SHA-256 前 16 位，与运行器打印的一致。

| 文件 | 字节 | 写入时间 | 记录的提交 | 工作区干净 | result 校验值 | 整个文件 SHA-256 前 16 位 |
| --- | ---: | --- | --- | --- | --- | --- |
| `042-gate42b-01/roundc1-B2R-mini.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc1-E.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc1-E_placebo.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc1-M3-8.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc1-M5.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc1-S4b.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc2-M3-8.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc2-M5.json` | 0 | 2026-11-13 12:02 | 空文件 | – | – | – |
| `042-gate42b-01/roundc3-all.json` | 7292 | 2026-11-13 12:03 | `0a3ff9e` | 是 | `335ee6441b39b37e` | `b3229b0943adfe93` |
| `042-gate42b-02/roundc1-B2R-mini.json` | 17383 | 2026-11-13 12:19 | `e15d829` | 是 | `bdd38dd54cf6bd2c` | `4a6bf5b72fdf2b45` |
| `042-gate42b-02/roundc1-E.json` | 16568 | 2026-11-13 12:14 | `e15d829` | 是 | `dda7709a89d2c2b0` | `51470fea8b81dd85` |
| `042-gate42b-02/roundc1-E_placebo.json` | 16527 | 2026-11-13 12:18 | `e15d829` | 是 | `0a5c2c0f7ca2281e` | `fb128e5f5e31c24f` |
| `042-gate42b-02/roundc1-M3-8-5000-5025.json` | 17120 | 2026-11-13 12:33 | `e15d829` | 是 | `7b6517099f449625` | `3d8ddb9f6617f94c` |
| `042-gate42b-02/roundc1-M3-8-5025-5050.json` | 17168 | 2026-11-13 12:35 | `e15d829` | 是 | `a04e03c3649f8baa` | `6a677367c33e9a90` |
| `042-gate42b-02/roundc1-M3-8-5050-5075.json` | 17125 | 2026-11-13 12:35 | `e15d829` | 是 | `17b28bf939769658` | `b837d7eb71d49043` |
| `042-gate42b-02/roundc1-M3-8-5075-5100.json` | 17131 | 2026-11-13 12:34 | `e15d829` | 是 | `8d60be70f16e8404` | `a03f004f1cbe65ce` |
| `042-gate42b-02/roundc1-M5-5000-5050.json` | 17344 | 2026-11-13 12:39 | `e15d829` | 是 | `a7c7ca0a79c33f5e` | `069aca1798fec4a9` |
| `042-gate42b-02/roundc1-M5-5050-5100.json` | 17424 | 2026-11-13 12:38 | `e15d829` | 是 | `bd6401c90d931ce2` | `e7307065bfa4a455` |
| `042-gate42b-02/roundc1-S4b.json` | 17009 | 2026-11-13 12:21 | `e15d829` | 是 | `d1943f6dbad16fe6` | `676b949c8cb33ed1` |
| `042-gate42b-02/roundc2-M3-8-5000-5030.json` | 6728 | 2026-11-13 12:24 | `e15d829` | 是 | `ece1b93eddc47055` | `59c556852c984889` |
| `042-gate42b-02/roundc2-M3-8-5030-5060.json` | 6709 | 2026-11-13 12:24 | `e15d829` | 是 | `f9003ee51a13d43d` | `466da26b3973e706` |
| `042-gate42b-02/roundc2-M5.json` | 6788 | 2026-11-13 12:27 | `e15d829` | 是 | `4fc41a9e94ce0a2b` | `cb76a1870a3bd3b0` |
| `042-gate42b-02/roundc3-all.json` | 7292 | 2026-11-13 12:09 | `e15d829` | 是 | `335ee6441b39b37e` | `5f1f879de98b4bd7` |
| `042-gate42b-03/roundc4-A.json` | 19040 | 2026-11-13 13:50 | `9703998` | 是 | `d02378bbb6816ebb` | `69f802b2a11ae04e` |
| `042-gate42b-03/roundc4-B2R-mini-6000-6030.json` | 19607 | 2026-11-13 13:59 | `9703998` | 是 | `caa0f8687222fb26` | `2297d067cfecf1da` |
| `042-gate42b-03/roundc4-B2R-mini-6030-6060.json` | 19576 | 2026-11-13 13:59 | `9703998` | 是 | `821b1e456d43e0e9` | `c33659efc313256a` |
| `042-gate42b-03/roundc4-controls.json` | 11515 | 2026-11-13 13:49 | `9703998` | 是 | `bceb45d23e2e16fc` | `92dddb08551f3c84` |
| `042-gate42b-03/roundc4-E.json` | 19017 | 2026-11-13 13:59 | `9703998` | 是 | `ae8c6cc513794471` | `8076533542843513` |
| `042-gate42b-03/roundc4-E_placebo.json` | 18986 | 2026-11-13 14:02 | `9703998` | 是 | `279e9bacda168d46` | `0ae8fd0101643fe8` |
| `042-gate42b-03/roundc4-M3-8-6000-6010.json` | 19261 | 2026-11-13 13:37 | `9703998` | 是 | `43bee7b45e6369a9` | `2cee7beff5315b41` |
| `042-gate42b-03/roundc4-M3-8-6010-6020.json` | 19228 | 2026-11-13 13:46 | `9703998` | 是 | `3cabae470accb96e` | `5f30d349f0561e07` |
| `042-gate42b-03/roundc4-M3-8-6020-6030.json` | 19196 | 2026-11-13 13:48 | `9703998` | 是 | `7ab61d7eb874820f` | `7582f2db64f92d22` |
| `042-gate42b-03/roundc4-M3-8-6030-6040.json` | 19302 | 2026-11-13 13:37 | `9703998` | 是 | `8d2560749f875b4a` | `3237a4d37c01dec2` |
| `042-gate42b-03/roundc4-M3-8-6040-6050.json` | 19181 | 2026-11-13 13:48 | `9703998` | 是 | `e5e99e0fa4e1828b` | `e398d1cfd643a9de` |
| `042-gate42b-03/roundc4-M3-8-6050-6060.json` | 19163 | 2026-11-13 13:50 | `9703998` | 是 | `2c7534dac1ade495` | `ac99ebe91c62d1d3` |
| `042-gate42b-03/roundc4-M5-6000-6015.json` | 19501 | 2026-11-13 13:47 | `9703998` | 是 | `04e266b13c048c92` | `8ef3cdbf8723981a` |
| `042-gate42b-03/roundc4-M5-6015-6030.json` | 19496 | 2026-11-13 13:39 | `9703998` | 是 | `be4930971dd06bd4` | `bd156d950d819b69` |
| `042-gate42b-03/roundc4-M5-6030-6045.json` | 19508 | 2026-11-13 13:54 | `9703998` | 是 | `f02740d25b940bf5` | `801629349b497393` |
| `042-gate42b-03/roundc4-M5-6045-6060.json` | 19515 | 2026-11-13 13:59 | `9703998` | 是 | `6a2def597b7055e4` | `103d4bd506c851aa` |
| `042-gate42b-03/roundc4-S4b-6000-6030.json` | 19655 | 2026-11-13 14:04 | `9703998` | 是 | `1ec38e738d6e7609` | `8abc06b5aebcfb7b` |
| `042-gate42b-03/roundc4-S4b-6030-6060.json` | 19631 | 2026-11-13 14:04 | `9703998` | 是 | `5083820418e6736e` | `687e20b5cfcb8cbe` |
| `042-gate42b-03/roundc4-thin-M3-8-6000-6015.json` | 7470 | 2026-11-13 13:10 | `9703998` | 是 | `7ef48dba7b745c12` | `098859b83e6dc06d` |
| `042-gate42b-03/roundc4-thin-M3-8-6015-6030.json` | 7502 | 2026-11-13 13:15 | `9703998` | 是 | `ae8f8104c1a6f355` | `dccd7678baf41bf1` |
| `042-gate42b-03/roundc4-thin-M3-8-6030-6045.json` | 7511 | 2026-11-13 13:10 | `9703998` | 是 | `15225345063eee5e` | `efec44bf7e58b4d3` |
| `042-gate42b-03/roundc4-thin-M3-8-6045-6060.json` | 7456 | 2026-11-13 13:15 | `9703998` | 是 | `2800c76dac75a0fe` | `a402df652b54a62f` |
| `042-gate42b-03/roundc4-thin-M5-6000-6020.json` | 7514 | 2026-11-13 13:31 | `9703998` | 是 | `15f72c92fd6e2ce0` | `a6f3695f7a72b3cf` |
| `042-gate42b-03/roundc4-thin-M5-6020-6040.json` | 7508 | 2026-11-13 13:36 | `9703998` | 是 | `d63e5ce9b1cae633` | `01de24f118a34529` |
| `042-gate42b-03/roundc4-thin-M5-6040-6060.json` | 7503 | 2026-11-13 13:42 | `9703998` | 是 | `8aed73a498b5aa74` | `ee438594252cc856` |
| `042-gate42b-04/roundc5-A.json` | 5045 | 2026-11-13 14:46 | `abf6ee6` | 是 | `de0daa050f8abcb0` | `72d60613393d057d` |
| `042-gate42b-04/roundc5-B2R-mini.json` | 5182 | 2026-11-13 14:46 | `abf6ee6` | 是 | `d2692984702a61b1` | `39fe4df7d6e09556` |
| `042-gate42b-04/roundc5-controls.json` | 6093 | 2026-11-13 14:46 | `abf6ee6` | 是 | `e36ae0ebccff242c` | `6a1c02859c54d6c4` |
| `042-gate42b-04/roundc5-E.json` | 5007 | 2026-11-13 14:46 | `abf6ee6` | 是 | `e5d6642a634d1d81` | `ea3239ab64d42bb8` |
| `042-gate42b-04/roundc5-E_placebo.json` | 4989 | 2026-11-13 14:46 | `abf6ee6` | 是 | `802e867702f11dcc` | `4392eee9df378586` |
| `042-gate42b-04/roundc5-M3-8.json` | 5204 | 2026-11-13 14:46 | `abf6ee6` | 是 | `0c1472d2b5c759db` | `71b96247aa88076f` |
| `042-gate42b-04/roundc5-M5.json` | 5146 | 2026-11-13 14:46 | `abf6ee6` | 是 | `d19beccc5adde53e` | `603059d2035f580d` |
| `042-gate42b-04/roundc5-S4b.json` | 5133 | 2026-11-13 14:46 | `abf6ee6` | 是 | `2f8a29894f0c4cc1` | `0b0414fc1d1c0dcf` |
| `042-gate42b-04/roundc5-thin-M3-8.json` | 2387 | 2026-11-13 14:46 | `abf6ee6` | 是 | `ce5c5aca29ec7c96` | `26496caaf481a147` |
| `042-gate42b-04/roundc5-thin-M5.json` | 2374 | 2026-11-13 14:46 | `abf6ee6` | 是 | `e97c7eb873cc3a1b` | `871931e00827030d` |
| `042-gate42b-repro/roundc1-E.json` | 16567 | 2026-11-13 12:48 | `e15d829` | 否 | `dda7709a89d2c2b0` | `30d6847852f2bfb4` |
| `042-gate42b-repro/roundc3-all.json` | 7291 | 2026-11-13 12:45 | `e15d829` | 否 | `335ee6441b39b37e` | `089086cdf64db33f` |
| `042-gate42b-repro2/roundc3-all.json` | 7291 | 2026-11-13 14:36 | `0614cf9` | 否 | `335ee6441b39b37e` | `d8bf5692fbf2103e` |
| `043a-r-01-digest-audit/naive-c4-A.json` | 19082 | 2026-11-13 15:35 | `–` | – | `975a49a350557f7a` | `467daf8efc042e8e` |
| `043a-r-01-digest-audit/naive-c4-controls.json` | 11556 | 2026-11-13 15:34 | `–` | – | `c046de6241dd0172` | `c4219645739b306d` |
| `043a-r-01-digest-audit/naive-c4-E.json` | 19058 | 2026-11-13 15:56 | `–` | – | `ae8c6cc513794471` | `d394026190d60aed` |
| `043a-r-01-digest-audit/naive-c4-M3-8-6000-6010.json` | 19302 | 2026-11-13 16:25 | `–` | – | `43bee7b45e6369a9` | `da329cb8b2f16b90` |
| `043a-r-01-digest-audit/naive-c4-M3-8-6010-6020.json` | 19268 | 2026-11-13 16:22 | `–` | – | `05408707d1e1f90a` | `d6dd9978f4a28194` |
| `043a-r-01-digest-audit/naive-c4-M3-8-6020-6030.json` | 19238 | 2026-11-13 16:24 | `–` | – | `ea954691861f60ec` | `eb302ab8e3444661` |
| `043a-r-01-digest-audit/naive-c4-M3-8-6040-6050.json` | 19223 | 2026-11-13 16:22 | `–` | – | `e5fd7850bfccc9cd` | `c6833913ff1ecdeb` |
| `043a-r-01-digest-audit/naive-c4-M3-8-6050-6060.json` | 19203 | 2026-11-13 16:25 | `–` | – | `eb6e59540a7b8a2c` | `abbd747697be4c05` |
| `043a-r-01-digest-audit/naive-c4-S4b-6000-6030.json` | 19696 | 2026-11-13 16:17 | `–` | – | `1ec38e738d6e7609` | `5b0696ff8d783074` |
| `043a-r-01-digest-audit/naive-c4-thin-M3-8-6015-6030.json` | 7542 | 2026-11-13 15:48 | `–` | – | `7294ab2ab5edbc8f` | `944d3e561b8b5608` |
| `043a-r-01-digest-audit/rerun-head/roundc3-all.json` | 7612 | 2026-11-13 15:48 | `e457e91` | 否 | `335ee6441b39b37e` | `5e6750359550734b` |
| `043a-r-01-digest-audit/rerun-head/roundc4-A.json` | 19369 | 2026-11-13 15:50 | `e457e91` | 否 | `d02378bbb6816ebb` | `055c03e5c3f9d6e6` |
| `043a-r-01-digest-audit/rerun-head/roundc5-E.json` | 5336 | 2026-11-13 15:47 | `e457e91` | 否 | `e5d6642a634d1d81` | `48594b7d8b4bba16` |
| `043a-r-02-corrected/roundd1-A.json` | 20391 | 2026-11-13 17:04 | `d04415b` | 是 | `fd1541e0b6e28801` | `0f2c213d2aa317d7` |
| `043a-r-02-corrected/roundd1-B2R-mini-6000-6030.json` | 21047 | 2026-11-13 17:08 | `d04415b` | 是 | `b51dd596e5e29a37` | `f1a7187daec713f5` |
| `043a-r-02-corrected/roundd1-B2R-mini-6030-6060.json` | 21036 | 2026-11-13 17:09 | `d04415b` | 是 | `8be7b9d07c16d9cd` | `618ec382243fc039` |
| `043a-r-02-corrected/roundd1-controls.json` | 21864 | 2026-11-13 17:04 | `d04415b` | 是 | `8053b2a2daed37e4` | `e480f7c4e0e51ef7` |
| `043a-r-02-corrected/roundd1-E.json` | 20295 | 2026-11-13 17:07 | `d04415b` | 是 | `bb1f332df2efb6d4` | `75548ea9a847dfdf` |
| `043a-r-02-corrected/roundd1-E_placebo.json` | 20284 | 2026-11-13 17:09 | `d04415b` | 是 | `51ac7084872b157d` | `1b849f9836875e1e` |
| `043a-r-02-corrected/roundd1-M3-8-6000-6010.json` | 20559 | 2026-11-13 16:36 | `d04415b` | 是 | `db47be9e4346e86c` | `33c7b6abee642131` |
| `043a-r-02-corrected/roundd1-M3-8-6010-6020.json` | 20368 | 2026-11-13 16:33 | `d04415b` | 是 | `43d7e393a0fb04f2` | `aa85d89dcf9aaa9b` |
| `043a-r-02-corrected/roundd1-M3-8-6020-6030.json` | 20483 | 2026-11-13 16:34 | `d04415b` | 是 | `08a1b5e5c6e98790` | `a525cf7ba776ea55` |
| `043a-r-02-corrected/roundd1-M3-8-6030-6040.json` | 20581 | 2026-11-13 16:36 | `d04415b` | 是 | `f0a7e877a4c7b102` | `236fc74faca2211c` |
| `043a-r-02-corrected/roundd1-M3-8-6040-6050.json` | 20462 | 2026-11-13 16:34 | `d04415b` | 是 | `f36bc34cbce4963e` | `3826cd84ec5f1ab3` |
| `043a-r-02-corrected/roundd1-M3-8-6050-6060.json` | 20476 | 2026-11-13 16:35 | `d04415b` | 是 | `2b483f43d72510e1` | `a9c125db629873dc` |
| `043a-r-02-corrected/roundd1-M5-6000-6015.json` | 20730 | 2026-11-13 16:51 | `d04415b` | 是 | `ac0f65ce12d8e103` | `50a544460ffa8fb1` |
| `043a-r-02-corrected/roundd1-M5-6015-6030.json` | 20737 | 2026-11-13 16:54 | `d04415b` | 是 | `fdf15d0a9c20b12b` | `bdfbaf0459009a03` |
| `043a-r-02-corrected/roundd1-M5-6030-6045.json` | 20808 | 2026-11-13 17:02 | `d04415b` | 是 | `5d852ee12853df14` | `fb754f90b760f3f7` |
| `043a-r-02-corrected/roundd1-M5-6045-6060.json` | 20770 | 2026-11-13 17:01 | `d04415b` | 是 | `4b4e9950b9989e4a` | `ce6746234d2b58e2` |
| `043a-r-02-corrected/roundd1-S4b-6000-6030.json` | 20890 | 2026-11-13 17:02 | `d04415b` | 是 | `bdcf1dabc5a8c357` | `2d175c3bc69a920d` |
| `043a-r-02-corrected/roundd1-S4b-6030-6060.json` | 20922 | 2026-11-13 17:12 | `d04415b` | 是 | `dd5426406ee04f48` | `7c9e93ea2b2aae58` |
| `043a-r-02-corrected/roundd1-thin-M3-8-6000-6015.json` | 8983 | 2026-11-13 16:08 | `d04415b` | 是 | `d31db5e82cb5ffb8` | `7c0cdad1eb0db450` |
| `043a-r-02-corrected/roundd1-thin-M3-8-6015-6030.json` | 9026 | 2026-11-13 16:09 | `d04415b` | 是 | `b2bafa222f9483df` | `6304d4cf86ec5b9f` |
| `043a-r-02-corrected/roundd1-thin-M3-8-6030-6045.json` | 8991 | 2026-11-13 16:24 | `d04415b` | 是 | `0133a3a9fe2a09fc` | `6e49637d4915a0cb` |
| `043a-r-02-corrected/roundd1-thin-M3-8-6045-6060.json` | 8986 | 2026-11-13 16:24 | `d04415b` | 是 | `ad3a92d9e6c351fd` | `6cff0b71cc8108f9` |
| `043a-r-02-corrected/roundd1-thin-M5-6000-6020.json` | 8891 | 2026-11-13 16:50 | `d04415b` | 是 | `95cb3bc3decf9524` | `550fd23482bea1f3` |
| `043a-r-02-corrected/roundd1-thin-M5-6020-6040.json` | 8868 | 2026-11-13 16:51 | `d04415b` | 是 | `b2a40a5222d0d704` | `9a7c03be8dd188a3` |
| `043a-r-02-corrected/roundd1-thin-M5-6040-6060.json` | 8849 | 2026-11-13 16:51 | `d04415b` | 是 | `a4fc87c4475e70bd` | `669aabf607abe90e` |
