"""Tests for the Claude login-token keep-alive."""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path
from typing import Self
from unittest.mock import patch

import aiohttp

from ductor_bot.cli import claude_token_keepalive as kal


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

    async def text(self) -> str:
        return json.dumps(self._payload) if self._payload is not None else ""


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

    def post(self, url: str, data: object = None) -> _FakeResp:
        return self._resp


_SESSION_PATCH = "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession"


def _write_creds(home: Path, *, refresh_token: str = "rt-old", expires_ms: int = 0) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    creds = home / ".credentials.json"
    creds.write_text(
        json.dumps(
            {
                "claudeAiOauth": {
                    "accessToken": "at-old",
                    "refreshToken": refresh_token,
                    "expiresAt": expires_ms,
                    "subscriptionType": "pro",
                }
            }
        )
    )
    return creds


_OK_PAYLOAD = {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 28800}


async def test_refresh_writes_new_tokens_and_preserves_fields(tmp_path: Path) -> None:
    creds = _write_creds(tmp_path)
    session = _FakeSession(_FakeResp(200, _OK_PAYLOAD))
    with patch(_SESSION_PATCH, return_value=session):
        ok = await kal.refresh_claude_token(tmp_path)
    assert ok is True
    data = json.loads(creds.read_text())["claudeAiOauth"]
    assert data["accessToken"] == "at-new"
    assert data["refreshToken"] == "rt-new"
    assert data["subscriptionType"] == "pro"  # preserved
    assert data["expiresAt"] > int(time.time() * 1000)


async def test_refresh_written_file_is_private(tmp_path: Path) -> None:
    creds = _write_creds(tmp_path)
    session = _FakeSession(_FakeResp(200, _OK_PAYLOAD))
    with patch(_SESSION_PATCH, return_value=session):
        await kal.refresh_claude_token(tmp_path)
    mode = stat.S_IMODE(creds.stat().st_mode)
    assert mode == 0o600


async def test_refresh_no_credentials(tmp_path: Path) -> None:
    assert await kal.refresh_claude_token(tmp_path) is False


async def test_refresh_missing_refresh_token(tmp_path: Path) -> None:
    _write_creds(tmp_path, refresh_token="")
    assert await kal.refresh_claude_token(tmp_path) is False


async def test_refresh_http_error_leaves_file_untouched(tmp_path: Path) -> None:
    creds = _write_creds(tmp_path)
    before = creds.read_text()
    session = _FakeSession(_FakeResp(400, {"error": "invalid_grant"}))
    with patch(_SESSION_PATCH, return_value=session):
        ok = await kal.refresh_claude_token(tmp_path)
    assert ok is False
    assert creds.read_text() == before  # unchanged


async def test_refresh_network_error_leaves_file_untouched(tmp_path: Path) -> None:
    creds = _write_creds(tmp_path)
    before = creds.read_text()
    session = _FakeSession(_FakeResp(200, _OK_PAYLOAD), raise_on_enter=aiohttp.ClientError("x"))
    with patch(_SESSION_PATCH, return_value=session):
        ok = await kal.refresh_claude_token(tmp_path)
    assert ok is False
    assert creds.read_text() == before


async def test_refresh_response_without_access_token(tmp_path: Path) -> None:
    creds = _write_creds(tmp_path)
    before = creds.read_text()
    session = _FakeSession(_FakeResp(200, {"expires_in": 28800}))
    with patch(_SESSION_PATCH, return_value=session):
        ok = await kal.refresh_claude_token(tmp_path)
    assert ok is False
    assert creds.read_text() == before


def test_remaining_sec() -> None:
    future = {"expiresAt": int((time.time() + 3600) * 1000)}
    assert 3500 < kal._remaining_sec(future) < 3700
    assert kal._remaining_sec({}) == -1.0
