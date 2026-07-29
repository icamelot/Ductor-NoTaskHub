# Sync Fork with Upstream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. This is
> inline execution; do not dispatch sub-agents. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Merge the locked official Ductor upstream commit into the fork while
preserving the fork's accepted Docker rebuild behavior and validating upstream
features and compatibility.

**Architecture:** Work in the existing isolated synchronization worktree. Add
one missing local characterization test, perform one ordinary merge of the exact
upstream commit, audit the four known overlapping files by behavior, and use
focused and complete test gates before reporting. Do not perform operational
Docker or service changes.

**Tech Stack:** Git, Python 3.11+, uv, pytest, pytest-asyncio, Ruff, mypy,
Pydantic, asyncio, Docker command construction with mocked unit-test runners.

## Global Constraints

- Worktree:
  `/home/zqxu/ductor/.worktrees/sync-upstream-2026-07-25`
- Branch: `chore/sync-upstream-2026-07-25`
- Locked local ancestor:
  `d1167a016eaddc779ecd3f7d70c077832b22a4eb`
- Locked upstream merge target:
  `3e3c88af57bc094105e73cd24673075e076591ab`
- Locked merge-base:
  `626d90bdbe3b4404b8e4795610ee52f368177457`
- Use an ordinary merge. Do not rebase, squash, or reselect existing local
  commits.
- Never resolve a whole overlapping file with `ours` or `theirs`.
- Preserve every local capability listed in the approved design.
- Accept M2-U configuration deep-merge and atomic writeback behavior.
- Accept L3: use upstream environment-value redaction, preserve existing rebuild
  protection, and only document the remaining mount/path and raw container-start
  diagnostic risks.
- Accept G1: adopt upstream Grok without adding Grok to the Docker image.
- New compatibility fixes require `superpowers:test-driven-development`.
- Do not run `ductor docker rebuild`.
- Do not stop, delete, recreate, inspect, or update real containers.
- Do not install, restart, or modify the live Ductor service.
- Do not read or rewrite real user configuration or persistent runtime data.
- Do not inspect or disclose credentials, environment values, complete process
  arguments, prompts, service logs, Docker mounts, or raw subprocess
  diagnostics.
- Preserve the old
  `/home/zqxu/ductor/.worktrees/docker-image-refresh` worktree.
- Do not use `git clean` or `git reset --hard`.
- Do not merge the result into `main`, push, or create a pull request.

---

## File and Responsibility Map

**Pre-merge local characterization**

- Modify: `tests/infra/test_docker.py`
  - prove container creation injects an agent `.env` value even when the host
    process has the same key.

**Known overlap audit after merge**

- Modify only if automatic merge is insufficient:
  `ductor_bot/cli/base.py`
  - upstream task IDs, prompt-file helpers, and command formatting;
  - local main/sub-agent/provider environment precedence.
- Modify only if automatic merge is insufficient:
  `ductor_bot/cli_commands/docker.py`
  - local candidate-first rebuild;
  - upstream extras dependency resolution.
- Modify only if automatic merge is insufficient:
  `ductor_bot/infra/docker.py`
  - local provider version build inputs and output suppression;
  - upstream command-log redaction.
- Modify only if automatic merge is insufficient:
  `tests/cli/test_env_injection.py`
  - retain both upstream task ID tests and local environment precedence tests.

**Upstream additions accepted without fork-specific redesign**

- `ductor_bot/cli/_log_redact.py`
- `ductor_bot/cli/grok_*.py`
- `ductor_bot/messenger/slack/`
- `ductor_bot/workspace/project_roots.py`
- upstream configuration, session, task, cron, webhook, documentation, packaging,
  and test changes.

**Local-only Docker files that must remain**

- `ductor_bot/infra/docker_image.py`
- `ductor_bot/infra/docker_rebuild.py`
- `Dockerfile.sandbox`
- `scripts/install-ductor-tool-image.sh`
- their focused tests under `tests/infra/` and `tests/cli/`.

---

### Task 1: Verify the Existing Worktree and Establish the Local Baseline

**Files:**

- Read: `AGENTS.md`
- Read:
  `docs/superpowers/specs/2026-07-25-sync-fork-with-upstream-design.md`
- Read:
  `docs/superpowers/plans/2026-07-25-sync-fork-with-upstream.md`
- Modify: `tests/infra/test_docker.py`

**Interfaces:**

- Consumes: the existing worktree and locked Git objects.
- Produces: a clean pre-merge branch with an explicit test contract for
  `DockerManager._env_secret_flags() -> list[str]`.

- [ ] **Step 1: Verify isolation, branch, ancestry, and immutable objects**

Run:

```bash
pwd
git status --short --branch
git branch --show-current
git rev-parse HEAD
git merge-base --is-ancestor d1167a016eaddc779ecd3f7d70c077832b22a4eb HEAD
git cat-file -e 3e3c88af57bc094105e73cd24673075e076591ab^{commit}
git merge-base d1167a016eaddc779ecd3f7d70c077832b22a4eb \
  3e3c88af57bc094105e73cd24673075e076591ab
git worktree list
```

Expected:

- path is the specified synchronization worktree;
- branch is `chore/sync-upstream-2026-07-25`;
- status is clean;
- the locked local commit is an ancestor;
- the upstream object exists;
- merge-base is exactly
  `626d90bdbe3b4404b8e4795610ee52f368177457`;
- the old Docker worktree is still listed and untouched.

Stop before changing files if any expectation fails.

- [ ] **Step 2: Prepare an isolated development environment**

Run from the synchronization worktree:

```bash
uv sync --frozen --all-extras
```

Expected: exit status 0 and a worktree-local `.venv`. This may install project
dependencies into the worktree; it must not install or restart the live Ductor
service.

- [ ] **Step 3: Run the focused pre-merge baseline**

Run:

```bash
uv run pytest -q \
  tests/cli/test_docker_rebuild_command.py \
  tests/cli/test_docker_wrap.py \
  tests/cli/test_env_injection.py \
  tests/infra/test_docker.py \
  tests/infra/test_docker_extras.py \
  tests/infra/test_docker_image.py \
  tests/infra/test_docker_mounts.py \
  tests/infra/test_docker_published_ports.py \
  tests/infra/test_docker_rebuild.py \
  tests/infra/test_docker_tools.py
```

Expected on the locked local code: 157 tests pass before the new
characterization test is added.

- [ ] **Step 4: Add the missing container-creation characterization test**

Add this method to `TestDockerManager` in `tests/infra/test_docker.py`:

```python
def test_env_secret_flags_inject_dotenv_when_host_has_same_key(
    self,
    docker_config: DockerConfig,
    docker_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker import DockerManager
    from ductor_bot.infra.env_secrets import clear_cache

    docker_paths.env_file.write_text("SAME_KEY=from-dotenv\n")
    clear_cache()
    manager = DockerManager(docker_config, docker_paths)

    with patch.dict("os.environ", {"SAME_KEY": "from-host"}, clear=False):
        flags = manager._env_secret_flags()

    assert flags == ["-e", "SAME_KEY=from-dotenv"]
```

This is a characterization test, not a new behavior change. It must pass against
the locked local implementation and would fail if resolution silently restored
the old upstream host-environment skip.

- [ ] **Step 5: Run the characterization and focused baseline**

Run:

```bash
uv run pytest -q \
  tests/infra/test_docker.py::TestDockerManager::test_env_secret_flags_inject_dotenv_when_host_has_same_key
uv run pytest -q \
  tests/cli/test_docker_rebuild_command.py \
  tests/cli/test_docker_wrap.py \
  tests/cli/test_env_injection.py \
  tests/infra/test_docker.py \
  tests/infra/test_docker_extras.py \
  tests/infra/test_docker_image.py \
  tests/infra/test_docker_mounts.py \
  tests/infra/test_docker_published_ports.py \
  tests/infra/test_docker_rebuild.py \
  tests/infra/test_docker_tools.py
```

Expected: the single test passes, then 158 focused tests pass.

- [ ] **Step 6: Run the complete pre-merge quality baseline**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy ductor_bot
uv run pytest -q
```

Expected: each command exits 0. The planning session's full pytest run stalled
without a result, so this execution-session run is the authoritative baseline.
If it fails or stops making progress, rerun the affected suite with:

```bash
uv run pytest -vv -x
```

Record the exact failing test, but do not dump service logs or raw subprocess
diagnostics. Stop and ask whether to investigate or proceed before merging when
the pre-merge baseline is not clean.

- [ ] **Step 7: Commit the characterization test**

Run:

```bash
git add tests/infra/test_docker.py
git diff --cached --check
git commit -m "test(docker): characterize container env injection"
```

Expected: one local test-only commit and a clean worktree.

---

### Task 2: Merge the Locked Upstream Commit and Audit the Four Overlaps

**Files:**

- Audit/modify: `ductor_bot/cli/base.py`
- Audit/modify: `ductor_bot/cli_commands/docker.py`
- Audit/modify: `ductor_bot/infra/docker.py`
- Audit/modify: `tests/cli/test_env_injection.py`
- Test: `tests/infra/test_docker.py`
- Test: `tests/cli/test_log_redact.py`
- Test: `tests/infra/test_docker_extras.py`
- Test: `tests/infra/test_docker_rebuild.py`
- Test: `tests/cli/test_docker_rebuild_command.py`

**Interfaces:**

- Consumes:
  - `async DockerManager._build_image(image: str, versions: ProviderCliVersions) -> bool`
  - `DockerManager._env_secret_flags() -> list[str]`
  - `docker_wrap(cmd: list[str], config: CLIConfig, *, extra_env:
    dict[str, str] | None = None, interactive: bool = False) ->
    tuple[list[str], str | None]`
  - `rebuild_docker_image(...) -> RebuildOutcome`
  - upstream `redact_cmd_for_log(cmd: list[str]) -> list[str]`
- Produces: one merge commit whose first parent is the synchronization branch
  and whose second parent is the exact locked upstream commit.

- [ ] **Step 1: Start one ordinary non-fast-forward merge**

Run:

```bash
git status --short --branch
git merge --no-ff --no-commit 3e3c88af57bc094105e73cd24673075e076591ab
git status --short
git diff --name-only --diff-filter=U
```

Expected: the merge uses the immutable commit and pauses before creating the
merge commit. A read-only merge-tree preview found four files changed by both
sides, but Git may merge them textually without conflict:

```text
ductor_bot/cli/base.py
ductor_bot/cli_commands/docker.py
ductor_bot/infra/docker.py
tests/cli/test_env_injection.py
```

If any other file is unresolved, stop and inspect the new evidence before
resolving it. Do not abort with destructive cleanup and do not choose a whole
file from either side.

- [ ] **Step 2: Audit `ductor_bot/cli/base.py`**

Require all of these elements in the staged merge result:

```python
from ductor_bot.cli._log_redact import redact_cmd_for_log
from ductor_bot.cli.types import CLIResponse, task_id_from_label
```

The Docker environment merge must retain:

```python
merged_extra = dict(load_env_secrets(main_home / ".env"))
if ductor_home != main_home:
    merged_extra.update(load_env_secrets(ductor_home / ".env"))
if extra_env:
    merged_extra.update(extra_env)
extra_env = merged_extra or None
```

The upstream task ID path must remain in `_docker_env_flags()`:

```python
if task_id := task_id_from_label(config.process_label):
    env_flags += ["-e", f"DUCTOR_TASK_ID={task_id}"]
```

Also retain upstream `format_cli_cmd()`, prompt temporary-file helpers, and stdin
handling. If manual editing is necessary, edit only the conflicting hunks and
stage the file.

- [ ] **Step 3: Audit `ductor_bot/infra/docker.py`**

Require the upstream import and safe Docker command log:

```python
from ductor_bot.cli._log_redact import redact_cmd_for_log
```

```python
logger.debug("docker run cmd: %s", " ".join(redact_cmd_for_log(cmd)))
```

Retain the local build contract:

```python
async def _build_image(
    self,
    image: str,
    versions: ProviderCliVersions,
) -> bool:
```

The build command must add all `versions.build_args()`, must not contain global
`--no-cache`, and `_exec_stream()` must continue returning no captured
diagnostics.

Retain unconditional `.env` injection:

```python
flags: list[str] = []
for key, value in load_env_secrets(self._paths.env_file).items():
    flags += ["-e", f"{key}={value}"]
return flags
```

Do not add L3 follow-up hardening for mount/path arguments or raw
container-start failure diagnostics in this merge.

- [ ] **Step 4: Audit `ductor_bot/cli_commands/docker.py`**

Require the local rebuild entry point:

```python
def docker_rebuild() -> None:
    """Build, verify, and deploy a candidate Docker image."""
    from ductor_bot.infra.docker_rebuild import rebuild_docker_image
```

The command must still:

- validate Docker availability and `DockerConfig`;
- call `rebuild_docker_image(...)`;
- return `SystemExit(1)` on failures;
- print only the approved safe completion summary.

Require upstream extras resolution in `docker_extras_add()`:

```python
from ductor_bot.infra.docker_extras import DOCKER_EXTRAS_BY_ID, resolve_extras
```

```python
new_ids = [e.id for e in resolve_extras([extra_id]) if e.id not in current_set]
```

Do not restore the old "remove container and image, rebuild later" command.

- [ ] **Step 5: Audit `tests/cli/test_env_injection.py`**

Require all three upstream task ID tests:

```text
test_subprocess_env_sets_task_id_for_task_label
test_subprocess_env_omits_task_id_for_other_labels
test_docker_wrap_sets_task_id_for_task_label
```

Require all local Docker environment tests:

```text
test_docker_wrap_injects_secrets
test_docker_wrap_env_file_wins_over_host_env
test_docker_wrap_sub_agent_env_overrides_main
test_docker_wrap_provider_extra_env_wins
```

The upstream test named `test_docker_wrap_does_not_override_host_env` expresses
the behavior deliberately replaced by the fork and must not coexist with the
local `env_file_wins_over_host_env` assertion.

- [ ] **Step 6: Run overlap-focused tests before committing the merge**

Stage any hunk-level conflict resolutions, then confirm no unresolved path
remains:

```bash
git add \
  ductor_bot/cli/base.py \
  ductor_bot/cli_commands/docker.py \
  ductor_bot/infra/docker.py \
  tests/cli/test_env_injection.py
git diff --name-only --diff-filter=U
```

Expected: the unresolved-path command prints nothing.

Synchronize the worktree-local environment to the staged upstream lockfile:

```bash
uv sync --frozen --all-extras
```

Expected: exit status 0 without installing or restarting the live service.

Run:

```bash
uv run pytest -q \
  tests/cli/test_env_injection.py \
  tests/cli/test_docker_wrap.py \
  tests/cli/test_log_redact.py \
  tests/cli/test_docker_rebuild_command.py \
  tests/infra/test_docker.py \
  tests/infra/test_docker_extras.py \
  tests/infra/test_docker_image.py \
  tests/infra/test_docker_rebuild.py \
  tests/infra/test_docker_tools.py
```

Expected: exit status 0. In particular:

- the new local characterization test passes;
- upstream Docker debug logging redacts environment values;
- task IDs remain available;
- candidate-first rebuild tests pass;
- extras remain before the provider layer;
- Playwright remains Python-only.

If a known overlap fails, invoke `superpowers:test-driven-development`, use the
failing contract as RED, make the smallest hunk-level correction described in
Steps 2–5, and rerun this exact command. For an unexpected behavior requiring
new design, stop and request approval instead of improvising.

- [ ] **Step 7: Verify and create the merge commit**

Run:

```bash
git diff --name-only --diff-filter=U
git diff --cached --check
git status --short
git commit -m "Merge upstream 3e3c88af into fork"
git rev-parse HEAD^1
git rev-parse HEAD^2
```

Expected:

- no unresolved paths;
- no whitespace errors;
- the merge commit is created;
- second parent is exactly
  `3e3c88af57bc094105e73cd24673075e076591ab`.

The first parent is the branch tip containing the approved documents and
pre-merge characterization commit.

---

### Task 3: Validate Upstream Configuration, Providers, Messaging, and Persistence

**Files:**

- Verify: `pyproject.toml`
- Verify: `uv.lock`
- Test: `tests/config/test_backward_compatibility_integration.py`
- Test: `tests/test_config.py`
- Test: `tests/test_main.py`
- Test: `tests/cli/test_log_redact.py`
- Test: `tests/cli/test_grok_discovery.py`
- Test: `tests/cli/test_grok_provider.py`
- Test: `tests/cli/test_init_wizard.py`
- Test: `tests/messenger/slack/`
- Test: `tests/workspace/test_project_roots.py`
- Test: `tests/multiagent/test_bus.py`
- Test: `tests/orchestrator/test_interagent.py`
- Test: `tests/session/test_named_recovery.py`

**Interfaces:**

- Consumes: the merge commit and upstream `AgentConfig`, Grok, Slack, project
  root, and scoped inter-agent session implementations.
- Produces: evidence that upstream-only behavior works without writing real user
  state or extending Grok Docker support.

- [ ] **Step 1: Synchronize the isolated environment to the merged lockfile**

Run:

```bash
uv sync --frozen --all-extras
```

Expected: exit status 0 using the merged upstream `uv.lock`. Do not run
`ductor install`, `uv tool install`, service installation, or onboarding.

- [ ] **Step 2: Verify packaging came from upstream**

Run:

```bash
git diff d1167a016eaddc779ecd3f7d70c077832b22a4eb..HEAD -- \
  pyproject.toml uv.lock
rg -n 'version = "0.20.1"|slack-bolt|slack-sdk' pyproject.toml
```

Expected: the package version is `0.20.1`, Slack optional dependencies are
present, and there is no fork-specific dependency rewrite.

- [ ] **Step 3: Run configuration and persistence compatibility tests**

Run:

```bash
uv run pytest -q \
  tests/config/test_backward_compatibility_integration.py \
  tests/test_config.py \
  tests/test_main.py \
  tests/multiagent/test_bus.py \
  tests/orchestrator/test_interagent.py \
  tests/session/test_named_recovery.py
```

Expected: exit status 0. Tests must use temporary paths. Confirm coverage for:

- recursive missing-default insertion without overwriting user values;
- transport normalization and Slack config;
- old `ia-<sender>` entries;
- new chat/topic-scoped inter-agent session names.

Do not run the application against the real Ductor home.

- [ ] **Step 4: Run upstream provider, messaging, workspace, and logging tests**

Run:

```bash
uv run pytest -q \
  tests/cli/test_log_redact.py \
  tests/cli/test_grok_discovery.py \
  tests/cli/test_grok_provider.py \
  tests/cli/test_init_wizard.py \
  tests/messenger/slack \
  tests/workspace/test_project_roots.py
```

Expected: exit status 0.

G1 boundary:

- do not add Grok to `Dockerfile.sandbox`;
- do not add Grok npm/version resolution;
- do not add a Docker-mode rejection;
- record the known missing Grok binary in the shared Docker image.

L3 boundary:

- keep upstream environment-value redaction;
- do not add new mount/path or raw container-start failure diagnostic
  redaction in this task.

- [ ] **Step 5: Stop on an unplanned compatibility requirement**

No production change is planned in this task. If a focused test fails because
the merge requires behavior not specified in the four-overlap resolution:

1. record the failing test name and whether it passed before the merge;
2. identify the upstream and local code paths involved;
3. stop and request a design/plan update.

Do not improvise a production fix. After approval and a concrete plan update,
the repair must use `superpowers:test-driven-development`.

---

### Task 4: Run Final Verification and Report Without Integrating

**Files:**

- Verify: all changed source, tests, and documentation.
- Do not modify production files unless a preceding RED test justifies an
  approved compatibility repair.

**Interfaces:**

- Consumes: the completed merge and any TDD compatibility commits.
- Produces: a local verified synchronization branch and an evidence-based final
  report.

- [ ] **Step 1: Run all synchronization-focused tests**

Run:

```bash
uv run pytest -q \
  tests/cli/test_docker_rebuild_command.py \
  tests/cli/test_docker_wrap.py \
  tests/cli/test_env_injection.py \
  tests/cli/test_log_redact.py \
  tests/infra/test_docker.py \
  tests/infra/test_docker_extras.py \
  tests/infra/test_docker_image.py \
  tests/infra/test_docker_mounts.py \
  tests/infra/test_docker_published_ports.py \
  tests/infra/test_docker_rebuild.py \
  tests/infra/test_docker_tools.py \
  tests/config/test_backward_compatibility_integration.py \
  tests/cli/test_grok_discovery.py \
  tests/cli/test_grok_provider.py \
  tests/messenger/slack \
  tests/workspace/test_project_roots.py \
  tests/multiagent/test_bus.py \
  tests/orchestrator/test_interagent.py \
  tests/session/test_named_recovery.py
```

Expected: exit status 0.

- [ ] **Step 2: Invoke verification-before-completion**

Read and follow `superpowers:verification-before-completion` before making any
claim that the synchronization is complete or passing.

- [ ] **Step 3: Run Ruff formatting and lint checks**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
```

Expected: both commands exit 0. Do not bulk-format unrelated upstream files to
hide a failure; identify whether any failure is pre-existing, upstream, or caused
by conflict resolution.

- [ ] **Step 4: Run mypy**

Run:

```bash
uv run mypy ductor_bot
```

Expected: exit status 0.

- [ ] **Step 5: Run the complete pytest suite**

Run:

```bash
uv run pytest -q
```

Expected: exit status 0. Compare against the Task 1 baseline. If it stalls,
rerun:

```bash
uv run pytest -vv -x
```

Do not call an interrupted or incomplete run a pass. Classify failures as:

- present before the merge;
- introduced by synchronization;
- environmental.

Synchronization regressions must be resolved through an approved RED/GREEN
cycle. Existing or environmental failures must be reported accurately.

- [ ] **Step 6: Verify Git topology and prohibited side effects**

Run:

```bash
git status --short --branch
git log --oneline --decorate --graph -12
sync_merge_commit=$(git rev-list --first-parent --merges -n 1 HEAD)
git rev-list --parents -n 1 "$sync_merge_commit"
test "$(git rev-parse "$sync_merge_commit^2")" = \
  3e3c88af57bc094105e73cd24673075e076591ab
git branch --show-current
git worktree list
```

Expected:

- branch remains `chore/sync-upstream-2026-07-25`;
- the ordinary merge contains locked upstream as a parent;
- the old Docker worktree still exists;
- no merge to `main`, push, or pull request occurred;
- no real Docker rebuild or container/service mutation occurred.

- [ ] **Step 7: Deliver the execution report and stop**

Report:

- locked local, merge-base, and upstream commits;
- merge commit and any compatibility commits;
- the four overlap resolutions;
- evidence for each protected local Docker capability;
- focused, Ruff, mypy, and complete pytest results;
- any baseline or environmental failures;
- M2-U configuration behavior;
- L3 residual logging risks;
- G1 Grok Docker limitation;
- explicit confirmation that no real rebuild, `main` integration, push, or pull
  request occurred.

Then stop and wait for user approval. Do not run
`superpowers:finishing-a-development-branch` and do not integrate the branch.
