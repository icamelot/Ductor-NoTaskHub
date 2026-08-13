"""Periodic main-agent DeepSeek balance observation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from ductor_bot.usage.models import DeepseekUsage
from ductor_bot.usage.snapshots import BalanceSnapshotRepository

logger = logging.getLogger(__name__)


class DeepSeekBalanceObserver:
    """Collect valid balance samples immediately and at a fixed interval."""

    def __init__(
        self,
        fetch: Callable[[], Awaitable[DeepseekUsage]],
        repository: BalanceSnapshotRepository,
        *,
        interval_seconds: float = 1800,
    ) -> None:
        self._fetch = fetch
        self._repository = repository
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(
            self._run(),
            name="deepseek-balance-observer",
        )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def collect_once(self) -> None:
        result = await self._fetch()
        if result.ok and result.balances:
            await self._repository.record(result.balances)

    async def _run(self) -> None:
        while True:
            try:
                await self.collect_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("DeepSeek balance collection failed category=unavailable")
            await asyncio.sleep(self._interval_seconds)
