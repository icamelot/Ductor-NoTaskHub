# Docker Development and Document Tools Design

## Goal

Extend the already-verified `ductor-sandbox` image with a fixed set of common
development, Office, PDF, and OCR tools while preserving the candidate-first
provider deployment flow, all configured `docker.extras`, and provider-layer
cache isolation.

Phase one is complete and accepted:

- the candidate Codex version matched the npm-resolved version;
- the production tag and all three configured containers used the same
  immutable image ID;
- a new Codex session successfully used `gpt-5.6-sol`.

Phase two changes only the image's cached base tooling and the manual
installation handoff.

## Source of Requirements

The approved package scope is derived from the original tool plan as historical
evidence, but its old Dockerfile implementation and tests are not reused or
assumed correct. Phase two is implemented from the current
`feat/docker-image-refresh-v2` branch after the accepted phase-one commits.

## Fixed Tool Contract

The image will contain the following development system tools:

- `wget`
- `jq`
- `rsync`
- `tree`
- `vim`
- `unzip`
- `p7zip-full`
- `file`
- `bat`
- `fd-find`
- `git-lfs`
- `less`
- `pipx`
- `ripgrep`
- `shellcheck`
- `shfmt`
- `sqlite3`
- `gh`

Debian installs `bat` and `fd-find` as `batcat` and `fdfind`. The image will add
stable `/usr/local/bin/bat` and `/usr/local/bin/fd` symlinks.

The image will also contain:

- Python development tools: `uv`, `ruff`;
- Node development tools: `pnpm`, `yarn`;
- LibreOffice components: Writer, Calc, Impress;
- PDF and image tools: Poppler utilities, qpdf, Ghostscript, ImageMagick,
  ExifTool;
- fonts: Liberation, Noto CJK, Noto Color Emoji;
- OCR: Tesseract with English, Simplified Chinese, and Traditional Chinese
  language data;
- Python document libraries: `python-docx`, `openpyxl`, `python-pptx`, `pypdf`.

`gh` comes from the Debian Bookworm repository. Phase two does not add a
third-party GitHub CLI apt repository.

## Dockerfile and Cache Architecture

`Dockerfile.sandbox` will declare the Dockerfile frontend explicitly:

```dockerfile
# syntax=docker/dockerfile:1.7
```

The final layer order is:

1. Node/Debian base and existing core runtime packages;
2. existing browser runtime libraries, with no browser binary;
3. development apt packages and command symlinks;
4. Python development tools;
5. Node development tools;
6. Office, PDF, OCR, and font apt packages;
7. Python document libraries;
8. the existing configured-extras insertion marker;
9. all configured `docker.extras`;
10. the single Claude/Codex/Gemini provider layer;
11. final labels, writable directory, sudo policy, user, workdir, and command.

The development and document apt layers use locked BuildKit cache mounts for:

- `/var/cache/apt`;
- `/var/lib/apt`.

Python layers cache `/root/.cache/pip`. Node layers cache `/root/.npm`.

Provider-only changes therefore invalidate the provider layer and following
metadata, while the large development, document, and extras layers remain
cacheable. Tool or extras changes naturally invalidate their layer and later
layers.

## Existing Extras and Browser Boundary

Every existing `DOCKER_EXTRAS` entry remains unchanged, including:

- FFmpeg and Whisper;
- OpenCV, Tesseract, and EasyOCR;
- PyMuPDF and Pandoc;
- SciPy, pandas, and Matplotlib;
- CPU-only PyTorch and Transformers;
- Playwright.

The Playwright extra continues to install only the Python `playwright` package.
Phase two must not add:

- Chromium, Chrome, or another browser binary;
- `playwright install`;
- `/ms-playwright`;
- browser profile initialization;
- browser cache initialization;
- browser profile or cache mounts.

Existing shared-library packages and comments that describe browser runtime
compatibility remain allowed. Tests inspect installation instructions rather
than rejecting the word "Chromium" in comments.

## Build Timeout

The current five-minute base build timeout is too short for a first uncached
LibreOffice/OCR build on a slow connection. The extras timeout calculation will
gain a 2400-second minimum:

```text
max(2400, base + sum(configured extra timeout additions))
```

This is only an upper bound. Successful builds finish immediately. Timeouts
still return a nonzero status. The change does not add polling, log collection,
or a rollback framework.

## Manual Installation Script

The repository will add:

```text
scripts/install-docker-tools.sh
```

The user runs it manually:

```bash
bash scripts/install-docker-tools.sh
```

The script will:

1. enable `set -euo pipefail`;
2. derive the repository root from the script's own location;
3. require `uv` and `docker` on `PATH`;
4. run `uv tool install --force --from "$repo_root" ductor`;
5. explain that Docker subprocess output is intentionally suppressed and that
   the first tool build may remain quiet for up to 40 minutes;
6. use `exec ductor docker rebuild` so the rebuild status becomes the script
   status.

The script will not:

- run Docker tag/container commands itself;
- perform acceptance checks;
- print environment variables or credentials;
- inspect service logs, Docker mounts, or subprocess diagnostics.

The assistant will not execute this script. After code verification, it will
give the command to the user and stop.

## Failure Handling

Phase two does not modify the accepted candidate-first rebuild state machine.
The existing behavior remains:

- resolve concrete provider versions;
- build a unique candidate without changing the production tag;
- verify candidate Codex directly;
- promote only after candidate verification;
- recreate exact old-image consumers;
- verify configured shared containers against the candidate immutable ID;
- return nonzero on failure;
- make one bounded best-effort restoration after a cutover failure.

The manual script stops at its first failure and propagates the nonzero status.

## TDD and Verification

Implementation is split into independent RED/GREEN tasks:

1. build timeout floor;
2. cached development tool layers;
3. cached Office, PDF, OCR, and Python document layers plus browser/extras
   preservation;
4. manual installation script.

Focused tests will verify:

- the exact approved apt, pip, and npm tool contract;
- `bat` and `fd` symlinks;
- tools before extras and providers;
- extras marker uniqueness and ordering;
- Playwright remaining Python-only;
- absence of browser installation/profile/cache instructions;
- the 2400-second build timeout floor and larger dynamic timeouts;
- shell syntax and exact install-before-rebuild order;
- nonzero propagation through `exec`.

Verification will run:

- focused Docker and script tests;
- `ruff format --check .`;
- `ruff check .`;
- `mypy ductor_bot`;
- the complete pytest suite compared with the recorded phase-one result of
  `3817 passed, 14 failed`, where all 14 failures are the pre-existing
  provider-auth-dependent `tests/workspace/test_init.py` failures.

Static tests replace a large smoke-check matrix. The real Docker build is the
user-controlled manual step.

## Operational Acceptance

After the user runs the script and reports the safe rebuild summary, acceptance
remains limited to:

1. direct candidate Codex equals the emitted npm-resolved Codex version;
2. `ductor-sandbox`, `ductor-sub-serveradmin`, and
   `ductor-sub-botbuilder` run on the emitted candidate immutable ID, with one
   container Codex spot-check;
3. a new Codex session succeeds with `gpt-5.6-sol`.

Tool presence is established by the reviewed Dockerfile contract and successful
image build; phase two does not add a long runtime smoke matrix.
