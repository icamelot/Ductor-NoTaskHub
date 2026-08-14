"""Tests for provider-neutral usage aggregation and formatting."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.usage.formatting import format_usage
from ductor_bot.usage.models import (
    Balance,
    BalanceDelta,
    DeepseekUsage,
    PlanUsage,
    UsageFailure,
    UsageReport,
    UsageWindow,
)
from ductor_bot.usage.service import UsageService


def _runtime(base_url: str = "https://api.deepseek.com/anthropic") -> DeepseekRuntime:
    return DeepseekRuntime(
        True,
        base_url,
        ("deepseek-chat",),
        api_key="deepseek-secret",
    )


def _successes() -> tuple[DeepseekUsage, PlanUsage, PlanUsage]:
    return (
        DeepseekUsage(ok=True, balances=(Balance("CNY", Decimal(10)),)),
        PlanUsage(provider="claude", ok=True),
        PlanUsage(provider="codex", ok=True),
    )


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.deltas: tuple[BalanceDelta, ...] = ()
        self.delta_error: Exception | None = None
        self.record_error: Exception | None = None

    async def today_deltas(
        self,
        current: tuple[Balance, ...],
        *,
        timezone: ZoneInfo,
        now: datetime | None = None,
    ) -> tuple[BalanceDelta, ...]:
        self.calls.append(("deltas", (current, timezone)))
        if self.delta_error:
            raise self.delta_error
        return self.deltas

    async def record(
        self,
        balances: tuple[Balance, ...],
        *,
        captured_at: datetime | None = None,
    ) -> bool:
        self.calls.append(("record", balances))
        if self.record_error:
            raise self.record_error
        return True


def _service(
    repository: _Repository,
    *,
    is_main: bool = True,
    deepseek_fetch: Any = None,
    claude_fetch: Any = None,
    codex_fetch: Any = None,
) -> UsageService:
    deepseek, claude, codex = _successes()
    return UsageService(
        _runtime(),
        repository,  # type: ignore[arg-type]
        user_timezone=ZoneInfo("UTC"),
        is_main=is_main,
        deepseek_fetch=deepseek_fetch or AsyncMock(return_value=deepseek),
        claude_fetch=claude_fetch or AsyncMock(return_value=claude),
        codex_fetch=codex_fetch or AsyncMock(return_value=codex),
    )


async def test_collect_starts_all_clients_concurrently() -> None:
    started = {name: asyncio.Event() for name in ("deepseek", "claude", "codex")}
    release = asyncio.Event()
    deepseek, claude, codex = _successes()

    async def deepseek_client(_runtime: DeepseekRuntime) -> DeepseekUsage:
        started["deepseek"].set()
        await release.wait()
        return deepseek

    async def claude_client() -> PlanUsage:
        started["claude"].set()
        await release.wait()
        return claude

    async def codex_client() -> PlanUsage:
        started["codex"].set()
        await release.wait()
        return codex

    service = _service(
        _Repository(),
        deepseek_fetch=deepseek_client,
        claude_fetch=claude_client,
        codex_fetch=codex_client,
    )
    task = asyncio.create_task(service.collect())
    await asyncio.gather(*(event.wait() for event in started.values()))
    release.set()

    report = await task

    assert report.deepseek.ok
    assert report.claude.ok
    assert report.codex.ok


@pytest.mark.parametrize("provider", ["deepseek", "claude", "codex"])
@pytest.mark.parametrize(
    ("error", "failure"),
    [(TimeoutError(), UsageFailure.TIMEOUT), (RuntimeError("private"), UsageFailure.UNAVAILABLE)],
)
async def test_provider_errors_are_independently_bounded(
    provider: str, error: Exception, failure: UsageFailure
) -> None:
    deepseek, claude, codex = _successes()

    async def deepseek_client(_runtime: DeepseekRuntime) -> DeepseekUsage:
        if provider == "deepseek":
            raise error
        return deepseek

    async def claude_client() -> PlanUsage:
        if provider == "claude":
            raise error
        return claude

    async def codex_client() -> PlanUsage:
        if provider == "codex":
            raise error
        return codex

    report = await _service(
        _Repository(),
        deepseek_fetch=deepseek_client,
        claude_fetch=claude_client,
        codex_fetch=codex_client,
    ).collect()

    failed = getattr(report, provider)
    assert failed.ok is False
    assert failed.failure is failure
    assert all(getattr(report, name).ok for name in {"deepseek", "claude", "codex"} - {provider})


@pytest.mark.parametrize("provider", ["deepseek", "claude", "codex"])
async def test_provider_cancellation_propagates(provider: str) -> None:
    deepseek, claude, codex = _successes()

    async def deepseek_client(_runtime: DeepseekRuntime) -> DeepseekUsage:
        if provider == "deepseek":
            raise asyncio.CancelledError
        return deepseek

    async def claude_client() -> PlanUsage:
        if provider == "claude":
            raise asyncio.CancelledError
        return claude

    async def codex_client() -> PlanUsage:
        if provider == "codex":
            raise asyncio.CancelledError
        return codex

    with pytest.raises(asyncio.CancelledError):
        await _service(
            _Repository(),
            deepseek_fetch=deepseek_client,
            claude_fetch=claude_client,
            codex_fetch=codex_client,
        ).collect()


async def test_main_reads_history_before_recording_once() -> None:
    repository = _Repository()
    repository.deltas = (BalanceDelta("CNY", Decimal(10), Decimal(2), "spend"),)

    report = await _service(repository).collect()

    assert report.deltas == repository.deltas
    assert [call[0] for call in repository.calls] == ["deltas", "record"]


async def test_subagent_reads_history_without_recording() -> None:
    repository = _Repository()

    await _service(repository, is_main=False).collect()

    assert [call[0] for call in repository.calls] == ["deltas"]


@pytest.mark.parametrize("failure_point", ["deltas", "record"])
async def test_snapshot_failure_does_not_hide_current_balance(failure_point: str) -> None:
    repository = _Repository()
    if failure_point == "deltas":
        repository.delta_error = OSError("private path")
    else:
        repository.record_error = OSError("private path")

    report = await _service(repository).collect()

    assert report.deepseek.ok is True
    assert report.deepseek.balances == (Balance("CNY", Decimal(10)),)
    if failure_point == "deltas":
        assert report.deltas == ()


async def test_update_deepseek_replaces_runtime_and_timezone() -> None:
    repository = _Repository()
    fetch = AsyncMock(return_value=_successes()[0])
    service = _service(repository, deepseek_fetch=fetch)
    updated = _runtime("https://gateway.example/anthropic")

    service.update_deepseek(updated, ZoneInfo("Asia/Shanghai"))
    await service.collect()

    fetch.assert_awaited_once_with(updated)
    assert repository.calls[0][1][1] == ZoneInfo("Asia/Shanghai")


_TRANSLATIONS = {
    "usage.header": "**Usage**",
    "usage.deepseek": "DeepSeek",
    "usage.claude": "Claude Code",
    "usage.codex": "Codex",
    "usage.balance": "Balance: {amount} {currency}",
    "usage.spent_today": "Spent today: {amount} {currency}",
    "usage.recharged_today": "Recharged today: {amount} {currency}",
    "usage.daily_unavailable": "Today's change: unavailable",
    "usage.plan": "Plan: {plan}",
    "usage.short_window": "Short window: {percent}%",
    "usage.five_hour": "5-hour usage: {percent}%",
    "usage.weekly": "7-day usage: {percent}%",
    "usage.resets": "resets {time}",
    "usage.window_unavailable": "Unavailable",
    **{
        f"usage.error_{failure.value}": label
        for failure, label in {
            UsageFailure.DISABLED: "Disabled",
            UsageFailure.NOT_CONFIGURED: "Not configured",
            UsageFailure.NOT_LOGGED_IN: "Not logged in",
            UsageFailure.EXPIRED: "Login expired",
            UsageFailure.RATE_LIMITED: "Rate limited",
            UsageFailure.TIMEOUT: "Timed out",
            UsageFailure.MALFORMED_RESPONSE: "Malformed provider response",
            UsageFailure.UNAVAILABLE: "Unavailable",
        }.items()
    },
}


@pytest.fixture(autouse=True)
def localized_formatter(monkeypatch: pytest.MonkeyPatch) -> None:
    def translate(key: str, **kwargs: object) -> str:
        return _TRANSLATIONS[key].format(**kwargs)

    monkeypatch.setattr("ductor_bot.usage.formatting.t", translate)


def test_format_usage_renders_three_ordered_complete_sections() -> None:
    report = UsageReport(
        deepseek=DeepseekUsage(
            ok=True,
            balances=(
                Balance("CNY", Decimal("100.50")),
                Balance("USD", Decimal("7.25")),
                Balance("EUR", Decimal(3)),
            ),
        ),
        claude=PlanUsage(
            provider="claude",
            ok=True,
            plan="max",
            short_window=UsageWindow(Decimal("12.50"), datetime(2026, 8, 13, 1, tzinfo=UTC)),
            weekly_window=UsageWindow(Decimal(40), None),
        ),
        codex=PlanUsage(
            provider="codex",
            ok=True,
            plan="plus",
            short_window=None,
            weekly_window=UsageWindow(Decimal(100), None),
        ),
        deltas=(
            BalanceDelta("CNY", Decimal("100.50"), Decimal("2.5"), "spend"),
            BalanceDelta("USD", Decimal("7.25"), Decimal("-1.25"), "recharge"),
            BalanceDelta("EUR", Decimal(3), None, "unavailable"),
        ),
    )

    rendered = format_usage(report, timezone=ZoneInfo("Asia/Shanghai"))

    assert rendered.index("DeepSeek") < rendered.index("Claude Code") < rendered.index("Codex")
    assert rendered.count("**DeepSeek**") == 1
    assert "Balance: 100.50 CNY" in rendered
    assert "Spent today: 2.5 CNY" in rendered
    assert "Recharged today: 1.25 USD" in rendered
    assert "Today's change: unavailable" in rendered
    assert "Plan: max" in rendered
    assert "Plan: plus" in rendered
    assert "5-hour usage: 12.50% (resets 2026-08-13 09:00 CST)" in rendered
    assert "7-day usage: 40%" in rendered
    assert "Short window: 100%" not in rendered
    assert "**Codex**\nPlan: plus\n7-day usage: 100%" in rendered
    assert "Unavailable\n7-day usage: 100%" not in rendered


def _report_with_codex(codex: PlanUsage) -> UsageReport:
    return UsageReport(
        deepseek=DeepseekUsage(ok=False, failure=UsageFailure.UNAVAILABLE),
        claude=PlanUsage(provider="claude", ok=False, failure=UsageFailure.UNAVAILABLE),
        codex=codex,
    )


def test_format_usage_hides_missing_weekly_window() -> None:
    rendered = format_usage(
        _report_with_codex(
            PlanUsage(
                provider="codex",
                ok=True,
                plan="plus",
                short_window=UsageWindow(Decimal(25), None),
            )
        ),
        timezone=ZoneInfo("UTC"),
    )

    codex_section = rendered.split("**Codex**\n", maxsplit=1)[1]
    assert codex_section == "Plan: plus\nShort window: 25%"


def test_format_usage_renders_one_unavailable_when_both_windows_are_missing() -> None:
    rendered = format_usage(
        _report_with_codex(PlanUsage(provider="codex", ok=True, plan="plus")),
        timezone=ZoneInfo("UTC"),
    )

    codex_section = rendered.split("**Codex**\n", maxsplit=1)[1]
    assert codex_section == "Plan: plus\nUnavailable"


@pytest.mark.parametrize("failure", list(UsageFailure))
def test_format_usage_localizes_every_failure(failure: UsageFailure) -> None:
    report = UsageReport(
        deepseek=DeepseekUsage(ok=False, failure=failure),
        claude=PlanUsage(provider="claude", ok=False, failure=failure),
        codex=PlanUsage(provider="codex", ok=False, failure=failure),
    )

    rendered = format_usage(report, timezone=ZoneInfo("UTC"))

    assert rendered.count(_TRANSLATIONS[f"usage.error_{failure.value}"]) == 3
    assert "secret-token" not in rendered
    assert "https://api.deepseek.com" not in rendered
    assert "private exception" not in rendered
