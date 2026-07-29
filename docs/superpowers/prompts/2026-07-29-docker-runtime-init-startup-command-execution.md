# New Session Prompt: Execute Docker Runtime Init and Main Startup Command

请在一个全新的 session 中实现并部署 Ductor 的 Docker 运行时 init 与 main
启动命令功能。

## 用户已批准的目标

当前三个 sandbox 都使用标准 `ductor-sandbox`。main 容器的默认命令已被镜像
重建恢复为 `sleep infinity`，所以宿主机挂载进容器的
`/ductor/workspace/daemons/start.sh` 仍然存在，但没有被调用。邮件与早晚报守护
进程因此没有运行。

同时，当前容器的 `HostConfig.Init` 是 `null`，`sleep infinity` 直接承担 PID 1，
存在无法回收孤儿子进程的结构性风险。

用户明确要求：

- 不使用派生镜像；
- 不修改或重建 `Dockerfile.sandbox`；
- 不影响以后通过 `ductor docker rebuild` 升级镜像内软件；
- 所有 sandbox 使用 Docker 原生 `--init`；
- 只有 main 通过持久化配置调用现有 `start.sh`；
- 子代理继续使用镜像默认命令；
- 实现、测试通过后在本机部署并验证。

## 仓库与必读文档

主仓库：

```text
/home/zqxu/ductor
```

开始前完整阅读：

```text
/home/zqxu/ductor/docs/superpowers/specs/2026-07-29-docker-runtime-init-startup-command-design.md
/home/zqxu/ductor/docs/superpowers/plans/2026-07-29-docker-runtime-init-startup-command.md
/home/zqxu/ductor/AGENTS.md
```

设计已经得到用户批准。实施计划是执行权威；如果本 prompt 的摘要与计划细节不一致，
以计划为准。

## 工作方式

使用以下 skills：

1. `using-superpowers`
2. `using-git-worktrees`
3. `executing-plans`
4. `test-driven-development`
5. 遇到异常时使用 `systematic-debugging`
6. 完成前使用 `verification-before-completion`
7. 代码与运行态完成后使用 `finishing-a-development-branch`

这是 **Inline Execution**。不要派生 sub-agent，也不要调用并行代理。

用户已授权为此任务创建隔离 worktree。按计划创建：

```text
目录：/home/zqxu/ductor/.worktrees/docker-runtime-init-startup-command
分支：feat/docker-runtime-init-startup-command
```

不要修改、删除或复用现有 worktree：

```text
/home/zqxu/ductor/.worktrees/docker-image-refresh
/home/zqxu/ductor/.worktrees/sync-upstream-2026-07-25
```

主 checkout 中存在用户的 `worktrees` 符号链接状态；不要删除或提交它。

测试工具使用主 checkout 已有虚拟环境：

```text
/home/zqxu/ductor/.venv/bin/pytest
/home/zqxu/ductor/.venv/bin/ruff
/home/zqxu/ductor/.venv/bin/mypy
```

## 严格执行要求

严格按 implementation plan 的 Task 0–5 顺序执行。

每项代码行为都必须：

1. 先写失败测试；
2. 实际运行并观察预期 RED；
3. 写使其通过的最小实现；
4. 实际运行并观察 GREEN；
5. 完成定向回归和静态检查；
6. 按计划单独提交。

计划要求的代码范围只有：

```text
ductor_bot/config.py
ductor_bot/infra/docker.py
tests/test_config.py
tests/infra/test_docker.py
```

不得：

- 修改 `Dockerfile.sandbox`；
- 创建或构建 `ductor-main-sandbox`；
- 修改 `workspace/daemons/start.sh`、mail daemon、digest daemon、broker 或 engine；
- 执行 `ductor docker rebuild`；
- 修改 `agents.json` 或子代理 Docker 配置；
- 将 command 拆成字符串或重新 shell tokenize；
- 顺手修复无关测试或重构无关代码；
- 输出 `.env`、token、password、secret、完整 Docker 环境参数或历史 service logs；
- 自动 merge 到 `main`；
- 删除 worktree 或分支。

## 固定实现接口

`DockerConfig` 新增：

```python
command: list[str] = Field(default_factory=list)
```

所有 `docker run` 固定包含：

```text
docker run -d --init ...
```

Docker 命令末尾固定为：

```python
cmd += [image, *self._config.command]
```

main runtime config 固定新增：

```json
"command": [
  "/bin/bash",
  "-lc",
  "bash /ductor/workspace/daemons/start.sh && exec sleep infinity"
]
```

不要给子代理添加该配置。

## 部署授权与边界

只有在以下检查都完成后才部署：

- focused tests 通过；
- Ruff format/check 通过；
- mypy 通过；
- full pytest 结果已准确记录；
- feature worktree 干净。

用户已授权在代码验证后执行：

```text
uv tool install --force --from <feature-worktree> ductor
修改 main 的 /home/zqxu/.ductor/config/config.json
ductor restart
Docker inspect/top/logs 的只读验收
```

不要重建镜像。部署前必须把 config 备份到：

```text
/home/zqxu/.ductor/backups/docker-runtime-init-20260729/config.json
```

如果部署验收失败，只执行计划给出的显式 rollback：

```text
恢复 config 备份
从 /home/zqxu/ductor 重新安装旧代码
重启一次
报告失败证据
```

不要在失败部署上叠加猜测性修复。

## 运行态验收标准

部署后必须逐项验证：

- `ductor.service` active；
- main、serveradmin、botbuilder 全部仍使用 `ductor-sandbox`；
- 三个容器全部 `HostConfig.Init=true`；
- main args 包含 `/ductor/workspace/daemons/start.sh`；
- 两个子代理 args 保持 `["sleep","infinity"]`；
- main 恰好各有一个：
  - `mail_daemon.py`
  - `generate_digest.py`
  - `notification_broker.py`
  - `/ductor/engine/engine.py`
- 子代理没有上述 main daemons；
- 所有容器进程状态中没有 `Z`；
- mail heartbeat 晚于本次重启；
- launcher 日志显示 daemon PID，且输出前已做敏感字段脱敏。

## 完成报告

最终报告必须包含：

- 每一项 RED 的命令与预期失败原因；
- 每一项 GREEN 的命令与结果；
- 三个独立功能提交；
- focused pytest、Ruff、mypy、full pytest 的新鲜结果；
- 安装和重启结果；
- 三个容器的 image/init/args 验收摘要；
- main daemon 数量、子代理隔离、僵尸状态和 heartbeat；
- 是否触发 rollback；
- feature 分支相对 `main` 的提交列表；
- 明确说明尚未 merge，并按 `finishing-a-development-branch` 给出后续集成选项。
