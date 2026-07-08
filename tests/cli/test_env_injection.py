"""Tests for .env secret injection into subprocess and Docker environments."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ductor_bot.cli.base import CLIConfig, docker_wrap
from ductor_bot.cli.executor import build_subprocess_env
from ductor_bot.infra.env_secrets import clear_cache


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


def test_subprocess_env_works_without_env_file(tmp_path: Path) -> None:
    """No .env file should not break subprocess env construction."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    config = CLIConfig(working_dir=str(workspace))
    clear_cache()
    env = build_subprocess_env(config)

    assert env is not None
    assert "DUCTOR_AGENT_NAME" in env


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
