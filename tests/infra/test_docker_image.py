from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ductor_bot.infra.docker_image import (
    ProviderCliVersions,
    resolve_provider_cli_versions,
)

_REPO_ROOT = Path(__file__).parents[2]


def test_resolve_provider_cli_versions_uses_exact_npm_queries() -> None:
    calls: list[list[str]] = []
    values = {
        "@anthropic-ai/claude-code": "2.1.215",
        "@openai/codex": "0.144.6",
        "@google/gemini-cli": "0.51.0",
    }

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(values[args[2]]),
            stderr="",
        )

    versions = resolve_provider_cli_versions(runner=runner)

    assert versions == ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    assert calls == [
        ["npm", "view", "@anthropic-ai/claude-code", "version", "--json"],
        ["npm", "view", "@openai/codex", "version", "--json"],
        ["npm", "view", "@google/gemini-cli", "version", "--json"],
    ]
    assert versions.build_args() == (
        ("CLAUDE_CLI_VERSION", "2.1.215"),
        ("CODEX_CLI_VERSION", "0.144.6"),
        ("GEMINI_CLI_VERSION", "0.51.0"),
    )


@pytest.mark.parametrize("value", ["latest", "", "1.2", "1.2.3 trailing"])
def test_resolve_provider_cli_versions_rejects_non_concrete_values(value: str) -> None:
    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(value), stderr="")

    with pytest.raises(RuntimeError, match="Invalid npm version response"):
        resolve_provider_cli_versions(runner=runner)


def test_resolve_provider_cli_versions_sanitizes_npm_failure() -> None:
    secret = "SENTINEL_TOKEN_DO_NOT_PRINT"

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 23, stdout=secret, stderr=secret)

    with pytest.raises(
        RuntimeError, match=r"npm command failed.*exit code 23"
    ) as exc_info:
        resolve_provider_cli_versions(runner=runner)

    assert secret not in str(exc_info.value)


def test_sandbox_dockerfile_installs_exact_provider_build_arguments() -> None:
    dockerfile = (_REPO_ROOT / "Dockerfile.sandbox").read_text()

    marker_position = dockerfile.index(
        "# -- Ductor configured extras insertion point --"
    )
    provider_position = dockerfile.index("ARG CLAUDE_CLI_VERSION")

    assert marker_position < provider_position
    assert "ARG CODEX_CLI_VERSION" in dockerfile
    assert "ARG GEMINI_CLI_VERSION" in dockerfile
    assert '"@anthropic-ai/claude-code@$CLAUDE_CLI_VERSION"' in dockerfile
    assert '"@openai/codex@$CODEX_CLI_VERSION"' in dockerfile
    assert '"@google/gemini-cli@$GEMINI_CLI_VERSION"' in dockerfile
    assert 'org.ductor.codex-version="$CODEX_CLI_VERSION"' in dockerfile
