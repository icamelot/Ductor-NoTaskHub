# DeepSeek, Usage, and Authentication Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore DeepSeek as an isolated logical provider, a transport-independent three-provider `/usage` report with Ductor-owned balance history, main-only Claude OAuth token keepalive, and exact sub-agent chat-auth synchronization on the current Ductor architecture.

**Architecture:** A validated `DeepseekRuntime` separates non-secret config from the root-home secret and is passed through the provider registry and CLI service without ever persisting the key. A new `ductor_bot.usage` package owns typed provider clients, snapshot persistence, daily deltas, formatting, and balance observation; the existing observer manager owns scheduling for both balance collection and Claude token keepalive. The supervisor synchronizes the resolved sub-agent config before a newly created or rebuilt stack can run.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, Pydantic 2, Decimal, ZoneInfo, atomic JSON/text writes, pytest, Ruff, mypy, TOML i18n catalogs.

## Global Constraints

- The approved design is `docs/superpowers/specs/2026-08-13-deepseek-usage-auth-sync-design.md`; it is authoritative when this plan is ambiguous.
- Start from `main` containing approved spec commit `4d98616` and this plan/prompt; use branch `feat/restore-deepseek-usage-auth` in `.worktrees/restore-deepseek-usage-auth`.
- Treat `feat/deepseek-provider` only as a read-only behavioral reference. Do not cherry-pick, merge, or copy whole files from it.
- Do not restore TaskHub, ComfyUI, fork version `0.999.0+icamelot`, personal-assistant changes, or abandoned Docker work.
- Do not modify Docker users, privileges, images, rebuild logic, containers, mounts, startup commands, or accepted Docker behavior.
- Keep DeepSeek's logical provider/session bucket named `deepseek`; only its process adapter is Claude CLI.
- Read `DEEPSEEK_API_KEY` only from the root Ductor home's `.env`; never persist it in JSON or expose it in logs, errors, metadata, status, reprs, or commands.
- DeepSeek config is hot reloadable, but the captured key is not. A changed `.env` takes effect only after Ductor restart.
- Network calls have a 10-second total timeout except Claude OAuth refresh, which also uses a finite 10-second timeout in this implementation.
- Only the main agent writes balance history and runs either new observer. Sub-agents read the root snapshot file and share the root DeepSeek key.
- Use `Decimal` strings for money, UTC for stored timestamps, and `user_timezone` only for presentation and local-day boundaries.
- Follow strict TDD for every behavior: write a focused test, run it and observe RED, implement the minimum behavior, then run it and observe GREEN.
- Commit each numbered implementation task independently. Do not mix documentation-only planning commits into the feature commits.
- Unit and integration tests must not require live credentials. Gemini, Claude, Grok, and other CLI auth failures in optional operational probes are non-blocking when the user is not logged in.
- After all verification and review, present the publication manifest and stop for explicit user approval. Only then merge into local `main`, reverify, and push `main` to `origin`.
- Package installation, service restart, Docker rebuild, deployment, and live credential probes are separate actions and are not authorized by this plan.

---

## File Structure

### New production files

- `ductor_bot/cli/deepseek.py`: validate DeepSeek config, capture the root secret, hold the redaction-safe runtime contract, and build per-invocation Anthropic environment overrides.
- `ductor_bot/cli/claude_token_keepalive.py`: read, refresh, compare, and atomically replace Claude OAuth login credentials; expose a cancel-safe observer.
- `ductor_bot/usage/__init__.py`: export the public usage-service types.
- `ductor_bot/usage/models.py`: typed success/failure results, usage windows, balances, reports, and daily deltas.
- `ductor_bot/usage/clients.py`: DeepSeek balance, Claude subscription, and Codex subscription HTTP/credential clients.
- `ductor_bot/usage/snapshots.py`: versioned snapshot schema, path-shared locking, legacy import, retention, deduplication, and local-day delta calculation.
- `ductor_bot/usage/service.py`: concurrently collect all providers, isolate failures, coordinate main-write/sub-read snapshot behavior, and render via the formatter.
- `ductor_bot/usage/formatting.py`: localized, provider-neutral `/usage` presentation.
- `ductor_bot/usage/observer.py`: immediate-then-30-minute main-only DeepSeek balance collection.

### Existing production files to modify

- `config.example.json`: add only non-secret DeepSeek defaults and `claude_token_keepalive`.
- `docs/config.md`: document DeepSeek config, root `.env`, `/usage`, snapshot ownership, and keepalive toggle.
- `ductor_bot/config.py`: add `DeepseekConfig`, `AgentConfig` fields, and instance-local DeepSeek model resolution.
- `ductor_bot/config_reload.py`: classify `deepseek` as hot reloadable and keep `claude_token_keepalive` restart-required.
- `ductor_bot/workspace/paths.py`: expose root-home, root `.env`, snapshot, legacy snapshot, and Claude credential paths.
- `ductor_bot/cli/base.py`: carry redaction-safe DeepSeek invocation data into host/Docker execution.
- `ductor_bot/cli/executor.py`: apply DeepSeek environment overrides to host subprocesses.
- `ductor_bot/cli/factory.py`: explicitly delegate logical `deepseek` to `ClaudeCodeCLI`.
- `ductor_bot/cli/service.py`: pass the runtime contract, reuse Claude CLI parameters, and retain logical provider identity.
- `ductor_bot/cli/param_resolver.py`: validate DeepSeek task overrides and reuse Claude reasoning effort/CLI parameters for cron/webhook execution.
- `ductor_bot/orchestrator/providers.py`: own DeepSeek availability, configured models, directives, metadata, and active-provider naming.
- `ductor_bot/orchestrator/selectors/model_selector.py`: display a separate DeepSeek provider and validate direct selection.
- `ductor_bot/orchestrator/core.py`: construct shared services, register `/usage`, rebuild full CLI config safely, and apply DeepSeek hot reload.
- `ductor_bot/orchestrator/commands.py`: expose the thin `/usage` handler.
- `ductor_bot/orchestrator/observers.py`: own new observer instances and their lifecycle.
- `ductor_bot/orchestrator/lifecycle.py`: distinguish main/sub-agent startup and include DeepSeek availability without Claude OAuth.
- `ductor_bot/multiagent/supervisor.py`: sync chat auth before first start and every sub-agent rebuild.
- `ductor_bot/commands.py`: add translated `/usage` menu metadata.
- `ductor_bot/messenger/commands.py`: classify `/usage` as an orchestrator command.
- `ductor_bot/i18n/{de,en,es,fr,id,nl,pt,ru}/commands.toml`: add the menu description.
- `ductor_bot/i18n/{de,en,es,fr,id,nl,pt,ru}/chat.toml`: add every `/usage` label and bounded error state.

### New and modified tests

- Create `tests/cli/test_deepseek.py`.
- Create `tests/cli/test_claude_token_keepalive.py`.
- Create `tests/usage/__init__.py`.
- Create `tests/usage/test_clients.py`.
- Create `tests/usage/test_snapshots.py`.
- Create `tests/usage/test_service.py`.
- Create `tests/usage/test_observer.py`.
- Modify focused existing tests under `tests/test_config.py`, `tests/test_config_reload.py`, `tests/workspace/test_paths.py`, `tests/cli/test_service.py`, `tests/cli/test_param_resolver.py`, `tests/orchestrator/`, `tests/session/`, `tests/messenger/`, `tests/multiagent/test_supervisor.py`, `tests/test_commands.py`, and `tests/i18n/test_loader.py`.

---

### Task 0: Create the Isolated Worktree and Establish the Baseline

**Files:**

- Read: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-08-13-deepseek-usage-auth-sync-design.md`
- Read: `docs/superpowers/plans/2026-08-13-deepseek-usage-auth-sync.md`
- Read: `docs/superpowers/prompts/2026-08-13-execute-deepseek-usage-auth-sync-plan.md`
- Create worktree: `/home/zqxu/ductor/.worktrees/restore-deepseek-usage-auth`

**Interfaces:**

- Consumes: current local `main`, including all three planning documents.
- Produces: clean branch `feat/restore-deepseek-usage-auth` with a recorded baseline.

- [ ] **Step 1: Inspect the source checkout without modifying user files**

Run from `/home/zqxu/ductor`:

```bash
git status --short --branch
git log -5 --oneline
git check-ignore -v .worktrees
git worktree list
```

Expected: `main` contains the approved spec, plan, and execution prompt; `.worktrees` is ignored. The four known untracked planning files and `worktrees` symlink in the main checkout are user-owned and must remain untouched.

- [ ] **Step 2: Create and enter the feature worktree**

```bash
git worktree add \
  /home/zqxu/ductor/.worktrees/restore-deepseek-usage-auth \
  -b feat/restore-deepseek-usage-auth main
cd /home/zqxu/ductor/.worktrees/restore-deepseek-usage-auth
git branch --show-current
git status --short
```

Expected: branch is `feat/restore-deepseek-usage-auth`; worktree status is empty.

- [ ] **Step 3: Read all authorities completely**

```bash
sed -n '1,9999p' AGENTS.md
sed -n '1,9999p' docs/superpowers/specs/2026-08-13-deepseek-usage-auth-sync-design.md
sed -n '1,9999p' docs/superpowers/plans/2026-08-13-deepseek-usage-auth-sync.md
sed -n '1,9999p' docs/superpowers/prompts/2026-08-13-execute-deepseek-usage-auth-sync-plan.md
```

Expected: all files are present and readable. If the plan is longer than the displayed range, continue with `sed` until EOF before editing.

- [ ] **Step 4: Run a clean baseline**

```bash
/home/zqxu/ductor/.venv/bin/pytest -q
/home/zqxu/ductor/.venv/bin/ruff format --check .
/home/zqxu/ductor/.venv/bin/ruff check .
/home/zqxu/ductor/.venv/bin/mypy ductor_bot
/home/zqxu/ductor/.venv/bin/python -m ductor_bot.i18n.check --quiet
```

Expected: every command exits 0. If any baseline command fails, record the exact failure and stop before changing code; do not absorb a pre-existing failure into this feature.

---

### Task 1: Add the DeepSeek Configuration, Secret Boundary, and Logical Model Registry

**Files:**

- Create: `ductor_bot/cli/deepseek.py`
- Modify: `ductor_bot/config.py`
- Modify: `ductor_bot/config_reload.py`
- Modify: `ductor_bot/workspace/paths.py`
- Modify: `config.example.json`
- Modify: `docs/config.md`
- Test: `tests/cli/test_deepseek.py`
- Test: `tests/test_config.py`
- Test: `tests/test_config_reload.py`
- Test: `tests/workspace/test_paths.py`

**Interfaces:**

- Produces `DeepseekConfig(enabled: bool, base_url: str, models: list[str])` and `AgentConfig.deepseek`.
- Produces `AgentConfig.claude_token_keepalive: bool = True` for Task 9.
- Produces `DeepseekRuntime(requested, base_url, models, api_key, error)` with secret field excluded from repr.
- Produces `load_deepseek_api_key(paths: DuctorPaths) -> str`, `resolve_deepseek_runtime(config: DeepseekConfig, api_key: str, *, reserved_models: frozenset[str]) -> DeepseekRuntime`, and `claude_cli_runnable(docker_container: str = "") -> bool`.
- Produces instance methods `ModelRegistry.configure_deepseek(models)` and `ModelRegistry.provider_for(model_id)`; DeepSeek model state must not be module-global.
- Produces `DuctorPaths.root_ductor_home`, `.root_env_file`, `.deepseek_balance_snapshots_path`, `.legacy_balance_snapshots_path`, and `.claude_credentials_path`.

- [ ] **Step 1: Write failing config, path, validation, and secret-separation tests**

Add tests with these exact assertions:

```python
def test_deepseek_defaults_and_keepalive_default() -> None:
    cfg = AgentConfig()
    assert cfg.deepseek.enabled is False
    assert cfg.deepseek.base_url == "https://api.deepseek.com/anthropic"
    assert cfg.deepseek.models == ["deepseek-v4-pro", "deepseek-v4-flash"]
    assert cfg.claude_token_keepalive is True
    assert "api_key" not in cfg.deepseek.model_dump()


def test_sub_agent_paths_resolve_root_owned_usage_state(tmp_path: Path) -> None:
    paths = DuctorPaths(ductor_home=tmp_path / "agents" / "worker")
    assert paths.root_ductor_home == tmp_path
    assert paths.root_env_file == tmp_path / ".env"
    assert paths.deepseek_balance_snapshots_path == tmp_path / "deepseek_balance_snapshots.json"
    assert paths.legacy_balance_snapshots_path == (
        tmp_path / "workspace" / "skills" / "personal-assistant" / ".balance_snapshots.json"
    )


def test_runtime_normalizes_models_and_hides_key() -> None:
    runtime = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, models=[" deepseek-a ", "deepseek-b"]),
        "secret-value",
        reserved_models=frozenset({"opus"}),
    )
    assert runtime.models == ("deepseek-a", "deepseek-b")
    assert runtime.configured is True
    assert "secret-value" not in repr(runtime)


@pytest.mark.parametrize(
    ("base_url", "models", "error"),
    [
        ("http://example.com/anthropic", ["deepseek-a"], "invalid_base_url"),
        ("not-a-url", ["deepseek-a"], "invalid_base_url"),
        ("https://api.deepseek.com/anthropic", ["bad model"], "invalid_model"),
        ("https://api.deepseek.com/anthropic", ["deepseek-a", " deepseek-a "], "duplicate_model"),
        ("https://api.deepseek.com/anthropic", ["opus"], "model_collision"),
    ],
)
def test_invalid_runtime_is_safely_disabled(
    base_url: str, models: list[str], error: str
) -> None:
    runtime = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, base_url=base_url, models=models),
        "secret",
        reserved_models=frozenset({"opus"}),
    )
    assert runtime.configured is False
    assert runtime.error == error


def test_loopback_http_is_allowed_but_remote_http_is_not() -> None:
    runtime = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, base_url="http://127.0.0.1:9000/anthropic"),
        "secret",
        reserved_models=frozenset(),
    )
    assert runtime.configured is True


def test_model_registry_keeps_deepseek_logically_separate() -> None:
    registry = ModelRegistry()
    registry.configure_deepseek(("deepseek-v4-pro", "deepseek-v4-flash"))
    assert registry.provider_for("deepseek-v4-pro") == "deepseek"
    assert registry.provider_for("opus") == "claude"
```

Also assert `classify_changes()` returns `deepseek` in the hot map and `claude_token_keepalive` in restart-required fields, and assert `json.loads(config.example.json)` has no `api_key` anywhere in its `deepseek` object.
Add probe tests that patch executable resolution/subprocess execution: host requires
a resolved `claude` whose `claude --version` exits 0; Docker requires
`docker exec <container> claude --version` to exit 0; missing executable,
nonzero exit, timeout, and `OSError` return false without exception text in logs.

- [ ] **Step 2: Run the focused tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/cli/test_deepseek.py \
  tests/test_config.py \
  tests/test_config_reload.py \
  tests/workspace/test_paths.py \
  -q
```

Expected: collection or assertions fail because the new config, runtime, paths, and model-registry APIs do not exist.

- [ ] **Step 3: Add the exact config and redaction-safe runtime contracts**

Use these contracts in `ductor_bot/config.py` and `ductor_bot/cli/deepseek.py`:

```python
class DeepseekConfig(BaseModel):
    enabled: bool = False
    base_url: str = "https://api.deepseek.com/anthropic"
    models: list[str] = Field(
        default_factory=lambda: ["deepseek-v4-pro", "deepseek-v4-flash"]
    )


@dataclass(frozen=True, slots=True)
class DeepseekRuntime:
    requested: bool
    base_url: str
    models: tuple[str, ...]
    api_key: str = field(default="", repr=False)
    error: str = ""

    @property
    def configured(self) -> bool:
        return (
            self.requested
            and bool(self.models)
            and bool(self.api_key)
            and not self.error
        )

    def invocation_env(self) -> dict[str, str]:
        if not self.configured:
            return {}
        return {
            "ANTHROPIC_BASE_URL": self.base_url,
            "ANTHROPIC_AUTH_TOKEN": self.api_key,
        }
```

`resolve_deepseek_runtime()` must trim model IDs; reject empty, length over 256, whitespace, control/NUL, duplicates, and any collision with `reserved_models`; accept only HTTPS or an HTTP hostname in `{localhost, 127.0.0.1, ::1}`; return one of `disabled`, `invalid_base_url`, `invalid_model`, `duplicate_model`, `model_collision`, or `missing_key` without including input values. `load_deepseek_api_key()` must call `load_env_secrets(paths.root_env_file).get("DEEPSEEK_API_KEY", "").strip()`.

The caller supplies the reserved set from all current Claude, Gemini
alias/discovered, Antigravity static/discovered, and Grok static/discovered
identifiers. It does not yet include Codex cache entries; Task 3 adds the late
Codex-cache collision guard after cache initialization.

`claude_cli_runnable()` resolves `claude` with `shutil.which()` on host and
runs `<resolved> --version`; in Docker it runs
`docker exec <container> claude --version`. Both probes use a 10-second timeout,
discard stdout/stderr, return true only for exit 0, and log only a bounded
availability category.

- [ ] **Step 4: Make model resolution instance-local and add root-owned paths**

Replace the static-only registry shape with:

```python
class ModelRegistry:
    def __init__(self) -> None:
        self._deepseek_models: frozenset[str] = frozenset()

    @property
    def deepseek_models(self) -> frozenset[str]:
        return self._deepseek_models

    def configure_deepseek(self, models: tuple[str, ...]) -> None:
        self._deepseek_models = frozenset(models)

    def provider_for(self, model_id: str) -> str:
        if model_id in self._deepseek_models:
            return "deepseek"
        # Preserve the current Claude, Gemini, Antigravity, Grok, then Codex ordering verbatim.
```

Add `DeepseekConfig` and `claude_token_keepalive: bool = True` to `AgentConfig`; add `"deepseek"` to `_HOT_RELOADABLE` only. `root_ductor_home` must return `ductor_home.parent.parent` only when `ductor_home.parent.name == "agents"`, otherwise `ductor_home`. All new root-owned path properties derive from that property.

- [ ] **Step 5: Update generated defaults and configuration documentation**

Add this JSON to `config.example.json`, with no key field:

```json
"deepseek": {
  "enabled": false,
  "base_url": "https://api.deepseek.com/anthropic",
  "models": ["deepseek-v4-pro", "deepseek-v4-flash"]
},
"claude_token_keepalive": true
```

In `docs/config.md`, document `DEEPSEEK_API_KEY` in the root `.env`, restart-on-key-change, config hot reload, the logical `deepseek` session bucket, `/usage`, root snapshot path, and main-only keepalive. State that sub-agents share the key but never copy it.

- [ ] **Step 6: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/cli/test_deepseek.py \
  tests/test_config.py \
  tests/test_config_reload.py \
  tests/workspace/test_paths.py \
  -q
/home/zqxu/ductor/.venv/bin/ruff check \
  ductor_bot/cli/deepseek.py ductor_bot/config.py ductor_bot/config_reload.py \
  ductor_bot/workspace/paths.py tests/cli/test_deepseek.py
/home/zqxu/ductor/.venv/bin/mypy \
  ductor_bot/cli/deepseek.py ductor_bot/config.py ductor_bot/workspace/paths.py
git add \
  config.example.json docs/config.md ductor_bot/config.py ductor_bot/config_reload.py \
  ductor_bot/workspace/paths.py ductor_bot/cli/deepseek.py \
  tests/cli/test_deepseek.py tests/test_config.py tests/test_config_reload.py \
  tests/workspace/test_paths.py
git commit -m "feat(deepseek): add logical provider configuration"
```

Expected: tests pass and quality commands exit 0.

---

### Task 2: Delegate DeepSeek Turns to Claude CLI with Invocation-Local Environment Overrides

**Files:**

- Modify: `ductor_bot/cli/base.py`
- Modify: `ductor_bot/cli/executor.py`
- Modify: `ductor_bot/cli/factory.py`
- Modify: `ductor_bot/cli/service.py`
- Test: `tests/cli/test_deepseek.py`
- Test: `tests/cli/test_docker_wrap.py`
- Test: `tests/cli/test_env_injection.py`
- Test: `tests/cli/test_service.py`

**Interfaces:**

- Consumes: `DeepseekRuntime` from Task 1.
- Adds `CLIServiceConfig.deepseek: DeepseekRuntime` and `CLIConfig.deepseek: DeepseekRuntime | None`.
- Produces `deepseek_invocation_env(config: CLIConfig) -> dict[str, str]`.
- Preserves `CLIConfig.provider == "deepseek"` while `create_cli()` returns `ClaudeCodeCLI`.

- [ ] **Step 1: Write failing delegation and two-direction environment-isolation tests**

Add these cases:

```python
def test_factory_delegates_deepseek_to_claude_without_changing_provider(runtime) -> None:
    config = CLIConfig(provider="deepseek", model="deepseek-v4-pro", deepseek=runtime)
    cli = create_cli(config)
    assert isinstance(cli, ClaudeCodeCLI)
    # ClaudeCodeCLI stores its constructor config in the existing private field;
    # do not add a test-only public accessor.
    assert cli._config.provider == "deepseek"


def test_host_deepseek_overrides_have_highest_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runtime
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://native.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "native-token")
    config = CLIConfig(
        provider="deepseek", working_dir=tmp_path / "workspace", deepseek=runtime
    )
    env = build_subprocess_env(config)
    assert env is not None
    assert env["ANTHROPIC_BASE_URL"] == runtime.base_url
    assert env["ANTHROPIC_AUTH_TOKEN"] == runtime.api_key


def test_native_claude_receives_no_deepseek_derived_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runtime
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://native.example")
    config = CLIConfig(provider="claude", working_dir=tmp_path / "workspace", deepseek=runtime)
    env = build_subprocess_env(config)
    assert env is not None
    assert env["ANTHROPIC_BASE_URL"] == "https://native.example"
    assert env.get("ANTHROPIC_AUTH_TOKEN") != runtime.api_key


def test_docker_deepseek_provider_env_wins_over_dotenv(tmp_path: Path, runtime) -> None:
    root = tmp_path
    agent_home = root / "agents" / "worker"
    workspace = agent_home / "workspace"
    workspace.mkdir(parents=True)
    (root / ".env").write_text(
        "ANTHROPIC_BASE_URL=https://root.example\nANTHROPIC_AUTH_TOKEN=root-token\n"
    )
    (agent_home / ".env").write_text(
        "ANTHROPIC_BASE_URL=https://agent.example\nANTHROPIC_AUTH_TOKEN=agent-token\n"
    )
    clear_cache()
    config = CLIConfig(
        provider="deepseek",
        working_dir=workspace,
        docker_container="sandbox",
        agent_name="worker",
        deepseek=runtime,
    )
    command, _ = docker_wrap(["claude"], config)
    injected = [command[index + 1] for index, item in enumerate(command) if item == "-e"]
    env = dict(item.split("=", 1) for item in injected)
    assert env["ANTHROPIC_BASE_URL"] == runtime.base_url
    assert env["ANTHROPIC_AUTH_TOKEN"] == runtime.api_key
    assert injected.count(f"ANTHROPIC_BASE_URL={runtime.base_url}") == 1
    assert injected.count(f"ANTHROPIC_AUTH_TOKEN={runtime.api_key}") == 1
```

Add a companion native-Claude Docker test with the same files and
`CLIConfig(provider="claude", working_dir=workspace, docker_container="sandbox", agent_name="worker", deepseek=runtime)`; assert the resulting mapping retains
`https://agent.example`/`agent-token` and contains neither DeepSeek runtime value.

- [ ] **Step 2: Run focused tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/cli/test_deepseek.py tests/cli/test_docker_wrap.py \
  tests/cli/test_env_injection.py tests/cli/test_service.py -q
```

Expected: failures show missing `deepseek` fields/delegation and absent environment overrides.

- [ ] **Step 3: Carry the runtime contract through CLI service construction**

Add a non-optional `DeepseekRuntime` field to `CLIServiceConfig`, pass it into `_make_cli()`, and add this mapping:

```python
def cli_parameters_for_provider(self, provider: str) -> list[str]:
    if provider == "deepseek":
        return list(self.claude_cli_parameters)
    if provider == "codex":
        return list(self.codex_cli_parameters)
    if provider == "gemini":
        return list(self.gemini_cli_parameters)
    if provider == "antigravity":
        return list(self.antigravity_cli_parameters)
    if provider == "grok":
        return list(self.grok_cli_parameters)
    return list(self.claude_cli_parameters)
```

`CLIService._make_cli()` must resolve the logical provider as today, set `CLIConfig.provider` to that logical provider, attach the runtime, and retain all current model, effort, transport, agent-name, Docker, transcription, and process-registry fields.

- [ ] **Step 4: Apply provider overrides only at process construction**

In `base.py`, define:

```python
def deepseek_invocation_env(config: CLIConfig) -> dict[str, str]:
    if config.provider != "deepseek" or config.deepseek is None:
        return {}
    return config.deepseek.invocation_env()
```

In `docker_wrap()`, merge environment in this fixed order:

```python
merged_extra = dict(load_env_secrets(main_home / ".env"))
if ductor_home != main_home:
    merged_extra.update(load_env_secrets(ductor_home / ".env"))
if extra_env:
    merged_extra.update(extra_env)
merged_extra.update(deepseek_invocation_env(config))
```

In `build_subprocess_env()`, preserve current host inheritance and `.env` semantics, then run `env.update(deepseek_invocation_env(config))` last. In `factory.py`, explicitly route both `claude` and `deepseek` to `ClaudeCodeCLI`; do not mutate the provider string.

- [ ] **Step 5: Verify no secret-bearing log path was added**

```bash
rg -n "api_key|ANTHROPIC_AUTH_TOKEN|deepseek.*env|format_cli_cmd|logger\." \
  ductor_bot/cli/deepseek.py ductor_bot/cli/base.py ductor_bot/cli/executor.py \
  ductor_bot/cli/factory.py ductor_bot/cli/service.py
```

Expected: the key is read and injected but never interpolated into a log call or dataclass repr. Existing redacted command formatting remains unchanged.

- [ ] **Step 6: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/cli/test_deepseek.py tests/cli/test_docker_wrap.py \
  tests/cli/test_env_injection.py tests/cli/test_service.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/cli tests/cli/test_deepseek.py
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/cli
git add ductor_bot/cli tests/cli/test_deepseek.py tests/cli/test_docker_wrap.py \
  tests/cli/test_env_injection.py tests/cli/test_service.py
git commit -m "feat(deepseek): delegate isolated turns to Claude CLI"
```

---

### Task 3: Integrate DeepSeek Availability, Model Selection, Task Resolution, and Hot Reload

**Files:**

- Modify: `ductor_bot/orchestrator/providers.py`
- Modify: `ductor_bot/orchestrator/selectors/model_selector.py`
- Modify: `ductor_bot/cli/param_resolver.py`
- Modify: `ductor_bot/orchestrator/core.py`
- Modify: `ductor_bot/orchestrator/lifecycle.py`
- Modify: `ductor_bot/i18n/{de,en,es,fr,id,nl,pt,ru}/chat.toml`
- Test: `tests/orchestrator/test_providers.py`
- Test: `tests/orchestrator/test_model_selector.py`
- Test: `tests/orchestrator/test_core_provider_info.py`
- Test: `tests/orchestrator/test_core.py`
- Test: `tests/cli/test_param_resolver.py`
- Test: `tests/cli/test_grok_provider.py`
- Test: `tests/cli/test_grok_discovery.py`

**Interfaces:**

- `ProviderManager(config, *, deepseek_runtime, claude_cli_runnable, codex_cache_fn=None)` owns the runtime and the separately probed Claude executable state.
- `ProviderManager.refresh_deepseek(runtime, cli_service)` reconfigures models and recomputes availability after hot reload.
- DeepSeek availability accepts Claude auth statuses `AUTHENTICATED` or `INSTALLED`, but rejects `NOT_FOUND`.
- `/model` and direct task overrides use `orch.available_providers` plus configured DeepSeek models.

- [ ] **Step 1: Write failing availability and selection tests**

Cover these exact cases:

```python
def test_deepseek_available_with_key_and_installed_claude_but_no_oauth(
    deepseek_runtime: DeepseekRuntime,
) -> None:
    manager = ProviderManager(
        AgentConfig(), deepseek_runtime=deepseek_runtime, claude_cli_runnable=True
    )
    cli_service = MagicMock()
    manager.apply_auth_results(
        {
            "claude": AuthResult("claude", AuthStatus.INSTALLED),
            "codex": AuthResult("codex", AuthStatus.NOT_FOUND),
        },
        auth_status_enum=AuthStatus,
        cli_service=cli_service,
    )
    assert "deepseek" in manager.available_providers
    assert "claude" not in manager.available_providers


@pytest.mark.parametrize("missing", ["disabled", "key", "models", "claude_cli"])
def test_deepseek_unavailable_when_requirement_missing(missing: str) -> None:
    cfg = DeepseekConfig(
        enabled=missing != "disabled",
        models=[] if missing == "models" else ["deepseek-v4-pro"],
    )
    runtime = resolve_deepseek_runtime(
        cfg,
        "" if missing == "key" else "secret",
        reserved_models=frozenset({"opus", "gemini-2.5-pro", "grok-4.5"}),
    )
    manager = ProviderManager(
        AgentConfig(),
        deepseek_runtime=runtime,
        claude_cli_runnable=missing != "claude_cli",
    )
    manager.apply_auth_results(
        {
            "claude": AuthResult(
                "claude",
                AuthStatus.INSTALLED,
            )
        },
        auth_status_enum=AuthStatus,
        cli_service=MagicMock(),
    )
    assert "deepseek" not in manager.available_providers


async def test_selector_lists_deepseek_as_separate_provider(orch, session_key) -> None:
    resp = await model_selector_start(orch, session_key)
    assert resp.buttons is not None
    assert any(button.text == "DEEPSEEK" for row in resp.buttons.rows for button in row)


async def test_direct_model_selection_rejects_unavailable_deepseek(orch, session_key) -> None:
    orch._providers._available_providers = frozenset({"claude"})
    result = await switch_model(orch, session_key, "deepseek-v4-pro")
    assert "not available" in result.lower()
```

Also test API metadata uses `id="deepseek"`, `name="DeepSeek"`, configured models only, and no key/base URL; hot reload disabled→enabled and enabled→disabled updates provider models/availability without rereading `.env`; cron/webhook `TaskOverrides(provider="deepseek")` validates against `base_config.deepseek.models`, uses Claude efforts, and uses `cli_parameters.claude`.
Update the existing selector auth fixtures so they set
`orch._providers._available_providers` directly; `model_selector_start()` no
longer performs a live `check_all_auth()` call. Preserve all existing one-,
many-, and zero-provider expectations through the cached availability set.

- [ ] **Step 2: Run focused tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/orchestrator/test_providers.py \
  tests/orchestrator/test_model_selector.py \
  tests/orchestrator/test_core_provider_info.py \
  tests/orchestrator/test_core.py \
  tests/cli/test_param_resolver.py -q
```

Expected: DeepSeek is absent from availability, selector, metadata, hot reload, and task resolution.

- [ ] **Step 3: Make provider availability independent from Claude OAuth**

`apply_auth_results()` must retain existing authenticated-provider behavior and
add `deepseek` when
`self._deepseek_runtime.configured and self._claude_cli_runnable`. The runnable
boolean comes from the independent Task 1 probe, not Claude OAuth status or a
`.claude` directory. `refresh_deepseek()` must call
`models.configure_deepseek(runtime.models if runtime.requested and not runtime.error else ())`,
refresh known IDs, recompute the same availability rule, and call
`cli_service.update_available_providers()`.

Add DeepSeek to active display name, provider directives, defaults, metadata, and model lists. `default_model_for_provider("deepseek")` returns the first configured model or `""`. Add localized `model.select_deepseek` to all eight `chat.toml` files in this task and pass `orch.models.deepseek_models` into `_build_model_step()` so the DeepSeek selector never uses Claude's static list. Update existing Grok discovery/provider tests from class-style `ModelRegistry.provider_for(...)` calls to `ModelRegistry().provider_for(...)` as part of the instance-method migration, with no behavioral change. After Codex cache initialization, call `ProviderManager.refresh_known_model_ids()`; if any configured DeepSeek ID matches a cached Codex model, set the effective runtime error to `model_collision`, clear DeepSeek models, and remove availability. Repeat this guard from every dynamic model-refresh callback. Add a cached-Codex collision test.

Add these exact locale values; `{provider}` must be preserved:

| Locale | `model.select_deepseek` | `model.provider_unavailable` |
|---|---|---|
| `en` | `Select DeepSeek model:` | `Provider {provider} is not available.` |
| `de` | `DeepSeek-Modell auswählen:` | `Anbieter {provider} ist nicht verfügbar.` |
| `es` | `Selecciona un modelo de DeepSeek:` | `El proveedor {provider} no está disponible.` |
| `fr` | `Sélectionnez un modèle DeepSeek :` | `Le fournisseur {provider} n’est pas disponible.` |
| `id` | `Pilih model DeepSeek:` | `Penyedia {provider} tidak tersedia.` |
| `nl` | `Selecteer een DeepSeek-model:` | `Provider {provider} is niet beschikbaar.` |
| `pt` | `Selecione um modelo DeepSeek:` | `O fornecedor {provider} não está disponível.` |
| `ru` | `Выберите модель DeepSeek:` | `Провайдер {provider} недоступен.` |

- [ ] **Step 4: Update selector and direct-selection validation**

Remove the selector's fresh `check_all_auth()` decision point and its now-unused
auth imports. Use:

```python
available = sorted(orch.available_providers)
```

Pass `tuple(sorted(orch.models.deepseek_models))` into model-step construction and render `DEEPSEEK` separately. Treat DeepSeek effort support as `CLAUDE_SUPPORTED_EFFORTS` in `_supported_efforts()`, `_validate_reasoning_effort()`, `_status_line()`, and sub-agent reasoning-effort persistence. Preserve current unknown-model/Codex behavior. For a configured model whose logical provider is `deepseek`, direct selection must fail before persistence with a new localized `model.provider_unavailable` message when DeepSeek is absent from `orch.available_providers`. Add that key with placeholder parity to all eight locales.

- [ ] **Step 5: Add DeepSeek to task resolution and safe hot reload**

Add `deepseek` to `_TASK_PROVIDERS`. Validate that its model is in the normalized configured set; reuse Claude effort validation and `cli_parameters.claude` explicitly. Do not add a `deepseek` field to `CLIParametersConfig`.

Extract one `_build_cli_service_config(config, docker_container)` helper in `core.py` so initialization and hot reload pass every existing field, including Grok parameters, `agent_name`, `interagent_port`, and transcription commands. Capture `_deepseek_api_key` once in `Orchestrator.__init__`; hot reload resolves new non-secret config against that captured value. Do not invoke `load_deepseek_api_key()` from `_on_config_hot_reload()`. In `create_orchestrator()`, probe `claude_cli_runnable(docker_container)` after Docker setup and pass that boolean into `ProviderManager`; availability must not depend on `AuthResult.is_authenticated`.

- [ ] **Step 6: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py \
  tests/orchestrator/test_core_provider_info.py tests/orchestrator/test_core.py \
  tests/cli/test_param_resolver.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/orchestrator ductor_bot/cli/param_resolver.py
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/orchestrator ductor_bot/cli/param_resolver.py
git add ductor_bot/orchestrator ductor_bot/cli/param_resolver.py \
  ductor_bot/i18n/{de,en,es,fr,id,nl,pt,ru}/chat.toml \
  tests/orchestrator/test_providers.py tests/orchestrator/test_model_selector.py \
  tests/orchestrator/test_core_provider_info.py tests/orchestrator/test_core.py \
  tests/cli/test_param_resolver.py tests/cli/test_grok_provider.py \
  tests/cli/test_grok_discovery.py
git commit -m "feat(deepseek): integrate availability and model selection"
```

---

### Task 4: Prove DeepSeek Session-Bucket Isolation Across Every Session-Sensitive Flow

**Files:**

- Modify: `tests/session/test_provider_isolation.py`
- Modify: `tests/orchestrator/test_flows.py`
- Modify: `tests/orchestrator/test_error_no_reset.py`
- Modify: `tests/orchestrator/test_memory_flush.py`
- Modify: `tests/orchestrator/test_core.py`

**Interfaces:**

- Consumes the logical `deepseek` result from `ModelRegistry.provider_for()`.
- Persists `provider_sessions["deepseek"]` independently of `provider_sessions["claude"]`.
- Makes no session-schema migration; the first DeepSeek turn has no resume ID.

- [ ] **Step 1: Write failing manager-level isolation and switch-back tests**

Add this complete manager case to `tests/session/test_provider_isolation.py`:

```python
async def test_deepseek_and_claude_switch_back_and_reset_are_isolated(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    key = SessionKey(chat_id=1)
    claude, _ = await manager.resolve_session(key, provider="claude", model="opus")
    await _simulate_cli_response(manager, claude, "claude-sid", cost_usd=0.2, tokens=100)

    deepseek, deepseek_new = await manager.resolve_session(
        key, provider="deepseek", model="deepseek-v4-pro"
    )
    assert deepseek_new is True
    assert deepseek.session_id == ""
    await _simulate_cli_response(
        manager, deepseek, "deepseek-sid", cost_usd=0.1, tokens=50
    )

    second_model, second_new = await manager.resolve_session(
        key, provider="deepseek", model="deepseek-v4-flash"
    )
    assert second_new is False
    assert second_model.session_id == "deepseek-sid"

    resumed_claude, claude_new = await manager.resolve_session(
        key, provider="claude", model="opus"
    )
    assert claude_new is False
    assert resumed_claude.session_id == "claude-sid"

    reset = await manager.reset_provider_session(
        key, provider="deepseek", model="deepseek-v4-pro"
    )
    assert reset.session_id == ""
    assert "deepseek" not in reset.provider_sessions
    assert reset.provider_sessions["claude"].session_id == "claude-sid"
```

- [ ] **Step 2: Write failing normal, streaming, topic, timeout, and error tests**

Add a helper in `tests/orchestrator/test_flows.py` that seeds distinct buckets:

```python
async def _seed_claude_and_deepseek(orch: Orchestrator, key: SessionKey) -> None:
    orch.models.configure_deepseek(("deepseek-v4-pro", "deepseek-v4-flash"))
    claude, _ = await orch._sessions.resolve_session(key, provider="claude", model="opus")
    claude.session_id = "claude-sid"
    await orch._sessions.update_session(claude)
    deepseek, _ = await orch._sessions.resolve_session(
        key, provider="deepseek", model="deepseek-v4-pro"
    )
    deepseek.session_id = "deepseek-sid"
    await orch._sessions.update_session(deepseek)
```

Then add exact assertions for both execution modes and topic isolation:

```python
@pytest.mark.parametrize(("streaming", "method"), [(False, "execute"), (True, "execute_streaming")])
async def test_deepseek_turn_resumes_only_deepseek_bucket(
    orch: Orchestrator, streaming: bool, method: str
) -> None:
    key = SessionKey(chat_id=1)
    await _seed_claude_and_deepseek(orch, key)
    execute = AsyncMock(return_value=_mock_response(session_id="deepseek-next"))
    object.__setattr__(orch._cli_service, method, execute)
    if streaming:
        await normal_streaming(orch, key, "hello", model_override="deepseek-v4-pro")
    else:
        await normal(orch, key, "hello", model_override="deepseek-v4-pro")
    request = execute.await_args.args[0]
    assert request.provider_override == "deepseek"
    assert request.resume_session == "deepseek-sid"
    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.provider_sessions["claude"].session_id == "claude-sid"
    assert session.provider_sessions["deepseek"].session_id == "deepseek-next"


async def test_switch_back_to_claude_resumes_only_claude_bucket(
    orch: Orchestrator,
) -> None:
    key = SessionKey(chat_id=1)
    await _seed_claude_and_deepseek(orch, key)
    execute = AsyncMock(return_value=_mock_response(session_id="claude-next"))
    object.__setattr__(orch._cli_service, "execute", execute)
    await normal(orch, key, "back", model_override="opus")
    request = execute.await_args.args[0]
    assert request.provider_override == "claude"
    assert request.resume_session == "claude-sid"
    session = await orch._sessions.get_active(key)
    assert session is not None
    assert session.provider_sessions["deepseek"].session_id == "deepseek-sid"
    assert session.provider_sessions["claude"].session_id == "claude-next"


async def test_topic_deepseek_bucket_does_not_touch_main_chat(orch: Orchestrator) -> None:
    main_key = SessionKey(chat_id=1)
    topic_key = SessionKey(chat_id=1, topic_id=42)
    await _seed_claude_and_deepseek(orch, main_key)
    orch.models.configure_deepseek(("deepseek-v4-pro",))
    execute = AsyncMock(return_value=_mock_response(session_id="topic-deepseek"))
    object.__setattr__(orch._cli_service, "execute", execute)
    await normal(orch, topic_key, "topic", model_override="deepseek-v4-pro")
    main = await orch._sessions.get_active(main_key)
    topic = await orch._sessions.get_active(topic_key)
    assert main is not None and topic is not None
    assert main.provider_sessions["deepseek"].session_id == "deepseek-sid"
    assert topic.provider_sessions["deepseek"].session_id == "topic-deepseek"
```

Extend the existing error/timeout tests by using `_seed_claude_and_deepseek()`, a DeepSeek model override, and typed error responses. Assert `deepseek-sid` is preserved for ordinary error/timeout, the Claude bucket remains `claude-sid`, and the request never resumes `claude-sid`.

- [ ] **Step 3: Write failing invalid-resume, process-recovery, reset, and memory tests**

In `tests/orchestrator/test_error_no_reset.py`, clone the existing stale/SIGKILL recovery cases with `model_override="deepseek-v4-pro"`; assert `reset_provider_session` is called with `provider="deepseek"`, the final Claude bucket is unchanged, and only the DeepSeek ID is cleared.

In `tests/orchestrator/test_memory_flush.py`, add:

```python
async def test_memory_flusher_resumes_active_deepseek_bucket(tmp_path: Path) -> None:
    flusher, cli = _make_flusher(
        tmp_path, compact_cfg=MemoryCompactionConfig(enabled=False)
    )
    key = SessionKey(chat_id=101)
    session = SessionData(chat_id=101, provider="deepseek", model="deepseek-v4-pro")
    session.provider_sessions["claude"] = ProviderSessionData(
        session_id="claude-sid", message_count=2
    )
    session.provider_sessions["deepseek"] = ProviderSessionData(
        session_id="deepseek-sid", message_count=3
    )
    flusher.mark_boundary(key)
    await flusher.maybe_flush(key, session)
    request = cli.execute.await_args.args[0]
    assert request.resume_session == "deepseek-sid"
    assert request.provider_override == "deepseek"
```

Extend `tests/orchestrator/test_core.py` reset tests so `/new` clears the configured default provider and `/reset` clears the currently active DeepSeek bucket, while both preserve the Claude bucket.

- [ ] **Step 4: Run the isolation group and observe RED where plumbing still assumes Claude**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/session/test_provider_isolation.py \
  tests/orchestrator/test_flows.py \
  tests/orchestrator/test_error_no_reset.py \
  tests/orchestrator/test_memory_flush.py \
  tests/orchestrator/test_core.py -q
```

Expected: new tests verify that every flow uses the logical provider. These are regression tests for existing generic session plumbing; production files are deliberately unchanged in this task. If a failure exposes a production defect, stop this task, use `systematic-debugging`, amend this plan with the exact corrective file/interface, then resume TDD rather than improvising a hidden architecture change.

- [ ] **Step 5: Verify the complete session regression group and commit tests**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/session tests/orchestrator/test_flows.py \
  tests/orchestrator/test_error_no_reset.py tests/orchestrator/test_memory_flush.py \
  tests/orchestrator/test_core.py -q
/home/zqxu/ductor/.venv/bin/ruff check tests/session tests/orchestrator/test_flows.py \
  tests/orchestrator/test_error_no_reset.py tests/orchestrator/test_memory_flush.py \
  tests/orchestrator/test_core.py
git add tests/session/test_provider_isolation.py tests/orchestrator/test_flows.py \
  tests/orchestrator/test_error_no_reset.py tests/orchestrator/test_memory_flush.py \
  tests/orchestrator/test_core.py
git commit -m "test(deepseek): enforce provider session isolation"
```

Expected: all session tests pass and the commit is test-only.

---

### Task 5: Build Typed, Independent Usage Clients

**Files:**

- Create: `ductor_bot/usage/__init__.py`
- Create: `ductor_bot/usage/models.py`
- Create: `ductor_bot/usage/clients.py`
- Create: `tests/usage/__init__.py`
- Create: `tests/usage/test_clients.py`

**Interfaces:**

- Produces `UsageFailure`: `disabled`, `not_configured`, `not_logged_in`, `expired`, `rate_limited`, `timeout`, `malformed_response`, `unavailable`.
- Produces `Balance(currency: str, total: Decimal)`, `DeepseekUsage`, `UsageWindow`, and `PlanUsage` frozen dataclasses; Task 7 adds `UsageReport` after delta types exist.
- Produces async clients `fetch_deepseek_balance(runtime)`, `fetch_claude_plan_usage(home=None)`, and `fetch_codex_plan_usage(home=None)`.
- All result objects contain normalized values or a bounded enum; they never contain credentials, headers, response bodies, or exception text.

- [ ] **Step 1: Write failing pure-parser and credential-reader tests**

Use representative provider payloads and assert:

```python
def test_parse_deepseek_multiple_currency_balances() -> None:
    result = parse_deepseek_balance(
        {"is_available": True, "balance_infos": [
            {"currency": "CNY", "total_balance": "123.450"},
            {"currency": "USD", "total_balance": "7.25"},
        ]}
    )
    assert result.balances == (
        Balance(currency="CNY", total=Decimal("123.450")),
        Balance(currency="USD", total=Decimal("7.25")),
    )


def test_codex_windows_are_classified_by_duration_not_position() -> None:
    result = parse_codex_usage({
        "plan_type": "plus",
        "rate_limit": {
            "primary_window": {"limit_window_seconds": 604800, "used_percent": 40},
        },
    })
    assert result.short_window is None
    assert result.weekly_window is not None
    assert result.weekly_window.used_percent == Decimal("40")
```

Also cover Claude millisecond expiry; Codex `CODEX_HOME`; absent/malformed credential structures; bool/non-finite/negative percentages and balances; ISO and epoch reset parsing; and preservation of plan/account metadata without tokens.

- [ ] **Step 2: Write failing async HTTP mapping tests**

For every client, patch `aiohttp.ClientSession` and assert 10-second total timeout, correct endpoint, required headers, 401/403 mapping, 429 mapping, other non-2xx mapping, timeout mapping, malformed JSON mapping, and successful normalization. DeepSeek URL must be exactly:

```python
def deepseek_balance_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/user/balance", "", ""))
```

Claude endpoint: `https://claude.ai/api/oauth/usage`. Codex endpoint: `https://chatgpt.com/backend-api/wham/usage`. Include `chatgpt-account-id` only when present.

- [ ] **Step 3: Run client tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/usage/test_clients.py -q
```

Expected: import/collection fails because the usage package does not exist.

- [ ] **Step 4: Implement the typed result boundary**

Use this public shape:

```python
class UsageFailure(StrEnum):
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    NOT_LOGGED_IN = "not_logged_in"
    EXPIRED = "expired"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    MALFORMED_RESPONSE = "malformed_response"
    UNAVAILABLE = "unavailable"


UsageProvider = Literal["deepseek", "claude", "codex"]


@dataclass(frozen=True, slots=True)
class Balance:
    currency: str
    total: Decimal


@dataclass(frozen=True, slots=True)
class UsageWindow:
    used_percent: Decimal
    resets_at: datetime | None
    duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class DeepseekUsage:
    ok: bool
    balances: tuple[Balance, ...] = ()
    failure: UsageFailure | None = None


@dataclass(frozen=True, slots=True)
class PlanUsage:
    provider: Literal["claude", "codex"]
    ok: bool
    plan: str = ""
    short_window: UsageWindow | None = None
    weekly_window: UsageWindow | None = None
    failure: UsageFailure | None = None


ProviderUsage = DeepseekUsage | PlanUsage


def failure_result(provider: UsageProvider, failure: UsageFailure) -> ProviderUsage:
    if provider == "deepseek":
        return DeepseekUsage(ok=False, failure=failure)
    return PlanUsage(provider=provider, ok=False, failure=failure)
```

Task 7 defines `UsageReport` after Task 6 adds `BalanceDelta`. Reject empty
currencies; normalize currency to uppercase; reject non-finite Decimal values
and negative percentage values; clamp percentages over 100 to
`Decimal("100")`. Catch only expected parsing/network exceptions inside
clients, propagate cancellation, and log only provider plus bounded category.

- [ ] **Step 5: Implement each HTTP client with an independent session/timeout**

Each function must return early for disabled/unconfigured/missing credentials, use `aiohttp.ClientTimeout(total=10)`, parse a 200 response only, and return a typed failure for every other expected state. Do not call `resp.text()` on failures. Claude's local expired record returns `EXPIRED` without HTTP; `/usage` never calls the keepalive module.

- [ ] **Step 6: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/usage/test_clients.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/usage tests/usage
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/usage
git add ductor_bot/usage tests/usage
git commit -m "feat(usage): add typed provider usage clients"
```

---

### Task 6: Own DeepSeek Snapshot Persistence, Legacy Import, and Local-Day Deltas

**Files:**

- Create: `ductor_bot/usage/snapshots.py`
- Create: `tests/usage/test_snapshots.py`
- Modify: `ductor_bot/usage/models.py`
- Modify: `ductor_bot/usage/__init__.py`

**Interfaces:**

- Consumes `Balance` from Task 5 and root-owned paths from Task 1.
- Produces `BalanceDelta(currency, current, change, kind)` where kind is `spend`, `recharge`, or `unavailable`.
- Produces `BalanceSnapshot(captured_at, balances)` and `BalanceSnapshotRepository(path, legacy_path)` with async `initialize()`, `record()`, `load()`, and `today_deltas()` methods.
- Uses a module-level lock registry keyed by canonical snapshot path so all instances serialize imports and writes.

- [ ] **Step 1: Write failing schema, round-trip, rejection, and atomic-write tests**

Create fixtures with fixed UTC datetimes and assert the exact persisted schema:

```python
async def test_record_round_trips_decimal_strings(tmp_path: Path) -> None:
    repo = BalanceSnapshotRepository(
        tmp_path / "deepseek_balance_snapshots.json",
        tmp_path / "legacy.json",
    )
    await repo.record(
        (Balance("CNY", Decimal("123.450")), Balance("USD", Decimal("8.20"))),
        captured_at=datetime(2026, 8, 13, 1, tzinfo=UTC),
    )
    raw = json.loads((tmp_path / "deepseek_balance_snapshots.json").read_text())
    assert raw == {
        "version": 1,
        "legacy_import_completed": True,
        "snapshots": [{
            "captured_at": "2026-08-13T01:00:00Z",
            "balances": [
                {"currency": "CNY", "total": "123.450"},
                {"currency": "USD", "total": "8.20"},
            ],
        }],
    }
```

Also assert malformed version/document/snapshot/balance/ISO timestamp is rejected as unavailable state and leaves the malformed target byte-for-byte unchanged; NaN, Infinity, empty currency, and values with exponent below `-18` are rejected; the original target survives a patched atomic-write failure; no `.tmp` residue remains after success. This implementation preserves malformed evidence in place rather than inventing a quarantine convention that the repository does not already have.

- [ ] **Step 2: Write failing deduplication, retention, lock, and delta tests**

Cover these cases with a controlled clock:

```python
async def test_identical_sample_inside_30_minutes_is_deduplicated(repo) -> None:
    first = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    balances = (Balance("CNY", Decimal("100")),)
    assert await repo.record(balances, captured_at=first) is True
    assert await repo.record(balances, captured_at=first + timedelta(minutes=29)) is False


async def test_changed_sample_inside_30_minutes_is_retained(repo) -> None:
    first = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    assert await repo.record((Balance("CNY", Decimal("100")),), captured_at=first)
    assert await repo.record(
        (Balance("CNY", Decimal("99")),),
        captured_at=first + timedelta(minutes=5),
    )


async def test_today_delta_uses_local_midnight_and_same_currency(repo) -> None:
    tz = ZoneInfo("Asia/Shanghai")
    current_at = datetime(2026, 8, 13, 4, 0, tzinfo=UTC)
    await repo.record(
        (Balance("CNY", Decimal("105")), Balance("USD", Decimal("12"))),
        captured_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
    )
    await repo.record(
        (Balance("CNY", Decimal("100")),),
        captured_at=datetime(2026, 8, 12, 16, 5, tzinfo=UTC),
    )
    await repo.record(
        (Balance("CNY", Decimal("95")),),
        captured_at=datetime(2026, 8, 12, 18, 0, tzinfo=UTC),
    )
    deltas = await repo.today_deltas(
        (
            Balance("CNY", Decimal("90")),
            Balance("USD", Decimal("10")),
            Balance("EUR", Decimal("7")),
        ),
        timezone=tz,
        now=current_at,
    )
    assert deltas[0].change == Decimal("10")
    assert deltas[0].kind == "spend"
    assert deltas[1].change == Decimal("2")
    assert deltas[1].kind == "spend"
    assert deltas[2].kind == "unavailable"
```

The CNY baseline is the earliest sample after local midnight, `100`; USD uses
the approved pre-midnight fallback; EUR proves the missing-history state.

Add recharge (`baseline - current < 0`), fallback to latest pre-midnight when there is no post-midnight sample, 35-day pruning, future-record exclusion, and two repository instances concurrently recording without lost updates.

- [ ] **Step 3: Write failing one-time legacy-import tests**

Use legacy records shaped like `{"timestamp": "...", "balance": 123.45}` and assert they import as CNY, normalize/deduplicate, never mutate the legacy file, and set `legacy_import_completed=true`. Repeat for missing, empty, malformed, and partially invalid legacy files; the second `initialize()` must not read the legacy path again.

- [ ] **Step 4: Run snapshot tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/usage/test_snapshots.py -q
```

Expected: import fails because the repository does not exist.

- [ ] **Step 5: Implement versioned parsing and path-shared serialization**

Use the exact public contracts:

```python
@dataclass(frozen=True, slots=True)
class BalanceDelta:
    currency: str
    current: Decimal
    change: Decimal | None
    kind: Literal["spend", "recharge", "unavailable"]


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    captured_at: datetime
    balances: tuple[Balance, ...]


_LOCKS: dict[Path, asyncio.Lock] = {}


def _lock_for(path: Path) -> asyncio.Lock:
    canonical = path.expanduser().resolve()
    return _LOCKS.setdefault(canonical, asyncio.Lock())


class BalanceSnapshotRepository:
    def __init__(self, path: Path, legacy_path: Path) -> None:
        self._path = path
        self._legacy_path = legacy_path
        self._lock = _lock_for(path)

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize_locked)

    async def record(
        self,
        balances: tuple[Balance, ...],
        *,
        captured_at: datetime | None = None,
    ) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self._record_locked, balances, captured_at or datetime.now(UTC)
            )

    async def load(self) -> tuple[BalanceSnapshot, ...]:
        async with self._lock:
            return await asyncio.to_thread(self._load_locked)

    async def today_deltas(
        self,
        current: tuple[Balance, ...],
        *,
        timezone: ZoneInfo,
        now: datetime | None = None,
    ) -> tuple[BalanceDelta, ...]:
        async with self._lock:
            return await asyncio.to_thread(
                self._today_deltas_locked,
                current,
                timezone,
                now or datetime.now(UTC),
            )
```

All public operations acquire the same lock. Parse the complete document before trusting any snapshot. A current-format parse failure raises one repository-specific bounded exception (for example `SnapshotUnavailable`) to the usage boundary and never writes the target. Save with `atomic_text_save(path, json.dumps(document, indent=2) + "\n")`. Convert a UTC `+00:00` suffix to `Z` only at serialization. Keep at most records where `captured_at >= now - timedelta(days=35)` and never fabricate or partially accept an invalid current-format file.

- [ ] **Step 6: Implement local-midnight baseline selection**

For each current currency independently:

```python
local_midnight = now.astimezone(timezone).replace(
    hour=0, minute=0, second=0, microsecond=0
)
midnight_utc = local_midnight.astimezone(UTC)
after = sorted(item for item in same_currency if midnight_utc <= item.captured_at <= now)
before = sorted(item for item in same_currency if item.captured_at < midnight_utc)
baseline = after[0] if after else (before[-1] if before else None)
```

Return `unavailable` without a change when no same-currency baseline exists; positive difference is `spend`, negative is `recharge`, and zero is `spend` with `Decimal("0")`.

- [ ] **Step 7: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/usage/test_snapshots.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/usage/snapshots.py tests/usage/test_snapshots.py
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/usage
git add ductor_bot/usage tests/usage/test_snapshots.py
git commit -m "feat(usage): own DeepSeek balance history"
```

---

### Task 7: Collect and Format All Usage Providers Behind One Service

**Files:**

- Create: `ductor_bot/usage/service.py`
- Create: `ductor_bot/usage/formatting.py`
- Create: `tests/usage/test_service.py`
- Modify: `ductor_bot/usage/models.py`
- Modify: `ductor_bot/usage/__init__.py`

**Interfaces:**

- Produces `UsageService(runtime, repository, *, user_timezone, is_main, deepseek_fetch, claude_fetch, codex_fetch)`; the three fetch callables default to the Task 5 clients and remain injectable in tests.
- Produces `UsageService.collect() -> UsageReport` and `UsageService.update_deepseek(runtime, user_timezone) -> None`.
- Produces `format_usage(report: UsageReport, *, timezone: ZoneInfo) -> str` using i18n keys only.
- A successful query computes deltas from already stored history; afterward the main agent records the current sample and a sub-agent never calls `record()`.
- Defines `UsageReport(deepseek: DeepseekUsage, claude: PlanUsage, codex: PlanUsage, deltas: tuple[BalanceDelta, ...] = ())` as a frozen slots dataclass in `models.py`.

- [ ] **Step 1: Write failing concurrency and failure-boundary tests**

Inject async client callables and prove all three start before any finishes:

```python
async def test_collect_starts_all_clients_concurrently(service_factory) -> None:
    started = {name: asyncio.Event() for name in ("deepseek", "claude", "codex")}
    release = asyncio.Event()

    async def client(name: str, result: object) -> object:
        started[name].set()
        await release.wait()
        return result

    task = asyncio.create_task(service_factory(client).collect())
    await asyncio.gather(*(event.wait() for event in started.values()))
    release.set()
    report = await task
    assert report.deepseek.ok and report.claude.ok and report.codex.ok
```

Also have each client independently raise `TimeoutError`, `RuntimeError`, and `CancelledError`: ordinary exceptions become that provider's `UNAVAILABLE` without hiding successes; cancellation propagates. Assert the main repository records once, sub-agent records zero times, and snapshot write failure does not hide the current balance.

- [ ] **Step 2: Write failing formatting tests for complete, partial, and failed reports**

Assert the rendered text always has exactly three ordered sections: DeepSeek, Claude Code, Codex. Cover multiple currencies, spend, recharge, no baseline, absent window, plan name, percentage normalization, reset conversion to `Asia/Shanghai`, and every `UsageFailure`. Assert no provider token/base URL/exception text appears.

Use keys under `[usage]`:

```toml
header = "**Usage**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Balance: {amount} {currency}"
spent_today = "Spent today: {amount} {currency}"
recharged_today = "Recharged today: {amount} {currency}"
daily_unavailable = "Today's change: unavailable"
plan = "Plan: {plan}"
short_window = "Short window: {percent}%"
five_hour = "5-hour usage: {percent}%"
weekly = "7-day usage: {percent}%"
resets = "resets {time}"
window_unavailable = "Unavailable"
error_disabled = "Disabled"
error_not_configured = "Not configured"
error_not_logged_in = "Not logged in"
error_expired = "Login expired"
error_rate_limited = "Rate limited"
error_timeout = "Timed out"
error_malformed_response = "Malformed provider response"
error_unavailable = "Unavailable"
```

The English strings define interpolation contracts; Task 8 adds all catalogs before command exposure.

- [ ] **Step 3: Run service tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/usage/test_service.py -q
```

Expected: service and formatter imports fail.

- [ ] **Step 4: Implement concurrent collection with typed exception conversion**

Use three separately wrapped coroutines in one gather:

```python
async def _bounded(
    provider: Literal["deepseek", "claude", "codex"],
    call: Callable[[], Awaitable[ProviderUsage]],
) -> ProviderUsage:
    try:
        return await asyncio.wait_for(call(), timeout=10)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        return failure_result(provider, UsageFailure.TIMEOUT)
    except Exception:
        logger.warning("Usage query failed provider=%s category=unavailable", provider)
        return failure_result(provider, UsageFailure.UNAVAILABLE)
```

`collect()` awaits `asyncio.gather()` over all three wrappers. If DeepSeek
succeeds, both roles call `today_deltas()` against existing history first, then
main calls `record()` while sub-agents remain read-only. This ordering prevents
the first query of a day from using itself as a fabricated zero-spend baseline.
Repository errors yield empty deltas without replacing the successful provider
result. The constructor stores `DeepseekRuntime`, `BalanceSnapshotRepository`,
`ZoneInfo`, and `is_main`; its injected callables have exact return types
`Callable[..., Awaitable[DeepseekUsage | PlanUsage]]`. `update_deepseek()`
atomically replaces only the runtime and presentation timezone used by later
collections; it never reloads the startup-captured key.

- [ ] **Step 5: Implement provider-neutral localized formatting**

Use `t("usage.<key>")` for every prose label and error. Format Decimal with fixed-point output and no binary-float conversion. Convert aware reset timestamps with `.astimezone(timezone)` and format `%Y-%m-%d %H:%M %Z`. Claude labels its short window as 5-hour; Codex labels it as short window. Missing individual windows render `window_unavailable` instead of moving the weekly window.

- [ ] **Step 6: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/usage/test_service.py tests/usage/test_clients.py \
  tests/usage/test_snapshots.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/usage tests/usage
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/usage
git add ductor_bot/usage tests/usage
git commit -m "feat(usage): aggregate and format provider usage"
```

---

### Task 8: Add the Balance Observer, `/usage` Command, All Transports, and All Locales

**Files:**

- Create: `ductor_bot/usage/observer.py`
- Create: `tests/usage/test_observer.py`
- Modify: `ductor_bot/orchestrator/core.py`
- Modify: `ductor_bot/orchestrator/commands.py`
- Modify: `ductor_bot/orchestrator/observers.py`
- Modify: `ductor_bot/orchestrator/lifecycle.py`
- Modify: `ductor_bot/commands.py`
- Modify: `ductor_bot/messenger/commands.py`
- Modify: `ductor_bot/i18n/{de,en,es,fr,id,nl,pt,ru}/commands.toml`
- Modify: `ductor_bot/i18n/{de,en,es,fr,id,nl,pt,ru}/chat.toml`
- Test: `tests/orchestrator/test_commands.py`
- Test: `tests/orchestrator/test_registry.py`
- Test: `tests/messenger/test_commands.py`
- Test: `tests/messenger/telegram/test_app.py`
- Test: `tests/messenger/matrix/test_transport.py`
- Test: `tests/messenger/slack/test_bot.py`
- Test: `tests/api/test_server_e2e.py`
- Test: `tests/test_commands.py`
- Test: `tests/i18n/test_loader.py`

**Interfaces:**

- Produces `DeepSeekBalanceObserver(fetch: Callable[[], Awaitable[DeepseekUsage]], repository: BalanceSnapshotRepository, *, interval_seconds=1800)` with `running: bool`, `start() -> None`, `stop() -> None`, and `collect_once() -> None`.
- `ObserverManager` starts it only for main+configured DeepSeek, stops it in `stop_all()`, and reconfigures it on `deepseek.enabled` hot reload.
- Registers `/usage` once in `CommandRegistry`; every command-capable transport routes to that handler.

- [ ] **Step 1: Write failing observer scheduling and lifecycle tests**

Use events rather than real sleep and assert:

```python
async def test_observer_collects_immediately_then_every_interval(repo, fake_fetch) -> None:
    observer = DeepSeekBalanceObserver(fake_fetch, repo, interval_seconds=0.01)
    await observer.start()
    for _ in range(100):
        if fake_fetch.await_count >= 2:
            break
        await asyncio.sleep(0.001)
    await observer.stop()
    assert fake_fetch.await_count >= 2
    assert observer.running is False


async def test_observer_skips_failed_and_partial_samples(repo, fake_fetch) -> None:
    fake_fetch.side_effect = [
        DeepseekUsage(ok=False, failure=UsageFailure.TIMEOUT),
        DeepseekUsage(ok=True, balances=()),
    ]
    observer = DeepSeekBalanceObserver(fake_fetch, repo)
    await observer.collect_once()
    await observer.collect_once()
    assert await repo.load() == ()
```

Also assert disabled/no-key creates no observer and no network call; sub-agent creates no observer; main starts exactly once; config hot reload enabled→disabled stops and disabled→enabled starts; `stop_all()` propagates cancellation and leaves no task.

- [ ] **Step 2: Write failing shared-command and transport-classification tests**

Assert `"usage"` appears exactly once in `BOT_COMMANDS`, belongs to
`ORCHESTRATOR_COMMANDS`, and `/usage` dispatches through the shared registry.
Extend the existing Telegram menu test with `assert "usage" in desired_names`.

For Slack, clone `test_routes_bare_message_command_without_leading_slash` with
`text="usage"` and assert `_handle_command` receives `/usage`. Matrix command
routing is already transport-agnostic; add this harness to
`tests/messenger/matrix/test_transport.py`:

```python
async def test_matrix_usage_is_routed_to_orchestrator() -> None:
    bot = object.__new__(MatrixBot)
    bot._COMMAND_DISPATCH = {}
    bot._cmd_orchestrator_locked = AsyncMock()
    spawned: list[Coroutine[object, object, None]] = []

    def capture(coro: Coroutine[object, object, None], *, name: str) -> None:
        assert name == "mx-orch-usage"
        spawned.append(coro)

    bot._spawn_task = capture
    await bot._handle_command("/usage", "!room:test", 7, MagicMock())
    assert len(spawned) == 1
    await spawned[0]
    bot._cmd_orchestrator_locked.assert_awaited_once()
```

For direct API, construct `_make_server(message_handler=handler)`, send encrypted
text `/usage`, receive the result, and assert the handler's second positional
argument is `/usage`. This proves the API preserves the command for the
orchestrator registry rather than adding a separate usage implementation.

- [ ] **Step 3: Write failing locale-completeness tests**

Add `bot.usage` plus every Task 7 `[usage]` key to English. Extend
`tests/i18n/test_loader.py` with one test that loads English as the source of
truth and, for every `LANGUAGES` code, asserts those keys exist and
`_extract_placeholders(localized[key]) == _extract_placeholders(english[key])`.
This proves key and placeholder parity across `de`, `en`, `es`, `fr`, `id`,
`nl`, `pt`, and `ru`.

- [ ] **Step 4: Run the focused group and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/usage/test_observer.py tests/orchestrator/test_commands.py \
  tests/orchestrator/test_registry.py tests/messenger/test_commands.py \
  tests/messenger/telegram/test_app.py tests/messenger/matrix/test_transport.py \
  tests/messenger/slack/test_bot.py tests/api/test_server_e2e.py \
  tests/test_commands.py tests/i18n/test_loader.py -q
```

Expected: observer, command, routing, menu, and translation tests fail because integration is absent.

- [ ] **Step 5: Implement cancel-safe balance observation and hot reload**

The loop must be:

```python
async def _run(self) -> None:
    while True:
        try:
            await self.collect_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("DeepSeek balance collection failed category=unavailable")
        await asyncio.sleep(self._interval_seconds)
```

`start()` is idempotent. `ObserverManager.start_all()` receives `is_main: bool`, initializes the repository once, then starts the balance observer only when `is_main and runtime.configured`. Hot reload schedules one async `reconfigure_deepseek(runtime)` operation that also updates `UsageService`; key remains the startup-captured value.

- [ ] **Step 6: Register one thin command implementation**

Add:

```python
async def cmd_usage(
    orch: Orchestrator, _key: SessionKey, _text: str
) -> OrchestratorResult:
    logger.info("Usage requested")
    report = await orch.usage_service.collect()
    return OrchestratorResult(
        text=format_usage(report, timezone=resolve_user_timezone(orch.config.user_timezone))
    )
```

Expose a read-only `usage_service` property on `Orchestrator`, register `/usage`, add it after `/status` in the menu, and classify it as orchestrator-routed. Do not add transport-specific provider queries.

- [ ] **Step 7: Add all translations with exact placeholder parity**

Keep the placeholders exactly `{amount}`, `{currency}`, `{plan}`, `{percent}`,
and `{time}`. Add these exact catalog entries (provider names remain product
names):

`en/commands.toml`: `usage = "Show plan usage"`

```toml
[usage]
header = "**Usage**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Balance: {amount} {currency}"
spent_today = "Spent today: {amount} {currency}"
recharged_today = "Recharged today: {amount} {currency}"
daily_unavailable = "Today's change: unavailable"
plan = "Plan: {plan}"
short_window = "Short window: {percent}%"
five_hour = "5-hour usage: {percent}%"
weekly = "7-day usage: {percent}%"
resets = "resets {time}"
window_unavailable = "Unavailable"
error_disabled = "Disabled"
error_not_configured = "Not configured"
error_not_logged_in = "Not logged in"
error_expired = "Login expired"
error_rate_limited = "Rate limited"
error_timeout = "Timed out"
error_malformed_response = "Malformed provider response"
error_unavailable = "Unavailable"
```

`de/commands.toml`: `usage = "Nutzung anzeigen"`

```toml
[usage]
header = "**Nutzung**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Guthaben: {amount} {currency}"
spent_today = "Heute verbraucht: {amount} {currency}"
recharged_today = "Heute aufgeladen: {amount} {currency}"
daily_unavailable = "Heutige Änderung: nicht verfügbar"
plan = "Tarif: {plan}"
short_window = "Kurzzeitfenster: {percent}%"
five_hour = "5-Stunden-Nutzung: {percent}%"
weekly = "7-Tage-Nutzung: {percent}%"
resets = "Zurücksetzung {time}"
window_unavailable = "Nicht verfügbar"
error_disabled = "Deaktiviert"
error_not_configured = "Nicht konfiguriert"
error_not_logged_in = "Nicht angemeldet"
error_expired = "Anmeldung abgelaufen"
error_rate_limited = "Rate-Limit erreicht"
error_timeout = "Zeitüberschreitung"
error_malformed_response = "Ungültige Anbieterantwort"
error_unavailable = "Nicht verfügbar"
```

`es/commands.toml`: `usage = "Ver uso de planes"`

```toml
[usage]
header = "**Uso**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Saldo: {amount} {currency}"
spent_today = "Gastado hoy: {amount} {currency}"
recharged_today = "Recargado hoy: {amount} {currency}"
daily_unavailable = "Cambio de hoy: no disponible"
plan = "Plan: {plan}"
short_window = "Ventana corta: {percent}%"
five_hour = "Uso de 5 horas: {percent}%"
weekly = "Uso de 7 días: {percent}%"
resets = "se reinicia {time}"
window_unavailable = "No disponible"
error_disabled = "Desactivado"
error_not_configured = "No configurado"
error_not_logged_in = "Sesión no iniciada"
error_expired = "Sesión caducada"
error_rate_limited = "Límite alcanzado"
error_timeout = "Tiempo agotado"
error_malformed_response = "Respuesta del proveedor no válida"
error_unavailable = "No disponible"
```

`fr/commands.toml`: `usage = "Voir l’utilisation"`

```toml
[usage]
header = "**Utilisation**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Solde : {amount} {currency}"
spent_today = "Dépensé aujourd’hui : {amount} {currency}"
recharged_today = "Rechargé aujourd’hui : {amount} {currency}"
daily_unavailable = "Variation du jour : indisponible"
plan = "Forfait : {plan}"
short_window = "Fenêtre courte : {percent}%"
five_hour = "Utilisation sur 5 h : {percent}%"
weekly = "Utilisation sur 7 jours : {percent}%"
resets = "réinitialisation {time}"
window_unavailable = "Indisponible"
error_disabled = "Désactivé"
error_not_configured = "Non configuré"
error_not_logged_in = "Non connecté"
error_expired = "Connexion expirée"
error_rate_limited = "Limite atteinte"
error_timeout = "Délai dépassé"
error_malformed_response = "Réponse du fournisseur incorrecte"
error_unavailable = "Indisponible"
```

`id/commands.toml`: `usage = "Lihat penggunaan"`

```toml
[usage]
header = "**Penggunaan**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Saldo: {amount} {currency}"
spent_today = "Terpakai hari ini: {amount} {currency}"
recharged_today = "Diisi hari ini: {amount} {currency}"
daily_unavailable = "Perubahan hari ini: tidak tersedia"
plan = "Paket: {plan}"
short_window = "Jendela singkat: {percent}%"
five_hour = "Penggunaan 5 jam: {percent}%"
weekly = "Penggunaan 7 hari: {percent}%"
resets = "direset {time}"
window_unavailable = "Tidak tersedia"
error_disabled = "Dinonaktifkan"
error_not_configured = "Belum dikonfigurasi"
error_not_logged_in = "Belum masuk"
error_expired = "Login kedaluwarsa"
error_rate_limited = "Batas laju tercapai"
error_timeout = "Waktu habis"
error_malformed_response = "Respons penyedia tidak valid"
error_unavailable = "Tidak tersedia"
```

`nl/commands.toml`: `usage = "Gebruik tonen"`

```toml
[usage]
header = "**Gebruik**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Saldo: {amount} {currency}"
spent_today = "Vandaag verbruikt: {amount} {currency}"
recharged_today = "Vandaag opgewaardeerd: {amount} {currency}"
daily_unavailable = "Wijziging vandaag: niet beschikbaar"
plan = "Abonnement: {plan}"
short_window = "Kort venster: {percent}%"
five_hour = "Gebruik in 5 uur: {percent}%"
weekly = "Gebruik in 7 dagen: {percent}%"
resets = "reset {time}"
window_unavailable = "Niet beschikbaar"
error_disabled = "Uitgeschakeld"
error_not_configured = "Niet geconfigureerd"
error_not_logged_in = "Niet aangemeld"
error_expired = "Aanmelding verlopen"
error_rate_limited = "Limiet bereikt"
error_timeout = "Time-out"
error_malformed_response = "Ongeldig antwoord van provider"
error_unavailable = "Niet beschikbaar"
```

`pt/commands.toml`: `usage = "Ver utilização"`

```toml
[usage]
header = "**Utilização**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Saldo: {amount} {currency}"
spent_today = "Gasto hoje: {amount} {currency}"
recharged_today = "Recarregado hoje: {amount} {currency}"
daily_unavailable = "Alteração de hoje: indisponível"
plan = "Plano: {plan}"
short_window = "Janela curta: {percent}%"
five_hour = "Utilização em 5 horas: {percent}%"
weekly = "Utilização em 7 dias: {percent}%"
resets = "reinicia {time}"
window_unavailable = "Indisponível"
error_disabled = "Desativado"
error_not_configured = "Não configurado"
error_not_logged_in = "Sessão não iniciada"
error_expired = "Sessão expirada"
error_rate_limited = "Limite atingido"
error_timeout = "Tempo esgotado"
error_malformed_response = "Resposta inválida do fornecedor"
error_unavailable = "Indisponível"
```

`ru/commands.toml`: `usage = "Показать лимиты"`

```toml
[usage]
header = "**Использование**"
deepseek = "DeepSeek"
claude = "Claude Code"
codex = "Codex"
balance = "Баланс: {amount} {currency}"
spent_today = "Потрачено сегодня: {amount} {currency}"
recharged_today = "Пополнено сегодня: {amount} {currency}"
daily_unavailable = "Изменение за сегодня: недоступно"
plan = "Тариф: {plan}"
short_window = "Короткое окно: {percent}%"
five_hour = "Использование за 5 часов: {percent}%"
weekly = "Использование за 7 дней: {percent}%"
resets = "сброс {time}"
window_unavailable = "Недоступно"
error_disabled = "Отключено"
error_not_configured = "Не настроено"
error_not_logged_in = "Вход не выполнен"
error_expired = "Сеанс входа истёк"
error_rate_limited = "Лимит достигнут"
error_timeout = "Время ожидания истекло"
error_malformed_response = "Некорректный ответ провайдера"
error_unavailable = "Недоступно"
```

- [ ] **Step 8: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/usage tests/orchestrator/test_commands.py tests/orchestrator/test_registry.py \
  tests/messenger/test_commands.py tests/messenger/telegram/test_app.py \
  tests/messenger/matrix/test_transport.py tests/messenger/slack/test_bot.py \
  tests/api/test_server_e2e.py tests/test_commands.py tests/i18n/test_loader.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/usage ductor_bot/orchestrator \
  ductor_bot/commands.py ductor_bot/messenger/commands.py tests/usage
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/usage ductor_bot/orchestrator
git add ductor_bot/usage ductor_bot/orchestrator ductor_bot/commands.py \
  ductor_bot/messenger/commands.py ductor_bot/i18n tests/usage \
  tests/orchestrator tests/messenger tests/api/test_server_e2e.py \
  tests/test_commands.py tests/i18n/test_loader.py
git commit -m "feat(usage): expose localized cross-transport usage"
```

---

### Task 9: Add Main-Only Claude OAuth Login-Token Keepalive

**Files:**

- Create: `ductor_bot/cli/claude_token_keepalive.py`
- Create: `tests/cli/test_claude_token_keepalive.py`
- Modify: `ductor_bot/orchestrator/observers.py`
- Modify: `ductor_bot/orchestrator/lifecycle.py`

**Interfaces:**

- Produces `ClaudeTokenKeepalive(credentials_path, *, interval_seconds=1800, refresh_before_seconds=7200, min_attempt_gap_seconds=14400)`.
- Produces `refresh_once() -> bool`, `start()`, `stop()`, and `running`.
- Manages only `claudeAiOauth` in `.claude/.credentials.json`; `/usage` never calls it.

- [ ] **Step 1: Write failing timing, eligibility, and main-only lifecycle tests**

Use injected wall/monotonic clocks and assert: no credentials, invalid JSON, missing OAuth record, missing refresh token, or more than two hours remaining makes no request; expiry within two hours attempts; a second attempt inside four monotonic hours makes no request; main+enabled starts once; main+disabled and every sub-agent start zero.

- [ ] **Step 2: Write failing success, rotation-race, permission, and failure tests**

For success, seed unknown top-level/OAuth fields and assert they survive while only returned `accessToken`, optional `refreshToken`, and valid `expiresAt` change. Assert final mode is `0o600` and replacement temp is in the same directory.

Patch the network call to rotate the on-disk `refreshToken` before returning; assert the response is discarded and the rotated file remains byte-for-byte unchanged. Repeat byte-preservation assertions for HTTP failure, timeout, malformed JSON, missing access token, invalid expires value, and atomic write failure. Assert no token or raw body appears in captured logs.

- [ ] **Step 3: Run keepalive tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/cli/test_claude_token_keepalive.py \
  tests/orchestrator/test_optional_model_observers.py -q
```

Expected: keepalive import and lifecycle assertions fail.

- [ ] **Step 4: Implement compare-before-replace and strict atomic mode**

Use these fixed constants and eligibility rule:

```python
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_TIMEOUT = aiohttp.ClientTimeout(total=10)

needs_refresh = expires_at_ms / 1000 - wall_time() <= self._refresh_before_seconds
gap_ok = monotonic() - self._last_attempt >= self._min_attempt_gap_seconds
```

Set `_last_attempt` immediately before the POST, whether it succeeds or fails. After a valid response, reread the full credential file, compare its current `refreshToken` to the request token, apply fields to that fresh document, then write through `tempfile.mkstemp(dir=path.parent)`, `os.fchmod(fd, 0o600)`, flush+`os.fsync`, and `os.replace`. Clean temp files on every failure. Never log exception strings from provider responses.

- [ ] **Step 5: Wire the cancel-safe observer into main lifecycle**

The loop catches ordinary exceptions, propagates cancellation, and sleeps 1800 seconds between inspections. `ObserverManager` owns one optional keepalive instance, creates it only when `is_main and config.claude_token_keepalive`, and stops it before model-cache teardown. No hot reload is required for this toggle.

- [ ] **Step 6: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/cli/test_claude_token_keepalive.py \
  tests/orchestrator/test_optional_model_observers.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/cli/claude_token_keepalive.py \
  ductor_bot/orchestrator/observers.py tests/cli/test_claude_token_keepalive.py
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/cli/claude_token_keepalive.py \
  ductor_bot/orchestrator/observers.py
git add ductor_bot/cli/claude_token_keepalive.py ductor_bot/orchestrator/observers.py \
  ductor_bot/orchestrator/lifecycle.py tests/cli/test_claude_token_keepalive.py \
  tests/orchestrator/test_optional_model_observers.py
git commit -m "feat(auth): keep Claude login token fresh"
```

---

### Task 10: Synchronize Sub-Agent Chat Authorization Before Every Start and Rebuild

**Files:**

- Modify: `ductor_bot/multiagent/supervisor.py`
- Test: `tests/multiagent/test_supervisor.py`
- Regression test: `tests/multiagent/test_models.py`

**Interfaces:**

- Produces `_sync_sub_agent_config(config_path: Path, config: AgentConfig) -> None`.
- Synchronizes exactly `provider`, `model`, `reasoning_effort`, `allowed_user_ids`, `allowed_group_ids`, and `group_mention_only` using `update_config_file_async()`.
- A sync failure prevents only that target sub-agent from being registered or run.

- [ ] **Step 1: Write failing exact-write and stale-placeholder tests**

Seed a generated sub-agent `config.json` containing placeholder allowlists, `group_mention_only=true`, and an unrelated nested Docker config. Start a sub-agent whose merged config has real users, empty groups, and false mention-only. Assert:

```python
assert written["allowed_user_ids"] == [7739164762]
assert written["allowed_group_ids"] == []
assert written["group_mention_only"] is False
assert written["docker"] == original_docker
```

Patch a later model update/reload and prove placeholders do not return. Keep existing `merge_sub_agent_config` tests that no allowlist inherits from main.

- [ ] **Step 2: Write failing rebuild-order and isolated-failure tests**

Record call order for `AgentStack.create`, config sync, bus registration, and `_supervised_run`. Assert sync completes before registration/task creation on initial start and rebuild. Patch sync to raise for `sub1`; assert no stack, health, bus entry, or task for `sub1`, while starting `sub2` still succeeds and main remains present. Assert captured log records only the agent name/category, never list values.

- [ ] **Step 3: Run supervisor tests and observe RED**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/multiagent/test_supervisor.py \
  tests/multiagent/test_models.py -q
```

Expected: existing code writes only provider/model/effort and rebuild bypasses auth synchronization.

- [ ] **Step 4: Extract one exact synchronization boundary**

Implement:

```python
async def _sync_sub_agent_config(
    self, config_path: Path, config: AgentConfig
) -> None:
    await update_config_file_async(
        config_path,
        provider=config.provider,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        allowed_user_ids=config.allowed_user_ids,
        allowed_group_ids=config.allowed_group_ids,
        group_mention_only=config.group_mention_only,
    )
```

Call it with `stack.paths.config_path` after `AgentStack.create()` has seeded files but before assigning `_stacks`, `_health`, bus handlers, or tasks. On failure, best-effort `stack.shutdown()`, log `Failed to synchronize sub-agent config name=%s`, and return without start. Apply the same boundary in `_rebuild_stack()` for `not old_stack.is_main`, using `new_stack.paths.config_path` and `new_stack.config`; let rebuild failure propagate to its existing supervisor recovery boundary. The main stack never passes through this synchronization method.

- [ ] **Step 5: Verify Docker and privilege fields remain untouched**

```bash
git diff -- ductor_bot/multiagent/supervisor.py tests/multiagent/test_supervisor.py
rg -n "docker|sudo|root|user|mount|image|command" ductor_bot/multiagent/supervisor.py
```

Expected: the only `user` occurrence introduced is the `allowed_user_ids` field name; no Docker/privilege code is added.

- [ ] **Step 6: Verify GREEN and commit**

```bash
/home/zqxu/ductor/.venv/bin/pytest tests/multiagent/test_supervisor.py \
  tests/multiagent/test_models.py -q
/home/zqxu/ductor/.venv/bin/ruff check ductor_bot/multiagent/supervisor.py \
  tests/multiagent/test_supervisor.py
/home/zqxu/ductor/.venv/bin/mypy ductor_bot/multiagent/supervisor.py
git add ductor_bot/multiagent/supervisor.py tests/multiagent/test_supervisor.py \
  tests/multiagent/test_models.py
git commit -m "fix(multiagent): synchronize sub-agent chat authorization"
```

---

### Task 11: Run Cross-Subsystem Regression, Review the Branch, and Enforce the Publication Gate

**Files:**

- Modify: files already listed in Tasks 1–10 when an accepted review finding requires a corrective patch.
- Read: `docs/superpowers/specs/2026-08-13-deepseek-usage-auth-sync-design.md`
- Read: `docs/superpowers/plans/2026-08-13-deepseek-usage-auth-sync.md`

**Interfaces:**

- Consumes all earlier task commits.
- Produces a clean, reviewed feature branch and a publication manifest.
- Does not merge or push before a new explicit user approval after the manifest is shown.

- [ ] **Step 1: Run focused cross-subsystem regression**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/cli/test_deepseek.py tests/cli/test_claude_token_keepalive.py \
  tests/cli/test_service.py tests/cli/test_param_resolver.py \
  tests/usage tests/session tests/orchestrator tests/multiagent \
  tests/messenger tests/api/test_server_e2e.py tests/test_config.py \
  tests/test_config_reload.py tests/test_commands.py tests/i18n/test_loader.py \
  -q
```

Expected: all focused and adjacent regression tests pass.

- [ ] **Step 2: Run accepted Docker/provider non-regression tests**

```bash
/home/zqxu/ductor/.venv/bin/pytest \
  tests/infra/test_docker.py tests/infra/test_docker_image.py \
  tests/infra/test_docker_rebuild.py tests/infra/test_docker_tools.py \
  tests/cli/test_claude_provider.py tests/cli/test_codex_provider.py \
  tests/cli/test_gemini_provider.py tests/cli/test_antigravity_provider.py \
  tests/cli/test_grok_provider.py -q
```

Expected: all tests pass and no Docker implementation file is changed by the feature branch.

- [ ] **Step 3: Run full fresh quality gates**

```bash
/home/zqxu/ductor/.venv/bin/ruff format .
/home/zqxu/ductor/.venv/bin/ruff format --check .
/home/zqxu/ductor/.venv/bin/ruff check .
/home/zqxu/ductor/.venv/bin/mypy ductor_bot
/home/zqxu/ductor/.venv/bin/python -m ductor_bot.i18n.check --quiet
/home/zqxu/ductor/.venv/bin/pytest -q
```

Expected: every command exits 0. Formatting changes must be inspected and included in the relevant feature commit or a dedicated `style: format restored usage features` commit; never silently leave them uncommitted.

- [ ] **Step 4: Perform secret, scope, and obsolete-feature audits**

```bash
git diff --name-only main...HEAD
git diff --check main...HEAD
git diff main...HEAD -- Dockerfile.sandbox ductor_bot/infra/docker.py \
  ductor_bot/infra/docker_image.py ductor_bot/infra/docker_rebuild.py
git grep -n "DEEPSEEK_API_KEY\|ANTHROPIC_AUTH_TOKEN" HEAD -- ':!tests/**'
git grep -n "TaskHub\|task_hub\|ComfyUI\|0.999.0+icamelot" HEAD -- ductor_bot config.example.json
```

Expected: no Docker diff; secret names appear only at loading/injection boundaries and never with values; no restored obsolete feature symbols in production/config.

- [ ] **Step 5: Review against every acceptance criterion**

Use `requesting-code-review` and inspect the complete `main...HEAD` diff. Resolve all accepted correctness, security, concurrency, and spec-coverage findings with RED→GREEN tests. Re-run Steps 1–4 after any fix and commit fixes with a scoped message. Explicitly verify all 12 acceptance criteria in the spec, including all eight locales and main-only writers/observers.

- [ ] **Step 6: Prepare and show the publication manifest, then stop**

Run:

```bash
git status --short
git log --oneline --reverse main..HEAD
git diff --stat main...HEAD
git remote -v
```

Expected: feature worktree is clean. Report to the user:

1. complete restored feature list;
2. changed behavior and config keys;
3. every focused/full test and quality result with command and count;
4. code-review findings and resolutions;
5. known limits, including 30-minute approximate daily baseline and restart-required key changes;
6. exact branch, commit list, local target `main`, and push target `origin/main`;
7. explicit statement that no deployment/restart/live auth probe is included.

Ask for explicit permission to merge and push. Do not run either operation in this step.

- [ ] **Step 7: After explicit approval only, merge into local main**

First confirm both checkouts and preserve all unrelated user files:

```bash
git -C /home/zqxu/ductor status --short --branch
git -C /home/zqxu/ductor/.worktrees/restore-deepseek-usage-auth status --short --branch
git -C /home/zqxu/ductor fetch origin
```

Expected: feature worktree is clean; main has only the already-known user-owned untracked files/symlink plus no new tracked change. If local `main` moved after branch creation, stop and reconcile without resetting or discarding user work.

With approval and an unchanged target:

```bash
git -C /home/zqxu/ductor merge --ff-only feat/restore-deepseek-usage-auth
```

Expected: local `main` fast-forwards to the reviewed feature tip. Do not delete the branch/worktree yet.

- [ ] **Step 8: Verify merged main and push to the user's remote**

```bash
cd /home/zqxu/ductor
/home/zqxu/ductor/.venv/bin/ruff format --check .
/home/zqxu/ductor/.venv/bin/ruff check .
/home/zqxu/ductor/.venv/bin/mypy ductor_bot
/home/zqxu/ductor/.venv/bin/python -m ductor_bot.i18n.check --quiet
/home/zqxu/ductor/.venv/bin/pytest -q
git push origin main
git status --short --branch
git log -1 --oneline
```

Expected: all merged-main checks pass, push succeeds, and `main` is no longer ahead of `origin/main`. Report the final main SHA and push result. Do not install the package, restart the service, rebuild Docker, run credential-dependent live probes, or remove the feature worktree without separate user instruction.
