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

    with pytest.raises(RuntimeError, match=r"npm command failed.*exit code 23") as exc_info:
        resolve_provider_cli_versions(runner=runner)

    assert secret not in str(exc_info.value)


def test_sandbox_dockerfile_installs_exact_provider_build_arguments() -> None:
    dockerfile = (_REPO_ROOT / "Dockerfile.sandbox").read_text()

    marker_position = dockerfile.index("# -- Ductor configured extras insertion point --")
    provider_position = dockerfile.index("ARG CLAUDE_CLI_VERSION")

    assert marker_position < provider_position
    assert "ARG CODEX_CLI_VERSION" in dockerfile
    assert "ARG GEMINI_CLI_VERSION" in dockerfile
    assert '"@anthropic-ai/claude-code@$CLAUDE_CLI_VERSION"' in dockerfile
    assert '"@openai/codex@$CODEX_CLI_VERSION"' in dockerfile
    assert '"@google/gemini-cli@$GEMINI_CLI_VERSION"' in dockerfile
    assert 'org.ductor.codex-version="$CODEX_CLI_VERSION"' in dockerfile


def test_candidate_image_ref_keeps_repository_and_uses_unique_token() -> None:
    from ductor_bot.infra.docker_image import candidate_image_ref

    assert (
        candidate_image_ref(
            "registry.example:5000/team/ductor-sandbox:stable",
            token_factory=lambda: "abc123",
        )
        == "registry.example:5000/team/ductor-sandbox:ductor-candidate-abc123"
    )


def test_inspect_image_id_returns_canonical_immutable_id() -> None:
    from ductor_bot.infra.docker_image import inspect_image_id

    image_id = f"sha256:{'a' * 64}"

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout=f"{image_id}\n", stderr="")

    assert inspect_image_id("candidate", runner=runner) == image_id


def test_verify_image_codex_version_requires_exact_expected_version() -> None:
    from ductor_bot.infra.docker_image import verify_image_codex_version

    calls: list[list[str]] = []

    def runner(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.144.6\n", stderr="")

    verify_image_codex_version("candidate", "0.144.6", runner=runner)

    assert calls == [["docker", "run", "--rm", "--entrypoint", "codex", "candidate", "--version"]]


def test_verify_image_codex_version_rejects_mismatch_without_raw_output() -> None:
    from ductor_bot.infra.docker_image import verify_image_codex_version

    secret = "SENTINEL_SECRET"

    def runner(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"codex-cli 0.142.5 {secret}",
            stderr=secret,
        )

    with pytest.raises(RuntimeError, match="candidate Codex version mismatch") as exc_info:
        verify_image_codex_version("candidate", "0.144.6", runner=runner)

    assert secret not in str(exc_info.value)


def test_verify_container_codex_version_uses_exact_container_command() -> None:
    from ductor_bot.infra.docker_image import verify_container_codex_version

    calls: list[list[str]] = []

    def runner(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.144.6\n", stderr="")

    verify_container_codex_version("ductor-sandbox", "0.144.6", runner=runner)

    assert calls == [["docker", "exec", "ductor-sandbox", "codex", "--version"]]


def test_tag_image_uses_exec_arguments() -> None:
    from ductor_bot.infra.docker_image import tag_image

    calls: list[list[str]] = []

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    tag_image(f"sha256:{'a' * 64}", "ductor-sandbox", runner=runner)

    assert calls == [["docker", "tag", f"sha256:{'a' * 64}", "ductor-sandbox"]]


def test_remove_image_tag_sanitizes_failure() -> None:
    from ductor_bot.infra.docker_image import remove_image_tag

    secret = "SENTINEL_SECRET"

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 17, stdout=secret, stderr=secret)

    with pytest.raises(RuntimeError, match="exit code 17") as exc_info:
        remove_image_tag("candidate", runner=runner)

    assert secret not in str(exc_info.value)


def test_list_direct_image_containers_selects_exact_immutable_id() -> None:
    from ductor_bot.infra.docker_image import (
        DockerContainerRef,
        list_direct_image_containers,
    )

    old_id = f"sha256:{'a' * 64}"
    other_id = f"sha256:{'c' * 64}"
    calls: list[list[str]] = []

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args == ["docker", "ps", "-aq"]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="c-main\nc-other\nc-bot\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                f"/ductor-sandbox\t{old_id}\n"
                f"/unrelated\t{other_id}\n"
                f"/ductor-sub-botbuilder\t{old_id}\n"
            ),
            stderr="",
        )

    refs = list_direct_image_containers(old_id, runner=runner)

    assert refs == [
        DockerContainerRef("c-main", "ductor-sandbox", old_id),
        DockerContainerRef("c-bot", "ductor-sub-botbuilder", old_id),
    ]
    assert calls[0] == ["docker", "ps", "-aq"]
    assert calls[1] == [
        "docker",
        "inspect",
        "--format",
        "{{.Name}}\t{{.Image}}",
        "c-main",
        "c-other",
        "c-bot",
    ]


def test_inspect_container_state_reads_image_and_running_flag() -> None:
    from ductor_bot.infra.docker_image import inspect_container_state

    image_id = f"sha256:{'b' * 64}"

    def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=f"{image_id}\ttrue\n",
            stderr="",
        )

    state = inspect_container_state("ductor-sandbox", runner=runner)

    assert state is not None
    assert state.image_id == image_id
    assert state.running is True
