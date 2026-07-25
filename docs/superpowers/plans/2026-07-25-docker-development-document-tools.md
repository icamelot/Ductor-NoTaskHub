# Docker Development and Document Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved cached development, Office, PDF, and OCR tools to
`ductor-sandbox`, preserve every existing extra and the provider-only cache
boundary, and hand installation to the user through one manual shell script.

**Architecture:** Extend `Dockerfile.sandbox` with fixed cached development and
document layers before the existing extras marker and provider layer. Keep the
accepted candidate-first rebuild implementation unchanged. Increase only the
Docker build timeout floor, then add a repository-local script that reinstalls
the current worktree and runs `ductor docker rebuild` when the user chooses.

**Tech Stack:** Dockerfile frontend 1.7, Docker BuildKit cache mounts, Debian
Bookworm apt, pip, npm, Bash, Python 3.11+, pytest, Ruff, mypy.

## Global Constraints

- Work only in
  `/home/zqxu/ductor/.worktrees/docker-image-refresh-v2` on
  `feat/docker-image-refresh-v2`.
- Do not modify or reuse
  `/home/zqxu/ductor/.worktrees/docker-image-refresh`.
- Old commits are historical evidence only. Do not cherry-pick or assume their
  implementation or tests are correct.
- Phase one is accepted. Do not redesign provider resolution, candidate
  verification, promotion, shared-container deployment, or recovery.
- Keep the layer order: base, development tools, document tools, configured
  extras, provider CLIs, final metadata.
- Preserve normal BuildKit caching. Do not add global `--no-cache`.
- Preserve every current `DOCKER_EXTRAS` entry.
- Playwright remains a Python-only extra.
- Do not install Chromium, Chrome, or another browser binary.
- Do not run `playwright install`.
- Do not add `/ms-playwright`, browser profiles, browser cache initialization,
  or browser profile/cache mounts.
- Do not print credentials, environment variables, prompts, complete subprocess
  arguments, or captured subprocess stdout/stderr.
- Follow strict TDD for every behavior: observe RED, make the minimal change,
  observe GREEN.
- Commit every independent task separately.
- Do not execute `scripts/install-docker-tools.sh`, `uv tool install`,
  `ductor docker rebuild`, or Docker acceptance commands. The user will run the
  installation script manually after code verification.
- Full-suite comparison baseline is `3817 passed, 14 failed`; all 14 known
  failures are in `tests/workspace/test_init.py` and depend on local provider
  authentication.

## File Structure

- Modify `Dockerfile.sandbox`: add the Dockerfile frontend declaration and
  cached development/document layers before the existing extras marker.
- Modify `ductor_bot/infra/docker_extras.py`: add a 2400-second minimum Docker
  build timeout without changing the extras registry or renderer.
- Modify `tests/infra/test_docker_extras.py`: prove the timeout floor and larger
  dynamic timeout behavior.
- Create `tests/infra/test_docker_tools.py`: define the exact Dockerfile tool,
  cache-order, extras-preservation, browser-exclusion, and manual-script
  contracts.
- Create `scripts/install-docker-tools.sh`: user-controlled local reinstall and
  rebuild entrypoint.

---

### Task 1: Give Full Tool Builds a Bounded Timeout Floor

**Files:**

- Modify: `ductor_bot/infra/docker_extras.py:205-215`
- Modify: `tests/infra/test_docker_extras.py:227-245,470-500`

**Interfaces:**

- Consumes:
  - `DockerExtra.build_timeout_extra: int`
  - `calculate_build_timeout(extras: list[DockerExtra], base: int = 300) -> int`
- Produces:
  - `_MIN_BUILD_TIMEOUT_SECONDS = 2400`
  - `calculate_build_timeout()` returning
    `max(2400, base + sum(extra.build_timeout_extra))`

- [ ] **Step 1: Change timeout tests to the approved floor**

Replace `TestBuildTimeout` in `tests/infra/test_docker_extras.py` with:

```python
class TestBuildTimeout:
    def test_base_only_uses_full_tool_build_floor(self) -> None:
        assert calculate_build_timeout([]) == 2400

    def test_custom_base_below_floor_uses_floor(self) -> None:
        assert calculate_build_timeout([], base=100) == 2400

    def test_with_normal_extras_uses_floor(self) -> None:
        extras = resolve_extras(["whisper"])

        assert calculate_build_timeout(extras) == 2400

    def test_large_dynamic_timeout_can_exceed_floor(self) -> None:
        extras = [
            DockerExtra(
                id="slow",
                name="Slow",
                description="Slow test package",
                category="ML Frameworks",
                size_estimate="test-only",
                build_timeout_extra=2500,
            )
        ]

        assert calculate_build_timeout(extras) == 2800
```

In
`TestDockerManagerExtras.test_build_timeout_scales_with_extras`, replace the
final assertion with:

```python
assert captured_timeout == 2400
```

- [ ] **Step 2: Run the focused timeout tests and observe RED**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_extras.py::TestBuildTimeout \
  tests/infra/test_docker_extras.py::TestDockerManagerExtras::test_build_timeout_scales_with_extras \
  -q
```

Expected: the floor assertions fail because the current implementation returns
300, 100, 420, and 480 seconds.

- [ ] **Step 3: Implement the minimum timeout**

Replace the current timeout function in
`ductor_bot/infra/docker_extras.py` with:

```python
_MIN_BUILD_TIMEOUT_SECONDS = 2400


def calculate_build_timeout(extras: list[DockerExtra], base: int = 300) -> int:
    """Return a bounded Docker build timeout in seconds."""
    calculated = base + sum(extra.build_timeout_extra for extra in extras)
    return max(_MIN_BUILD_TIMEOUT_SECONDS, calculated)
```

Do not change any `DockerExtra`, `DOCKER_EXTRAS`, dependency, package, or
Dockerfile-rendering definition in this task.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_extras.py::TestBuildTimeout \
  tests/infra/test_docker_extras.py::TestDockerManagerExtras::test_build_timeout_scales_with_extras \
  -q
.venv/bin/ruff check \
  ductor_bot/infra/docker_extras.py tests/infra/test_docker_extras.py
```

Expected: five focused tests pass and Ruff exits 0.

- [ ] **Step 5: Commit**

```bash
git add ductor_bot/infra/docker_extras.py tests/infra/test_docker_extras.py
git commit -m "fix(docker): allow full tool image builds"
```

---

### Task 2: Add Cached Development Tool Layers

**Files:**

- Modify: `Dockerfile.sandbox:1-45`
- Create: `tests/infra/test_docker_tools.py`

**Interfaces:**

- Consumes:
  - existing `Dockerfile.sandbox`
  - existing marker
    `# -- Ductor configured extras insertion point --`
- Produces:
  - marker `# -- Ductor development tools --`
  - Dockerfile frontend `docker/dockerfile:1.7`
  - cached apt, pip, and npm development layers

- [ ] **Step 1: Write the development-tool Dockerfile contract**

Create `tests/infra/test_docker_tools.py` with:

```python
from __future__ import annotations

import re
from pathlib import Path

from ductor_bot.infra.docker_extras import DOCKER_EXTRAS_MARKER

_REPO_ROOT = Path(__file__).parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile.sandbox"
_DEVELOPMENT_MARKER = "# -- Ductor development tools --"


def _dockerfile() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _section(content: str, start: str, end: str) -> str:
    return content.split(start, 1)[1].split(end, 1)[0]


def test_dockerfile_declares_buildkit_frontend_and_development_layer() -> None:
    content = _dockerfile()

    assert content.startswith("# syntax=docker/dockerfile:1.7\n")
    assert content.count(_DEVELOPMENT_MARKER) == 1
    assert content.index(_DEVELOPMENT_MARKER) < content.index(DOCKER_EXTRAS_MARKER)
    assert content.index(DOCKER_EXTRAS_MARKER) < content.index(
        "ARG CLAUDE_CLI_VERSION"
    )


def test_development_layer_contains_exact_approved_tools_and_caches() -> None:
    content = _dockerfile()
    section = _section(content, _DEVELOPMENT_MARKER, DOCKER_EXTRAS_MARKER)
    apt_packages = {
        "wget",
        "jq",
        "rsync",
        "tree",
        "vim",
        "unzip",
        "p7zip-full",
        "file",
        "bat",
        "fd-find",
        "git-lfs",
        "less",
        "pipx",
        "ripgrep",
        "shellcheck",
        "shfmt",
        "sqlite3",
        "gh",
    }

    for package in apt_packages:
        assert re.search(rf"(?<![A-Za-z0-9_.+-]){re.escape(package)}(?![A-Za-z0-9_.+-])", section)

    assert "--mount=type=cache,target=/var/cache/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/var/lib/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/root/.cache/pip" in section
    assert "--mount=type=cache,target=/root/.npm" in section
    assert "python3 -m pip install uv ruff" in section
    assert "npm install -g pnpm yarn" in section
    assert "ln -sf /usr/bin/batcat /usr/local/bin/bat" in section
    assert "ln -sf /usr/bin/fdfind /usr/local/bin/fd" in section
```

- [ ] **Step 2: Run the new tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_tools.py -q
```

Expected: both tests fail because the frontend declaration, development marker,
and tools do not exist.

- [ ] **Step 3: Declare the Dockerfile frontend**

Insert this as the first line of `Dockerfile.sandbox`, followed by a blank line:

```dockerfile
# syntax=docker/dockerfile:1.7
```

- [ ] **Step 4: Add the development layers**

Insert the following after the existing externally-managed guard and before the
extras marker:

```dockerfile
# -- Ductor development tools --

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
       bat fd-find file gh git-lfs jq less p7zip-full pipx ripgrep rsync \
       shellcheck shfmt sqlite3 tree unzip vim wget \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install uv ruff

RUN --mount=type=cache,target=/root/.npm \
    npm install -g pnpm yarn
```

Do not add a third-party apt repository for `gh`. Do not move or change the
extras marker or provider block.

- [ ] **Step 5: Verify GREEN and provider ordering**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_tools.py \
  tests/infra/test_docker_image.py::test_sandbox_dockerfile_installs_exact_provider_build_arguments \
  tests/infra/test_docker_extras.py::TestGenerateDockerfile::test_extras_are_inserted_before_provider_layer \
  -q
.venv/bin/ruff check tests/infra/test_docker_tools.py
! rg -n -- '--no-cache([[:space:]]|$)' Dockerfile.sandbox
```

Expected: four tests pass, Ruff exits 0, and no global Docker `--no-cache`
argument exists.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile.sandbox tests/infra/test_docker_tools.py
git commit -m "feat(docker): add cached development tools"
```

---

### Task 3: Add Cached Office, PDF, OCR, and Document Libraries

**Files:**

- Modify: `Dockerfile.sandbox:40-85`
- Modify: `tests/infra/test_docker_tools.py`

**Interfaces:**

- Consumes:
  - `# -- Ductor development tools --`
  - `DOCKER_EXTRAS_MARKER`
  - current `DOCKER_EXTRAS_BY_ID`
- Produces:
  - marker `# -- Ductor document tools --`
  - cached Office/PDF/OCR apt layer
  - cached Python document-library layer

- [ ] **Step 1: Add RED tests for the document contract**

Add this import to `tests/infra/test_docker_tools.py`:

```python
from ductor_bot.infra.docker_extras import (
    DOCKER_EXTRAS_BY_ID,
    DOCKER_EXTRAS_MARKER,
)
```

Replace the single-line `DOCKER_EXTRAS_MARKER` import. Add:

```python
_DOCUMENT_MARKER = "# -- Ductor document tools --"
```

Append:

```python
def test_document_layer_contains_approved_office_pdf_ocr_tools() -> None:
    content = _dockerfile()
    section = _section(content, _DOCUMENT_MARKER, DOCKER_EXTRAS_MARKER)
    apt_packages = {
        "libreoffice-writer",
        "libreoffice-calc",
        "libreoffice-impress",
        "poppler-utils",
        "qpdf",
        "ghostscript",
        "imagemagick",
        "libimage-exiftool-perl",
        "fonts-noto-cjk",
        "tesseract-ocr",
        "tesseract-ocr-eng",
        "tesseract-ocr-chi-sim",
        "tesseract-ocr-chi-tra",
    }

    for package in apt_packages:
        assert re.search(rf"(?<![A-Za-z0-9_.+-]){re.escape(package)}(?![A-Za-z0-9_.+-])", section)

    assert "--mount=type=cache,target=/var/cache/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/var/lib/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/root/.cache/pip" in section
    assert "python3 -m pip install python-docx openpyxl python-pptx pypdf" in section
    assert "fonts-liberation" in content
    assert "fonts-noto-color-emoji" in content


def test_document_and_provider_layers_keep_cache_order() -> None:
    content = _dockerfile()

    assert content.index(_DEVELOPMENT_MARKER) < content.index(_DOCUMENT_MARKER)
    assert content.index(_DOCUMENT_MARKER) < content.index(DOCKER_EXTRAS_MARKER)
    assert content.index(DOCKER_EXTRAS_MARKER) < content.index(
        "ARG CLAUDE_CLI_VERSION"
    )


def test_playwright_extra_stays_python_only() -> None:
    playwright = DOCKER_EXTRAS_BY_ID["playwright"]

    assert playwright.pip_packages == ["playwright"]
    assert playwright.apt_packages == []


def test_dockerfile_has_no_browser_installation_or_profile_instructions() -> None:
    content = _dockerfile()
    instructions = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("#")
    ).lower()

    assert re.search(r"\b(chromium|chromium-browser|google-chrome)\b", instructions) is None
    assert "playwright install" not in instructions
    assert "/ms-playwright" not in instructions
    assert ".cache/ms-playwright" not in instructions
    assert ".config/chrom" not in instructions
```

- [ ] **Step 2: Run the document tests and observe RED**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_tools.py::test_document_layer_contains_approved_office_pdf_ocr_tools \
  tests/infra/test_docker_tools.py::test_document_and_provider_layers_keep_cache_order \
  -q
```

Expected: both tests fail because the document marker and packages do not
exist.

- [ ] **Step 3: Add the document-system layer**

Insert after the Node development layer and before the extras marker:

```dockerfile
# -- Ductor document tools --

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends \
       fonts-noto-cjk ghostscript imagemagick libimage-exiftool-perl \
       libreoffice-calc libreoffice-impress libreoffice-writer \
       poppler-utils qpdf tesseract-ocr tesseract-ocr-chi-sim \
       tesseract-ocr-chi-tra tesseract-ocr-eng

RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install python-docx openpyxl python-pptx pypdf
```

The existing base browser-library layer already supplies `fonts-liberation` and
`fonts-noto-color-emoji`; do not duplicate them in this new apt layer.

- [ ] **Step 4: Verify GREEN and all extras/browser boundaries**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_tools.py \
  tests/infra/test_docker_image.py \
  tests/infra/test_docker_extras.py \
  -q
.venv/bin/ruff check tests/infra/test_docker_tools.py
```

Expected: all focused tool, provider, and extras tests pass. The browser
exclusion test passes without rejecting existing comments or shared runtime
libraries.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.sandbox tests/infra/test_docker_tools.py
git commit -m "feat(docker): add office PDF and OCR tools"
```

---

### Task 4: Add the User-Controlled Installation Script

**Files:**

- Create: `scripts/install-docker-tools.sh`
- Modify: `tests/infra/test_docker_tools.py`

**Interfaces:**

- Consumes:
  - repository root containing `pyproject.toml`
  - host commands `uv` and `docker`
  - installed command `ductor docker rebuild`
- Produces:
  - `bash scripts/install-docker-tools.sh`
  - nonzero propagation for missing prerequisites, install failure, or rebuild
    failure

- [ ] **Step 1: Add RED tests for the manual script**

Add imports:

```python
import os
import subprocess
```

Add:

```python
_INSTALL_SCRIPT = _REPO_ROOT / "scripts" / "install-docker-tools.sh"
```

Append:

```python
def test_manual_install_script_has_safe_install_then_rebuild_contract() -> None:
    script = _INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in script
    assert 'command -v uv >/dev/null 2>&1' in script
    assert 'command -v docker >/dev/null 2>&1' in script
    install = 'uv tool install --force --from "$repo_root" ductor'
    rebuild = "exec ductor docker rebuild"
    assert install in script
    assert rebuild in script
    assert script.index(install) < script.index(rebuild)
    assert "up to 40 minutes" in script
    assert "docker tag" not in script
    assert "docker rm" not in script
    assert "docker rmi" not in script
    assert "docker inspect" not in script


def test_manual_install_script_is_executable_and_valid_bash() -> None:
    assert os.access(_INSTALL_SCRIPT, os.X_OK)

    result = subprocess.run(
        ["bash", "-n", str(_INSTALL_SCRIPT)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0
```

- [ ] **Step 2: Run the script tests and observe RED**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_tools.py::test_manual_install_script_has_safe_install_then_rebuild_contract \
  tests/infra/test_docker_tools.py::test_manual_install_script_is_executable_and_valid_bash \
  -q
```

Expected: both tests fail because `scripts/install-docker-tools.sh` does not
exist.

- [ ] **Step 3: Create the manual installation script**

Create `scripts/install-docker-tools.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'Required command not found: uv' >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'Required command not found: docker' >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

printf '%s\n' 'Reinstalling ductor from this worktree...'
uv tool install --force --from "$repo_root" ductor

printf '%s\n' \
  'Starting the verified Docker rebuild.' \
  'Docker subprocess output is intentionally suppressed.' \
  'The first full tool build may remain quiet for up to 40 minutes.'

exec ductor docker rebuild
```

Make it executable:

```bash
chmod +x scripts/install-docker-tools.sh
```

Do not execute the script.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/infra/test_docker_tools.py -q
bash -n scripts/install-docker-tools.sh
.venv/bin/ruff check tests/infra/test_docker_tools.py
git diff --check
```

Expected: all tool/script tests pass, Bash syntax is valid, Ruff exits 0, and
the diff has no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-docker-tools.sh tests/infra/test_docker_tools.py
git commit -m "feat(docker): add manual tool image installer"
```

---

### Task 5: Phase-Two Quality Gate and User Handoff

**Files:**

- No planned source edits.
- If a check fails, return to the task that owns the failing behavior.

**Interfaces:**

- Consumes: Tasks 1-4.
- Produces: a clean, tested branch and the manual command for the user.

- [ ] **Step 1: Run all focused Docker tests**

Run:

```bash
.venv/bin/pytest \
  tests/infra/test_docker_tools.py \
  tests/infra/test_docker_image.py \
  tests/infra/test_docker_rebuild.py \
  tests/infra/test_docker.py \
  tests/infra/test_docker_extras.py \
  tests/cli/test_docker_rebuild_command.py \
  -q
```

Expected: all focused Docker, provider, candidate, extras, tool, and script
tests pass.

- [ ] **Step 2: Run formatting, lint, and type checks**

Run:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy ductor_bot
```

Expected: all three commands exit 0. If Ruff formatting is required, format
only files modified by this phase, rerun focused tests and static checks, and
commit the format-only change separately.

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
.venv/bin/pytest
```

Expected: no Docker-related failure. Compare with the recorded phase-one result
of `3817 passed, 14 failed`, with every known failure in
`tests/workspace/test_init.py`. Added phase-two tests increase the pass count.
Do not claim the full suite passes unless the fresh result has zero failures.
Do not modify unrelated workspace tests.

- [ ] **Step 4: Review scope and commits**

Run:

```bash
git status --short --branch
git log --oneline 565a4e4..HEAD
git diff --check 565a4e4..HEAD
git diff --stat 565a4e4..HEAD
! rg -n '@openai/codex@0\\.144\\.6' Dockerfile.sandbox ductor_bot
! rg -n -- '--no-cache([[:space:]]|$)' Dockerfile.sandbox ductor_bot
```

Expected: the scope contains only the phase-two plan/prompt, timeout floor,
Dockerfile tool layers, tests, and manual script. Production provider versions
remain dynamic and no global `--no-cache` appears.

- [ ] **Step 5: Perform completion review**

Use `superpowers:verification-before-completion`, then
`superpowers:requesting-code-review`. Because the user selected Inline
Execution, do not spawn sub-agents; perform the review in the current session
and resolve every critical or important issue before handoff.

- [ ] **Step 6: Hand the command to the user and stop**

Report the fresh verification results and provide:

```bash
cd /home/zqxu/ductor/.worktrees/docker-image-refresh-v2
bash scripts/install-docker-tools.sh
```

Do not run either command. Do not reinstall the fork. Do not start or poll a
Docker rebuild. Wait for the user to report the script's safe final summary
before providing the already-established three acceptance commands.
