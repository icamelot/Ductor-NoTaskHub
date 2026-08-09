# Remove TaskHub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user explicitly prohibited sub-agents and worktrees for this task.

**Goal:** Completely remove the legacy TaskHub product surface and runtime while preserving all unrelated Ductor automation, transports, provider execution, named sessions, sub-agents, and inter-agent messaging.

**Architecture:** Perform a layered hard deletion in one final change: remove public entry points and prompt injection, detach Supervisor/InternalAgentAPI wiring, delete TaskHub delivery and process-label semantics, then remove the dead implementation, configuration, workspace defaults, tests, documentation, and translations. Upgrade migrations remove the obsolete top-level `tasks` config and known deployed `task_tools` files, but never touch `tasks.json` or existing `workspace/tasks/` task data.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, Pydantic 2, aiogram, matrix-nio, slack-bolt, pytest, Ruff, mypy, Git/GitHub.

## Global Constraints

- Work inline in this session; do not dispatch sub-agents.
- Use the existing environment only; do not install or upgrade dependencies.
- Do not create a worktree.
- The active local `main` starts at `origin/main`; `archive/comfyui-plans` preserves the three excluded ComfyUI documentation commits.
- Do not use `git clean`, `git reset --hard`, `git checkout --`, rebase, or history rewriting.
- Preserve all protected untracked paths: both TaskHub prompts, the PixAI spec, and `worktrees`.
- Do not modify or delete runtime `~/.ductor/tasks.json` or `~/.ductor/workspace/tasks/` data.
- Remove old `/tasks` and `/tasks/*` routes completely; do not retain removed/tombstone responses.
- Preserve `asyncio.Task`, `ductor_bot/background/`, `ductor_bot/infra/task_runner.py::TaskResult`, cron, webhook, heartbeat, memory, named sessions, sub-agents, async inter-agent messaging, provider executors, generic process management, and `ns:` labels.
- Remove the historical `workspace/tasks -> workspace/cron_tasks` migration as explicitly approved after confirming the current installation has no pending cron data.
- Preserve historical `docs/superpowers` plan/spec/prompt records; treat their TaskHub text as explained historical residue, not product documentation.
- Do not commit until implementation, tests, diff review, and the final publication confirmation are complete.

---

## File Structure

### Delete

- `ductor_bot/tasks/` — TaskHub, registry, and TaskHub-specific models.
- `ductor_bot/orchestrator/selectors/task_selector.py` — `/tasks` selector and `tsc:*` callback implementation.
- `ductor_bot/_home_defaults/workspace/tasks/` — TaskHub task-folder template.
- `ductor_bot/_home_defaults/workspace/tools/task_tools/` — deployed TaskHub CLI scripts and rules.
- `tests/tasks/` — TaskHub implementation and API tests.
- `docs/modules/tasks.md` — TaskHub product documentation.

### Modify: configuration and workspace migration

- `ductor_bot/config.py` — remove `TasksConfig` and `AgentConfig.tasks`.
- `config.example.json` — remove the `tasks` object.
- `ductor_bot/workspace/paths.py` — remove `tasks_dir` and `tasks_registry_path`.
- `ductor_bot/workspace/init.py` — remove TaskHub default directories/Zone 2 registration and the old cron migration; migrate raw config and clean known deployed TaskHub tools safely.
- `tests/test_config.py`, `tests/config/test_backward_compatibility_integration.py` — cover old config compatibility.
- `tests/workspace/test_init.py`, `tests/workspace/test_paths_extended.py` — cover no-new-directory behavior and safe deployed-tool cleanup.

### Modify: runtime and public surface

- `ductor_bot/orchestrator/core.py`, `commands.py`, `hooks.py` — remove TaskHub ownership, `/tasks`, and delegation prompt hooks.
- `ductor_bot/commands.py`, `ductor_bot/messenger/commands.py` — remove command discovery/classification.
- `ductor_bot/messenger/callback_router.py` — remove `tsc:*` routing.
- `ductor_bot/multiagent/internal_api.py` — remove `/tasks/*`, TaskHub state, and task-only semantics.
- `ductor_bot/multiagent/supervisor.py` — remove TaskHub creation, wiring, abort, and shutdown.
- `ductor_bot/bus/adapters.py`, `ductor_bot/bus/envelope.py` — remove TaskHub adapters and origins only.
- `ductor_bot/messenger/protocol.py`, `ductor_bot/messenger/multi.py` — remove result/question callback interfaces and fan-out.
- Telegram, Matrix, and Slack bot/transport modules — remove TaskHub handlers/help entries while retaining all other origins and messages.
- `ductor_bot/cli/types.py`, `base.py`, `executor.py`, `process_registry.py`, `_log_redact.py` — remove TaskHub labels, env injection, cancellation helper, and secret-name entry.

### Modify: tests, translations, and documentation

- Shared command, orchestrator, multiagent, bus, CLI, messenger, and transport tests — replace TaskHub-specific expectations with negative or shared-infrastructure assertions.
- `ductor_bot/i18n/*/commands.toml`, `ductor_bot/i18n/*/chat.toml`, and `ductor_bot/i18n/__init__.py` — remove TaskHub command/UI keys only.
- Root documentation, current docs, module docs, default workspace rules, and default config rules — remove all current TaskHub entry points and correct named-session wording.
- `llms.txt` — remove TaskHub capability references.

---

### Task 1: Remove User-Facing Commands, Selectors, and Delegation Prompts

**Files:**

- Modify: `tests/test_commands.py`
- Modify: `tests/messenger/test_commands.py`
- Create: `tests/messenger/test_callback_router.py`
- Modify: `tests/messenger/telegram/test_middleware.py`
- Modify: `tests/orchestrator/test_hooks.py`
- Modify: `tests/orchestrator/test_injection.py`
- Modify: `ductor_bot/commands.py`
- Modify: `ductor_bot/messenger/commands.py`
- Modify: `ductor_bot/messenger/callback_router.py`
- Modify: `ductor_bot/messenger/telegram/app.py`
- Modify: `ductor_bot/messenger/telegram/middleware.py`
- Modify: `ductor_bot/orchestrator/commands.py`
- Modify: `ductor_bot/orchestrator/core.py`
- Modify: `ductor_bot/orchestrator/hooks.py`
- Delete: `ductor_bot/orchestrator/selectors/task_selector.py`

**Interfaces:**

- Consumes: existing `CommandRegistry`, `route_callback`, and `MessageHookRegistry` behavior.
- Produces: no `/tasks` registration, no `tsc:*` callback recognition, and no TaskHub prompt suffix.

- [ ] **Step 1: Add failing negative command and callback tests**

Add exact assertions to the existing command/callback test modules:

```python
def test_taskhub_command_is_not_advertised() -> None:
    assert "tasks" not in {name for name, _description in get_bot_commands()}
    assert "tasks" not in ORCHESTRATOR_COMMANDS


async def test_taskhub_callback_is_not_handled(orch: Orchestrator) -> None:
    result = await route_callback(orch, SessionKey.telegram(1), "tsc:r")
    assert result.handled is False
```

Also replace TaskHub-specific process labels in generic injection tests with a neutral label such as `"async-result"`; those tests protect generic injection, not TaskHub. Add `("/tasks", False)` to the existing `is_quick_command` parameterization.

- [ ] **Step 2: Run the focused tests and verify the new assertions fail**

Run:

```bash
.venv/bin/pytest tests/test_commands.py tests/messenger/test_commands.py tests/messenger/test_callback_router.py tests/orchestrator/test_hooks.py tests/orchestrator/test_injection.py -q
```

Expected: failures show `tasks` is still advertised/routed and delegation hooks are still registered.

- [ ] **Step 3: Remove the public surface**

Remove:

- `("tasks", ...)` from bot command discovery;
- `"tasks"` from orchestrator command classification and Telegram quick-command handling;
- Telegram's explicit `Command("tasks")` registration and `_on_tasks` method;
- `cmd_tasks` import, implementation, and registry entry;
- TaskHub property/setter from `Orchestrator`;
- `DELEGATION_BRIEF`, `DELEGATION_REMINDER`, their condition helper, and registration;
- task-selector imports and `tsc:*` branch from the shared callback router;
- the selector module itself.

Do not change `/sessions`, `nsc:*`, `/session`, memory hooks, or generic prompt injection.

- [ ] **Step 4: Re-run the focused tests**

Run the Step 2 command.

Expected: all selected tests pass; generic hook and injection tests remain active.

---

### Task 2: Detach Supervisor and Remove Internal Task APIs

**Files:**

- Modify: `tests/multiagent/test_internal_api.py`
- Modify: `tests/multiagent/test_supervisor.py`
- Delete: `tests/tasks/test_api_endpoints.py`
- Modify: `ductor_bot/multiagent/internal_api.py`
- Modify: `ductor_bot/multiagent/supervisor.py`

**Interfaces:**

- Consumes: `InterAgentBus`, `/interagent/*`, `/interagent/health`, agent stacks, and shared-knowledge lifecycle.
- Produces: Supervisor startup/shutdown without TaskHub and an InternalAgentAPI whose `/tasks/*` paths naturally return 404.

- [ ] **Step 1: Add failing route-absence and startup tests**

Add to `tests/multiagent/test_internal_api.py`:

```python
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/tasks/create"),
        ("post", "/tasks/resume"),
        ("post", "/tasks/ask_parent"),
        ("get", "/tasks/list"),
        ("post", "/tasks/cancel"),
        ("post", "/tasks/delete"),
    ],
)
async def test_taskhub_routes_are_not_registered(
    client: TestClient, method: str, path: str
) -> None:
    response = await getattr(client, method)(path)
    assert response.status == 404
```

Add/adjust Supervisor assertions so startup never constructs `TaskHub` or `TaskRegistry` and shutdown has no TaskHub branch, while InternalAgentAPI health/inter-agent startup remains required.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
.venv/bin/pytest tests/multiagent/test_internal_api.py tests/multiagent/test_supervisor.py -q
```

Expected: `/tasks/*` currently returns TaskHub responses rather than 404 and TaskHub wiring assertions fail.

- [ ] **Step 3: Delete the TaskHub API and supervisor wiring**

In `InternalAgentAPI`, remove the TaskHub type import, `_task_hub`, all six route registrations, `set_task_hub`, six handlers, and task-only wording. Keep health and inter-agent routes unchanged.

In `AgentSupervisor`, remove TaskHub/TaskRegistry/TaskHub-only ProcessRegistry imports and state; initialization; `_wire_task_hub`; post-startup wiring; `_abort_all_tasks`; abort aggregation; and shutdown. Keep `self._tasks: dict[str, asyncio.Task[int]]`, because it tracks agent lifecycles.

- [ ] **Step 4: Re-run focused tests**

Run the Step 2 command.

Expected: all selected tests pass, including health, async inter-agent, start failure, abort-all, and shutdown coverage.

---

### Task 3: Remove TaskHub Bus and Transport Delivery

**Files:**

- Modify: `tests/bus/test_adapters.py`
- Modify: `tests/bus/test_bus.py`
- Modify: `tests/bus/test_envelope.py`
- Modify: `tests/messenger/test_multi.py`
- Modify: transport tests under `tests/messenger/{telegram,matrix,slack}/`
- Modify: `ductor_bot/bus/adapters.py`
- Modify: `ductor_bot/bus/envelope.py`
- Modify: `ductor_bot/messenger/protocol.py`
- Modify: `ductor_bot/messenger/multi.py`
- Modify: `ductor_bot/messenger/telegram/app.py`
- Modify: `ductor_bot/messenger/telegram/transport.py`
- Modify: `ductor_bot/messenger/matrix/bot.py`
- Modify: `ductor_bot/messenger/matrix/transport.py`
- Modify: `ductor_bot/messenger/slack/bot.py`
- Modify: `ductor_bot/messenger/slack/transport.py`

**Interfaces:**

- Consumes: generic `Envelope`, `LockMode`, `DeliveryMode`, transport routing, and async inter-agent result delivery.
- Produces: no TaskHub origins/adapters/callbacks; unchanged delivery for background sessions, cron, heartbeat, webhook, and inter-agent messages.

- [ ] **Step 1: Convert shared tests to the post-TaskHub contract**

Delete TaskHub-only fake result types and cases. Update the origin assertion to the exact remaining set:

```python
assert {origin.value for origin in Origin} == {
    "background",
    "cron",
    "webhook_wake",
    "webhook_cron",
    "heartbeat",
    "interagent",
    "user",
    "api",
}
```

Retain generic lock/injection tests but use `Origin.INTERAGENT` or `Origin.BACKGROUND`, never `Origin.TASK_RESULT`. Remove only TaskHub fan-out and transport delivery cases; retain all other transport dispatch/fallback tests.

- [ ] **Step 2: Run focused tests and verify contract failures**

```bash
.venv/bin/pytest tests/bus tests/messenger/test_multi.py tests/messenger/telegram/test_transport.py tests/messenger/matrix/test_transport.py tests/messenger/slack/test_transport.py -q
```

Expected: the remaining-origin contract fails until TaskHub origins are removed.

- [ ] **Step 3: Remove TaskHub delivery code**

Delete `from_task_result`, `_build_task_injection_prompt`, and `from_task_question`; remove the two origins; remove `BotProtocol` callbacks and `MultiBotAdapter` fan-out; remove bot callback methods and task-selector handler; remove TaskHub transport handlers and dispatch entries in all three transports.

Do not alter the generic bus injector, lock pool, delivery acknowledgement, broadcast behavior, or async inter-agent callback.

- [ ] **Step 4: Re-run focused tests**

Run the Step 2 command.

Expected: all selected bus and transport tests pass.

---

### Task 4: Remove TaskHub Process Labels and Environment Injection

**Files:**

- Modify: `tests/cli/test_env_injection.py`
- Modify: `tests/cli/test_process_registry.py`
- Modify: `tests/cli/test_types.py`
- Modify: `ductor_bot/cli/types.py`
- Modify: `ductor_bot/cli/base.py`
- Modify: `ductor_bot/cli/executor.py`
- Modify: `ductor_bot/cli/process_registry.py`
- Modify: `ductor_bot/cli/_log_redact.py`

**Interfaces:**

- Consumes: generic `AgentRequest.process_label`, Docker/host env construction, process registration, topic abort, `kill_all`, and `ns:` named-session protection.
- Produces: no `task:`/`task_result:` semantics, no `DUCTOR_TASK_ID`, and no `kill_for_task`; generic process tracking remains intact.

- [ ] **Step 1: Write the negative env/label tests**

Replace TaskHub-positive tests with:

```python
def test_subprocess_env_never_injects_legacy_task_id(tmp_path: Path) -> None:
    config = CLIConfig(working_dir=tmp_path, process_label="task:legacy")
    env = build_subprocess_env(config)
    assert env is not None
    assert "DUCTOR_TASK_ID" not in env


def test_only_named_sessions_are_preserved() -> None:
    assert _PRESERVED_LABEL_PREFIXES == ("ns:",)
```

Update topic-abort tests so `ns:` remains protected while neutral foreground labels are killed. Delete the `kill_for_task` test block.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
.venv/bin/pytest tests/cli/test_env_injection.py tests/cli/test_process_registry.py tests/cli/test_types.py -q
```

Expected: legacy TaskHub labels still inject/preserve and fail the new contract.

- [ ] **Step 3: Remove label-specific production code**

Delete `task_id_from_label` and its prefix; remove host/Docker `DUCTOR_TASK_ID` injection and the log-redaction key; reduce `_PRESERVED_LABEL_PREFIXES` to `("ns:",)`; delete `kill_for_task`. Keep `AgentRequest.resume_session`, `CLIResponse.session_id`, and provider resume support.

- [ ] **Step 4: Re-run focused tests**

Run the Step 2 command.

Expected: all selected CLI/process tests pass.

---

### Task 5: Remove TaskHub Configuration, Runtime Package, and Workspace Deployment

**Files:**

- Modify: `tests/test_config.py`
- Modify: `tests/config/test_backward_compatibility_integration.py`
- Modify: `tests/workspace/test_init.py`
- Modify: `tests/workspace/test_paths_extended.py`
- Modify: `ductor_bot/config.py`
- Modify: `config.example.json`
- Modify: `ductor_bot/workspace/paths.py`
- Modify: `ductor_bot/workspace/init.py`
- Delete: `ductor_bot/tasks/`
- Delete: `tests/tasks/`
- Delete: `ductor_bot/_home_defaults/workspace/tasks/`
- Delete: `ductor_bot/_home_defaults/workspace/tools/task_tools/`

**Interfaces:**

- Consumes: raw JSON config smart-merge and workspace initialization.
- Produces: old configs are atomically cleaned, known deployed TaskHub tools are removed safely, and startup never creates TaskHub paths or imports `ductor_bot.tasks`.

- [ ] **Step 1: Add failing migration and workspace tests**

Cover these exact cases:

```python
def test_workspace_init_removes_legacy_tasks_config_and_preserves_unknown_key(
    tmp_path: Path,
) -> None:
    paths = _make_paths(tmp_path)
    paths.config_path.parent.mkdir(parents=True)
    paths.config_path.write_text(
        json.dumps({"tasks": {"enabled": True}, "future_key": {"value": 7}})
    )
    init_workspace(paths)
    saved = json.loads(paths.config_path.read_text())
    assert "tasks" not in saved
    assert saved["future_key"] == {"value": 7}


def test_workspace_init_removes_known_task_tools_but_preserves_unknown_file(
    tmp_path: Path,
) -> None:
    paths = _make_paths(tmp_path)
    legacy = paths.workspace / "tools" / "task_tools"
    legacy.mkdir(parents=True)
    (legacy / "create_task.py").write_text("legacy")
    (legacy / "my_notes.txt").write_text("keep")
    init_workspace(paths)
    assert not (legacy / "create_task.py").exists()
    assert (legacy / "my_notes.txt").read_text() == "keep"
```

Also assert a fresh init does not create `workspace/tasks` or deploy `task_tools`; invalid JSON is not overwritten; `DuctorPaths` has no TaskHub path properties; and `AgentConfig.model_validate({"tasks": {...}})` still succeeds by ignoring the unknown field.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
.venv/bin/pytest tests/test_config.py tests/config/test_backward_compatibility_integration.py tests/workspace/test_init.py tests/workspace/test_paths_extended.py -q
```

Expected: old fields remain, fresh startup creates TaskHub paths/tools, and TaskHub path properties still exist.

- [ ] **Step 3: Implement safe upgrade cleanup**

In `_smart_merge_config`, remove only the obsolete top-level field before merge/write:

```python
removed_tasks = "tasks" in existing
existing.pop("tasks", None)
merged = {**defaults, **existing}
if removed_tasks:
    logger.info("Removed obsolete TaskHub config field: tasks")
if removed_tasks or merged != existing:
    atomic_json_save(paths.config_path, merged)
```

Define a fixed legacy filename set containing the shipped scripts/rules and remove only those from `workspace/tools/task_tools`; remove the directory only if empty. Catch `OSError` per file/directory and log a warning without aborting startup. Do not inspect or touch `tasks.json` or `workspace/tasks` data.

- [ ] **Step 4: Delete dead configuration, paths, defaults, and runtime**

Remove `TasksConfig`, `AgentConfig.tasks`, the example JSON block, TaskHub path properties, `workspace/tasks` from `_REQUIRED_DIRS`, `task_tools` from `_ZONE2_PY_DIRS`, and `_migrate_tasks_to_cron_tasks`. Delete the four production TaskHub files, all six dedicated test files, the task-folder default, and all eight task-tool files/rules.

- [ ] **Step 5: Prove no production imports remain**

```bash
rg -n 'ductor_bot\.tasks|TaskHub|TaskRegistry|TaskSubmit|TaskInFlight|TasksConfig' ductor_bot tests -g '*.py'
```

Expected: no output, except no false positive from `ductor_bot.infra.task_runner.TaskResult` because the pattern does not match it.

- [ ] **Step 6: Re-run focused migration tests**

Run the Step 2 command.

Expected: all selected tests pass.

---

### Task 6: Remove Product Documentation, Rules, Help Text, and i18n

**Files:**

- Modify: `README.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `llms.txt`
- Modify: `docs/README.md`, `docs/architecture.md`, `docs/automation.md`, `docs/config.md`, `docs/developer_quickstart.md`, `docs/system_overview.md`
- Modify: `docs/modules/background.md`, `bot.md`, `bus.md`, `cli.md`, `logging.md`, `messenger.md`, `multiagent.md`, `orchestrator.md`, `supervisor.md`, `workspace.md`
- Delete: `docs/modules/tasks.md`
- Modify: `ductor_bot/_home_defaults/workspace/RULES.md`
- Modify: `ductor_bot/_home_defaults/workspace/tools/RULES.md`
- Modify: `ductor_bot/_home_defaults/config/RULES-{all-clis,claude-only,codex-only,gemini-only}.md`
- Modify: locale command/chat TOML files and `ductor_bot/i18n/__init__.py`
- Modify: `tests/i18n/test_loader.py`

**Interfaces:**

- Consumes: post-removal command/runtime behavior.
- Produces: no active documentation or default prompt tells a user/agent to use TaskHub; named background sessions and cron remain accurately documented.

- [ ] **Step 1: Remove TaskHub-only i18n keys and update their callers/tests**

Delete the `bot.tasks` command descriptions and `[tasks]` chat tables in every locale, plus TaskHub plural examples. Keep generic phrases used by named sessions, async inter-agent tasks, scheduled tasks, and interrupted foreground turns.

- [ ] **Step 2: Delete TaskHub documentation and rewrite active indexes**

Delete `docs/modules/tasks.md`. Remove every active reference to TaskHub, `/tasks`, `/tasks/*`, `task_tools`, `tasks.json`, `workspace/tasks`, TaskHub callbacks/origins, `kill_for_task`, `TASKMEMORY`, and `DUCTOR_TASK_ID`. Rewrite “background tasks” to “named background sessions” only where the code refers to `/session`; do not globally replace the word `task`.

- [ ] **Step 3: Remove default workspace and config instructions**

Delete the entire TaskHub delegation section from workspace `RULES.md`, remove the task-tools entry from the tools index, and remove `tasks.enabled/max_parallel` from all four config rule variants. Preserve cron task rules and generic sub-agent guidance.

- [ ] **Step 4: Scan active Markdown and configuration docs**

```bash
rg -n -g '*.md' -g '*.toml' -g '*.json' -g '*.txt' \
  -g '!docs/superpowers/**' \
  '(TaskHub|TasksConfig|ductor_bot/tasks|tasks\.json|workspace/tasks|task_tools|/tasks(?:/|\b)|TASKMEMORY|DUCTOR_TASK_ID|DELEGATION_BRIEF|DELEGATION_REMINDER|tsc:|kill_for_task|on_task_result|on_task_question|task_result|task_question)' \
  README.md AGENTS.md CLAUDE.md GEMINI.md config.example.json llms.txt docs ductor_bot/_home_defaults ductor_bot/i18n
```

Expected: no output. Any generic `task` matches from broader scans must map to cron, named sessions, asyncio, platform Task Scheduler/taskkill, or historical material.

---

### Task 7: Run Layered Regression and Full Verification

**Files:**

- Modify only files required to fix genuine regressions discovered by the approved removal.
- Do not weaken or delete unrelated assertions.

**Interfaces:**

- Consumes: completed Tasks 1–6.
- Produces: evidence that TaskHub is gone and protected Ductor capabilities still pass.

- [ ] **Step 1: Run targeted subsystem suites**

```bash
.venv/bin/pytest \
  tests/config tests/workspace tests/orchestrator tests/bus tests/cli \
  tests/multiagent tests/messenger tests/background tests/cron tests/webhook \
  tests/heartbeat tests/session tests/infra/test_task_runner.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run top-level integration/regression tests**

```bash
.venv/bin/pytest tests/integration tests/test_integration.py tests/test_run.py tests/test_main.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run the full test suite**

```bash
.venv/bin/pytest -q
```

Expected: exit 0 with no failures.

- [ ] **Step 4: Run formatting, lint, and type checking**

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy ductor_bot
```

Expected: all commands exit 0.

- [ ] **Step 5: Run production and repository residue scans**

```bash
rg -n '(ductor_bot\.tasks|TaskHub|TaskRegistry|TaskSubmit|TaskInFlight|TasksConfig|task_hub|set_task_hub|/tasks(?:/|\b)|tsc:|TASKMEMORY|DUCTOR_TASK_ID|DELEGATION_BRIEF|DELEGATION_REMINDER|kill_for_task|from_task_result|from_task_question|on_task_result|on_task_question|task_result:|task:<)' ductor_bot tests README.md AGENTS.md CLAUDE.md GEMINI.md config.example.json llms.txt docs -g '!docs/superpowers/**'
rg -n '(task|background)' ductor_bot tests README.md AGENTS.md CLAUDE.md GEMINI.md config.example.json llms.txt docs -g '!docs/superpowers/**'
```

Expected: the first command has no output. Classify every second-command match as an allowed shared meaning; fix any TaskHub residue.

- [ ] **Step 6: Review diff and protected paths**

```bash
git diff --check
git diff --stat
git diff --name-status
git status --short --branch
git branch -vv
```

Expected: only approved TaskHub removal/plan files are modified or deleted; protected untracked paths remain untracked; `archive/comfyui-plans` still points to `d000307`; no commit exists yet.

---

### Task 8: Final Review, Commit, Push, and Rename Gate

**Files:**

- No further source changes unless review finds a concrete defect.

**Interfaces:**

- Consumes: clean verification evidence and reviewed diff.
- Produces: one intentional local commit, renamed personal GitHub repository, verified remotes, and a final report.

- [ ] **Step 1: Present the final publication manifest before mutation**

Report:

- every file to be committed;
- deletion totals and residue classification;
- exact test/lint/type-check results;
- proposed commit message `refactor: remove TaskHub`;
- `main` commit range to push (TaskHub commit only beyond current `origin/main`);
- repository rename target `icamelot/Ductor-NoTaskHub`;
- final `origin` and unchanged `upstream` URLs;
- confirmation that protected untracked files and `archive/comfyui-plans` are excluded.

Then request one final explicit user confirmation. Stop before commit, push, GitHub rename, or remote edit.

- [ ] **Step 2: After confirmation, stage only the reviewed manifest and commit**

Use explicit paths or a reviewed `git add -u` plus the single plan path. Do not use `git add .` while protected untracked content exists.

```bash
git diff --cached --check
git status --short
git commit -m "refactor: remove TaskHub"
```

Expected: one commit on local `main`; protected content remains untracked.

- [ ] **Step 3: Push the implementation to the existing personal repository**

```bash
git push origin main
```

Expected: `icamelot/ductor` remote `main` advances to the reviewed commit; `archive/comfyui-plans` is not pushed.

- [ ] **Step 4: Rename only the personal GitHub repository**

Use the GitHub CLI/API to rename `icamelot/ductor` to the exact case-sensitive name `Ductor-NoTaskHub`. Do not alter `PleasePrompto/ductor`.

- [ ] **Step 5: Update and verify remotes and remote state**

```bash
git remote set-url origin https://github.com/icamelot/Ductor-NoTaskHub.git
git remote -v
git ls-remote --heads origin main
git ls-remote --heads upstream main
git status --short --branch
```

Expected:

```text
origin   https://github.com/icamelot/Ductor-NoTaskHub.git
upstream https://github.com/PleasePrompto/ductor.git
```

The origin `main` SHA equals local `HEAD`, GitHub reports `main` as the default branch, and the final report includes commit SHA, tests, remotes, repository URL, protected untracked state, and local archive branch state.

---

## Plan Self-Review

- Spec coverage: all approved runtime, migration, documentation, testing, Git separation, and publication requirements map to Tasks 1–8.
- Placeholder scan: no TBD/TODO or unspecified implementation step remains.
- Type consistency: `AgentRequest.resume_session`, `infra.task_runner.TaskResult`, generic `Envelope`, `LockMode`, `ProcessRegistry`, and `ns:` semantics are explicitly retained.
- Scope check: this is one cohesive subtractive change; the GitHub rename is sequenced behind a separate final confirmation gate rather than treated as an independent implementation subsystem.
