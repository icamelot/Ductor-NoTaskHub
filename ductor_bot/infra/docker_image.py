from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
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


@dataclass(frozen=True, slots=True)
class DockerContainerRef:
    id: str
    name: str
    image_id: str


@dataclass(frozen=True, slots=True)
class DockerContainerState:
    image_id: str
    running: bool


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, check=False, text=True)


def _npm_version(package: str, runner: CommandRunner) -> str:
    result = runner(["npm", "view", package, "version", "--json"])
    if result.returncode != 0:
        raise RuntimeError(
            f"Unable to resolve {package}: npm command failed (exit code {result.returncode})"
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
    pattern = re.compile(rf"(^|[^0-9A-Za-z.+-]){re.escape(expected)}([^0-9A-Za-z.+-]|$)")
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
            f"Docker candidate Codex version check failed (exit code {result.returncode})"
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
        raise RuntimeError(f"Docker image tag removal failed (exit code {result.returncode})")


def _canonical_image_id(value: str, *, context: str) -> str:
    if _IMAGE_ID_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"{context}: invalid immutable image ID")
    return value


def list_direct_image_containers(
    image_id: str,
    *,
    runner: CommandRunner = _run,
) -> list[DockerContainerRef]:
    expected = _canonical_image_id(image_id, context="Unable to list image containers")
    listed = runner(["docker", "ps", "-aq"])
    if listed.returncode != 0:
        raise RuntimeError(f"Unable to list Docker containers (exit code {listed.returncode})")
    ids = listed.stdout.split()
    if not ids:
        return []
    args = ["docker", "inspect", "--format", "{{.Name}}\t{{.Image}}", *ids]
    inspected = runner(args)
    if inspected.returncode != 0:
        raise RuntimeError(
            f"Unable to inspect Docker containers (exit code {inspected.returncode})"
        )
    lines = inspected.stdout.splitlines()
    if len(lines) != len(ids):
        raise RuntimeError("Docker inspect returned an unexpected container count")

    refs: list[DockerContainerRef] = []
    for container_id, line in zip(ids, lines, strict=True):
        if line.count("\t") != 1:
            raise RuntimeError("Docker inspect returned invalid container metadata")
        raw_name, raw_image_id = line.split("\t")
        name = raw_name.removeprefix("/")
        actual = _canonical_image_id(
            raw_image_id,
            context="Docker inspect returned invalid container metadata",
        )
        if not name or name != name.strip():
            raise RuntimeError("Docker inspect returned invalid container metadata")
        if actual == expected:
            refs.append(DockerContainerRef(container_id, name, actual))
    return refs


def remove_containers(
    containers: list[DockerContainerRef],
    *,
    runner: CommandRunner = _run,
) -> None:
    for container in containers:
        result = runner(["docker", "rm", "-f", container.id])
        if result.returncode != 0:
            raise RuntimeError(f"Unable to remove Docker container (exit code {result.returncode})")


def inspect_container_state(
    name: str,
    *,
    runner: CommandRunner = _run,
) -> DockerContainerState | None:
    args = [
        "docker",
        "inspect",
        name,
        "--format",
        "{{.Image}}\t{{.State.Running}}",
    ]
    result = runner(args)
    if result.returncode != 0:
        return None
    if result.stdout.strip().count("\t") != 1:
        raise RuntimeError("Docker inspect returned invalid container state")
    raw_image_id, raw_running = result.stdout.strip().split("\t")
    if raw_running not in {"true", "false"}:
        raise RuntimeError("Docker inspect returned invalid container state")
    return DockerContainerState(
        _canonical_image_id(
            raw_image_id,
            context="Docker inspect returned invalid container state",
        ),
        raw_running == "true",
    )


def wait_for_container_images(
    names: tuple[str, ...],
    expected_image_id: str,
    *,
    timeout_seconds: float = 120,
    poll_seconds: float = 1,
    runner: CommandRunner = _run,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        states = [inspect_container_state(name, runner=runner) for name in names]
        if all(
            state is not None and state.running and state.image_id == expected_image_id
            for state in states
        ):
            return
        time.sleep(poll_seconds)
    raise RuntimeError("Docker containers did not reach the candidate image")
