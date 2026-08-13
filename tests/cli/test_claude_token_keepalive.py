"""Tests for main-only Claude OAuth login-token keepalive."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Self
from unittest.mock import patch

import aiohttp
import pytest

from ductor_bot.cli.claude_token_keepalive import ClaudeTokenKeepalive


class _Clock:
    def __init__(self, wall: float = 1_700_000_000, monotonic: float = 100) -> None:
        self.wall = wall
        self.monotonic = monotonic

    def wall_time(self) -> float:
        return self.wall

    def monotonic_time(self) -> float:
        return self.monotonic


class _Response:
    def __init__(
        self,
        status: int,
        payload: object,
        *,
        before_json: object = None,
    ) -> None:
        self.status = status
        self.payload = payload
        self.before_json = before_json
        self.json_calls = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def json(self, *, content_type: object = None) -> object:
        self.json_calls += 1
        if callable(self.before_json):
            self.before_json()
        return self.payload


class _Session:
    def __init__(
        self,
        response: _Response | BaseException,
        captured: dict[str, object],
        **kwargs: object,
    ) -> None:
        self.response = response
        self.captured = captured
        captured.update(kwargs)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def post(self, url: str, *, json: object) -> _Response:
        self.captured["url"] = url
        self.captured["json"] = json
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _document(
    clock: _Clock,
    *,
    expires_in: float = 60,
    refresh_token: str | None = "refresh-secret",
) -> dict[str, object]:
    oauth: dict[str, object] = {
        "accessToken": "access-secret",
        "expiresAt": (clock.wall + expires_in) * 1000,
        "subscriptionType": "max",
        "unknownOauth": {"keep": True},
    }
    if refresh_token is not None:
        oauth["refreshToken"] = refresh_token
    return {"claudeAiOauth": oauth, "unknownTop": {"keep": True}}


def _write(path: Path, document: object) -> bytes:
    evidence = json.dumps(document, separators=(",", ":")).encode()
    path.write_bytes(evidence)
    return evidence


def _directory_entries(path: Path) -> list[Path]:
    return list(path.iterdir())


def _keepalive(path: Path, clock: _Clock) -> ClaudeTokenKeepalive:
    return ClaudeTokenKeepalive(
        path,
        wall_time=clock.wall_time,
        monotonic=clock.monotonic_time,
    )


@pytest.mark.parametrize(
    "contents",
    [
        None,
        b"not json",
        b"{}",
        json.dumps({"claudeAiOauth": {}}).encode(),
        json.dumps({"claudeAiOauth": {"refreshToken": "refresh", "expiresAt": "invalid"}}).encode(),
    ],
)
async def test_ineligible_credentials_make_no_request(
    tmp_path: Path,
    contents: bytes | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / ".credentials.json"
    if contents is not None:
        path.write_bytes(contents)
    clock = _Clock()
    monkeypatch.setattr(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **_kwargs: pytest.fail("ineligible credentials must not call HTTP"),
    )

    assert await _keepalive(path, clock).refresh_once() is False


async def test_token_with_more_than_two_hours_remaining_makes_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    _write(path, _document(clock, expires_in=7201))
    monkeypatch.setattr(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **_kwargs: pytest.fail("fresh credentials must not call HTTP"),
    )

    assert await _keepalive(path, clock).refresh_once() is False


async def test_refresh_uses_fixed_endpoint_payload_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    _write(path, _document(clock))
    captured: dict[str, object] = {}
    response = _Response(200, {"access_token": "new-access", "expires_in": 3600})
    monkeypatch.setattr(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, captured, **kwargs),
    )

    assert await _keepalive(path, clock).refresh_once() is True
    assert captured["url"] == "https://platform.claude.com/v1/oauth/token"
    assert captured["json"] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-secret",
        "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
    }
    assert isinstance(captured["timeout"], aiohttp.ClientTimeout)
    assert captured["timeout"].total == 10


async def test_second_attempt_inside_four_monotonic_hours_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    _write(path, _document(clock))
    captured: dict[str, object] = {}
    response = _Response(500, {"secret": "must-not-be-read"})
    monkeypatch.setattr(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, captured, **kwargs),
    )
    keepalive = _keepalive(path, clock)

    assert await keepalive.refresh_once() is False
    clock.monotonic += 14_399
    assert await keepalive.refresh_once() is False

    assert response.json_calls == 0


async def test_success_preserves_unknown_fields_rotates_tokens_and_sets_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    original = _document(clock)
    _write(path, original)
    captured: dict[str, object] = {}
    response = _Response(
        200,
        {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "ignored": "provider-field",
        },
    )
    monkeypatch.setattr(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, captured, **kwargs),
    )

    assert await _keepalive(path, clock).refresh_once() is True

    written = json.loads(path.read_text())
    assert written["unknownTop"] == {"keep": True}
    oauth = written["claudeAiOauth"]
    assert oauth["unknownOauth"] == {"keep": True}
    assert oauth["subscriptionType"] == "max"
    assert oauth["accessToken"] == "new-access"
    assert oauth["refreshToken"] == "new-refresh"
    assert oauth["expiresAt"] == (clock.wall + 3600) * 1000
    assert path.stat().st_mode & 0o777 == 0o600
    assert await asyncio.to_thread(_directory_entries, tmp_path) == [path]


async def test_missing_rotated_refresh_token_preserves_existing_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    _write(path, _document(clock))
    response = _Response(200, {"access_token": "new-access", "expires_in": 3600})
    monkeypatch.setattr(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, {}, **kwargs),
    )

    assert await _keepalive(path, clock).refresh_once() is True
    assert json.loads(path.read_text())["claudeAiOauth"]["refreshToken"] == "refresh-secret"


async def test_refresh_rotation_race_discards_response(tmp_path: Path) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    _write(path, _document(clock))
    rotated = _write(path, _document(clock, refresh_token="refresh-secret"))

    def rotate() -> None:
        nonlocal rotated
        rotated = _write(path, _document(clock, refresh_token="other-process-token"))

    response = _Response(
        200,
        {"access_token": "new-access", "expires_in": 3600},
        before_json=rotate,
    )
    with patch(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, {}, **kwargs),
    ):
        assert await _keepalive(path, clock).refresh_once() is False

    assert path.read_bytes() == rotated


@pytest.mark.parametrize(
    "response",
    [
        _Response(500, {"raw_token": "must-not-log"}),
        TimeoutError("access-secret"),
        _Response(200, object()),
        _Response(200, {"expires_in": 3600}),
        _Response(200, {"access_token": "new", "expires_in": "invalid"}),
        _Response(200, {"access_token": "new", "expires_in": -1}),
    ],
)
async def test_refresh_failures_preserve_original_bytes_and_sanitize_logs(
    tmp_path: Path,
    response: _Response | BaseException,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    evidence = _write(path, _document(clock))
    with patch(
        "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
        lambda **kwargs: _Session(response, {}, **kwargs),
    ):
        assert await _keepalive(path, clock).refresh_once() is False

    assert path.read_bytes() == evidence
    assert "access-secret" not in caplog.text
    assert "refresh-secret" not in caplog.text
    assert "must-not-log" not in caplog.text


async def test_atomic_write_failure_preserves_original_and_cleans_temp(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".credentials.json"
    clock = _Clock()
    evidence = _write(path, _document(clock))
    response = _Response(200, {"access_token": "new-access", "expires_in": 3600})
    real_replace = os.replace

    def fail_target_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == path:
            raise OSError("simulated atomic failure")
        real_replace(source, target)

    with (
        patch(
            "ductor_bot.cli.claude_token_keepalive.aiohttp.ClientSession",
            lambda **kwargs: _Session(response, {}, **kwargs),
        ),
        patch("ductor_bot.cli.claude_token_keepalive.os.replace", fail_target_replace),
    ):
        assert await _keepalive(path, clock).refresh_once() is False

    assert path.read_bytes() == evidence
    assert await asyncio.to_thread(_directory_entries, tmp_path) == [path]


async def test_observer_loop_is_idempotent_and_cancel_safe(tmp_path: Path) -> None:
    clock = _Clock()
    keepalive = _keepalive(tmp_path / ".credentials.json", clock)
    with patch.object(keepalive, "refresh_once", side_effect=RuntimeError("private")) as refresh:
        keepalive._interval_seconds = 0
        await keepalive.start()
        first_task = keepalive._task
        await keepalive.start()
        for _ in range(100):
            if refresh.await_count >= 2:
                break
            await asyncio.sleep(0)
        await keepalive.stop()

    assert refresh.await_count >= 2
    assert first_task is not None
    assert keepalive.running is False
