"""Tests for Claude/Codex coding-plan usage fetching."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Self
from unittest.mock import patch

import aiohttp

from ductor_bot.cli.plan_usage import (
    _load_claude_oauth,
    _load_codex_tokens,
    _parse_claude_usage,
    _parse_codex_usage,
    fetch_claude_usage,
    fetch_codex_usage,
)

# Real response shapes captured from the live endpoints.
_CLAUDE_SAMPLE = {
    "five_hour": {"utilization": 49.0, "resets_at": "2026-07-09T15:10:00.437762+00:00"},
    "seven_day": {"utilization": 21.0, "resets_at": "2026-07-15T10:00:00.437786+00:00"},
}
_CODEX_SAMPLE = {
    "plan_type": "plus",
    "rate_limit": {
        "primary_window": {
            "used_percent": 1,
            "limit_window_seconds": 18000,
            "reset_at": 1783611755,
        },
        "secondary_window": {
            "used_percent": 1,
            "limit_window_seconds": 604800,
            "reset_at": 1784177180,
        },
    },
}


class _FakeResp:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self, content_type: object = None) -> object:
        return self._payload


class _FakeSession:
    def __init__(self, resp: _FakeResp, raise_on_enter: Exception | None = None) -> None:
        self._resp = resp
        self._raise = raise_on_enter

    async def __aenter__(self) -> Self:
        if self._raise is not None:
            raise self._raise
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def get(self, url: str) -> _FakeResp:
        return self._resp


_SESSION_PATCH = "ductor_bot.cli.plan_usage.aiohttp.ClientSession"


def _write_claude(home: Path, expires_ms: int) -> None:
    (home / ".credentials.json").write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "tok-abc",
                    "subscriptionType": "pro",
                    "expiresAt": expires_ms,
                }
            }
        ),
        encoding="utf-8",
    )


def _write_codex(home: Path) -> None:
    (home / "auth.json").write_text(
        json.dumps({"tokens": {"access_token": "tok-xyz", "account_id": "acct-1"}}),
        encoding="utf-8",
    )


# -- parsing --


def test_parse_claude_usage() -> None:
    usage = _parse_claude_usage(_CLAUDE_SAMPLE, "pro")
    assert usage.ok
    assert usage.plan == "pro"
    assert usage.five_hour_pct == 49.0
    assert usage.weekly_pct == 21.0
    assert usage.five_hour_reset is not None
    assert usage.weekly_reset is not None


def test_parse_claude_usage_bad_shape() -> None:
    assert _parse_claude_usage("nope", "pro").ok is False
    partial = _parse_claude_usage({"five_hour": {}}, "pro")
    assert partial.ok
    assert partial.five_hour_pct is None


def test_parse_codex_usage() -> None:
    usage = _parse_codex_usage(_CODEX_SAMPLE)
    assert usage.ok
    assert usage.plan == "plus"
    assert usage.five_hour_pct == 1.0
    assert usage.weekly_pct == 1.0
    assert usage.five_hour_reset is not None
    assert usage.weekly_reset is not None


def test_parse_codex_usage_no_5h_window() -> None:
    """Codex dropped the 5h window: only the weekly window is present."""
    data = {
        "plan_type": "plus",
        "rate_limit": {
            "secondary_window": {
                "used_percent": 5,
                "limit_window_seconds": 604800,
                "reset_at": 1784177180,
            }
        },
    }
    usage = _parse_codex_usage(data)
    assert usage.ok
    assert usage.five_hour_pct is None
    assert usage.weekly_pct == 5.0


def test_parse_codex_usage_weekly_in_primary_slot() -> None:
    """Weekly window is classified by length even if it lands in primary_window."""
    data = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 7,
                "limit_window_seconds": 604800,
                "reset_at": 1784177180,
            }
        }
    }
    usage = _parse_codex_usage(data)
    assert usage.five_hour_pct is None
    assert usage.weekly_pct == 7.0


# -- token loading --


def test_load_claude_oauth(tmp_path: Path) -> None:
    _write_claude(tmp_path, expires_ms=int((time.time() + 3600) * 1000))
    creds = _load_claude_oauth(tmp_path)
    assert creds is not None
    token, plan, expired = creds
    assert token == "tok-abc"
    assert plan == "pro"
    assert expired is False


def test_load_claude_oauth_expired(tmp_path: Path) -> None:
    _write_claude(tmp_path, expires_ms=int((time.time() - 60) * 1000))
    creds = _load_claude_oauth(tmp_path)
    assert creds is not None
    assert creds[2] is True  # expired


def test_load_claude_oauth_missing(tmp_path: Path) -> None:
    assert _load_claude_oauth(tmp_path) is None


def test_load_codex_tokens(tmp_path: Path) -> None:
    _write_codex(tmp_path)
    creds = _load_codex_tokens(tmp_path)
    assert creds == ("tok-xyz", "acct-1")


def test_load_codex_tokens_missing(tmp_path: Path) -> None:
    assert _load_codex_tokens(tmp_path) is None


# -- fetch (mocked HTTP) --


async def test_fetch_claude_usage_ok(tmp_path: Path) -> None:
    _write_claude(tmp_path, expires_ms=int((time.time() + 3600) * 1000))
    session = _FakeSession(_FakeResp(200, _CLAUDE_SAMPLE))
    with patch(_SESSION_PATCH, return_value=session):
        usage = await fetch_claude_usage(tmp_path)
    assert usage.ok
    assert usage.five_hour_pct == 49.0


async def test_fetch_claude_usage_no_auth(tmp_path: Path) -> None:
    usage = await fetch_claude_usage(tmp_path)
    assert usage.ok is False
    assert usage.error == "no_auth"


async def test_fetch_claude_usage_expired_token(tmp_path: Path) -> None:
    _write_claude(tmp_path, expires_ms=int((time.time() - 60) * 1000))
    usage = await fetch_claude_usage(tmp_path)
    assert usage.ok is False
    assert usage.error == "expired"


async def test_fetch_claude_usage_401(tmp_path: Path) -> None:
    _write_claude(tmp_path, expires_ms=int((time.time() + 3600) * 1000))
    session = _FakeSession(_FakeResp(401, None))
    with patch(_SESSION_PATCH, return_value=session):
        usage = await fetch_claude_usage(tmp_path)
    assert usage.error == "expired"


async def test_fetch_claude_usage_network_error(tmp_path: Path) -> None:
    _write_claude(tmp_path, expires_ms=int((time.time() + 3600) * 1000))
    session = _FakeSession(_FakeResp(200, _CLAUDE_SAMPLE), raise_on_enter=aiohttp.ClientError("x"))
    with patch(_SESSION_PATCH, return_value=session):
        usage = await fetch_claude_usage(tmp_path)
    assert usage.error == "error"


async def test_fetch_codex_usage_ok(tmp_path: Path) -> None:
    _write_codex(tmp_path)
    session = _FakeSession(_FakeResp(200, _CODEX_SAMPLE))
    with patch(_SESSION_PATCH, return_value=session):
        usage = await fetch_codex_usage(tmp_path)
    assert usage.ok
    assert usage.plan == "plus"
    assert usage.weekly_pct == 1.0


async def test_fetch_codex_usage_no_auth(tmp_path: Path) -> None:
    usage = await fetch_codex_usage(tmp_path)
    assert usage.error == "no_auth"
