# New Session Prompt: Execute Docker Development and Document Tools Phase

请在一个全新的 session 中继续 Ductor Docker 镜像更新的第二阶段。

## 工作区

- 仓库：`/home/zqxu/ductor`
- 已有独立 worktree：
  `/home/zqxu/ductor/.worktrees/docker-image-refresh-v2`
- 分支：`feat/docker-image-refresh-v2`
- 基线最初来自：
  `08ecc315bd20defaf886cf5d2232d52e89099224`

直接使用现有 v2 worktree，不要创建或切换到其他 worktree。不要修改或复用：

```text
/home/zqxu/ductor/.worktrees/docker-image-refresh
```

不得 cherry-pick 旧分支提交。旧历史只能作为证据阅读，不得假设其实现或测试正确。

## 已完成且不可重做的阶段一

阶段一的 candidate-first provider 更新已经实现并实际验收：

- candidate 内 Codex 等于当次 npm 解析版本 `0.145.0`；
- 正式 tag 和三个运行容器使用同一个 candidate immutable image ID；
- 新 Codex session 成功使用 `gpt-5.6-sol`。

不要重新设计或重写以下内容：

- npm provider 版本解析；
- candidate tag 和 candidate 直接验证；
- production tag promotion；
- shared-container immutable-ID 更新；
- bounded recovery；
- CLI 非零失败和安全摘要。

## 必读文件

开始前完整阅读：

```text
/home/zqxu/ductor/.worktrees/docker-image-refresh-v2/docs/superpowers/specs/2026-07-25-docker-development-document-tools-design.md
/home/zqxu/ductor/.worktrees/docker-image-refresh-v2/docs/superpowers/plans/2026-07-25-docker-development-document-tools.md
```

设计已获用户批准。使用 `using-superpowers`、`executing-plans`、
`test-driven-development` 和 `verification-before-completion`。这是 Inline
Execution：不要派生 sub-agent。

## 执行要求

严格按 implementation plan 的 Task 1–5 顺序执行：

1. 每项行为先写失败测试并实际观察 RED。
2. 只写让测试通过的最小实现。
3. 实际观察 GREEN。
4. 每个独立任务单独提交。
5. 保持 worktree 干净，不覆盖用户的无关修改。

第二阶段固定工具范围为：

- 开发：`wget jq rsync tree vim unzip p7zip-full file bat fd git-lfs less pipx ripgrep shellcheck shfmt sqlite3 gh`
- Python/Node：`uv ruff pnpm yarn`
- Office/PDF：LibreOffice Writer/Calc/Impress、Poppler、qpdf、Ghostscript、ImageMagick、ExifTool
- OCR：Tesseract，含英文、简体中文、繁体中文
- Python 文档库：`python-docx openpyxl python-pptx pypdf`

保持层顺序：

```text
base → development tools → document tools → configured extras
     → provider CLIs → final metadata
```

保留正常 BuildKit 缓存和全部现有 `docker.extras`。Playwright 只能保留
Python package。禁止：

- Chromium、Chrome 或其他浏览器二进制；
- `playwright install`；
- `/ms-playwright`；
- 浏览器 profile/cache 初始化；
- 浏览器 profile/cache mounts；
- 全局 `--no-cache`。

错误和报告中不得包含 token、环境变量、prompt、完整 argv、Docker mounts、
service logs 或 subprocess stdout/stderr 原文。

## 手动安装边界

实现并测试：

```text
scripts/install-docker-tools.sh
```

但你不得执行它，也不得执行：

```text
uv tool install
ductor docker rebuild
docker run
docker inspect
```

代码验证完成后，只把以下命令交给用户，由用户在有 Docker 权限的宿主机终端手动运行：

```bash
cd /home/zqxu/ductor/.worktrees/docker-image-refresh-v2
bash scripts/install-docker-tools.sh
```

不要启动后台 rebuild，不要轮询终端，不要自行进行 Docker 验收。

## 验证基线

阶段一的最新质量结果：

- Docker 定向测试：`90 passed`
- Ruff format/check：通过
- mypy：通过
- 完整 pytest：`3817 passed, 14 failed`
- 14 个失败全部位于 `tests/workspace/test_init.py`，是 provider-auth 相关的既有基线失败

第二阶段新增测试会提高 passed 数量。不得修改这些无关 workspace 测试，也不得在仍有
14 个已知失败时声称完整 pytest 全部通过。

完成 Task 1–5 后，报告：

- 每个 RED/GREEN 证据；
- 每个独立提交；
- 定向测试、Ruff、mypy、完整 pytest 的新鲜结果；
- 变更范围；
- 给用户的手动 shell 脚本命令。
