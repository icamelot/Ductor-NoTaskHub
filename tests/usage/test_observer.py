"""Tests for periodic DeepSeek balance observation and lifecycle wiring."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.config import AgentConfig
from ductor_bot.orchestrator.observers import ObserverManager
from ductor_bot.usage.models import Balance, DeepseekUsage, UsageFailure
from ductor_bot.usage.observer import DeepSeekBalanceObserver
from ductor_bot.usage.snapshots import BalanceSnapshotRepository
from ductor_bot.workspace.paths import DuctorPaths


@pytest.fixture
def repository(tmp_path: Path) -> BalanceSnapshotRepository:
    return BalanceSnapshotRepository(tmp_path / "snapshots.json", tmp_path / "legacy.json")


def _runtime(*, configured: bool = True) -> DeepseekRuntime:
    return DeepseekRuntime(
        True,
        "https://api.deepseek.com/anthropic",
        ("deepseek-chat",),
        api_key="secret" if configured else "",
        error="" if configured else "missing_key",
    )


async def test_observer_collects_immediately_then_every_interval(
    repository: BalanceSnapshotRepository,
) -> None:
    fetch = AsyncMock(
        return_value=DeepseekUsage(
            ok=True,
            balances=(Balance("CNY", Decimal(100)),),
        )
    )
    observer = DeepSeekBalanceObserver(fetch, repository, interval_seconds=0.01)

    await observer.start()
    first_task = observer._task
    await observer.start()
    for _ in range(100):
        if fetch.await_count >= 2:
            break
        await asyncio.sleep(0.001)
    await observer.stop()

    assert fetch.await_count >= 2
    assert first_task is not None
    assert observer.running is False


async def test_observer_skips_failed_and_partial_samples(
    repository: BalanceSnapshotRepository,
) -> None:
    fetch = AsyncMock(
        side_effect=[
            DeepseekUsage(ok=False, failure=UsageFailure.TIMEOUT),
            DeepseekUsage(ok=True, balances=()),
        ]
    )
    observer = DeepSeekBalanceObserver(fetch, repository)

    await observer.collect_once()
    await observer.collect_once()

    assert await repository.load() == ()


async def test_observer_loop_survives_ordinary_failure(
    repository: BalanceSnapshotRepository,
) -> None:
    fetch = AsyncMock(
        side_effect=[
            RuntimeError("private"),
            DeepseekUsage(ok=False, failure=UsageFailure.TIMEOUT),
        ]
    )
    observer = DeepSeekBalanceObserver(fetch, repository, interval_seconds=0)

    await observer.start()
    for _ in range(100):
        if fetch.await_count >= 2:
            break
        await asyncio.sleep(0)
    await observer.stop()

    assert fetch.await_count >= 2
    assert observer.running is False


async def _start_manager(
    tmp_path: Path,
    *,
    is_main: bool,
    runtime: DeepseekRuntime,
) -> tuple[ObserverManager, MagicMock, AsyncMock]:
    manager = ObserverManager(
        AgentConfig(claude_token_keepalive=False),
        DuctorPaths(ductor_home=tmp_path),
    )
    manager.heartbeat.start = AsyncMock()
    manager.heartbeat.stop = AsyncMock()
    manager.cleanup.start = AsyncMock()
    manager.cleanup.stop = AsyncMock()
    usage_service = MagicMock()
    fetch = AsyncMock(return_value=DeepseekUsage(ok=False, failure=UsageFailure.UNAVAILABLE))
    with (
        patch("ductor_bot.orchestrator.observers.watch_rule_files", new_callable=AsyncMock),
        patch("ductor_bot.orchestrator.observers.watch_skill_sync", new_callable=AsyncMock),
        patch("ductor_bot.orchestrator.observers.fetch_deepseek_balance", fetch),
    ):
        await manager.start_all(
            is_main=is_main,
            deepseek_runtime=runtime,
            usage_service=usage_service,
        )
        await asyncio.sleep(0)
    return manager, usage_service, fetch


@pytest.mark.parametrize(
    ("is_main", "configured", "expected"),
    [(True, True, True), (True, False, False), (False, True, False)],
)
async def test_manager_starts_balance_observer_only_for_configured_main(
    tmp_path: Path,
    is_main: bool,
    configured: bool,
    expected: bool,
) -> None:
    manager, _service, fetch = await _start_manager(
        tmp_path,
        is_main=is_main,
        runtime=_runtime(configured=configured),
    )

    assert (manager.deepseek_balance is not None) is expected
    assert (fetch.await_count > 0) is expected
    if not is_main:
        assert not (tmp_path / "deepseek_balance_snapshots.json").exists()
    await manager.stop_all()
    assert manager.deepseek_balance is None


async def test_manager_hot_reload_stops_and_restarts_balance_observer(
    tmp_path: Path,
) -> None:
    manager, service, _fetch = await _start_manager(
        tmp_path,
        is_main=True,
        runtime=_runtime(),
    )

    disabled = _runtime(configured=False)
    await manager.reconfigure_deepseek(disabled, ZoneInfo("UTC"))
    assert manager.deepseek_balance is None
    service.update_deepseek.assert_called_with(disabled, ZoneInfo("UTC"))

    enabled = _runtime()
    await manager.reconfigure_deepseek(enabled, ZoneInfo("Asia/Shanghai"))
    assert manager.deepseek_balance is not None
    assert manager.deepseek_balance.running
    service.update_deepseek.assert_called_with(enabled, ZoneInfo("Asia/Shanghai"))

    await manager.stop_all()
