"""Tests for ProviderManager: model resolution, directives, auth, and defaults."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ductor_bot.cli.auth import AuthResult, AuthStatus
from ductor_bot.cli.deepseek import DeepseekRuntime, resolve_deepseek_runtime
from ductor_bot.config import (
    AgentConfig,
    DeepseekConfig,
    reset_antigravity_models,
    reset_gemini_models,
    reset_grok_models,
    set_gemini_models,
)
from ductor_bot.orchestrator.providers import ProviderManager


@pytest.fixture(autouse=True)
def _reset_gemini():
    reset_gemini_models()
    reset_antigravity_models()
    reset_grok_models()
    yield
    reset_gemini_models()
    reset_antigravity_models()
    reset_grok_models()


def _pm(
    *,
    model: str = "sonnet",
    provider: str = "claude",
    codex_cache_fn: object | None = None,
) -> ProviderManager:
    cfg = AgentConfig(model=model, provider=provider)
    return ProviderManager(cfg, codex_cache_fn=codex_cache_fn)  # type: ignore[arg-type]


def _deepseek_runtime() -> DeepseekRuntime:
    return resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, models=["deepseek-v4-pro", "deepseek-v4-flash"]),
        "secret",
        reserved_models=frozenset({"opus"}),
    )


def test_deepseek_available_with_key_and_installed_claude_but_no_oauth() -> None:
    manager = ProviderManager(
        AgentConfig(), deepseek_runtime=_deepseek_runtime(), claude_cli_runnable=True
    )
    cli_service = MagicMock()
    manager.apply_auth_results(
        {
            "claude": AuthResult("claude", AuthStatus.INSTALLED),
            "codex": AuthResult("codex", AuthStatus.NOT_FOUND),
        },
        auth_status_enum=AuthStatus,
        cli_service=cli_service,
    )
    assert "deepseek" in manager.available_providers
    assert "claude" not in manager.available_providers


@pytest.mark.parametrize("missing", ["disabled", "key", "models", "claude_cli"])
def test_deepseek_unavailable_when_requirement_missing(missing: str) -> None:
    cfg = DeepseekConfig(
        enabled=missing != "disabled",
        models=[] if missing == "models" else ["deepseek-v4-pro"],
    )
    runtime = resolve_deepseek_runtime(
        cfg,
        "" if missing == "key" else "secret",
        reserved_models=frozenset({"opus", "gemini-2.5-pro", "grok-4.5"}),
    )
    manager = ProviderManager(
        AgentConfig(),
        deepseek_runtime=runtime,
        claude_cli_runnable=missing != "claude_cli",
    )
    manager.apply_auth_results(
        {"claude": AuthResult("claude", AuthStatus.INSTALLED)},
        auth_status_enum=AuthStatus,
        cli_service=MagicMock(),
    )
    assert "deepseek" not in manager.available_providers


def test_deepseek_directive_default_and_active_name() -> None:
    config = AgentConfig(
        provider="deepseek", model="deepseek-v4-pro", deepseek=DeepseekConfig(enabled=True)
    )
    manager = ProviderManager(
        config, deepseek_runtime=_deepseek_runtime(), claude_cli_runnable=True
    )
    assert manager.resolve_session_directive("deepseek") == (
        "deepseek",
        "deepseek-v4-pro",
    )
    assert manager.active_provider_name == "DeepSeek"


def test_cached_codex_collision_disables_deepseek() -> None:
    model = MagicMock(id="deepseek-v4-pro")
    cache = MagicMock(models=[model])
    manager = ProviderManager(
        AgentConfig(),
        deepseek_runtime=_deepseek_runtime(),
        claude_cli_runnable=True,
        codex_cache_fn=lambda: cache,
    )
    manager._available_providers = frozenset({"deepseek"})

    manager.refresh_known_model_ids()

    assert manager.models.deepseek_models == frozenset()
    assert "deepseek" not in manager.available_providers


@pytest.mark.parametrize(
    "callback_name",
    [
        "on_gemini_models_refresh",
        "on_antigravity_models_refresh",
        "on_grok_models_refresh",
    ],
)
def test_dynamic_provider_collision_disables_deepseek(callback_name: str) -> None:
    collision = "late-discovered-model"
    runtime = resolve_deepseek_runtime(
        DeepseekConfig(enabled=True, models=[collision]),
        "secret",
        reserved_models=frozenset({"opus"}),
    )
    manager = ProviderManager(
        AgentConfig(),
        deepseek_runtime=runtime,
        claude_cli_runnable=True,
    )
    manager._available_providers = frozenset({"deepseek"})

    getattr(manager, callback_name)((collision,))

    assert manager.deepseek_runtime.error == "model_collision"
    assert manager.models.deepseek_models == frozenset()
    assert "deepseek" not in manager.available_providers


# ---------------------------------------------------------------------------
# resolve_runtime_target
# ---------------------------------------------------------------------------


class TestResolveRuntimeTarget:
    def test_default_model(self) -> None:
        pm = _pm(model="opus")
        model, provider = pm.resolve_runtime_target()
        assert model == "opus"
        assert provider == "claude"

    def test_explicit_model(self) -> None:
        pm = _pm()
        model, provider = pm.resolve_runtime_target("haiku")
        assert model == "haiku"
        assert provider == "claude"

    def test_gemini_model(self) -> None:
        pm = _pm()
        model, provider = pm.resolve_runtime_target("auto")
        assert model == "auto"
        assert provider == "gemini"

    def test_codex_model(self) -> None:
        pm = _pm()
        model, provider = pm.resolve_runtime_target("o3-mini")
        assert model == "o3-mini"
        assert provider == "codex"

    def test_none_falls_back_to_config(self) -> None:
        pm = _pm(model="haiku")
        model, provider = pm.resolve_runtime_target(None)
        assert model == "haiku"
        assert provider == "claude"


# ---------------------------------------------------------------------------
# resolve_session_directive
# ---------------------------------------------------------------------------


class TestResolveSessionDirective:
    def test_provider_name_claude(self) -> None:
        pm = _pm(model="opus", provider="claude")
        result = pm.resolve_session_directive("claude")
        assert result is not None
        assert result[0] == "claude"
        assert result[1] == "opus"  # default_model_for_provider returns config.model

    def test_provider_name_gemini(self) -> None:
        pm = _pm()
        result = pm.resolve_session_directive("gemini")
        assert result is not None
        assert result[0] == "gemini"
        assert result[1] == ""  # gemini default is empty

    def test_provider_name_codex(self) -> None:
        pm = _pm()
        result = pm.resolve_session_directive("codex")
        assert result is not None
        assert result[0] == "codex"

    def test_known_model(self) -> None:
        pm = _pm()
        result = pm.resolve_session_directive("opus")
        assert result is not None
        assert result == ("claude", "opus")

    def test_known_gemini_alias(self) -> None:
        pm = _pm()
        result = pm.resolve_session_directive("auto")
        assert result is not None
        assert result == ("gemini", "auto")

    def test_unknown_returns_none(self) -> None:
        pm = _pm()
        assert pm.resolve_session_directive("unknown-model-xyz") is None


# ---------------------------------------------------------------------------
# is_known_model
# ---------------------------------------------------------------------------


class TestIsKnownModel:
    def test_claude_models(self) -> None:
        pm = _pm()
        for name in ("haiku", "sonnet", "opus"):
            assert pm.is_known_model(name) is True

    def test_gemini_aliases(self) -> None:
        pm = _pm()
        assert pm.is_known_model("auto") is True
        assert pm.is_known_model("flash") is True

    def test_gemini_runtime_models(self) -> None:
        set_gemini_models(frozenset({"gemini-2.5-pro"}))
        pm = _pm()
        assert pm.is_known_model("gemini-2.5-pro") is True

    def test_unknown_model(self) -> None:
        pm = _pm()
        assert pm.is_known_model("nonexistent-model") is False

    def test_codex_via_cache(self) -> None:
        cache = MagicMock()
        cache.validate_model.return_value = True
        pm = _pm(codex_cache_fn=lambda: cache)
        assert pm.is_known_model("o3-mini") is True
        cache.validate_model.assert_called_once_with("o3-mini")

    def test_codex_cache_none(self) -> None:
        pm = _pm(codex_cache_fn=lambda: None)
        assert pm.is_known_model("o3-mini") is False


# ---------------------------------------------------------------------------
# default_model_for_provider
# ---------------------------------------------------------------------------


class TestDefaultModelForProvider:
    def test_claude_default(self) -> None:
        pm = _pm(model="opus", provider="claude")
        assert pm.default_model_for_provider("claude") == "opus"

    def test_claude_when_not_active_provider(self) -> None:
        pm = _pm(model="o3-mini", provider="codex")
        assert pm.default_model_for_provider("claude") == "sonnet"

    def test_codex_with_cache_default(self) -> None:
        model = MagicMock()
        model.is_default = True
        model.id = "o4-mini"
        cache = MagicMock()
        cache.models = [model]
        pm = _pm(codex_cache_fn=lambda: cache)
        assert pm.default_model_for_provider("codex") == "o4-mini"

    def test_codex_no_cache(self) -> None:
        pm = _pm()
        assert pm.default_model_for_provider("codex") == ""

    def test_gemini(self) -> None:
        pm = _pm()
        assert pm.default_model_for_provider("gemini") == ""

    def test_unknown_provider(self) -> None:
        pm = _pm()
        assert pm.default_model_for_provider("unknown") == ""


# ---------------------------------------------------------------------------
# apply_auth_results
# ---------------------------------------------------------------------------


class TestApplyAuthResults:
    def test_updates_available_providers(self) -> None:
        pm = _pm()
        cli_service = MagicMock()

        auth_status = MagicMock()
        auth_status.AUTHENTICATED = "auth"
        auth_status.INSTALLED = "inst"

        result_claude = MagicMock()
        result_claude.status = "auth"
        result_claude.is_authenticated = True

        result_codex = MagicMock()
        result_codex.status = "inst"
        result_codex.is_authenticated = False

        pm.apply_auth_results(
            {"claude": result_claude, "codex": result_codex},
            auth_status_enum=auth_status,
            cli_service=cli_service,
        )
        assert pm.available_providers == frozenset({"claude"})
        cli_service.update_available_providers.assert_called_once_with(frozenset({"claude"}))

    def test_all_authenticated(self) -> None:
        pm = _pm()
        cli_service = MagicMock()

        auth_status = MagicMock()
        auth_status.AUTHENTICATED = "auth"
        auth_status.INSTALLED = "inst"

        results = {}
        for name in ("claude", "codex", "gemini"):
            r = MagicMock()
            r.status = "auth"
            r.is_authenticated = True
            results[name] = r

        pm.apply_auth_results(
            results,
            auth_status_enum=auth_status,
            cli_service=cli_service,
        )
        assert pm.available_providers == frozenset({"claude", "codex", "gemini"})


# ---------------------------------------------------------------------------
# active_provider_name
# ---------------------------------------------------------------------------


class TestActiveProviderName:
    def test_claude(self) -> None:
        pm = _pm(model="sonnet", provider="claude")
        assert pm.active_provider_name == "Claude Code"

    def test_gemini(self) -> None:
        pm = _pm(model="auto", provider="gemini")
        assert pm.active_provider_name == "Gemini"

    def test_codex(self) -> None:
        pm = _pm(model="o3-mini", provider="codex")
        assert pm.active_provider_name == "Codex"


# ---------------------------------------------------------------------------
# on_gemini_models_refresh
# ---------------------------------------------------------------------------


class TestOnGeminiModelsRefresh:
    def test_updates_known_model_ids(self) -> None:
        pm = _pm()
        assert not pm.is_known_model("gemini-2.5-pro")

        pm.on_gemini_models_refresh(("gemini-2.5-pro", "gemini-2.5-flash"))
        assert pm.is_known_model("gemini-2.5-pro")
        assert pm.is_known_model("gemini-2.5-flash")

    def test_invalidates_gemini_api_key_mode(self) -> None:
        pm = _pm()
        pm._gemini_api_key_mode = True
        pm.on_gemini_models_refresh(("gemini-2.5-pro",))
        assert pm._gemini_api_key_mode is None
