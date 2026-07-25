from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


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
