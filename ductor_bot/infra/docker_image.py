from __future__ import annotations

import json
import re
import secrets
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
TimedCommandRunner = Callable[[list[str], float], subprocess.CompletedProcess[str]]
TokenFactory = Callable[[], str]

_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


@dataclass(frozen=True, slots=True)
class ProviderCliVersions:
    claude: str
    codex: str
    gemini: str

    def build_args(self) -> tuple[tuple[str, str], ...]:
        return (
            ("CLAUDE_CLI_VERSION", self.claude),
            ("CODEX_CLI_VERSION", self.codex),
            ("GEMINI_CLI_VERSION", self.gemini),
        )


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, check=False, text=True)


def _npm_version(package: str, runner: CommandRunner) -> str:
    result = runner(["npm", "view", package, "version", "--json"])
    if result.returncode != 0:
        raise RuntimeError(
            f"Unable to resolve {package}: npm command failed "
            f"(exit code {result.returncode})"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid npm version response for {package}") from exc
    if not isinstance(value, str) or _SEMVER_PATTERN.fullmatch(value.strip()) is None:
        raise RuntimeError(f"Invalid npm version response for {package}")
    return value.strip()


def resolve_provider_cli_versions(
    *,
    runner: CommandRunner = _run,
) -> ProviderCliVersions:
    return ProviderCliVersions(
        claude=_npm_version("@anthropic-ai/claude-code", runner),
        codex=_npm_version("@openai/codex", runner),
        gemini=_npm_version("@google/gemini-cli", runner),
    )


def candidate_image_ref(
    image: str,
    *,
    token_factory: TokenFactory = lambda: secrets.token_hex(12),
) -> str:
    if not image or image != image.strip() or "@" in image:
        raise ValueError("Invalid Docker image target")
    repository = image
    tail = repository.rsplit("/", 1)[-1]
    if ":" in tail:
        repository = repository.rsplit(":", 1)[0]
    token = token_factory()
    if _TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError("Invalid Docker candidate token")
    return f"{repository}:ductor-candidate-{token}"


def inspect_image_id(
    image: str,
    *,
    runner: CommandRunner = _run,
) -> str | None:
    result = runner(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if _IMAGE_ID_PATTERN.fullmatch(value) is None:
        raise RuntimeError("Docker image inspect returned an invalid immutable ID")
    return value


def _contains_exact_version(output: str, expected: str) -> bool:
    pattern = re.compile(
        rf"(^|[^0-9A-Za-z.+-]){re.escape(expected)}([^0-9A-Za-z.+-]|$)"
    )
    return pattern.search(output) is not None


def _run_with_timeout(
    args: list[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )


def verify_image_codex_version(
    image: str,
    expected: str,
    *,
    runner: TimedCommandRunner = _run_with_timeout,
    timeout_seconds: float = 60,
) -> None:
    args = ["docker", "run", "--rm", "--entrypoint", "codex", image, "--version"]
    try:
        result = runner(args, timeout_seconds)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker candidate Codex version check timed out") from None
    if result.returncode != 0:
        raise RuntimeError(
            "Docker candidate Codex version check failed "
            f"(exit code {result.returncode})"
        )
    if not _contains_exact_version(result.stdout, expected):
        raise RuntimeError("Docker candidate Codex version mismatch")


def verify_container_codex_version(
    name: str,
    expected: str,
    *,
    runner: TimedCommandRunner = _run_with_timeout,
    timeout_seconds: float = 60,
) -> None:
    args = ["docker", "exec", name, "codex", "--version"]
    try:
        result = runner(args, timeout_seconds)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Docker container Codex version check timed out") from None
    if result.returncode != 0 or not _contains_exact_version(result.stdout, expected):
        raise RuntimeError("Docker container Codex version check failed")


def tag_image(
    source: str,
    target: str,
    *,
    runner: CommandRunner = _run,
) -> None:
    result = runner(["docker", "tag", source, target])
    if result.returncode != 0:
        raise RuntimeError(f"Docker tag failed (exit code {result.returncode})")


def remove_image_tag(
    image: str,
    *,
    runner: CommandRunner = _run,
) -> None:
    result = runner(["docker", "rmi", image])
    if result.returncode != 0:
        raise RuntimeError(
            f"Docker image tag removal failed (exit code {result.returncode})"
        )
