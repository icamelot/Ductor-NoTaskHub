"""Localized rendering for provider-neutral usage reports."""

from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo

from ductor_bot.i18n import t
from ductor_bot.usage.models import (
    BalanceDelta,
    PlanUsage,
    UsageFailure,
    UsageReport,
    UsageWindow,
)


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _error(failure: UsageFailure | None) -> str:
    bounded = failure or UsageFailure.UNAVAILABLE
    return t(f"usage.error_{bounded.value}")


def _window(
    window: UsageWindow | None,
    *,
    label: str,
    timezone: ZoneInfo,
) -> str:
    if window is None:
        return t("usage.window_unavailable")
    percent = min(window.used_percent, Decimal(100))
    rendered = t(label, percent=_decimal(percent))
    if window.resets_at is not None:
        reset = window.resets_at.astimezone(timezone).strftime("%Y-%m-%d %H:%M %Z")
        rendered = f"{rendered} ({t('usage.resets', time=reset)})"
    return rendered


def _plan_lines(usage: PlanUsage, *, timezone: ZoneInfo) -> list[str]:
    lines: list[str] = []
    if usage.plan:
        lines.append(t("usage.plan", plan=usage.plan))
    if not usage.ok:
        lines.append(_error(usage.failure))
        return lines
    short_label = "usage.five_hour" if usage.provider == "claude" else "usage.short_window"
    lines.extend(
        [
            _window(usage.short_window, label=short_label, timezone=timezone),
            _window(usage.weekly_window, label="usage.weekly", timezone=timezone),
        ]
    )
    return lines


def _delta_line(delta: BalanceDelta | None, currency: str) -> str:
    if delta is None or delta.change is None or delta.kind == "unavailable":
        return t("usage.daily_unavailable")
    key = "usage.spent_today" if delta.kind == "spend" else "usage.recharged_today"
    return t(key, amount=_decimal(abs(delta.change)), currency=currency)


def format_usage(report: UsageReport, *, timezone: ZoneInfo) -> str:
    """Render exactly three ordered provider sections using localized prose."""
    lines = [t("usage.header"), "", f"**{t('usage.deepseek')}**"]
    if report.deepseek.ok:
        deltas = {item.currency: item for item in report.deltas}
        for balance in report.deepseek.balances:
            lines.extend(
                [
                    t(
                        "usage.balance",
                        amount=_decimal(balance.total),
                        currency=balance.currency,
                    ),
                    _delta_line(deltas.get(balance.currency), balance.currency),
                ]
            )
    else:
        lines.append(_error(report.deepseek.failure))

    lines.extend(["", f"**{t('usage.claude')}**"])
    lines.extend(_plan_lines(report.claude, timezone=timezone))
    lines.extend(["", f"**{t('usage.codex')}**"])
    lines.extend(_plan_lines(report.codex, timezone=timezone))
    return "\n".join(lines)
