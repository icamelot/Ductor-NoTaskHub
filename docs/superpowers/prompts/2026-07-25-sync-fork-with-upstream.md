# New Session Prompt: Investigate Upstream Before Syncing the Fork

请在一个全新的 session 中调查 Ductor 官方上游的新版本。这个 session 的首要目标是
先让我了解上游新增了什么，再根据真实差异设计同步方案；不得直接开始同步。

## 仓库与远程

- 本地仓库：`/home/zqxu/ductor`
- 我的 fork：`origin`，`https://github.com/icamelot/ductor.git`
- 官方仓库：`upstream`，`https://github.com/PleasePrompto/ductor.git`
- 当前本地 `main` 在本 prompt 生成前包含已完成的 Docker 镜像更新，并领先
  `origin/main` 18 个提交。不要假设这些数字或 commit 在新 session 中仍未变化，
  必须重新检查并记录实际状态。

本地已有以下用户状态，必须原样保留：

- 未跟踪的 `.worktrees/`
- 未跟踪的 `worktrees` 符号链接
- 旧 worktree：
  `/home/zqxu/ductor/.worktrees/docker-image-refresh`

不得删除、清理、重置或复用旧 worktree。不得使用 `git clean`、`git reset --hard`
或其他可能丢失用户数据的命令。

## 必须保留的本地能力

本地 `main` 已经完成并实际验收以下 Docker 能力。调查时需要专门分析上游是否修改了
相同区域，但不得预设上游或本地实现一定正确：

- rebuild 时从 npm 动态解析 Claude、Codex、Gemini CLI 的具体版本；
- 使用唯一 candidate tag 构建，在切换正式 tag 前直接验证 candidate；
- 通过 immutable image ID promotion 和更新共享容器；
- main agent 与 sub-agent 使用同一个共享镜像；
- 正常使用 BuildKit 缓存，不使用全局 `--no-cache`；
- 重型开发、Office、PDF、OCR 工具层位于 provider CLI 层之前；
- 保留全部 `docker.extras`；
- Playwright 只包含 Python package，不安装 Chromium，不运行
  `playwright install`，不增加浏览器 profile/cache 或 mounts；
- rebuild 失败返回非零状态，并避免输出凭据、环境变量、完整 argv、prompt、
  service logs、Docker mounts 或 subprocess diagnostics 原文。

这些是同步设计必须保护的行为约束，不代表发生冲突时可以盲目保留旧代码。

## 工作方式与技能

开始时使用 `using-superpowers`。这是 Inline Execution，不要派生 sub-agent。

整个工作分为“调查”和“设计文档”两部分，中间有不可跳过的用户批准关卡。
本 session 不执行实际 upstream merge。

## 第一部分：只读调查

### 1. 建立可复核的基线

先进行安全的只读检查：

- `git status --short --branch`
- `git worktree list`
- `git remote -v`
- 当前本地 `main`、`origin/main` 和现有 `upstream/main` 的 commit

确认远程 URL 与上文一致。不得修改远程配置。

允许执行以下 fetch，因为需要了解官方最新版本：

```bash
git fetch upstream --prune --tags
git fetch origin --prune
```

fetch 之后记录：

- 本地 `main` 的 immutable commit ID；
- 最新 `upstream/main` 的 immutable commit ID；
- `origin/main` 的 immutable commit ID；
- 本地 `main` 与 `upstream/main` 的 merge-base；
- 双方各自 ahead/behind 的提交数量；
- merge-base 之后的官方 release/tag（如果存在）。

后续所有结论都必须引用这些确切 commit，不要只写“最新版”。

### 2. 调查上游新功能

以 merge-base 到锁定的 `upstream/main` commit 为范围，检查实际提交和 diff。
结合仓库内 changelog、release notes、文档、配置、CLI、依赖和测试变化，整理：

- 面向用户的新功能；
- CLI 命令或参数变化；
- 配置格式、默认值或迁移要求；
- agent/provider、Docker、workspace、Telegram 等行为变化；
- 依赖、Python 版本、打包或安装方式变化；
- bug fixes、性能和安全相关变化；
- breaking changes、废弃项和已删除能力。

不要只根据 commit 标题猜测功能。重要结论至少应由实际 diff、测试、文档或官方
release 信息之一支持；有疑问时明确标为推断。

如果需要浏览网页，只使用官方 Ductor GitHub 仓库、官方 release 页面或项目明确链接的
一手资料，并在报告中给出链接。不得用第三方文章替代仓库证据。

### 3. 分析本地改动与冲突风险

同样检查 merge-base 到本地 `main` 的实际 diff，尤其关注：

- Dockerfile 生成及 image build 路径；
- provider npm 版本解析和 build args；
- candidate 验证、tag promotion、container 更新和恢复逻辑；
- `docker.extras`、缓存层和预装工具；
- CLI rebuild 命令、错误处理和测试；
- 上游对相同文件、接口、测试或配置模型的修改。

区分：

1. Git 文本冲突；
2. 没有文本冲突但存在行为/语义冲突；
3. 可以直接接受的上游变化；
4. 本地已有、上游也实现了且可能需要去重的能力。

### 4. 报告格式

向我提交一份简洁但可复核的中文报告，至少包含：

- 本地、fork、上游、merge-base 的确切 commit；
- ahead/behind 和上游 release/tag 范围；
- 按用户价值分类的新功能摘要；
- breaking changes 与迁移注意事项；
- 与本地 Docker 改动的重叠文件和行为；
- 预期文本冲突与语义冲突；
- 哪些本地能力应保留、适配、替换或可能删除，以及对应证据；
- 建议的同步与测试范围；
- 尚未确定、需要我选择的问题。

报告不得包含 token、凭据、环境变量、完整 argv、prompt、service logs、
Docker mounts 或 subprocess stdout/stderr 原文。

### 5. 强制停止

提交报告后立即停止并等待我批准。此时禁止：

- checkout 或创建同步分支/worktree；
- merge、rebase、cherry-pick 或修改生产代码；
- 编写同步 spec/plan；
- 安装或重装 Ductor；
- 执行 `ductor docker rebuild`；
- 停止、删除或重建容器；
- push `origin`、创建 PR 或修改远程状态。

## 第二部分：批准后先 brainstorming，再写下一阶段文档

只有我明确批准第一部分报告后，才继续本部分。

### 1. Brainstorming 硬关卡

在任何同步操作、worktree 创建或生产代码修改之前，完整使用
`brainstorming`。基于第一部分锁定的真实 upstream commit 和 diff：

- 一次只问我一个问题；
- 比较 2–3 个可行同步策略；
- 默认推荐已经选定的 Plan A：从本地 `main` 创建独立分支，然后普通 merge
  锁定的 `upstream/main` commit；
- 不使用 rebase、squash 或重新挑选本地已有提交，除非新证据表明 Plan A
  无法安全执行，并先得到我批准；
- 逐段确认冲突原则、本地 Docker 能力保留方式、迁移策略和验收范围。

设计获批之前，不得创建同步 worktree、修改文件或编写 implementation plan。

### 2. 设计获批后创建规划 worktree

设计获批后，使用 `using-git-worktrees` 创建新的独立 worktree：

```text
分支：chore/sync-upstream-2026-07-25
worktree：/home/zqxu/ductor/.worktrees/sync-upstream-2026-07-25
```

创建前验证分支和路径均不存在。如果任一已存在，不得覆盖或复用，向我报告并等待指令。

worktree 必须从第一部分记录的本地 `main` commit 创建。若本地 `main` 已经移动，
停止并重新评估调查结论，不得静默改用新基线。

### 3. 只生成 spec、plan 和 execution prompt

在新 worktree 中：

1. 按 `brainstorming` 要求保存已批准设计：
   `docs/superpowers/specs/2026-07-25-sync-fork-with-upstream-design.md`
2. 使用 `writing-plans` 编写可逐项执行的计划：
   `docs/superpowers/plans/2026-07-25-sync-fork-with-upstream.md`
3. 生成供另一个全新 session 手动输入的执行 prompt：
   `docs/superpowers/prompts/2026-07-25-sync-fork-with-upstream-execution.md`

计划和 execution prompt 必须锁定第一部分记录的 upstream immutable commit，
并要求执行 session：

- 先使用 `using-git-worktrees` 核对既有 worktree，再使用 `executing-plans`；
- 普通 merge 锁定的 upstream commit，不 rebase、不 squash；
- 对需要新增的兼容性修复严格使用 `test-driven-development`；
- 保留获批设计中列出的本地能力；
- 先运行针对性测试，再运行 Ruff、mypy 和完整 pytest；
- 使用 `verification-before-completion`，区分新增回归与已有失败；
- 不实际运行 Docker rebuild，除非我另外明确批准；
- 不合并回本地 `main`，不 push `origin`，不创建 PR；
- 完成同步分支和验证后报告，再次等待我批准后续集成。

可以提交纯文档 commit，但本 session 不得执行 implementation plan，不得 merge
upstream，不得修改生产代码。

### 4. 最终交付

完成自检后向我报告：

- 锁定的本地与 upstream commit；
- spec、plan 和 execution prompt 的绝对路径；
- 纯文档提交（如果创建）；
- 明确声明尚未执行 upstream merge；
- 提醒我需要开启另一个新 session，并手动输入 execution prompt。

然后停止。
