"""Tests for optional provider model-cache observers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from ductor_bot.cli.codex_cache import CodexModelCache
from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.config import AgentConfig
from ductor_bot.orchestrator.observers import ObserverManager
from ductor_bot.workspace.paths import DuctorPaths


def _manager() -> ObserverManager:
    return ObserverManager(MagicMock(), MagicMock())


async def test_skips_observers_for_missing_optional_clis() -> None:
    manager = _manager()

    with (
        patch("ductor_bot.orchestrator.observers.GeminiCacheObserver") as gemini_cls,
        patch("ductor_bot.orchestrator.observers.AntigravityCacheObserver") as agy_cls,
        patch("ductor_bot.orchestrator.observers.GrokCacheObserver") as grok_cls,
        patch("ductor_bot.orchestrator.observers.CodexCacheObserver") as codex_cls,
    ):
        cache = await manager.init_model_caches(
            installed_providers=frozenset({"claude"}),
            on_gemini_refresh=MagicMock(),
            on_antigravity_refresh=MagicMock(),
            on_grok_refresh=MagicMock(),
        )

    gemini_cls.assert_not_called()
    agy_cls.assert_not_called()
    grok_cls.assert_not_called()
    codex_cls.assert_not_called()
    assert manager.gemini_cache_obs is None
    assert manager.antigravity_cache_obs is None
    assert manager.grok_cache_obs is None
    assert manager.codex_cache_obs is None
    assert cache.models == []


async def test_starts_observers_for_installed_optional_clis() -> None:
    manager = _manager()
    gemini_observer = MagicMock()
    gemini_observer.start = AsyncMock()
    agy_observer = MagicMock()
    agy_observer.start = AsyncMock()
    grok_observer = MagicMock()
    grok_observer.start = AsyncMock()
    codex_observer = MagicMock()
    codex_observer.start = AsyncMock()
    codex_observer.get_cache.return_value = CodexModelCache("", [])

    with (
        patch(
            "ductor_bot.orchestrator.observers.GeminiCacheObserver",
            return_value=gemini_observer,
        ),
        patch(
            "ductor_bot.orchestrator.observers.AntigravityCacheObserver",
            return_value=agy_observer,
        ),
        patch("ductor_bot.orchestrator.observers.GrokCacheObserver", return_value=grok_observer),
        patch("ductor_bot.orchestrator.observers.CodexCacheObserver", return_value=codex_observer),
    ):
        await manager.init_model_caches(
            installed_providers=frozenset({"claude", "codex", "gemini", "antigravity", "grok"}),
            on_gemini_refresh=MagicMock(),
            on_antigravity_refresh=MagicMock(),
            on_grok_refresh=MagicMock(),
        )

    gemini_observer.start.assert_awaited_once()
    agy_observer.start.assert_awaited_once()
    grok_observer.start.assert_awaited_once()
    assert manager.gemini_cache_obs is gemini_observer
    assert manager.antigravity_cache_obs is agy_observer
    assert manager.grok_cache_obs is grok_observer
    assert manager.codex_cache_obs is codex_observer
    codex_observer.start.assert_awaited_once()


async def test_installed_but_unauthenticated_provider_still_gets_observer() -> None:
    """INSTALLED (not AUTHENTICATED) is enough — the set is auth-detection based."""
    manager = _manager()
    codex_observer = MagicMock()
    codex_observer.start = AsyncMock()
    codex_observer.get_cache.return_value = CodexModelCache("", [])

    with (
        patch("ductor_bot.orchestrator.observers.GeminiCacheObserver") as gemini_cls,
        patch("ductor_bot.orchestrator.observers.AntigravityCacheObserver") as agy_cls,
        patch("ductor_bot.orchestrator.observers.GrokCacheObserver") as grok_cls,
        patch("ductor_bot.orchestrator.observers.CodexCacheObserver", return_value=codex_observer),
    ):
        await manager.init_model_caches(
            installed_providers=frozenset({"claude", "codex"}),
            on_gemini_refresh=MagicMock(),
            on_antigravity_refresh=MagicMock(),
            on_grok_refresh=MagicMock(),
        )

    gemini_cls.assert_not_called()
    agy_cls.assert_not_called()
    grok_cls.assert_not_called()
    codex_observer.start.assert_awaited_once()


async def test_claude_keepalive_starts_only_for_enabled_main(tmp_path) -> None:
    runtime = DeepseekRuntime(False, "", (), error="disabled")
    for is_main, enabled, expected in (
        (True, True, 1),
        (True, False, 0),
        (False, True, 0),
    ):
        manager = ObserverManager(
            AgentConfig(claude_token_keepalive=enabled),
            DuctorPaths(ductor_home=tmp_path / f"{is_main}-{enabled}"),
        )
        manager.heartbeat.start = AsyncMock()
        manager.heartbeat.stop = AsyncMock()
        manager.cleanup.start = AsyncMock()
        manager.cleanup.stop = AsyncMock()
        keepalive = MagicMock()
        keepalive.start = AsyncMock()
        keepalive.stop = AsyncMock()
        with (
            patch(
                "ductor_bot.orchestrator.observers.ClaudeTokenKeepalive",
                return_value=keepalive,
            ) as keepalive_cls,
            patch("ductor_bot.orchestrator.observers.watch_rule_files", new_callable=AsyncMock),
            patch("ductor_bot.orchestrator.observers.watch_skill_sync", new_callable=AsyncMock),
        ):
            await manager.start_all(
                is_main=is_main,
                deepseek_runtime=runtime,
                usage_service=MagicMock(),
            )
            await manager.stop_all()

        assert keepalive_cls.call_count == expected
        assert keepalive.start.await_count == expected
        assert keepalive.stop.await_count == expected
