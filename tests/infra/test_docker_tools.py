from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from ductor_bot.infra.docker_extras import (
    DOCKER_EXTRAS_BY_ID,
    DOCKER_EXTRAS_MARKER,
)

_REPO_ROOT = Path(__file__).parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile.sandbox"
_INSTALL_SCRIPT = _REPO_ROOT / "scripts" / "install-docker-tools.sh"
_DEVELOPMENT_MARKER = "# -- Ductor development tools --"
_DOCUMENT_MARKER = "# -- Ductor document tools --"


def _dockerfile() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _section(content: str, start: str, end: str) -> str:
    return content.split(start, 1)[1].split(end, 1)[0]


def test_dockerfile_declares_buildkit_frontend_and_development_layer() -> None:
    content = _dockerfile()

    assert content.startswith("# syntax=docker/dockerfile:1.7\n")
    assert content.count(_DEVELOPMENT_MARKER) == 1
    assert content.index(_DEVELOPMENT_MARKER) < content.index(DOCKER_EXTRAS_MARKER)
    assert content.index(DOCKER_EXTRAS_MARKER) < content.index("ARG CLAUDE_CLI_VERSION")


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
        assert re.search(
            rf"(?<![A-Za-z0-9_.+-]){re.escape(package)}(?![A-Za-z0-9_.+-])",
            section,
        )

    assert "--mount=type=cache,target=/var/cache/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/var/lib/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/root/.cache/pip" in section
    assert "--mount=type=cache,target=/root/.npm" in section
    assert "python3 -m pip install uv ruff" in section
    assert "npm install -g pnpm" in section
    assert "ln -sf /usr/bin/batcat /usr/local/bin/bat" in section
    assert "ln -sf /usr/bin/fdfind /usr/local/bin/fd" in section


def test_node_development_layer_preserves_base_yarn_command() -> None:
    content = _dockerfile()
    section = _section(content, _DEVELOPMENT_MARKER, _DOCUMENT_MARKER)

    assert "FROM node:22-bookworm-slim" in content
    assert "npm install -g pnpm yarn" not in section
    assert "yarn --version" in section


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
        assert re.search(
            rf"(?<![A-Za-z0-9_.+-]){re.escape(package)}(?![A-Za-z0-9_.+-])",
            section,
        )

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
    assert content.index(DOCKER_EXTRAS_MARKER) < content.index("ARG CLAUDE_CLI_VERSION")


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


def test_manual_install_script_has_safe_install_then_rebuild_contract() -> None:
    script = _INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in script
    assert "command -v uv >/dev/null 2>&1" in script
    assert "command -v docker >/dev/null 2>&1" in script
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
