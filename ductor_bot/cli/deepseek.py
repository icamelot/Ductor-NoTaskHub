"""DeepSeek configuration validation and Claude CLI availability probing."""

from __future__ import annotations

import logging
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ductor_bot.config import DeepseekConfig
from ductor_bot.infra.env_secrets import load_env_secrets
from ductor_bot.workspace.paths import DuctorPaths

logger = logging.getLogger(__name__)

_LOCAL_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True)
class DeepseekRuntime:
    """Validated runtime data whose secret is excluded from representations."""

    requested: bool
    base_url: str
    models: tuple[str, ...]
    api_key: str = field(default="", repr=False)
    error: str = ""

    @property
    def configured(self) -> bool:
        """Whether DeepSeek has all non-process requirements configured."""
        return self.requested and bool(self.models) and bool(self.api_key) and not self.error

    def invocation_env(self) -> dict[str, str]:
        """Return invocation-local Anthropic-compatible environment overrides."""
        if not self.configured:
            return {}
        return {
            "ANTHROPIC_BASE_URL": self.base_url,
            "ANTHROPIC_AUTH_TOKEN": self.api_key,
        }


def load_deepseek_api_key(paths: DuctorPaths) -> str:
    """Load the DeepSeek key from the root Ductor home's startup secret file."""
    return load_env_secrets(paths.root_env_file).get("DEEPSEEK_API_KEY", "").strip()


def _valid_base_url(value: str) -> bool:
    parsed = urlsplit(value)
    if not parsed.netloc or parsed.hostname is None or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname.lower() in _LOCAL_HTTP_HOSTS


def _valid_model_id(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 256
        and not any(char.isspace() or unicodedata.category(char).startswith("C") for char in value)
    )


def resolve_deepseek_runtime(
    config: DeepseekConfig,
    api_key: str,
    *,
    reserved_models: frozenset[str],
) -> DeepseekRuntime:
    """Validate non-secret DeepSeek config and combine it with a captured key."""
    base_url = config.base_url.strip()
    models = tuple(model.strip() for model in config.models)
    key = api_key.strip()

    error = ""
    if not config.enabled:
        error = "disabled"
    elif not _valid_base_url(base_url):
        error = "invalid_base_url"
    elif any(not _valid_model_id(model) for model in models):
        error = "invalid_model"
    elif len(set(models)) != len(models):
        error = "duplicate_model"
    elif any(model in reserved_models for model in models):
        error = "model_collision"
    elif not key:
        error = "missing_key"

    return DeepseekRuntime(
        requested=config.enabled,
        base_url=base_url,
        models=models,
        api_key=key,
        error=error,
    )


def claude_cli_runnable(docker_container: str = "") -> bool:
    """Probe Claude CLI execution independently from native Claude OAuth state."""
    if docker_container:
        docker = shutil.which("docker")
        if docker is None:
            logger.info("Claude CLI probe category=executable_not_found")
            return False
        command = [docker, "exec", docker_container, "claude", "--version"]
    else:
        claude = shutil.which("claude")
        if claude is None:
            logger.info("Claude CLI probe category=executable_not_found")
            return False
        command = [claude, "--version"]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI probe category=timeout")
        return False
    except OSError:
        logger.warning("Claude CLI probe category=unavailable")
        return False
    if result.returncode != 0:
        logger.info("Claude CLI probe category=nonzero_exit")
        return False
    return True
