"""Tests for typed provider usage clients."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Self

import aiohttp
import pytest

from ductor_bot.cli.deepseek import DeepseekRuntime
from ductor_bot.usage.clients import (
    deepseek_balance_url,
    fetch_claude_plan_usage,
    fetch_codex_plan_usage,
    fetch_deepseek_balance,
    parse_claude_usage,
    parse_codex_usage,
    parse_deepseek_balance,
)
from ductor_bot.usage.models import Balance, UsageFailure


class _Response:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.payload = payload
        self.json_calls = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def json(self, *, content_type: object = None) -> object:
        self.json_calls += 1
        return self.payload


class _Session:
    def __init__(self, response: _Response, captured: dict[str, object], **kwargs: object) -> None:
        self.response = response
        self.captured = captured
        captured.update(kwargs)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def get(self, url: str) -> _Response:
        self.captured["url"] = url
        return self.response


def test_parse_deepseek_multiple_currency_balances() -> None:
    result = parse_deepseek_balance(
        {
            "is_available": True,
            "balance_infos": [
                {"currency": "CNY", "total_balance": "123.450"},
                {"currency": "USD", "total_balance": "7.25"},
            ],
        }
    )
    assert result.balances == (
        Balance(currency="CNY", total=Decimal("123.450")),
        Balance(currency="USD", total=Decimal("7.25")),
    )


def test_codex_windows_are_classified_by_duration_not_position() -> None:
    result = parse_codex_usage(
        {
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {
                    "limit_window_seconds": 604800,
                    "used_percent": 40,
                },
            },
        }
    )
    assert result.short_window is None
    assert result.weekly_window is not None
    assert result.weekly_window.used_percent == Decimal(40)


def test_claude_parser_normalizes_windows_and_iso_reset() -> None:
    result = parse_claude_usage(
        {
            "five_hour": {"utilization": "12.50", "resets_at": "2026-08-13T01:00:00Z"},
            "seven_day": {"utilization": 140},
        },
        plan="pro",
    )
    assert result.ok is True
    assert result.plan == "pro"
    assert result.short_window is not None
    assert result.short_window.used_percent == Decimal("12.50")
    assert result.short_window.resets_at == datetime(2026, 8, 13, 1, tzinfo=UTC)
    assert result.weekly_window is not None
    assert result.weekly_window.used_percent == Decimal(100)


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", -1])
def test_invalid_deepseek_money_is_malformed(value: object) -> None:
    result = parse_deepseek_balance(
        {"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": value}]}
    )
    assert result.ok is False
    assert result.failure is UsageFailure.MALFORMED_RESPONSE


def test_deepseek_balance_url_uses_only_configured_authority() -> None:
    assert (
        deepseek_balance_url("https://api.deepseek.com/anthropic?ignored=yes")
        == "https://api.deepseek.com/user/balance"
    )


async def test_missing_credentials_return_bounded_failure(tmp_path: Path) -> None:
    claude = await fetch_claude_plan_usage(tmp_path)
    codex = await fetch_codex_plan_usage(tmp_path)
    assert claude.failure is UsageFailure.NOT_LOGGED_IN
    assert codex.failure is UsageFailure.NOT_LOGGED_IN


async def test_locally_expired_claude_record_does_not_call_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".credentials.json").write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "token",
                    "subscriptionType": "pro",
                    "expiresAt": 1,
                }
            }
        )
    )
    monkeypatch.setattr(
        "ductor_bot.usage.clients.aiohttp.ClientSession",
        lambda **_kwargs: pytest.fail("expired credentials must not call HTTP"),
    )
    result = await fetch_claude_plan_usage(tmp_path)
    assert result.failure is UsageFailure.EXPIRED


async def test_disabled_and_unconfigured_deepseek_are_bounded() -> None:
    disabled = DeepseekRuntime(False, "https://api.deepseek.com/anthropic", (), error="disabled")
    missing = DeepseekRuntime(True, "https://api.deepseek.com/anthropic", (), error="missing_key")
    assert (await fetch_deepseek_balance(disabled)).failure is UsageFailure.DISABLED
    assert (await fetch_deepseek_balance(missing)).failure is UsageFailure.NOT_CONFIGURED


async def test_deepseek_http_uses_timeout_header_and_normalized_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = DeepseekRuntime(
        True,
        "https://api.deepseek.com/anthropic",
        ("deepseek-v4-pro",),
        api_key="token",
    )
    captured: dict[str, object] = {}
    response = _Response(
        200,
        {
            "is_available": True,
            "balance_infos": [{"currency": "CNY", "total_balance": "8.50"}],
        },
    )
    monkeypatch.setattr(
        "ductor_bot.usage.clients.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, captured, **kwargs),
    )

    result = await fetch_deepseek_balance(runtime)

    assert result.ok is True
    assert isinstance(captured["timeout"], aiohttp.ClientTimeout)
    assert captured["timeout"].total == 10
    assert captured["headers"] == {"Authorization": "Bearer token"}
    assert captured["url"] == "https://api.deepseek.com/user/balance"


@pytest.mark.parametrize(
    ("status", "failure"),
    [
        (401, UsageFailure.EXPIRED),
        (403, UsageFailure.EXPIRED),
        (429, UsageFailure.RATE_LIMITED),
        (500, UsageFailure.UNAVAILABLE),
    ],
)
async def test_deepseek_http_failure_never_reads_body(
    monkeypatch: pytest.MonkeyPatch, status: int, failure: UsageFailure
) -> None:
    runtime = DeepseekRuntime(
        True,
        "https://api.deepseek.com/anthropic",
        ("deepseek-v4-pro",),
        api_key="token",
    )
    response = _Response(status, {"secret": "must-not-be-read"})
    monkeypatch.setattr(
        "ductor_bot.usage.clients.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, {}, **kwargs),
    )
    result = await fetch_deepseek_balance(runtime)
    assert result.failure is failure
    assert response.json_calls == 0
