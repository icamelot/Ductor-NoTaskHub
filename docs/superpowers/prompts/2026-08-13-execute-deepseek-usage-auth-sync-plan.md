# Execute the DeepSeek, Usage, and Authentication Restoration Plan

请在 `/home/zqxu/ductor` 仓库中完整执行：

- `docs/superpowers/specs/2026-08-13-deepseek-usage-auth-sync-design.md`
- `docs/superpowers/plans/2026-08-13-deepseek-usage-auth-sync.md`

目标是在当前 Ductor 架构上恢复并整合以下功能：

1. DeepSeek 独立逻辑 provider 与独立会话桶，底层委托 Claude CLI；
2. 跨全部命令入口的完整 `/usage`，同时查询 DeepSeek、Claude Code 和 Codex；
3. Ductor 自己维护的 DeepSeek 余额快照、当日消费/充值估算和一次性旧快照导入；
4. 仅主 agent 运行的 Claude OAuth 登录令牌保活；
5. 子 agent 在首次启动和每次重建前同步聊天鉴权配置。

这是一份执行 prompt，不是重新 brainstorming 或重新设计。设计已经由用户批准；除非发现设计内部矛盾、现实代码结构与计划冲突，或继续执行会引入范围外修改，否则不要重复询问已决定的问题。

## 启动要求

开始任何实现前：

1. 使用 `using-superpowers`，完整读取其 `SKILL.md`；
2. 使用 `using-git-worktrees`，完整读取其 `SKILL.md`；
3. 使用 `executing-plans`，完整读取其 `SKILL.md`；
4. 实现任何功能或修复前使用 `test-driven-development`；
5. 遇到测试失败、意外行为或计划与代码不一致时使用 `systematic-debugging`；
6. 完成实现后使用 `requesting-code-review`；
7. 声称完成、合并或推送前使用 `verification-before-completion`；
8. 用户在发布闸门处明确批准后，再使用 `finishing-a-development-branch` 完成合并和推送。

必须完整读取上述每个实际使用的技能文件。若技能指向与本任务直接相关的附加说明，也必须按技能要求读取。

采用 `executing-plans` 的 inline 执行方式，不要创建 sub-agent，也不要委派任务，除非用户在这个新会话里另行明确要求。用户已经授权连续执行计划中的 Task 0–11；不需要在每个 task 或每个小批次后停下来征求许可。每完成一个 task，发送简短进度更新并继续。只有以下情况需要暂停：

- 缺少会实质改变结果的用户选择；
- 同一真实阻塞在穷尽安全排查后仍无法解除；
- 计划需要范围外架构修改；
- 已到 Task 11 的发布批准闸门。

## 权威文件和基线

先在源 checkout `/home/zqxu/ductor` 中运行只读检查，然后完整读取：

```bash
cd /home/zqxu/ductor
git status --short --branch
git log -5 --oneline
git worktree list
sed -n '1,9999p' AGENTS.md
sed -n '1,9999p' docs/superpowers/specs/2026-08-13-deepseek-usage-auth-sync-design.md
sed -n '1,9999p' docs/superpowers/plans/2026-08-13-deepseek-usage-auth-sync.md
sed -n '1,9999p' docs/superpowers/prompts/2026-08-13-execute-deepseek-usage-auth-sync-plan.md
```

权威顺序：

1. 用户在新会话中的明确指令；
2. 已批准 spec；
3. implementation plan；
4. 本执行 prompt。

已知文档提交：

- spec：`4d98616 docs: design restored DeepSeek usage and auth features`
- plan：`41356a2 docs: plan DeepSeek usage and auth restoration`

从包含 spec、plan 和本 prompt 的当前本地 `main` 创建：

- branch：`feat/restore-deepseek-usage-auth`
- worktree：`/home/zqxu/ductor/.worktrees/restore-deepseek-usage-auth`

如果该 branch 或 worktree 已存在，不要删除、重置或覆盖。先检查其状态和 ancestry：如果它是本计划的干净、可继续工作树，就从中继续；否则停止并向用户说明精确冲突。不要用 `git reset --hard`、`git checkout --` 或任何会丢弃文件的操作。

## 必须保护的用户文件

源 checkout 中以下未跟踪项目属于用户，不能添加、移动、改写、提交或删除：

- `docs/superpowers/prompts/2026-08-06-taskhub-background-job-redesign-brainstorming.md`
- `docs/superpowers/prompts/2026-08-08-execute-remove-taskhub-plan.md`
- `docs/superpowers/prompts/2026-08-08-remove-taskhub-and-rename-repo.md`
- `docs/superpowers/specs/2026-08-05-pixai-persistent-cookie-model-download-design.md`
- `worktrees` 符号链接

工作树中发现的其他用户修改也要保留。只提交当前 task 明确列出的文件；每次 commit 前检查 staged 文件列表。

## 执行规则

严格按 plan 的 Task 0 到 Task 11 顺序执行，不跳步，不把多个编号 task 混成一个提交。

每个行为必须遵循 RED → GREEN → REFACTOR：

1. 先写最小失败测试；
2. 运行 plan 给出的 focused command，确认失败原因正是缺失行为；
3. 实现最小改动；
4. 重新运行 focused tests；
5. 运行该 task 的 Ruff/mypy/相邻回归；
6. 检查 diff 和 staged 文件；
7. 使用 plan 指定的提交信息提交。

如果 RED 阶段意外通过，不要假装测试有效；检查它是否已经覆盖目标行为。如果失败原因与预期不同，先系统调试。测试失败时不要盲目扩大修改范围。

计划中的接口、文件清单、测试命令、提交边界和验收标准都属于执行要求。若现实代码证明某个精确接口无法成立：

- 先收集代码和测试证据；
- 使用 `systematic-debugging` 找到根因；
- 说明计划中哪一句与现实冲突；
- 只做保持 spec 语义的最小修订；
- 在继续实现前把修订写回 plan 并单独提交文档变更。

不要因为实现方便而改变 approved behavior。

## 范围边界

只实现 spec 和 plan 中列出的功能。明确禁止恢复或顺带修改：

- TaskHub；
- ComfyUI；
- `0.999.0+icamelot` fork 版本；
- personal-assistant 的其他功能；
- 被放弃分支的 Docker 强化；
- Docker 用户、root 权限、sudo、镜像、mount、容器、重建逻辑、启动命令或现有 Docker 行为。

此前用户确认，Docker 中已有且已接受的软件更新、Codex 等 CLI 更新和工具安装应保持原样；本任务既不能回退它们，也不能把新的 Docker 强化混进来。

`feat/deepseek-provider` 只能通过 `git show`、`git log` 或 `git diff` 作为只读行为参考。禁止 cherry-pick、merge、rebase 该分支，也禁止整文件照搬。所有实现必须基于当前 `main` 架构重新落地。

## DeepSeek 和会话约束

- DeepSeek 的逻辑 provider 名必须始终是 `deepseek`；底层使用 Claude CLI 不得让它落入 `claude` 会话桶。
- Claude 与 DeepSeek 的 session ID、resume、reset、timeout、错误恢复、topic、streaming 和 memory flush 必须双向隔离。
- 多个 DeepSeek 模型共享同一个 DeepSeek provider bucket；用户切换 DeepSeek 模型时无需额外创建模型级桶。
- 不新增自动“更新会话桶”的隐藏机制；沿用当前 provider 级会话模型。用户手动切换 model 时，当前 DeepSeek 桶继续复用。
- DeepSeek 可用性使用独立的 Claude CLI runnable probe，不能依赖 Claude OAuth 是否登录。
- DeepSeek config 可热重载；root `.env` 中的 key 只在启动时捕获，变化必须重启 Ductor 才生效。

## Secret 和持久化约束

- `DEEPSEEK_API_KEY` 只从 root Ductor home 的 `.env` 读取。
- 不得把 secret 写入 `config.json`、snapshot、session、metadata、status、异常、日志、repr、测试输出或命令展示。
- host 和 Docker invocation 都只能对单次 DeepSeek 子进程注入 `ANTHROPIC_AUTH_TOKEN` 和 `ANTHROPIC_BASE_URL`；Claude invocation 必须明确剥离这两个变量。
- `/usage` 返回结构化、有限枚举错误；不包含响应 body、header、token 或原始异常文本。
- snapshot 金额使用 `Decimal` 字符串，时间使用 UTC，展示和当日边界使用 `user_timezone`。
- malformed current snapshot 必须保持原文件证据不变并作为 unavailable 处理，不能部分信任或静默覆盖。
- legacy snapshot 只进行一次 best-effort 导入，绝不改写、重命名或删除旧文件。
- Claude credential refresh 必须 compare-before-replace、同目录原子写入且最终权限为 `0600`。

## `/usage` 和 observer 约束

- `/usage` 必须经过共享 `CommandRegistry`，不能为 Telegram、Slack、Matrix 或 direct API 各写一套 provider 查询。
- 三个 provider 查询并发执行、失败互相隔离、各自有限 10 秒超时。
- 输出始终按 DeepSeek、Claude Code、Codex 三段顺序展示。
- 八种现有语言 `de/en/es/fr/id/nl/pt/ru` 的 key 与 placeholder 必须完整一致。
- 当日 delta 必须在当前 `/usage` 样本写入前读取历史；主 agent 成功查询后可以写 snapshot，子 agent 永远只读。
- DeepSeek balance observer 和 Claude keepalive observer 仅主 agent 运行；普通失败不能终止 Ductor，取消必须传播。

## 子 agent 鉴权同步约束

首次启动和每次 rebuild 都必须在 stack 注册、bus handler、health entry 和 run task 之前，将以下字段精确同步到该 sub-agent 的 `stack.paths.config_path`：

- `provider`
- `model`
- `reasoning_effort`
- `allowed_user_ids`
- `allowed_group_ids`
- `group_mention_only`

不得同步或改写 Docker、权限、用户、mount、image 等无关字段。某个 sub-agent 同步失败只阻止该目标启动/注册，不能影响 main 或其他 sub-agent。

## 鉴权失败处理

用户没有登录 Gemini、Claude 和 Grok。不要执行要求这些真实账号登录的 live auth probe，也不要因为可选 operational probe 报 auth failure 而中断本任务。

但这不意味着忽略测试失败：

- mock/unit/integration tests 必须全部通过；
- 若无凭证测试期望返回 bounded `not_logged_in`/`expired`，必须精确满足；
- 只有明确依赖真实外部登录、且不属于 plan 验收命令的手工 live probe 才可跳过，并在发布 manifest 中说明未运行。

## 验证和 review

Task 11 必须从干净状态重新运行 plan 中所有 focused regression、Docker/provider non-regression、Ruff format/check、mypy、i18n checker 和完整 pytest。不要引用较早输出代替最终 fresh verification。

完成后使用 `requesting-code-review` 审查 `main...HEAD` 的完整 diff。所有接受的 correctness、security、concurrency、i18n 或 scope finding 都要通过新的 RED 测试和最小修复解决，然后重新运行受影响 focused tests 与完整最终 gates。

同时核对 spec 的全部 12 条 acceptance criteria，并执行：

- secret 泄露审计；
- Docker 文件零 diff 审计；
- TaskHub/ComfyUI/fork symbol 审计；
- 八语言 key/placeholder 审计；
- main-only writer/observer 审计；
- git diff whitespace 和工作树清洁检查。

在没有新的、完整的成功输出前，不得声称“完成”“修好”或“测试通过”。

## 发布闸门

完成 Task 11 的实现、测试和 review 后，先向用户展示 publication manifest，至少包含：

1. 已恢复功能的完整清单；
2. 行为变化和新增 config key；
3. 每条 focused/full test 与 quality command 的结果和测试数量；
4. review findings 及其处理；
5. 已知限制，例如 30 分钟采样导致的近似日基线，以及 `.env` key 改动需要重启；
6. feature branch、按顺序的 commit 列表、本地合并目标 `main`、远程推送目标 `origin/main`；
7. 明确声明未进行安装、service restart、Docker rebuild、部署或 live auth probe。

展示 manifest 后必须停止并明确询问：是否允许将 `feat/restore-deepseek-usage-auth` 合并到本地 `main` 并 push 到用户的 `origin/main`？

当前 prompt 对 Task 0–11 的实现授权，不构成未来 merge/push 授权；之前会话中的“确认发布”也不能复用于这个新 feature。必须等用户在看到本次 manifest 后再次明确同意。

得到明确同意后：

1. 使用 `finishing-a-development-branch`；
2. 检查源 checkout 与 feature worktree，保护所有用户文件；
3. fetch `origin`；
4. 如果本地 `main` 已移动，停止并安全协调，不 reset、不覆盖；
5. 仅在可 fast-forward 时将 feature branch 合并到本地 `main`；
6. 在合并后的 `main` 上重新运行完整质量门；
7. 全部通过后 `git push origin main`；
8. 报告最终 main SHA 和 push 结果。

即使用户批准 merge/push，也不自动安装 package、不运行 `ductor service stop/start`、不 rebuild Docker、不执行部署、不删除 branch/worktree。这些都需要独立指令。

现在开始执行 Task 0，并持续推进到 Task 11 的 publication gate。
