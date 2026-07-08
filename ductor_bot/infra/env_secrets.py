"""Centralised loading of user-defined environment secrets from ``~/.ductor/.env``.

The file uses standard dotenv syntax::

    # Comment
    PPLX_API_KEY=sk-xxx
    DEEPSEEK_API_KEY=sk-yyy
    export MY_VAR="quoted value"

Values are injected into CLI subprocesses (host and Docker) but never
override variables that are already set in the environment.

The file is re-read automatically when its mtime changes, so edits take
effect on the next CLI invocation without a bot restart.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Per-path cache: {path: (mtime, parsed_vars)}. Multi-agent mode reads
# several .env files (main + one per sub-agent) on every CLI invocation.
_cache: dict[Path, tuple[float, dict[str, str]]] = {}


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file into a ``{key: value}`` dict.

    Supports ``#`` comments, ``export`` prefix, single/double quotes.
    """
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return result

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        if sep != "=":
            continue
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # Strip matching quotes.
        if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
            value = value[1:-1]
        else:
            # Remove inline comment (unquoted values only).
            value = value.split("#", 1)[0].strip()
        result[key] = value

    return result


def _current_mtime(path: Path) -> float:
    """Return mtime of *path*, or ``0.0`` if the file does not exist."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def load_env_secrets(env_file: Path) -> dict[str, str]:
    """Load secrets from *env_file*, re-reading when the file changes.

    Uses mtime-based cache invalidation so edits to ``.env`` take effect
    on the next CLI invocation without a bot restart.  Each path is cached
    independently so multiple agents' .env files don't evict each other.
    """
    mtime = _current_mtime(env_file)

    cached = _cache.get(env_file)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    # File missing or deleted.
    if mtime == 0.0:
        if cached is not None and cached[0] != 0.0:
            logger.info("Env file removed: %s", env_file)
        _cache[env_file] = (0.0, {})
        return _cache[env_file][1]

    # (Re-)parse.
    parsed = _parse_dotenv(env_file)
    _cache[env_file] = (mtime, parsed)
    if parsed:
        logger.info("Loaded %d secret(s) from %s", len(parsed), env_file)
    return parsed


def clear_cache() -> None:
    """Reset the cached secrets (for tests)."""
    _cache.clear()
