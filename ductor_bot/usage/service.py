"""Concurrent, provider-neutral usage collection service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal
from zoneinfo import ZoneInfo

from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.usage.clients import (
    fetch_claude_plan_usage,
    fetch_codex_plan_usage,
    fetch_deepseek_balance,
)
from ductor_bot.usage.models import (
    BalanceDelta,
    DeepseekUsage,
    PlanUsage,
    ProviderUsage,
    UsageFailure,
    UsageReport,
    failure_result,
)
from ductor_bot.usage.snapshots import BalanceSnapshotRepository

logger = logging.getLogger(__name__)

DeepseekFetch = Callable[[DeepseekRuntime], Awaitable[DeepseekUsage]]
PlanFetch = Callable[[], Awaitable[PlanUsage]]


async def _bounded(
    provider: Literal["deepseek", "claude", "codex"],
    call: Callable[[], Awaitable[ProviderUsage]],
) -> ProviderUsage:
    try:
        return await asyncio.wait_for(call(), timeout=10)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        return failure_result(provider, UsageFailure.TIMEOUT)
    except Exception:
        logger.warning("Usage query failed provider=%s category=unavailable", provider)
        return failure_result(provider, UsageFailure.UNAVAILABLE)


class UsageService:
    """Aggregate independent provider usage without coupling failure domains."""

    def __init__(  # noqa: PLR0913 - injectable clients are part of the public contract
        self,
        runtime: DeepseekRuntime,
        repository: BalanceSnapshotRepository,
        *,
        user_timezone: ZoneInfo,
        is_main: bool,
        deepseek_fetch: DeepseekFetch = fetch_deepseek_balance,
        claude_fetch: PlanFetch = fetch_claude_plan_usage,
        codex_fetch: PlanFetch = fetch_codex_plan_usage,
    ) -> None:
        self._runtime = runtime
        self._repository = repository
        self._user_timezone = user_timezone
        self._is_main = is_main
        self._deepseek_fetch = deepseek_fetch
        self._claude_fetch = claude_fetch
        self._codex_fetch = codex_fetch

    def update_deepseek(self, runtime: DeepseekRuntime, user_timezone: ZoneInfo) -> None:
        """Replace reloadable DeepSeek presentation state for future queries."""
        self._runtime, self._user_timezone = runtime, user_timezone

    async def collect(self) -> UsageReport:
        runtime = self._runtime
        timezone = self._user_timezone
        deepseek_result, claude_result, codex_result = await asyncio.gather(
            _bounded("deepseek", lambda: self._deepseek_fetch(runtime)),
            _bounded("claude", self._claude_fetch),
            _bounded("codex", self._codex_fetch),
        )
        deepseek = (
            deepseek_result
            if isinstance(deepseek_result, DeepseekUsage)
            else DeepseekUsage(ok=False, failure=UsageFailure.UNAVAILABLE)
        )
        claude = (
            claude_result
            if isinstance(claude_result, PlanUsage) and claude_result.provider == "claude"
            else PlanUsage(provider="claude", ok=False, failure=UsageFailure.UNAVAILABLE)
        )
        codex = (
            codex_result
            if isinstance(codex_result, PlanUsage) and codex_result.provider == "codex"
            else PlanUsage(provider="codex", ok=False, failure=UsageFailure.UNAVAILABLE)
        )

        deltas: tuple[BalanceDelta, ...] = ()
        if deepseek.ok and deepseek.balances:
            try:
                deltas = await self._repository.today_deltas(
                    deepseek.balances,
                    timezone=timezone,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Usage snapshot failed operation=deltas category=unavailable")
            if self._is_main:
                try:
                    await self._repository.record(deepseek.balances)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("Usage snapshot failed operation=record category=unavailable")

        return UsageReport(
            deepseek=deepseek,
            claude=claude,
            codex=codex,
            deltas=deltas,
        )
