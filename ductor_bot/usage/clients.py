"""Independent HTTP and credential clients for provider usage data."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.usage.models import (
    Balance,
    DeepseekUsage,
    PlanUsage,
    UsageFailure,
    UsageWindow,
)

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_CLAUDE_URL = "https://claude.ai/api/oauth/usage"
_CODEX_URL = "https://chatgpt.com/backend-api/wham/usage"
_SHORT_WINDOW_MAX_SECONDS = 86400


def _decimal(value: object, *, percentage: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError from None
    if not result.is_finite() or result < 0:
        raise ValueError
    if percentage and result > 100:
        return Decimal(100)
    return result


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            raise ValueError from None
    if not isinstance(value, str) or not value:
        raise ValueError
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError from None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _parse_deepseek_balance(data: object) -> DeepseekUsage:
    if not isinstance(data, dict) or data.get("is_available") is not True:
        raise TypeError
    raw = data.get("balance_infos")
    if not isinstance(raw, list) or not raw:
        raise TypeError
    balances: list[Balance] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError
        currency = item.get("currency")
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError
        balances.append(
            Balance(currency=currency.strip().upper(), total=_decimal(item.get("total_balance")))
        )
    return DeepseekUsage(ok=True, balances=tuple(balances))


def parse_deepseek_balance(data: object) -> DeepseekUsage:
    try:
        return _parse_deepseek_balance(data)
    except (TypeError, ValueError):
        return DeepseekUsage(ok=False, failure=UsageFailure.MALFORMED_RESPONSE)


def _window(data: object, percent_key: str, reset_key: str) -> UsageWindow | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError
    if percent_key not in data:
        return None
    duration = data.get("limit_window_seconds")
    if duration is not None:
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise TypeError
        if isinstance(duration, float):
            if not duration.is_integer():
                raise ValueError
            duration = int(duration)
    return UsageWindow(
        used_percent=_decimal(data[percent_key], percentage=True),
        resets_at=_datetime(data.get(reset_key)),
        duration_seconds=duration,
    )


def _parse_claude_usage(data: object, plan: str) -> PlanUsage:
    if not isinstance(data, dict):
        raise TypeError
    return PlanUsage(
        provider="claude",
        ok=True,
        plan=plan,
        short_window=_window(data.get("five_hour"), "utilization", "resets_at"),
        weekly_window=_window(data.get("seven_day"), "utilization", "resets_at"),
    )


def parse_claude_usage(data: object, *, plan: str = "") -> PlanUsage:
    try:
        return _parse_claude_usage(data, plan)
    except (TypeError, ValueError):
        return PlanUsage(
            provider="claude", ok=False, plan=plan, failure=UsageFailure.MALFORMED_RESPONSE
        )


def _parse_codex_usage(data: object) -> PlanUsage:
    if not isinstance(data, dict):
        raise TypeError
    raw_limits = data.get("rate_limit", {})
    if not isinstance(raw_limits, dict):
        raise TypeError
    short: UsageWindow | None = None
    weekly: UsageWindow | None = None
    for raw in raw_limits.values():
        if not isinstance(raw, dict):
            continue
        window = _window(raw, "used_percent", "reset_at")
        if window is None:
            continue
        if (
            window.duration_seconds is not None
            and window.duration_seconds <= _SHORT_WINDOW_MAX_SECONDS
        ):
            short = window
        else:
            weekly = window
    plan = data.get("plan_type", "")
    return PlanUsage(
        provider="codex",
        ok=True,
        plan=plan if isinstance(plan, str) else str(plan),
        short_window=short,
        weekly_window=weekly,
    )


def parse_codex_usage(data: object) -> PlanUsage:
    try:
        return _parse_codex_usage(data)
    except (TypeError, ValueError):
        return PlanUsage(provider="codex", ok=False, failure=UsageFailure.MALFORMED_RESPONSE)


def deepseek_balance_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/user/balance", "", ""))


def _claude_credentials(home: Path) -> tuple[str, str, bool] | None:
    try:
        data = json.loads((home / ".credentials.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        return None
    expires = oauth.get("expiresAt")
    expired = (
        isinstance(expires, (int, float))
        and not isinstance(expires, bool)
        and expires / 1000 <= time.time()
    )
    plan = oauth.get("subscriptionType", "")
    return token, plan if isinstance(plan, str) else "", expired


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def _codex_credentials(home: Path) -> tuple[str, str] | None:
    try:
        data = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tokens = data.get("tokens") if isinstance(data, dict) else None
    if not isinstance(tokens, dict):
        return None
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        return None
    account = tokens.get("account_id", "")
    return access, account if isinstance(account, str) else ""


def _http_failure(status: int, *, authenticated: bool = True) -> UsageFailure | None:
    if status in {401, 403}:
        return UsageFailure.EXPIRED if authenticated else UsageFailure.NOT_LOGGED_IN
    if status == 429:
        return UsageFailure.RATE_LIMITED
    if status != 200:
        return UsageFailure.UNAVAILABLE
    return None


async def fetch_deepseek_balance(runtime: DeepseekRuntime) -> DeepseekUsage:  # noqa: PLR0911
    if not runtime.requested or runtime.error == "disabled":
        return DeepseekUsage(ok=False, failure=UsageFailure.DISABLED)
    if not runtime.configured:
        return DeepseekUsage(ok=False, failure=UsageFailure.NOT_CONFIGURED)
    headers = {"Authorization": f"Bearer {runtime.api_key}"}
    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
            session.get(deepseek_balance_url(runtime.base_url)) as response,
        ):
            failure = _http_failure(response.status)
            if failure:
                return DeepseekUsage(ok=False, failure=failure)
            try:
                data = await response.json(content_type=None)
            except (json.JSONDecodeError, ValueError, TypeError):
                return DeepseekUsage(ok=False, failure=UsageFailure.MALFORMED_RESPONSE)
    except TimeoutError:
        return DeepseekUsage(ok=False, failure=UsageFailure.TIMEOUT)
    except aiohttp.ClientError:
        return DeepseekUsage(ok=False, failure=UsageFailure.UNAVAILABLE)
    return parse_deepseek_balance(data)


async def fetch_claude_plan_usage(home: Path | None = None) -> PlanUsage:  # noqa: PLR0911
    credentials = _claude_credentials(home or Path.home() / ".claude")
    if credentials is None:
        return PlanUsage(provider="claude", ok=False, failure=UsageFailure.NOT_LOGGED_IN)
    token, plan, expired = credentials
    if expired:
        return PlanUsage(provider="claude", ok=False, plan=plan, failure=UsageFailure.EXPIRED)
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
    }
    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
            session.get(_CLAUDE_URL) as response,
        ):
            failure = _http_failure(response.status)
            if failure:
                return PlanUsage(provider="claude", ok=False, plan=plan, failure=failure)
            try:
                data = await response.json(content_type=None)
            except (json.JSONDecodeError, ValueError, TypeError):
                return PlanUsage(
                    provider="claude",
                    ok=False,
                    plan=plan,
                    failure=UsageFailure.MALFORMED_RESPONSE,
                )
    except TimeoutError:
        return PlanUsage(provider="claude", ok=False, plan=plan, failure=UsageFailure.TIMEOUT)
    except aiohttp.ClientError:
        return PlanUsage(provider="claude", ok=False, plan=plan, failure=UsageFailure.UNAVAILABLE)
    return parse_claude_usage(data, plan=plan)


async def fetch_codex_plan_usage(home: Path | None = None) -> PlanUsage:
    credentials = _codex_credentials(home or _codex_home())
    if credentials is None:
        return PlanUsage(provider="codex", ok=False, failure=UsageFailure.NOT_LOGGED_IN)
    token, account = credentials
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "ductor-usage/1.0",
    }
    if account:
        headers["chatgpt-account-id"] = account
    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
            session.get(_CODEX_URL) as response,
        ):
            failure = _http_failure(response.status)
            if failure:
                return PlanUsage(provider="codex", ok=False, failure=failure)
            try:
                data = await response.json(content_type=None)
            except (json.JSONDecodeError, ValueError, TypeError):
                return PlanUsage(
                    provider="codex", ok=False, failure=UsageFailure.MALFORMED_RESPONSE
                )
    except TimeoutError:
        return PlanUsage(provider="codex", ok=False, failure=UsageFailure.TIMEOUT)
    except aiohttp.ClientError:
        return PlanUsage(provider="codex", ok=False, failure=UsageFailure.UNAVAILABLE)
    return parse_codex_usage(data)
