"""Tests for .env secret injection into subprocess and Docker environments."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ductor_bot.cli.base import CLIConfig, docker_wrap
from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.cli.executor import build_subprocess_env
from ductor_bot.infra.env_secrets import clear_cache

_REMOVED_ENV_PARTS = ("DUCTOR", "TASK", "ID")
_REMOVED_TASK_ENV = "_".join(_REMOVED_ENV_PARTS)


def _deepseek_runtime() -> DeepseekRuntime:
    return DeepseekRuntime(
        requested=True,
        base_url="https://api.deepseek.com/anthropic",
        models=("deepseek-v4-pro",),
        api_key="deepseek-token",
    )


def test_subprocess_env_merges_secrets(tmp_path: Path) -> None:
    """Secrets from .env are merged into the subprocess env dict."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("MY_SECRET=hunter2\n")

    config = CLIConfig(working_dir=str(workspace))
    clear_cache()
    env = build_subprocess_env(config)

    assert env is not None
    assert env["MY_SECRET"] == "hunter2"


def test_subprocess_env_does_not_override_existing(tmp_path: Path) -> None:
    """Existing environment variables must not be overridden by .env."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("PATH=/evil\n")

    config = CLIConfig(working_dir=str(workspace))
    clear_cache()
    env = build_subprocess_env(config)

    assert env is not None
    assert env["PATH"] != "/evil"


def test_host_deepseek_overrides_have_highest_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _deepseek_runtime()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://native.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "native-token")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = CLIConfig(provider="deepseek", working_dir=workspace, deepseek=runtime)
    env = build_subprocess_env(config)
    assert env is not None
    assert env["ANTHROPIC_BASE_URL"] == runtime.base_url
    assert env["ANTHROPIC_AUTH_TOKEN"] == runtime.api_key


def test_native_claude_receives_no_deepseek_derived_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _deepseek_runtime()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://native.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "native-token")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = CLIConfig(provider="claude", working_dir=workspace, deepseek=runtime)
    env = build_subprocess_env(config)
    assert env is not None
    assert env["ANTHROPIC_BASE_URL"] == "https://native.example"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "native-token"
    assert env.get("ANTHROPIC_AUTH_TOKEN") != runtime.api_key


def test_subprocess_env_works_without_env_file(tmp_path: Path) -> None:
    """No .env file should not break subprocess env construction."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = CLIConfig(working_dir=str(workspace))
    clear_cache()
    env = build_subprocess_env(config)

    assert env is not None
    assert "DUCTOR_AGENT_NAME" in env


def test_subprocess_env_never_injects_legacy_task_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = CLIConfig(working_dir=str(workspace), process_label="task:legacy")
    clear_cache()
    env = build_subprocess_env(config)

    assert env is not None
    assert _REMOVED_TASK_ENV not in env


def test_subprocess_env_omits_task_id_for_other_labels(tmp_path: Path) -> None:
    """Non-task labels must not leak the removed task identifier variable."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    for label in ("main", "ns:build", "interagent:worker"):
        config = CLIConfig(working_dir=str(workspace), process_label=label)
        clear_cache()
        env = build_subprocess_env(config)

        assert env is not None
        assert _REMOVED_TASK_ENV not in env


def test_docker_wrap_never_injects_legacy_task_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = CLIConfig(
        working_dir=str(workspace),
        docker_container="test-container",
        process_label="task:legacy",
    )
    clear_cache()
    cmd, _ = docker_wrap(["codex"], config)

    assert not any(part.startswith(f"{_REMOVED_TASK_ENV}=") for part in cmd)


def test_docker_wrap_injects_secrets(tmp_path: Path) -> None:
    """Docker wrap should include .env secrets as -e flags."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("PPLX_API_KEY=sk-test\n")

    config = CLIConfig(
        working_dir=str(workspace),
        docker_container="test-container",
    )
    clear_cache()
    with patch.dict("os.environ", {}, clear=False):
        cmd, cwd = docker_wrap(["gemini"], config)

    assert cwd is None  # Docker mode
    assert "PPLX_API_KEY=sk-test" in cmd


def test_docker_wrap_env_file_wins_over_host_env(tmp_path: Path) -> None:
    """Secrets are injected even when the host env has the same key.

    The exec'd container process does not inherit the host environment, so
    skipping injection would silently drop the variable inside the container
    (or leave a stale image-baked value in place).
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING_VAR=from-dotenv\n")

    config = CLIConfig(
        working_dir=str(workspace),
        docker_container="test-container",
    )
    clear_cache()
    with patch.dict("os.environ", {"EXISTING_VAR": "from-host"}, clear=False):
        cmd, _ = docker_wrap(["gemini"], config)

    assert "EXISTING_VAR=from-dotenv" in cmd


def test_docker_wrap_sub_agent_env_overrides_main(tmp_path: Path) -> None:
    """A sub-agent's own .env takes priority over the main agent's .env."""
    agent_home = tmp_path / "agents" / "botbuilder"
    workspace = agent_home / "workspace"
    workspace.mkdir(parents=True)
    (tmp_path / ".env").write_text("SHARED_KEY=from-main\nMAIN_ONLY=main-val\n")
    (agent_home / ".env").write_text("SHARED_KEY=from-agent\nAGENT_ONLY=agent-val\n")

    config = CLIConfig(
        working_dir=str(workspace),
        docker_container="test-container",
        agent_name="botbuilder",
    )
    clear_cache()
    with patch.dict("os.environ", {}, clear=False):
        cmd, _ = docker_wrap(["claude"], config)

    assert "SHARED_KEY=from-agent" in cmd
    assert "SHARED_KEY=from-main" not in cmd
    # Main .env stays available as the low-priority baseline.
    assert "MAIN_ONLY=main-val" in cmd
    assert "AGENT_ONLY=agent-val" in cmd


def test_docker_wrap_provider_extra_env_wins(tmp_path: Path) -> None:
    """Provider-specific extra_env must override .env values."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=from-dotenv\n")

    config = CLIConfig(
        working_dir=str(workspace),
        docker_container="test-container",
    )
    clear_cache()
    with patch.dict("os.environ", {}, clear=False):
        cmd, _ = docker_wrap(
            ["gemini"],
            config,
            extra_env={"GEMINI_API_KEY": "from-provider"},
        )

    assert "GEMINI_API_KEY=from-provider" in cmd
    assert "GEMINI_API_KEY=from-dotenv" not in cmd


def test_docker_deepseek_provider_env_wins_over_dotenv(tmp_path: Path) -> None:
    runtime = _deepseek_runtime()
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


def test_docker_native_claude_keeps_dotenv_and_not_deepseek_runtime(tmp_path: Path) -> None:
    runtime = _deepseek_runtime()
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
        provider="claude",
        working_dir=workspace,
        docker_container="sandbox",
        agent_name="worker",
        deepseek=runtime,
    )
    command, _ = docker_wrap(["claude"], config)
    injected = [command[index + 1] for index, item in enumerate(command) if item == "-e"]
    env = dict(item.split("=", 1) for item in injected)
    assert env["ANTHROPIC_BASE_URL"] == "https://agent.example"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "agent-token"
    assert runtime.base_url not in injected
    assert runtime.api_key not in injected
