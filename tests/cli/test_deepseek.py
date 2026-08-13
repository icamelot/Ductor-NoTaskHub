"""Tests for the redaction-safe DeepSeek runtime boundary."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from ductor_bot.cli.base import CLIConfig
from ductor_bot.cli.claude_provider import ClaudeCodeCLI
from ductor_bot.cli.deepseek import (
    DeepseekRuntime,
    claude_cli_runnable,
    load_deepseek_api_key,
    resolve_deepseek_runtime,
)
from ductor_bot.cli.factory import create_cli
from ductor_bot.config import DeepseekConfig
from ductor_bot.infra.env_secrets import clear_cache
from ductor_bot.workspace.paths import DuctorPaths


@pytest.fixture
def runtime() -> DeepseekRuntime:
    return resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, models=["deepseek-v4-pro"]),
        "secret-value",
        reserved_models=frozenset(),
    )


def test_factory_delegates_deepseek_to_claude_without_changing_provider(
    runtime: DeepseekRuntime,
) -> None:
    config = CLIConfig(provider="deepseek", model="deepseek-v4-pro", deepseek=runtime)
    cli = create_cli(config)
    assert isinstance(cli, ClaudeCodeCLI)
    assert cli._config.provider == "deepseek"


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
        (
            "https://api.deepseek.com/anthropic",
            ["deepseek-a", " deepseek-a "],
            "duplicate_model",
        ),
        ("https://api.deepseek.com/anthropic", ["opus"], "model_collision"),
    ],
)
def test_invalid_runtime_is_safely_disabled(base_url: str, models: list[str], error: str) -> None:
    runtime = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, base_url=base_url, models=models),
        "secret",
        reserved_models=frozenset({"opus"}),
    )
    assert runtime.configured is False
    assert runtime.error == error


@pytest.mark.parametrize(
    "model",
    ["", "a" * 257, "line\nbreak", "tab\tmodel", "nul\0model"],
)
def test_invalid_model_shapes_are_rejected(model: str) -> None:
    runtime = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, models=[model]),
        "secret",
        reserved_models=frozenset(),
    )
    assert runtime.configured is False
    assert runtime.error == "invalid_model"


def test_loopback_http_is_allowed_but_remote_http_is_not() -> None:
    runtime = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, base_url="http://127.0.0.1:9000/anthropic"),
        "secret",
        reserved_models=frozenset(),
    )
    assert runtime.configured is True


def test_disabled_and_missing_key_have_bounded_errors() -> None:
    disabled = resolve_deepseek_runtime(DeepseekConfig(), "secret", reserved_models=frozenset())
    missing = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True), "", reserved_models=frozenset()
    )
    assert disabled.error == "disabled"
    assert missing.error == "missing_key"


def test_load_key_uses_root_env_for_sub_agent(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY= root-secret \n", encoding="utf-8")
    agent_home = tmp_path / "agents" / "worker"
    agent_home.mkdir(parents=True)
    (agent_home / ".env").write_text("DEEPSEEK_API_KEY=wrong\n", encoding="utf-8")
    clear_cache()

    assert load_deepseek_api_key(DuctorPaths(ductor_home=agent_home)) == "root-secret"


def test_host_probe_requires_resolved_runnable_claude(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["timeout"] == 10
        assert kwargs["stdout"] is subprocess.DEVNULL
        assert kwargs["stderr"] is subprocess.DEVNULL
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("ductor_bot.cli.deepseek.shutil.which", lambda _name: "/bin/claude")
    monkeypatch.setattr("ductor_bot.cli.deepseek.subprocess.run", run)

    assert claude_cli_runnable() is True
    assert calls == [["/bin/claude", "--version"]]


def test_docker_probe_uses_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("ductor_bot.cli.deepseek.shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr("ductor_bot.cli.deepseek.subprocess.run", run)

    assert claude_cli_runnable("sandbox") is True
    assert calls == [["/bin/docker", "exec", "sandbox", "claude", "--version"]]


@pytest.mark.parametrize("failure", ["missing", "nonzero", "timeout", "oserror"])
def test_probe_failures_are_bounded_and_do_not_log_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    sentinel = "sensitive-probe-detail"
    monkeypatch.setattr(
        "ductor_bot.cli.deepseek.shutil.which",
        lambda _name: None if failure == "missing" else "/bin/claude",
    )

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if failure == "nonzero":
            return subprocess.CompletedProcess(command, 1)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10, output=sentinel)
        if failure == "oserror":
            raise OSError(sentinel)
        raise AssertionError("subprocess must not run when executable is missing")

    monkeypatch.setattr("ductor_bot.cli.deepseek.subprocess.run", run)
    with caplog.at_level(logging.WARNING):
        assert claude_cli_runnable() is False
    assert sentinel not in caplog.text
