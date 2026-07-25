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
        assert re.search(
            rf"(?<![A-Za-z0-9_.+-]){re.escape(package)}(?![A-Za-z0-9_.+-])",
            section,
        )

    assert "--mount=type=cache,target=/var/cache/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/var/lib/apt,sharing=locked" in section
    assert "--mount=type=cache,target=/root/.cache/pip" in section
    assert "--mount=type=cache,target=/root/.npm" in section
    assert "python3 -m pip install uv ruff" in section
    assert "npm install -g pnpm yarn" in section
    assert "ln -sf /usr/bin/batcat /usr/local/bin/bat" in section
    assert "ln -sf /usr/bin/fdfind /usr/local/bin/fd" in section
