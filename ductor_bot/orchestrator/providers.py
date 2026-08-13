"""Provider/model resolution extracted from the Orchestrator core."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.config import (
    _GEMINI_ALIASES,
    ANTIGRAVITY_MODELS,
    CLAUDE_MODELS,
    GROK_MODELS,
    ModelRegistry,
    get_antigravity_models,
    get_gemini_models,
    get_grok_models,
    get_grok_models_ordered,
    set_antigravity_models,
    set_gemini_models,
    set_grok_models,
)

if TYPE_CHECKING:
    from ductor_bot.cli.auth import AuthResult, AuthStatus
    from ductor_bot.cli.codex_cache import CodexModelCache
    from ductor_bot.cli.codex_cache_observer import CodexCacheObserver
    from ductor_bot.cli.service import CLIService
    from ductor_bot.config import AgentConfig

logger = logging.getLogger(__name__)


def _disabled_deepseek_runtime() -> DeepseekRuntime:
    return DeepseekRuntime(
        requested=False,
        base_url="https://api.deepseek.com/anthropic",
        models=(),
        error="disabled",
    )


class ProviderManager:
    """Owns provider authentication state, model resolution, and provider metadata.

    Extracted from ``Orchestrator`` to keep the core slim.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        deepseek_runtime: DeepseekRuntime | None = None,
        claude_cli_runnable: bool = False,
        codex_cache_fn: Callable[[], CodexModelCache | None] | None = None,
    ) -> None:
        self._config = config
        self._models = ModelRegistry()
        self._deepseek_runtime = deepseek_runtime or _disabled_deepseek_runtime()
        self._claude_cli_runnable = claude_cli_runnable
        self._models.configure_deepseek(
            self._deepseek_runtime.models if self._deepseek_runtime.configured else ()
        )
        self._known_model_ids: frozenset[str] = frozenset()
        self._available_providers: frozenset[str] = frozenset()
        self._gemini_api_key_mode: bool | None = None
        self._codex_cache_fn = codex_cache_fn
        self._cli_service: CLIService | None = None
        self.refresh_known_model_ids()

    # -- Public properties ----------------------------------------------------

    @property
    def models(self) -> ModelRegistry:
        """Public access to the model registry."""
        return self._models

    @property
    def deepseek_runtime(self) -> DeepseekRuntime:
        """Effective redaction-safe DeepSeek runtime."""
        return self._deepseek_runtime

    @property
    def available_providers(self) -> frozenset[str]:
        """The set of authenticated provider names."""
        return self._available_providers

    @property
    def gemini_api_key_mode(self) -> bool:
        """Return cached Gemini API-key mode status."""
        if self._gemini_api_key_mode is None:
            from ductor_bot.cli.auth import gemini_uses_api_key_mode

            self._gemini_api_key_mode = gemini_uses_api_key_mode()
        return self._gemini_api_key_mode

    @property
    def active_provider_name(self) -> str:
        """Human-readable name for the active CLI provider."""
        _model, provider = self.resolve_runtime_target(self._config.model)
        if provider == "claude":
            return "Claude Code"
        if provider == "deepseek":
            return "DeepSeek"
        if provider == "gemini":
            return "Gemini"
        if provider == "antigravity":
            return "Antigravity"
        if provider == "grok":
            return "Grok Build"
        return "Codex"

    # -- Auth / init ----------------------------------------------------------

    def apply_auth_results(
        self,
        auth_results: dict[str, AuthResult],
        *,
        auth_status_enum: type[AuthStatus],
        cli_service: CLIService,
    ) -> None:
        """Log provider auth states and update the runtime provider set."""
        authenticated = auth_status_enum.AUTHENTICATED
        installed = auth_status_enum.INSTALLED

        for provider, result in auth_results.items():
            if result.status == authenticated:
                logger.info("Provider [%s]: authenticated", provider)
            elif result.status == installed:
                logger.warning("Provider [%s]: installed but NOT authenticated", provider)
            else:
                logger.info("Provider [%s]: not found", provider)

        self._available_providers = frozenset(
            name for name, res in auth_results.items() if res.is_authenticated
        )
        if self._deepseek_runtime.configured and self._claude_cli_runnable:
            self._available_providers |= frozenset({"deepseek"})
        self._cli_service = cli_service
        cli_service.update_available_providers(self._available_providers)

    def refresh_deepseek(
        self,
        runtime: DeepseekRuntime,
        cli_service: CLIService,
    ) -> None:
        """Apply hot-reloaded non-secret DeepSeek configuration."""
        self._deepseek_runtime = runtime
        self._models.configure_deepseek(runtime.models if runtime.configured else ())
        self.refresh_known_model_ids()
        providers = set(self._available_providers)
        providers.discard("deepseek")
        if self._deepseek_runtime.configured and self._claude_cli_runnable:
            providers.add("deepseek")
        self._available_providers = frozenset(providers)
        self._cli_service = cli_service
        cli_service.update_available_providers(self._available_providers)

    def init_gemini_state(self, paths_workspace: object) -> None:
        """Cache Gemini API-key mode and trust workspace once at startup."""
        from ductor_bot.cli.auth import gemini_uses_api_key_mode

        self._gemini_api_key_mode = gemini_uses_api_key_mode()
        if "gemini" in self._available_providers:
            from ductor_bot.cli.gemini_utils import trust_workspace

            trust_workspace(paths_workspace)  # type: ignore[arg-type]

    # -- Model resolution -----------------------------------------------------

    def on_gemini_models_refresh(self, models: tuple[str, ...]) -> None:
        """Callback for GeminiCacheObserver: update model registry."""
        set_gemini_models(frozenset(models))
        self.refresh_known_model_ids()
        self._gemini_api_key_mode = None  # Invalidate to re-check on next access

    def on_antigravity_models_refresh(self, models: tuple[str, ...]) -> None:
        """Callback for AntigravityCacheObserver: update model registry."""
        set_antigravity_models(frozenset(models))
        self.refresh_known_model_ids()

    def on_grok_models_refresh(self, models: tuple[str, ...]) -> None:
        """Callback for GrokCacheObserver: update model registry."""
        set_grok_models(models)
        self.refresh_known_model_ids()

    def refresh_gemini_api_key_mode(self) -> bool:
        """Re-read ``~/.gemini/settings.json`` and update the cache.

        Allows runtime auth-mode flips (e.g. user switches from API-key to
        OAuth in Gemini CLI) without a ductor restart.
        """
        from ductor_bot.cli.auth import gemini_uses_api_key_mode

        self._gemini_api_key_mode = gemini_uses_api_key_mode()
        return self._gemini_api_key_mode

    def refresh_known_model_ids(self) -> None:
        """Refresh directive-known model IDs from dynamic provider registries."""
        cache = self._codex_cache_fn() if self._codex_cache_fn else None
        codex_ids = frozenset(
            model.id for model in getattr(cache, "models", ()) if isinstance(model.id, str)
        )
        reserved_ids = (
            CLAUDE_MODELS
            | ANTIGRAVITY_MODELS
            | GROK_MODELS
            | _GEMINI_ALIASES
            | get_gemini_models()
            | get_antigravity_models()
            | get_grok_models()
            | codex_ids
        )
        if reserved_ids.intersection(self._deepseek_runtime.models):
            self._deepseek_runtime = replace(self._deepseek_runtime, error="model_collision")
            self._models.configure_deepseek(())
            self._available_providers = frozenset(
                provider for provider in self._available_providers if provider != "deepseek"
            )
            if self._cli_service is not None:
                self._cli_service.update_available_providers(self._available_providers)
        self._known_model_ids = reserved_ids | self._models.deepseek_models

    def resolve_runtime_target(self, requested_model: str | None = None) -> tuple[str, str]:
        """Resolve requested model to the effective ``(model, provider)`` pair."""
        model_name = requested_model or self._config.model
        return model_name, self._models.provider_for(model_name)

    def is_known_model(self, candidate: str) -> bool:
        """Return True if *candidate* is a recognized model ID for any provider."""
        if candidate in self._known_model_ids:
            return True
        codex = self._codex_cache_fn() if self._codex_cache_fn else None
        return bool(codex and codex.validate_model(candidate))

    def default_model_for_provider(self, provider: str) -> str:
        """Return the default model ID for a provider, or empty string if unknown."""
        if provider == "claude":
            return self._config.model if self._config.provider == "claude" else "sonnet"
        if provider == "deepseek":
            return (
                self._config.model
                if self._config.provider == "deepseek"
                and self._config.model in self._models.deepseek_models
                else (self._deepseek_runtime.models[0] if self._deepseek_runtime.models else "")
            )
        if provider == "grok":
            return self._config.model if self._config.provider == "grok" else "grok-4.5"
        if provider == "codex":
            codex = self._codex_cache_fn() if self._codex_cache_fn else None
            if codex:
                for m in codex.models:
                    if m.is_default:
                        return m.id
            return ""
        # gemini has no static default; unknown providers fall through to "".
        return {"antigravity": "antigravity-default"}.get(provider, "")

    def resolve_session_directive(self, key: str) -> tuple[str, str] | None:
        """Resolve a ``@key`` directive to ``(provider, model)`` or ``None``.

        Handles three cases:
        - provider name (``@codex``) -> (provider, default_model)
        - known model   (``@opus``)  -> (inferred_provider, model)
        - unknown                    -> None
        """
        if key in ("claude", "deepseek", "codex", "gemini", "antigravity", "grok"):
            return key, self.default_model_for_provider(key)
        if self.is_known_model(key):
            provider = self._models.provider_for(key)
            return provider, key
        return None

    # -- Provider metadata for API --------------------------------------------

    def build_provider_info(
        self,
        codex_cache_obs: CodexCacheObserver | None = None,
    ) -> list[dict[str, object]]:
        """Build provider metadata for the API auth_ok response.

        Only includes authenticated providers.
        """
        provider_meta: dict[str, tuple[str, str]] = {
            "claude": ("Claude Code", "#F97316"),
            "deepseek": ("DeepSeek", "#4D6BFE"),
            "gemini": ("Gemini", "#8B5CF6"),
            "codex": ("Codex", "#10B981"),
            "antigravity": ("Antigravity", "#3B82F6"),
            "grok": ("Grok Build", "#111827"),
        }
        providers: list[dict[str, object]] = []
        for pid in sorted(self._available_providers):
            name, color = provider_meta.get(pid, (pid.title(), "#A1A1AA"))
            models: list[str]
            if pid == "claude":
                models = sorted(CLAUDE_MODELS)
            elif pid == "deepseek":
                models = sorted(self._models.deepseek_models)
            elif pid == "gemini":
                gemini = get_gemini_models()
                models = sorted(gemini) if gemini else sorted(_GEMINI_ALIASES)
            elif pid == "codex":
                cache = codex_cache_obs.get_cache() if codex_cache_obs else None
                models = [m.id for m in cache.models] if cache and cache.models else []
            elif pid == "antigravity":
                antigravity = get_antigravity_models()
                models = sorted(antigravity) if antigravity else sorted(ANTIGRAVITY_MODELS)
            elif pid == "grok":
                models = list(get_grok_models_ordered())
            else:
                models = []
            providers.append({"id": pid, "name": name, "color": color, "models": models})
        return providers
