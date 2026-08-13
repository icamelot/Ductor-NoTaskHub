"""Typed, provider-neutral usage result models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal


class UsageFailure(StrEnum):
    DISABLED = "disabled"
    NOT_CONFIGURED = "not_configured"
    NOT_LOGGED_IN = "not_logged_in"
    EXPIRED = "expired"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    MALFORMED_RESPONSE = "malformed_response"
    UNAVAILABLE = "unavailable"


UsageProvider = Literal["deepseek", "claude", "codex"]


@dataclass(frozen=True, slots=True)
class Balance:
    currency: str
    total: Decimal


@dataclass(frozen=True, slots=True)
class BalanceDelta:
    currency: str
    current: Decimal
    change: Decimal | None
    kind: Literal["spend", "recharge", "unavailable"]


@dataclass(frozen=True, slots=True)
class UsageWindow:
    used_percent: Decimal
    resets_at: datetime | None
    duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class DeepseekUsage:
    ok: bool
    balances: tuple[Balance, ...] = ()
    failure: UsageFailure | None = None


@dataclass(frozen=True, slots=True)
class PlanUsage:
    provider: Literal["claude", "codex"]
    ok: bool
    plan: str = ""
    short_window: UsageWindow | None = None
    weekly_window: UsageWindow | None = None
    failure: UsageFailure | None = None


ProviderUsage = DeepseekUsage | PlanUsage


def failure_result(provider: UsageProvider, failure: UsageFailure) -> ProviderUsage:
    if provider == "deepseek":
        return DeepseekUsage(ok=False, failure=failure)
    return PlanUsage(provider=provider, ok=False, failure=failure)
