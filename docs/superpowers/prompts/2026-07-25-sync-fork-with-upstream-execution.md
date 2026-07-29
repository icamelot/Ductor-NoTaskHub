# New Session Prompt: Execute the Locked Upstream Synchronization

请在一个全新的 session 中执行已经批准的 Ductor upstream 同步计划。

## 仓库、分支与 worktree

- 主仓库：`/home/zqxu/ductor`
- 已有同步分支：`chore/sync-upstream-2026-07-25`
- 已有同步 worktree：
  `/home/zqxu/ductor/.worktrees/sync-upstream-2026-07-25`
- 锁定本地祖先：
  `d1167a016eaddc779ecd3f7d70c077832b22a4eb`
- 锁定官方 upstream commit：
  `3e3c88af57bc094105e73cd24673075e076591ab`
- 锁定 merge-base：
  `626d90bdbe3b4404b8e4795610ee52f368177457`

不要创建第二个同步 worktree，不要静默改用移动后的 `upstream/main`。

保留并且不得删除、清理、重置或复用旧 worktree：

`/home/zqxu/ductor/.worktrees/docker-image-refresh`

不得使用 `git clean`、`git reset --hard` 或其他可能丢失用户数据的命令。

## 开始时必须使用的技能

这是 Inline Execution，不要派生 sub-agent。

依次执行：

1. 使用 `using-superpowers`。
2. 使用 `using-git-worktrees` 核对当前已经存在的同步 worktree；不要再创建一个。
3. 完整读取：
   - `AGENTS.md`
   - `docs/superpowers/specs/2026-07-25-sync-fork-with-upstream-design.md`
   - `docs/superpowers/plans/2026-07-25-sync-fork-with-upstream.md`
4. 使用 `executing-plans`，严格逐项执行计划并保留检查点。
5. 对任何需要新增的兼容性修复使用 `test-driven-development`。
6. 在最终声明完成前使用 `verification-before-completion`。

不要使用 `subagent-driven-development`。

## 已批准的同步设计

采用 Plan A：

- 从现有同步分支普通 merge 锁定的 upstream commit；
- 不 rebase；
- 不 squash；
- 不重新 cherry-pick 或挑选本地已有提交；
- 不对重叠文件整体使用 `ours` 或 `theirs`；
- 如果普通 merge 无法安全保留双方行为，立即停止并报告。

使用 C1-R 能力保护门禁：

- merge 前运行本地基线；
- 为容器创建时的 `.env` 注入补 characterization test；
- 按行为逐 hunk 审核四个已知重叠文件；
- 同时运行本地和上游针对性测试；
- Git 没有文本冲突不代表没有语义冲突。

四个已知重叠文件：

- `ductor_bot/cli/base.py`
- `ductor_bot/cli_commands/docker.py`
- `ductor_bot/infra/docker.py`
- `tests/cli/test_env_injection.py`

## 必须保留的本地 Docker 能力

- rebuild 时从 npm 动态解析 Claude、Codex、Gemini CLI 的具体版本；
- 使用唯一 candidate tag 构建，在切换正式 tag 前直接验证 candidate；
- 通过 immutable image ID promotion 和更新共享容器；
- main agent 与 sub-agent 使用同一个共享镜像；
- 正常使用 BuildKit 缓存，不使用全局 `--no-cache`；
- 重型开发、Office、PDF、OCR 工具层位于 provider CLI 层之前；
- 保留全部 `docker.extras`；
- Playwright 只包含 Python package，不安装 Chromium，不运行
  `playwright install`，不增加浏览器 profile/cache 或 mounts；
- rebuild 失败返回非零状态；
- 保留本地 build stream 对原始 subprocess diagnostics 的抑制。

这些是行为契约，不要求保留旧实现文本。优先采用上游的新结构和接口，再适配本地行为。

## 配置、日志和 Grok 决策

M2-U：

- 采用上游 `AgentConfig` 默认值、递归缺失字段合并和原子写回；
- 不覆盖已有用户值；
- 保留上游对 `api` 等特殊字段的排除；
- 只用临时 fixture 测试，不读取后写回真实用户配置；
- 不主动迁移真实 session、task、cron 或 webhook 数据。

L3：

- 采用上游环境变量日志脱敏；
- 保留本地 rebuild 和 build-output 保护；
- 不在本次额外修复 Docker mount/path DEBUG 信息；
- 不在本次额外修复 container-start 原始 ERROR diagnostics；
- 将这两项作为剩余风险报告。

G1：

- 采用上游 Grok provider；
- 不把 Grok 加入本地共享 Docker 镜像；
- 不增加 Grok npm/version resolver；
- 不增加 Docker 模式拒绝逻辑；
- 报告 Grok Docker 镜像缺少二进制这一已知缺口。

## 验证要求

严格按计划：

1. merge 前针对性测试；
2. merge 前 Ruff、mypy 和完整 pytest 基线；
3. 普通 merge 锁定 upstream commit；
4. overlap、配置、日志、Grok、Slack、workspace、session 针对性测试；
5. Ruff format check 和 lint；
6. mypy；
7. 完整 pytest。

区分：

- merge 前已有失败；
- 同步新增回归；
- 环境问题。

不得把中断、卡住或未运行完的测试称为通过。同步新增回归必须在批准范围内用
RED/GREEN 修复；超出批准设计时停止并请求决定。

## 严格禁止

除非我另行明确批准：

- 不实际运行 `ductor docker rebuild`；
- 不停止、删除、重建、inspect 或更新真实容器；
- 不安装、重装、启动或重启正在使用的 Ductor 服务；
- 不使用真实用户配置或持久化数据进行迁移测试；
- 不读取或输出凭据、环境变量值、完整 argv、prompt、service logs、
  Docker mounts 或 subprocess diagnostics 原文；
- 不 merge 回本地 `main`；
- 不 push `origin`；
- 不创建 PR；
- 不执行 branch finishing 或集成流程。

允许在隔离 worktree 内使用 `uv sync --frozen --all-extras` 安装测试依赖，也允许按计划创建
本地测试、merge 和兼容性修复 commits。这不授权修改 live service。

## 最终报告

完成同步分支和全部验证后，报告：

- 锁定的本地、merge-base 和 upstream commits；
- merge commit 与兼容性 commits；
- 四个重叠文件的处理结果；
- 本地能力矩阵的保留证据；
- 针对性测试、Ruff、mypy、完整 pytest 结果；
- 已有或环境失败；
- L3 剩余日志风险；
- G1 Grok Docker 缺口；
- 明确声明没有真实 rebuild、没有合回 `main`、没有 push、没有 PR。

然后立即停止，等待我批准后续集成或运行时验收。
