# Docker Provider Refresh v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a verified candidate `ductor-sandbox` image whose Codex
version exactly matches the concrete version resolved from npm, without changing
the current image or containers before candidate verification succeeds.

**Architecture:** Add a small Docker image boundary for safe npm resolution,
candidate naming, immutable-ID inspection, and version probes. Extend
`DockerManager` to build a supplied candidate tag with concrete provider build
arguments and existing extras before the provider layer. A separate rebuild
orchestrator promotes the verified immutable ID, recreates every configured
shared-image container, and performs one bounded restore attempt if cutover fails.

**Tech Stack:** Python 3.11+, asyncio, subprocess exec-style argument lists,
Pydantic 2, Docker/BuildKit, pytest, Ruff, mypy.

## Global Constraints

- Start from `08ecc315bd20defaf886cf5d2232d52e89099224` on
  `feat/docker-image-refresh-v2`; do not cherry-pick Docker commits after the
  baseline.
- Phase one changes only provider CLI build/deployment reliability. Do not add
  new development, Office, PDF, OCR, or browser tools.
- Resolve Claude, Codex, and Gemini versions from npm at rebuild time and pass
  concrete versions into the image build. Never hardcode `0.144.6` as the target.
- Preserve normal Docker/BuildKit caching and every configured `docker.extras`
  entry, including the Playwright Python package.
- Do not install Chromium, run `playwright install`, create browser profiles, or
  add browser/cache mounts.
- Build a unique candidate tag and verify it before changing the current tag,
  service, or containers.
- Do not use global `--no-cache`.
- Failures return nonzero and do not expose credentials, environment variables,
  prompts, complete argv, or captured subprocess stdout/stderr.
- The assistant must launch each formal rebuild in a background terminal,
  immediately notify the user, and then stop without polling or reading the
  complete build log.
- Phase two gets a separate implementation plan only after phase one passes its
  operational acceptance.

## File Structure

- Create `ductor_bot/infra/docker_image.py`: provider versions, safe Docker image
  primitives, candidate and container version probes.
- Create `ductor_bot/infra/docker_rebuild.py`: candidate preparation, promotion,
  shared-container verification, and bounded cutover recovery.
- Modify `ductor_bot/infra/docker.py`: accept concrete versions, generate the
  configured Dockerfile, and execute a sanitized cached build.
- Modify `ductor_bot/infra/docker_extras.py`: insert configured extras at the
  explicit pre-provider marker.
- Modify `Dockerfile.sandbox`: declare provider build arguments and keep the
  provider npm layer after the extras marker.
- Modify `ductor_bot/cli_commands/docker.py`: replace destructive deletion with
  the candidate-first rebuild command and runtime callbacks.
- Create `tests/infra/test_docker_image.py`: unit tests for npm and Docker image
  primitives.
- Create `tests/infra/test_docker_rebuild.py`: event-order, no-pre-verification
  mutation, promotion, shared-container, and recovery tests.
- Create `tests/cli/test_docker_rebuild_command.py`: CLI exit/status and sanitized
  reporting tests.
- Modify `tests/infra/test_docker.py`: build-argument and sanitized build runner
  tests.
- Modify `tests/infra/test_docker_extras.py`: marker placement and Playwright
  preservation tests.

---

### Task 1: Concrete Provider Version Resolution and Dockerfile Contract

**Files:**

- Create: `ductor_bot/infra/docker_image.py`
- Create: `tests/infra/test_docker_image.py`
- Modify: `Dockerfile.sandbox:33-42`

**Interfaces:**

- Produces:
  - `ProviderCliVersions(claude: str, codex: str, gemini: str)`
  - `ProviderCliVersions.build_args() -> tuple[tuple[str, str], ...]`
  - `resolve_provider_cli_versions(*, runner: CommandRunner = _run) -> ProviderCliVersions`
- Consumes: no earlier task interfaces.

- [ ] **Step 1: Write failing provider-resolution tests**

Create `tests/infra/test_docker_image.py` with the concrete success and rejection
cases:

```python
from __future__ import annotations

import json
import subprocess

import pytest

from ductor_bot.infra.docker_image import (
    ProviderCliVersions,
    resolve_provider_cli_versions,
)


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

    with pytest.raises(RuntimeError, match="npm command failed.*exit code 23") as exc_info:
        resolve_provider_cli_versions(runner=runner)

    assert secret not in str(exc_info.value)
```

- [ ] **Step 2: Run the new test and observe RED**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_image.py -q
```

Expected: collection fails because `ductor_bot.infra.docker_image` does not exist.

- [ ] **Step 3: Implement the minimal provider-version module**

Create `ductor_bot/infra/docker_image.py` with:

```python
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
```

- [ ] **Step 4: Add the provider Dockerfile contract**

Replace the unversioned npm installation in `Dockerfile.sandbox` with:

```dockerfile
# -- Ductor configured extras insertion point --

ARG CLAUDE_CLI_VERSION
ARG CODEX_CLI_VERSION
ARG GEMINI_CLI_VERSION

USER root
RUN --mount=type=cache,target=/root/.npm \
    npm install -g \
      "@anthropic-ai/claude-code@$CLAUDE_CLI_VERSION" \
      "@openai/codex@$CODEX_CLI_VERSION" \
      "@google/gemini-cli@$GEMINI_CLI_VERSION"

LABEL org.ductor.claude-version="$CLAUDE_CLI_VERSION" \
      org.ductor.codex-version="$CODEX_CLI_VERSION" \
      org.ductor.gemini-version="$GEMINI_CLI_VERSION"
```

Keep the existing final `USER node`, `WORKDIR`, and `CMD` after this block.

- [ ] **Step 5: Verify GREEN and the no-hardcode contract**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_image.py -q
rg -n 'ARG (CLAUDE|CODEX|GEMINI)_CLI_VERSION|@openai/codex@\\$CODEX_CLI_VERSION' Dockerfile.sandbox
! rg -n '@openai/codex@0\\.144\\.6' Dockerfile.sandbox ductor_bot
```

Expected: provider tests pass; the Dockerfile contains all three arguments; no
historical Codex version is hardcoded in production files.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile.sandbox ductor_bot/infra/docker_image.py \
  tests/infra/test_docker_image.py
git commit -m "feat(docker): resolve provider CLI versions"
```

---

### Task 2: Cache-Preserving Extras Placement and Versioned Builds

**Files:**

- Modify: `ductor_bot/infra/docker_extras.py:10-250`
- Modify: `ductor_bot/infra/docker.py:178-310, 423-486`
- Modify: `tests/infra/test_docker_extras.py:110-180, 395-490`
- Modify: `tests/infra/test_docker.py:90-130`

**Interfaces:**

- Consumes:
  - `ProviderCliVersions.build_args()`
  - `resolve_provider_cli_versions()`
- Produces:
  - `DOCKER_EXTRAS_MARKER: str`
  - `DockerManager._build_image(image: str, versions: ProviderCliVersions) -> bool`

- [ ] **Step 1: Write RED tests for pre-provider extras and build arguments**

Change the extras test base and add the placement assertion:

```python
from ductor_bot.infra.docker_extras import DOCKER_EXTRAS_MARKER

_BASE = (
    "FROM ubuntu\n"
    f"{DOCKER_EXTRAS_MARKER}\n"
    "ARG CODEX_CLI_VERSION\n"
    "RUN npm install -g @openai/codex@$CODEX_CLI_VERSION\n"
    "USER node\n"
)


def test_extras_are_inserted_before_provider_layer() -> None:
    result = generate_dockerfile_extras(_BASE, resolve_extras(["playwright", "ffmpeg"]))

    assert result.index("pip install --no-cache-dir playwright") < result.index(
        "ARG CODEX_CLI_VERSION"
    )
    assert result.index("apt-get install") < result.index("ARG CODEX_CLI_VERSION")
    assert "playwright install" not in result
    assert "chromium" not in result.lower()
```

Add a build-command test to `tests/infra/test_docker.py`:

```python
async def test_build_image_passes_concrete_provider_build_args(
    docker_config: DockerConfig,
    docker_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker import DockerManager
    from ductor_bot.infra.docker_image import ProviderCliVersions

    (docker_paths.framework_root / "Dockerfile.sandbox").write_text(
        "FROM node:22\n# -- Ductor configured extras insertion point --\n"
    )
    manager = DockerManager(docker_config, docker_paths)
    calls: list[tuple[str, ...]] = []

    async def run(*args: str, **_kwargs: object) -> tuple[int, str]:
        calls.append(args)
        return 0, ""

    versions = ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    with patch.object(manager, "_exec_stream", side_effect=run):
        assert await manager._build_image("candidate", versions)

    build = calls[0]
    assert "--no-cache" not in build
    assert "CLAUDE_CLI_VERSION=2.1.215" in build
    assert "CODEX_CLI_VERSION=0.144.6" in build
    assert "GEMINI_CLI_VERSION=0.51.0" in build
    assert build[build.index("-t") + 1] == "candidate"
```

Add a shared fixture to `tests/infra/test_docker.py` and pass it to every existing
test that directly calls `_build_image()`:

```python
@pytest.fixture
def provider_versions() -> ProviderCliVersions:
    return ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
```

Change direct calls from:

```python
await manager._build_image("test-img")
```

to:

```python
await manager._build_image("test-img", provider_versions)
```

In `test_setup_builds_image_when_auto_build`, patch the resolver:

```python
with (
    patch("shutil.which", return_value="/usr/bin/docker"),
    patch.object(manager, "_exec", side_effect=mock_exec),
    patch.object(manager, "_exec_stream", side_effect=mock_exec),
    patch(
        "ductor_bot.infra.docker.resolve_provider_cli_versions",
        return_value=provider_versions,
    ),
):
    result = await manager.setup()
```

Apply the same `provider_versions` fixture and explicit second argument to the
three direct `_build_image()` calls in `tests/infra/test_docker_extras.py`.

Replace the old base-prefix assertion with:

```python
def test_preserves_base_content_around_marker() -> None:
    result = generate_dockerfile_extras(_BASE, resolve_extras(["ffmpeg"]))

    assert result.startswith("FROM ubuntu\n")
    assert result.count(DOCKER_EXTRAS_MARKER) == 1
    assert "ARG CODEX_CLI_VERSION" in result
    assert result.rstrip().endswith("USER node")
```

- [ ] **Step 2: Run the focused tests and observe RED**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_extras.py::TestGenerateDockerfile \
  tests/infra/test_docker.py::test_build_image_passes_concrete_provider_build_args -q
```

Expected: import/signature or ordering failures because the marker constant and
versioned build interface do not exist.

- [ ] **Step 3: Insert extras at the explicit marker**

In `ductor_bot/infra/docker_extras.py`, add:

```python
DOCKER_EXTRAS_MARKER = "# -- Ductor configured extras insertion point --"
```

Refactor `generate_dockerfile_extras()` so its generated block is inserted before
the marker:

```python
def generate_dockerfile_extras(base_content: str, extras: list[DockerExtra]) -> str:
    if not extras:
        return base_content
    if base_content.count(DOCKER_EXTRAS_MARKER) != 1:
        raise ValueError("Docker extras marker must appear exactly once")

    block = _render_dockerfile_extras(extras)
    return base_content.replace(
        DOCKER_EXTRAS_MARKER,
        f"{block}\n\n{DOCKER_EXTRAS_MARKER}",
        1,
    )
```

Move the existing apt/pip/user-switch rendering logic, unchanged in behavior,
into:

```python
def _render_dockerfile_extras(extras: list[DockerExtra]) -> str:
    all_apt: list[str] = []
    pip_groups: dict[str | None, list[str]] = {}
    for extra in extras:
        all_apt.extend(extra.apt_packages)
        _collect_pip(extra.pip_packages, pip_groups)

    lines = ["# -- Docker extras (auto-generated) --", "", "USER root"]
    if all_apt:
        apt_joined = " ".join(sorted(set(all_apt)))
        lines.append(
            "RUN apt-get update \\\n"
            f"    && apt-get install -y --no-install-recommends {apt_joined} \\\n"
            "    && rm -rf /var/lib/apt/lists/*"
        )

    has_custom_index = any(url is not None for url in pip_groups)
    for index_url in sorted(pip_groups, key=lambda url: (url is None, url or "")):
        packages = " ".join(pip_groups[index_url])
        if index_url:
            lines.append(
                f"RUN pip install --no-cache-dir {packages} --index-url {index_url}"
            )
        elif has_custom_index:
            lines.append(
                "RUN pip freeze > /tmp/idx-constraints.txt \\\n"
                f"    && pip install --no-cache-dir -c /tmp/idx-constraints.txt {packages} \\\n"
                "    && rm -f /tmp/idx-constraints.txt"
            )
        else:
            lines.append(f"RUN pip install --no-cache-dir {packages}")

    lines.extend(["", "USER node"])
    return "\n".join(lines)
```

Keep `_collect_pip()` and every `DockerExtra` definition unchanged.

- [ ] **Step 4: Make DockerManager require and pass concrete versions**

Change the build signature and command construction in
`ductor_bot/infra/docker.py`:

```python
from ductor_bot.infra.docker_image import (
    ProviderCliVersions,
    resolve_provider_cli_versions,
)


async def _build_image(
    self,
    image: str,
    versions: ProviderCliVersions,
) -> bool:
    # Keep existing Dockerfile selection, extras resolution, temp context,
    # and calculated timeout.
    build_cmd = ["docker", "build"]
    for name, value in versions.build_args():
        build_cmd += ["--build-arg", f"{name}={value}"]
    build_cmd += ["-t", image, "-f", str(ctx_dockerfile), ctx]
    rc, _ = await self._exec_stream(*build_cmd, deadline_seconds=timeout)
    if rc != 0:
        logger.error("Docker image build failed (exit code %d)", rc)
    return rc == 0
```

In the auto-build path, resolve once and pass the result:

```python
try:
    versions = resolve_provider_cli_versions()
except RuntimeError:
    logger.error("Provider CLI version resolution failed")
    return None
if not await self._build_image(image, versions):
    return None
```

Do not print or log captured npm diagnostics.

- [ ] **Step 5: Sanitize streamed build execution**

Change `_exec_stream()` so it drains subprocess output without printing,
retaining, or logging its contents:

```python
async def _exec_stream(
    self,
    *args: str,
    deadline_seconds: float = 30,
) -> tuple[int, str]:
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async with asyncio.timeout(deadline_seconds):
            async for _raw_line in proc.stdout:
                pass
            await proc.wait()
        return proc.returncode or 0, ""
    except TimeoutError:
        if proc is not None:
            proc.kill()
            await proc.wait()
        return 1, ""
    except OSError:
        return 1, ""
```

Update its tests to use a sentinel in child output and assert the sentinel is
absent from captured logs and the returned value.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker.py tests/infra/test_docker_extras.py -q
```

Expected: both files pass, including Playwright preservation and concrete build
arguments.

- [ ] **Step 7: Commit**

```bash
git add ductor_bot/infra/docker.py ductor_bot/infra/docker_extras.py \
  tests/infra/test_docker.py tests/infra/test_docker_extras.py
git commit -m "feat(docker): cache extras before provider CLIs"
```

---

### Task 3: Candidate Image and Immutable-ID Primitives

**Files:**

- Modify: `ductor_bot/infra/docker_image.py`
- Modify: `tests/infra/test_docker_image.py`

**Interfaces:**

- Consumes: `ProviderCliVersions`
- Produces:
  - `candidate_image_ref(image: str, *, token_factory: Callable[[], str]) -> str`
  - `inspect_image_id(image: str, *, runner: CommandRunner = _run) -> str | None`
  - `verify_image_codex_version(image: str, expected: str, ...) -> None`
  - `verify_container_codex_version(name: str, expected: str, ...) -> None`
  - `tag_image(source: str, target: str, ...) -> None`
  - `remove_image_tag(image: str, ...) -> None`

- [ ] **Step 1: Write RED tests for candidate identity and exact Codex probes**

Append tests that require:

```python
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

    assert calls == [
        ["docker", "run", "--rm", "--entrypoint", "codex", "candidate", "--version"]
    ]


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
```

Add the container execution test:

```python
def test_verify_container_codex_version_uses_exact_container_command() -> None:
    from ductor_bot.infra.docker_image import verify_container_codex_version

    calls: list[list[str]] = []

    def runner(args: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="codex-cli 0.144.6\n", stderr="")

    verify_container_codex_version("ductor-sandbox", "0.144.6", runner=runner)

    assert calls == [["docker", "exec", "ductor-sandbox", "codex", "--version"]]
```

- [ ] **Step 2: Run the focused tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_image.py -q
```

Expected: imports fail for the new candidate and Docker primitives.

- [ ] **Step 3: Implement candidate references and immutable image IDs**

Add:

```python
import secrets

TimedCommandRunner = Callable[[list[str], float], subprocess.CompletedProcess[str]]
TokenFactory = Callable[[], str]
_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


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


def inspect_image_id(image: str, *, runner: CommandRunner = _run) -> str | None:
    result = runner(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if _IMAGE_ID_PATTERN.fullmatch(value) is None:
        raise RuntimeError("Docker image inspect returned an invalid immutable ID")
    return value
```

The `None` result is only used as “not inspectable”; callers report the safe
stage and exit code without forwarding Docker diagnostics.

- [ ] **Step 4: Implement safe exact Codex version probes**

Add a private boundary-aware expected-version matcher and two probes:

```python
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
```

Add one-command tag wrappers:

```python
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
```

Add runner tests:

```python
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
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_image.py -q
```

Expected: all provider, candidate, immutable-ID, and Codex probe tests pass.

- [ ] **Step 6: Commit**

```bash
git add ductor_bot/infra/docker_image.py tests/infra/test_docker_image.py
git commit -m "feat(docker): add candidate image verification"
```

---

### Task 4: Build and Verify Candidate Before Any Runtime Mutation

**Files:**

- Create: `ductor_bot/infra/docker_rebuild.py`
- Create: `tests/infra/test_docker_rebuild.py`

**Interfaces:**

- Consumes:
  - `DockerManager._build_image(image, versions)`
  - `resolve_provider_cli_versions()`
  - `candidate_image_ref()`
  - `inspect_image_id()`
  - `verify_image_codex_version()`
  - `remove_image_tag()`
- Produces:
  - `CandidateImage(ref: str, image_id: str, versions: ProviderCliVersions)`
  - `build_verified_candidate(config: DockerConfig, paths: DuctorPaths) -> CandidateImage`

- [ ] **Step 1: Write the actual-break RED test**

Create `tests/infra/test_docker_rebuild.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ductor_bot.config import DockerConfig
from ductor_bot.infra.docker_image import ProviderCliVersions
from ductor_bot.workspace.paths import DuctorPaths


@pytest.fixture
def rebuild_paths(tmp_path: Path) -> DuctorPaths:
    home = tmp_path / ".ductor"
    home.mkdir()
    framework = tmp_path / "framework"
    framework.mkdir()
    (framework / "Dockerfile.sandbox").write_text(
        "FROM node:22\n# -- Ductor configured extras insertion point --\n"
    )
    return DuctorPaths(
        ductor_home=home,
        home_defaults=framework / "workspace",
        framework_root=framework,
    )


async def test_candidate_verification_failure_has_no_runtime_or_tag_mutation(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import build_verified_candidate

    versions = ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    stop_runtime = Mock()
    tag_production = Mock()
    remove_containers = Mock()

    with (
        patch(
            "ductor_bot.infra.docker_rebuild.resolve_provider_cli_versions",
            return_value=versions,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.candidate_image_ref",
            return_value="ductor-sandbox:ductor-candidate-test",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.DockerManager._build_image",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            return_value=f"sha256:{'b' * 64}",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.verify_image_codex_version",
            side_effect=RuntimeError("candidate Codex version mismatch"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_image_tag") as cleanup,
        pytest.raises(RuntimeError, match="candidate Codex version mismatch"),
    ):
        await build_verified_candidate(
            DockerConfig(enabled=True),
            rebuild_paths,
        )

    stop_runtime.assert_not_called()
    tag_production.assert_not_called()
    remove_containers.assert_not_called()
    cleanup.assert_called_once_with("ductor-sandbox:ductor-candidate-test")
```

The three unused mocks document the mutation boundary explicitly: the candidate
builder has no runtime, production-tag, or container dependency.

- [ ] **Step 2: Run the test and observe RED**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_rebuild.py::test_candidate_verification_failure_has_no_runtime_or_tag_mutation \
  -q
```

Expected: collection fails because `docker_rebuild.py` does not exist.

- [ ] **Step 3: Implement candidate preparation**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass

from ductor_bot.config import DockerConfig
from ductor_bot.infra.docker import DockerManager
from ductor_bot.infra.docker_image import (
    ProviderCliVersions,
    candidate_image_ref,
    inspect_image_id,
    remove_image_tag,
    resolve_provider_cli_versions,
    verify_image_codex_version,
)
from ductor_bot.workspace.paths import DuctorPaths


@dataclass(frozen=True, slots=True)
class CandidateImage:
    ref: str
    image_id: str
    versions: ProviderCliVersions


async def build_verified_candidate(
    config: DockerConfig,
    paths: DuctorPaths,
) -> CandidateImage:
    versions = resolve_provider_cli_versions()
    candidate_ref = candidate_image_ref(config.image_name)
    manager = DockerManager(config, paths)
    try:
        if not await manager._build_image(candidate_ref, versions):
            raise RuntimeError("Docker candidate build failed")
        image_id = inspect_image_id(candidate_ref)
        if image_id is None:
            raise RuntimeError("Docker candidate image cannot be inspected")
        verify_image_codex_version(candidate_ref, versions.codex)
    except Exception:
        try:
            remove_image_tag(candidate_ref)
        except RuntimeError:
            pass
        raise
    return CandidateImage(candidate_ref, image_id, versions)
```

Do not accept runtime callbacks in this function. That type boundary is what
prevents accidental pre-verification mutation.

- [ ] **Step 4: Add the candidate success-order test**

```python
async def test_build_verified_candidate_orders_resolve_build_inspect_verify(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import build_verified_candidate

    events: list[str] = []
    image_id = f"sha256:{'b' * 64}"
    versions = ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    with (
        patch(
            "ductor_bot.infra.docker_rebuild.resolve_provider_cli_versions",
            side_effect=lambda: events.append("resolve") or versions,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.candidate_image_ref",
            return_value="ductor-sandbox:ductor-candidate-test",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.DockerManager._build_image",
            new=AsyncMock(side_effect=lambda *_: events.append("build") or True),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            side_effect=lambda *_: events.append("inspect") or image_id,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.verify_image_codex_version",
            side_effect=lambda *_: events.append("verify"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_image_tag") as cleanup,
    ):
        candidate = await build_verified_candidate(
            DockerConfig(enabled=True),
            rebuild_paths,
        )

    assert events == ["resolve", "build", "inspect", "verify"]
    assert candidate.ref == "ductor-sandbox:ductor-candidate-test"
    assert candidate.image_id == image_id
    assert candidate.versions.codex == "0.144.6"
    cleanup.assert_not_called()
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_rebuild.py -q
```

Expected: candidate success and failure-boundary tests pass.

- [ ] **Step 6: Commit**

```bash
git add ductor_bot/infra/docker_rebuild.py tests/infra/test_docker_rebuild.py
git commit -m "feat(docker): build verified candidate before cutover"
```

---

### Task 5: Promote the Candidate to Every Shared-Image Container

**Files:**

- Modify: `ductor_bot/infra/docker_image.py`
- Modify: `ductor_bot/infra/docker_rebuild.py`
- Modify: `tests/infra/test_docker_image.py`
- Modify: `tests/infra/test_docker_rebuild.py`

**Interfaces:**

- Consumes: `CandidateImage`
- Produces:
  - `DockerContainerRef(id: str, name: str, image_id: str)`
  - `DockerContainerState(image_id: str, running: bool)`
  - `list_direct_image_containers(image_id: str) -> list[DockerContainerRef]`
  - `remove_containers(containers: list[DockerContainerRef]) -> None`
  - `inspect_container_state(name: str) -> DockerContainerState | None`
  - `wait_for_container_images(names, expected_image_id) -> None`
  - `configured_container_names(paths, main_docker) -> tuple[str, ...]`
  - `RebuildOutcome(old_image_id, candidate_ref, candidate_image_id, codex_version)`
  - `rebuild_docker_image(...callbacks...) -> RebuildOutcome`

- [ ] **Step 1: Write RED tests for exact shared-image consumers**

In `tests/infra/test_docker_image.py`, add:

```python
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
```

Add the container-state test:

```python
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
```

- [ ] **Step 2: Write RED tests for configured container names**

Write an `agents.json` whose relevant sub-agents explicitly select the shared
image and unique container names:

```python
def test_configured_container_names_selects_enabled_shared_image_agents(
    rebuild_paths: DuctorPaths,
) -> None:
    import json

    from ductor_bot.infra.docker_rebuild import configured_container_names

    agents = [
        {
            "name": "serveradmin",
            "docker": {
                "enabled": True,
                "image_name": "ductor-sandbox",
                "container_name": "ductor-sub-serveradmin",
            },
        },
        {
            "name": "botbuilder",
            "docker": {
                "enabled": True,
                "image_name": "ductor-sandbox",
                "container_name": "ductor-sub-botbuilder",
            },
        },
        {
            "name": "other",
            "docker": {
                "enabled": True,
                "image_name": "other-image",
                "container_name": "other-container",
            },
        },
    ]
    (rebuild_paths.ductor_home / "agents.json").write_text(json.dumps(agents))
    main_docker = DockerConfig(
        enabled=True,
        image_name="ductor-sandbox",
        container_name="ductor-sandbox",
    )

    assert configured_container_names(rebuild_paths, main_docker) == (
        "ductor-sandbox",
        "ductor-sub-serveradmin",
        "ductor-sub-botbuilder",
    )
```

The helper must instantiate `SubAgentConfig` through `AgentRegistry.load()` and
must never print or return tokens or unrelated agent configuration.

- [ ] **Step 3: Write the promotion-order RED test**

Use a complete event-order test:

```python
async def test_rebuild_promotes_only_after_candidate_and_verifies_shared_containers(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import (
        CandidateImage,
        rebuild_docker_image,
    )

    old_id = f"sha256:{'a' * 64}"
    new_id = f"sha256:{'b' * 64}"
    versions = ProviderCliVersions("2.1.215", "0.144.6", "0.51.0")
    candidate = CandidateImage(
        "ductor-sandbox:ductor-candidate-test",
        new_id,
        versions,
    )
    names = (
        "ductor-sandbox",
        "ductor-sub-serveradmin",
        "ductor-sub-botbuilder",
    )
    events: list[str] = []

    with (
        patch(
            "ductor_bot.infra.docker_rebuild.build_verified_candidate",
            new=AsyncMock(side_effect=lambda *_: events.append("candidate") or candidate),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            side_effect=lambda *_: events.append("inspect-old") or old_id,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.configured_container_names",
            return_value=names,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.tag_image",
            side_effect=lambda *_: events.append("tag-candidate"),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.list_direct_image_containers",
            side_effect=lambda *_: events.append("list-old-consumers") or [],
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.remove_containers",
            side_effect=lambda *_: events.append("remove-old-consumers"),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.wait_for_container_images",
            side_effect=lambda *_: events.append("wait-containers"),
        ) as wait,
        patch(
            "ductor_bot.infra.docker_rebuild.verify_container_codex_version",
            side_effect=lambda *_: events.append("verify-container-codex"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_image_tag") as remove_candidate,
    ):
        outcome = await rebuild_docker_image(
            DockerConfig(enabled=True),
            rebuild_paths,
            runtime_was_running=True,
            stop_runtime=lambda: events.append("stop"),
            start_runtime=lambda: events.append("start"),
        )

    assert events == [
        "candidate",
        "inspect-old",
        "stop",
        "tag-candidate",
        "list-old-consumers",
        "remove-old-consumers",
        "start",
        "wait-containers",
        "verify-container-codex",
    ]
    wait.assert_called_once_with(names, new_id)
    assert outcome.candidate_image_id == new_id
    assert outcome.codex_version == "0.144.6"
    remove_candidate.assert_not_called()
```

Assert the production tag receives the candidate immutable ID, every configured
container is verified against that same ID, and `candidate.ref` remains tagged
after success.

- [ ] **Step 4: Run the focused tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_image.py tests/infra/test_docker_rebuild.py -q
```

Expected: failures for missing container and promotion interfaces.

- [ ] **Step 5: Implement exact container primitives**

Add `import time` and the following definitions to `docker_image.py`:

```python
@dataclass(frozen=True, slots=True)
class DockerContainerRef:
    id: str
    name: str
    image_id: str


@dataclass(frozen=True, slots=True)
class DockerContainerState:
    image_id: str
    running: bool


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
        raise RuntimeError(
            f"Unable to list Docker containers (exit code {listed.returncode})"
        )
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
            raise RuntimeError(
                f"Unable to remove Docker container (exit code {result.returncode})"
            )


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
            state is not None
            and state.running
            and state.image_id == expected_image_id
            for state in states
        ):
            return
        time.sleep(poll_seconds)
    raise RuntimeError("Docker containers did not reach the candidate image")
```

All errors contain only safe operation names and exit codes. Do not include
Docker stdout/stderr or full argument lists.

This internal condition wait is part of the rebuild command. It does not change
the separate rule that the assistant must not poll the background terminal.

- [ ] **Step 6: Implement configured-name resolution**

In `docker_rebuild.py`:

```python
from ductor_bot.multiagent.registry import AgentRegistry


def configured_container_names(
    paths: DuctorPaths,
    main_docker: DockerConfig,
) -> tuple[str, ...]:
    names = [main_docker.container_name]
    registry = AgentRegistry(paths.ductor_home / "agents.json")
    for sub in registry.load():
        docker = sub.docker or main_docker
        if (
            docker.enabled
            and docker.image_name == main_docker.image_name
            and docker.container_name not in names
        ):
            names.append(docker.container_name)
    return tuple(names)
```

- [ ] **Step 7: Implement promotion and bounded recovery**

Add `from collections.abc import Callable` and import these Task 5 primitives from
`docker_image`: `list_direct_image_containers`, `remove_containers`, `tag_image`,
`verify_container_codex_version`, and `wait_for_container_images`. Then add:

```python
@dataclass(frozen=True, slots=True)
class RebuildOutcome:
    old_image_id: str | None
    candidate_ref: str
    candidate_image_id: str
    codex_version: str


async def rebuild_docker_image(
    config: DockerConfig,
    paths: DuctorPaths,
    *,
    runtime_was_running: bool,
    stop_runtime: Callable[[], None],
    start_runtime: Callable[[], None],
) -> RebuildOutcome:
    candidate = await build_verified_candidate(config, paths)
    old_id = inspect_image_id(config.image_name)
    names = configured_container_names(paths, config)
    stopped = False
    promoted = False
    start_attempted = False
    try:
        stop_runtime()
        stopped = True
        tag_image(candidate.image_id, config.image_name)
        promoted = True
        if old_id is not None:
            remove_containers(list_direct_image_containers(old_id))
        if runtime_was_running:
            start_attempted = True
            start_runtime()
            wait_for_container_images(names, candidate.image_id)
            verify_container_codex_version(names[0], candidate.versions.codex)
    except Exception:
        if start_attempted:
            try:
                stop_runtime()
            except Exception:
                pass
        if promoted and old_id is not None:
            try:
                remove_containers(list_direct_image_containers(candidate.image_id))
                tag_image(old_id, config.image_name)
            except Exception:
                pass
        if (
            stopped
            and runtime_was_running
            and (not promoted or old_id is not None)
        ):
            try:
                start_runtime()
            except Exception:
                pass
        raise
    return RebuildOutcome(
        old_image_id=old_id,
        candidate_ref=candidate.ref,
        candidate_image_id=candidate.image_id,
        codex_version=candidate.versions.codex,
    )
```

Do not remove `candidate.ref` after success; it is needed for user-controlled
post-rebuild acceptance.

- [ ] **Step 8: Add recovery tests**

Add the cutover recovery test:

```python
async def test_runtime_verification_failure_restores_old_image_once(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_image import DockerContainerRef
    from ductor_bot.infra.docker_rebuild import CandidateImage, rebuild_docker_image

    old_id = f"sha256:{'a' * 64}"
    new_id = f"sha256:{'b' * 64}"
    candidate = CandidateImage(
        "ductor-sandbox:ductor-candidate-test",
        new_id,
        ProviderCliVersions("2.1.215", "0.144.6", "0.51.0"),
    )
    stop_runtime = Mock()
    start_runtime = Mock()
    candidate_container = DockerContainerRef("new-c1", "ductor-sandbox", new_id)

    def containers(image_id: str) -> list[DockerContainerRef]:
        return [] if image_id == old_id else [candidate_container]

    with (
        patch(
            "ductor_bot.infra.docker_rebuild.build_verified_candidate",
            new=AsyncMock(return_value=candidate),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            return_value=old_id,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.configured_container_names",
            return_value=("ductor-sandbox",),
        ),
        patch("ductor_bot.infra.docker_rebuild.tag_image") as tag,
        patch(
            "ductor_bot.infra.docker_rebuild.list_direct_image_containers",
            side_effect=containers,
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_containers") as remove,
        patch(
            "ductor_bot.infra.docker_rebuild.wait_for_container_images",
            side_effect=RuntimeError("containers did not reach candidate"),
        ),
        pytest.raises(RuntimeError, match="containers did not reach candidate"),
    ):
        await rebuild_docker_image(
            DockerConfig(enabled=True),
            rebuild_paths,
            runtime_was_running=True,
            stop_runtime=stop_runtime,
            start_runtime=start_runtime,
        )

    assert tag.call_args_list == [
        ((new_id, "ductor-sandbox"),),
        ((old_id, "ductor-sandbox"),),
    ]
    assert stop_runtime.call_count == 2
    assert start_runtime.call_count == 2
    remove.assert_any_call([candidate_container])
```

Add the pre-promotion tag failure test:

```python
async def test_promotion_tag_failure_does_not_remove_containers(
    rebuild_paths: DuctorPaths,
) -> None:
    from ductor_bot.infra.docker_rebuild import CandidateImage, rebuild_docker_image

    candidate = CandidateImage(
        "ductor-sandbox:ductor-candidate-test",
        f"sha256:{'b' * 64}",
        ProviderCliVersions("2.1.215", "0.144.6", "0.51.0"),
    )
    remove = Mock()
    start_runtime = Mock()
    with (
        patch(
            "ductor_bot.infra.docker_rebuild.build_verified_candidate",
            new=AsyncMock(return_value=candidate),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.inspect_image_id",
            return_value=f"sha256:{'a' * 64}",
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.configured_container_names",
            return_value=("ductor-sandbox",),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.tag_image",
            side_effect=RuntimeError("Docker tag failed (exit code 9)"),
        ),
        patch("ductor_bot.infra.docker_rebuild.remove_containers", remove),
        pytest.raises(RuntimeError, match="Docker tag failed"),
    ):
        await rebuild_docker_image(
            DockerConfig(enabled=True),
            rebuild_paths,
            runtime_was_running=True,
            stop_runtime=Mock(),
            start_runtime=start_runtime,
        )

    remove.assert_not_called()
    start_runtime.assert_called_once_with()
```

- [ ] **Step 9: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_image.py tests/infra/test_docker_rebuild.py -q
```

Expected: all exact-ID, configured-name, promotion, and bounded recovery tests
pass.

- [ ] **Step 10: Commit**

```bash
git add ductor_bot/infra/docker_image.py ductor_bot/infra/docker_rebuild.py \
  tests/infra/test_docker_image.py tests/infra/test_docker_rebuild.py
git commit -m "feat(docker): promote candidate to shared containers"
```

---

### Task 6: Wire `ductor docker rebuild` with Nonzero Safe Failures

**Files:**

- Modify: `ductor_bot/cli_commands/docker.py:1-180`
- Create: `tests/cli/test_docker_rebuild_command.py`
- Modify: `ductor_bot/i18n/en/cli.toml:79-90` only if existing text says the
  command merely deletes the image.

**Interfaces:**

- Consumes: `rebuild_docker_image()`, `RebuildOutcome`
- Produces:
  - `_runtime_is_running() -> bool`
  - `_stop_runtime_for_rebuild() -> None`
  - `_start_runtime_for_rebuild() -> None`
  - `docker_rebuild() -> None`, raising `SystemExit(1)` on any failed stage.

- [ ] **Step 1: Write the CLI RED test for the original destructive breakpoint**

Create:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ductor_bot.infra.docker_rebuild import RebuildOutcome


def _docker_data() -> dict[str, object]:
    return {
        "docker": {
            "enabled": True,
            "image_name": "ductor-sandbox",
            "container_name": "ductor-sandbox",
            "extras": ["playwright"],
        }
    }


def test_docker_rebuild_candidate_failure_does_not_stop_or_remove_runtime() -> None:
    from ductor_bot.cli_commands.docker import docker_rebuild

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(None, _docker_data()),
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.rebuild_docker_image",
            new=AsyncMock(side_effect=RuntimeError("candidate verification failed")),
        ),
        patch("ductor_bot.cli_commands.lifecycle.stop_bot") as stop_bot,
        patch("ductor_bot.cli_commands.docker.subprocess.run") as raw_docker,
        pytest.raises(SystemExit) as exc_info,
    ):
        docker_rebuild()

    assert exc_info.value.code == 1
    stop_bot.assert_not_called()
    raw_docker.assert_not_called()
```

This is the explicit regression for the baseline behavior.

- [ ] **Step 2: Run the test and observe RED**

Run:

```bash
.venv/bin/pytest \
  tests/cli/test_docker_rebuild_command.py::test_docker_rebuild_candidate_failure_does_not_stop_or_remove_runtime \
  -q
```

Expected: failure because the baseline command calls `stop_bot()` and raw
`docker rm/rmi` before any candidate exists.

- [ ] **Step 3: Implement runtime callbacks**

Add helpers without service logs or environment inspection:

```python
def _runtime_is_running() -> bool:
    from ductor_bot.infra.service import is_service_installed, is_service_running

    if is_service_installed() and is_service_running():
        return True
    pid_file = resolve_paths().ductor_home / "bot.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    from ductor_bot.infra.pidlock import _is_process_alive

    return _is_process_alive(pid)


def _stop_runtime_for_rebuild() -> None:
    from ductor_bot.cli_commands.lifecycle import stop_bot

    stop_bot()


def _start_runtime_for_rebuild() -> None:
    from ductor_bot.infra.service import is_service_installed, start_service

    if is_service_installed():
        start_service(_console)
        return
    subprocess.Popen(
        [sys.executable, "-m", "ductor_bot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
```

Add these module imports:

```python
import asyncio
import sys

from ductor_bot.config import DockerConfig
```

Import `rebuild_docker_image` locally inside `docker_rebuild()` so the RED test
can patch the source boundary before the baseline CLI is wired.

- [ ] **Step 4: Replace the destructive command**

Implement:

```python
def docker_rebuild() -> None:
    from ductor_bot.infra.docker_rebuild import rebuild_docker_image

    if not shutil.which("docker"):
        _console.print("[bold red]Docker not found.[/bold red]")
        raise SystemExit(1)
    result = docker_read_config()
    if result is None:
        raise SystemExit(1)
    _, data = result
    raw = data.get("docker")
    if not isinstance(raw, dict):
        _console.print("[bold red]Invalid Docker configuration.[/bold red]")
        raise SystemExit(1)
    try:
        config = DockerConfig.model_validate(raw)
    except ValueError:
        _console.print("[bold red]Invalid Docker configuration.[/bold red]")
        raise SystemExit(1) from None
    if not config.enabled:
        _console.print("[bold red]Docker sandboxing is not enabled.[/bold red]")
        raise SystemExit(1)

    was_running = _runtime_is_running()
    try:
        outcome = asyncio.run(
            rebuild_docker_image(
                config,
                resolve_paths(),
                runtime_was_running=was_running,
                stop_runtime=_stop_runtime_for_rebuild,
                start_runtime=_start_runtime_for_rebuild,
            )
        )
    except Exception as exc:
        _console.print(f"[bold red]Docker rebuild failed:[/bold red] {exc}")
        raise SystemExit(1) from None

    _console.print(t_rich("docker.rebuild.done"))
    _console.print(
        "[dim]"
        f"candidate={outcome.candidate_ref} "
        f"image={outcome.candidate_image_id} "
        f"codex={outcome.codex_version}"
        "[/dim]"
    )
```

The three summary fields are the only rebuild values needed for later
acceptance. They are controlled candidate/version/image values and contain no
subprocess diagnostics.

- [ ] **Step 5: Add CLI safety and success tests**

Add a success test:

```python
def test_docker_rebuild_prints_only_safe_acceptance_summary() -> None:
    from pathlib import Path

    from ductor_bot.cli_commands.docker import docker_rebuild

    image_id = f"sha256:{'b' * 64}"
    outcome = RebuildOutcome(
        old_image_id=f"sha256:{'a' * 64}",
        candidate_ref="ductor-sandbox:ductor-candidate-test",
        candidate_image_id=image_id,
        codex_version="0.144.6",
    )
    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(Path("/tmp/config.json"), _docker_data()),
        ),
        patch(
            "ductor_bot.cli_commands.docker._runtime_is_running",
            return_value=True,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.rebuild_docker_image",
            new=AsyncMock(return_value=outcome),
        ),
        patch("ductor_bot.cli_commands.docker._console.print") as printer,
        patch("ductor_bot.cli_commands.docker.subprocess.run") as raw_docker,
    ):
        docker_rebuild()

    rendered = "\n".join(str(call.args[0]) for call in printer.call_args_list)
    assert "candidate=ductor-sandbox:ductor-candidate-test" in rendered
    assert f"image={image_id}" in rendered
    assert "codex=0.144.6" in rendered
    raw_docker.assert_not_called()
```

Add invalid and failed-stage tests:

```python
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"docker": "invalid"},
        {"docker": {"enabled": False}},
    ],
)
def test_docker_rebuild_invalid_or_disabled_config_exits_one(
    data: dict[str, object],
) -> None:
    from pathlib import Path

    from ductor_bot.cli_commands.docker import docker_rebuild

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(Path("/tmp/config.json"), data),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        docker_rebuild()

    assert exc_info.value.code == 1


def test_docker_rebuild_failed_stage_exits_one_without_success_summary() -> None:
    from pathlib import Path

    from ductor_bot.cli_commands.docker import docker_rebuild

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch(
            "ductor_bot.cli_commands.docker.docker_read_config",
            return_value=(Path("/tmp/config.json"), _docker_data()),
        ),
        patch(
            "ductor_bot.cli_commands.docker._runtime_is_running",
            return_value=True,
        ),
        patch(
            "ductor_bot.infra.docker_rebuild.rebuild_docker_image",
            new=AsyncMock(side_effect=RuntimeError("Docker candidate build failed")),
        ),
        patch("ductor_bot.cli_commands.docker._console.print") as printer,
        pytest.raises(SystemExit) as exc_info,
    ):
        docker_rebuild()

    assert exc_info.value.code == 1
    rendered = "\n".join(str(call.args[0]) for call in printer.call_args_list)
    assert "Docker candidate build failed" in rendered
    assert "candidate=" not in rendered
```

Provider/Docker primitive tests from Tasks 1-5 remain responsible for proving
that raw stdout/stderr and sentinel secrets cannot reach this CLI boundary.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/cli/test_docker_rebuild_command.py \
  tests/infra/test_docker_image.py tests/infra/test_docker_rebuild.py -q
```

Expected: all command, candidate, promotion, and sanitized-error tests pass.

- [ ] **Step 7: Commit**

```bash
git add ductor_bot/cli_commands/docker.py ductor_bot/i18n/en/cli.toml \
  tests/cli/test_docker_rebuild_command.py
git commit -m "feat(docker): deploy verified provider image"
```

---

### Task 7: Phase-One Quality Gate, Local Reinstall, and Background Rebuild

**Files:**

- No planned source edits. A verification failure returns to the task that owns
  the failing behavior instead of adding an ad hoc Task 7 change.
- Do not create phase-two tool changes.

**Interfaces:**

- Consumes: complete phase-one implementation.
- Produces: a locally installed fork ready for the user-controlled formal
  rebuild and the safe summary values needed for acceptance.

- [ ] **Step 1: Run all focused Docker tests**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_image.py \
  tests/infra/test_docker_rebuild.py \
  tests/infra/test_docker.py \
  tests/infra/test_docker_extras.py \
  tests/cli/test_docker_rebuild_command.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run formatting, lint, and type checks**

Run:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy ductor_bot
```

Expected: all three commands exit 0. If formatting changes are required, run
`.venv/bin/ruff format` only on modified files, re-run the checks, and commit the
format-only correction separately.

- [ ] **Step 3: Run the complete test suite and compare with the recorded baseline**

Run:

```bash
.venv/bin/pytest
```

Expected: Docker-related tests pass. The recorded clean-baseline result was
`3786 passed, 14 failed`, with all 14 failures in
`tests/workspace/test_init.py` due to provider-auth-dependent rule selection.
Do not claim the complete suite passes unless the fresh result is actually zero
failures. Do not modify unrelated workspace tests as part of this feature.

- [ ] **Step 4: Verify commit and diff scope**

Run:

```bash
git status --short
git log --oneline 08ecc315..HEAD
git diff --check 08ecc315..HEAD
git diff --stat 08ecc315..HEAD
```

Expected: only the design, plan, provider rebuild implementation, and related
tests/docs are present; each independent task has its own commit.

- [ ] **Step 5: Reinstall the local fork**

Run:

```bash
uv tool install --force \
  --from /home/zqxu/ductor/.worktrees/docker-image-refresh-v2 ductor
```

Expected: `ductor` is installed from the v2 worktree. Verify only the package
source/version path needed to establish that fact; do not print environment
variables or credentials.

- [ ] **Step 6: Launch the phase-one formal rebuild and pause**

Start this command in a background terminal:

```bash
ductor docker rebuild
```

Immediately tell the user that the background rebuild has started. Do not poll
the terminal, do not inspect Docker state, and do not read the complete build
output. End the turn and wait for the user to report that the terminal has
finished.

- [ ] **Step 7: After the user reports completion, perform only the three acceptances**

Use the safe summary `candidate`, `image`, and `codex` values emitted by the
command:

1. Run the candidate directly and require its Codex version to equal the emitted
   npm-resolved `codex` value.
2. Require `ductor-sandbox`, `ductor-sub-serveradmin`, and
   `ductor-sub-botbuilder` to be running on the emitted immutable `image` ID;
   spot-check container Codex against the same version.
3. Start a new Codex session using `gpt-5.6-sol`, suppress provider
   stdout/stderr, and report only success/failure.

Do not inspect service logs, environment variables, mounts, credentials, full
argv, prompts, or raw subprocess diagnostics.

- [ ] **Step 8: Stop at the phase boundary**

Report phase-one acceptance. Do not add development/Office/PDF/OCR tools yet.
Only after the user confirms phase one is accepted, use `brainstorming` and
`writing-plans` as applicable to write the separate phase-two implementation
plan from the approved design.
