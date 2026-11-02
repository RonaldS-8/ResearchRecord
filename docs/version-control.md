# 本地与云端版本同步

## 两端结构

每次任务先选定一端修改，只实施一次；另一端通过提交同步。云端完成运行验证，本地用于说明、阅读和文档管理。切换修改端之前，应先提交并同步，确认两端没有遗留改动。不要在同一任务中独立修改两份代码。

本地 `/Users/ronald/Research/Learning/Agent/Master_thesis` 对应云端 `/home/ubuntu/Song/Agent`。仓库根目录内只有一个 `.git`，ToolMaze 和 CostBench 都是普通子目录。

本地 `origin` 指向 `LabServer:/home/ubuntu/Song/Agent`，默认分支为 `main`。云端是带工作目录的仓库，并配置了 `receive.denyCurrentBranch=updateInstead`：本地推送成功时会同步更新云端工作文件；若云端有未提交修改，Git 会拒绝覆盖，需要先提交或处理这些修改。

此设置保存在云端 `.git/config` 中，不是版本文件。重建云端仓库时需要重新设置：

```bash
git config receive.denyCurrentBranch updateInstead
```

## 云端修改，本地查看

先在云端提交，再在本地拉取。以下提交示例用 `git add -A`，提交前先检查差异：

```bash
# 云端终端
cd /home/ubuntu/Song/Agent
git status --short
git diff
git add -A
git diff --cached --stat
git commit -m "Describe the change"
```

```bash
# 本地终端
cd /Users/ronald/Research/Learning/Agent/Master_thesis
git pull --ff-only
```

## 本地修改，推送到云端

```bash
cd /Users/ronald/Research/Learning/Agent/Master_thesis
git pull --ff-only
# 阅读或修改文件后
git diff
git add -A
git diff --cached --stat
git commit -m "Describe the change"
git push
```

推送更新磁盘上的源码，不会自动重启已运行的 vLLM 或实验进程。模型服务参数变更后需要重启对应服务；避免在实验运行时推送相关代码。

两端同时修改时，先提交各自的改动，再合并；`--ff-only` 遇到分叉会停止，便于检查，勿直接强制推送或重置工作文件。

## 查看修改

```bash
git log --oneline -5
git show --stat HEAD
git diff
git diff HEAD~1 HEAD -- benchmarks/ToolMaze
```

本地无需安装推理环境。权重、数据和运行产物不会随 `git push` / `git pull` 传输。`.gitignore` 不能阻止 `git add -f`，不要强制添加这些目录。
