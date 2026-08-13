"""Main-agent keepalive for Claude OAuth login credentials."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"  # noqa: S105 - endpoint URL
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


def _read_document(path: Path) -> tuple[dict[str, object], dict[str, object]] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    oauth = raw.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    return raw, oauth


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _eligible_refresh_token(
    loaded: tuple[dict[str, object], dict[str, object]] | None,
    *,
    wall_time: float,
    refresh_before_seconds: float,
) -> str | None:
    if loaded is None:
        return None
    _document, oauth = loaded
    refresh_token = oauth.get("refreshToken")
    expires_at_ms = _number(oauth.get("expiresAt"))
    if not isinstance(refresh_token, str) or not refresh_token or expires_at_ms is None:
        return None
    needs_refresh = expires_at_ms / 1000 - wall_time <= refresh_before_seconds
    return refresh_token if needs_refresh else None


def _validated_response(
    response: dict[str, object],
) -> tuple[str, str | None, float] | None:
    access_token = response.get("access_token")
    expires_in = _number(response.get("expires_in"))
    rotated_token = response.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        return None
    if expires_in is None or expires_in <= 0:
        return None
    if rotated_token is not None and (not isinstance(rotated_token, str) or not rotated_token):
        return None
    return access_token, rotated_token, expires_in


def _secure_atomic_save(path: Path, document: dict[str, object]) -> None:
    content = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    fd, temporary_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)  # noqa: PTH105 - explicit atomic replacement contract
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        temporary.unlink(missing_ok=True)
        raise


class ClaudeTokenKeepalive:
    """Refresh a near-expiry Claude login token without racing token rotation."""

    def __init__(  # noqa: PLR0913 - clocks are injectable for deterministic timing
        self,
        credentials_path: Path,
        *,
        interval_seconds: float = 1800,
        refresh_before_seconds: float = 7200,
        min_attempt_gap_seconds: float = 14400,
        wall_time: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._credentials_path = credentials_path
        self._interval_seconds = interval_seconds
        self._refresh_before_seconds = refresh_before_seconds
        self._min_attempt_gap_seconds = min_attempt_gap_seconds
        self._wall_time = wall_time
        self._monotonic = monotonic
        self._last_attempt: float | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(
            self._run(),
            name="claude-token-keepalive",
        )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def refresh_once(self) -> bool:
        loaded = await asyncio.to_thread(_read_document, self._credentials_path)
        refresh_token = _eligible_refresh_token(
            loaded,
            wall_time=self._wall_time(),
            refresh_before_seconds=self._refresh_before_seconds,
        )
        if refresh_token is None:
            return False
        now = self._monotonic()
        if (
            self._last_attempt is not None
            and now - self._last_attempt < self._min_attempt_gap_seconds
        ):
            return False

        response = await self._request(refresh_token, now)
        if response is None:
            return False
        validated = _validated_response(response)
        if validated is None:
            logger.warning("Claude token refresh category=malformed_response")
            return False
        return await self._replace_if_current(refresh_token, validated)

    async def _replace_if_current(
        self,
        request_token: str,
        refreshed: tuple[str, str | None, float],
    ) -> bool:
        access_token, rotated_token, expires_in = refreshed
        fresh = await asyncio.to_thread(_read_document, self._credentials_path)
        if fresh is None:
            logger.warning("Claude token refresh category=credentials_unavailable")
            return False
        fresh_document, fresh_oauth = fresh
        if fresh_oauth.get("refreshToken") != request_token:
            logger.info("Claude token refresh category=credentials_changed")
            return False

        fresh_oauth["accessToken"] = access_token
        if isinstance(rotated_token, str):
            fresh_oauth["refreshToken"] = rotated_token
        fresh_oauth["expiresAt"] = int((self._wall_time() + expires_in) * 1000)
        try:
            await asyncio.to_thread(
                _secure_atomic_save,
                self._credentials_path,
                fresh_document,
            )
        except asyncio.CancelledError:
            raise
        except OSError:
            logger.warning("Claude token refresh category=write_failed")
            return False
        logger.info("Claude token refresh category=success")
        return True

    async def _request(
        self,
        refresh_token: str,
        attempt_time: float,
    ) -> dict[str, object] | None:
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                self._last_attempt = attempt_time
                async with session.post(
                    _TOKEN_URL,
                    json={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": _CLIENT_ID,
                    },
                ) as response:
                    if response.status != 200:
                        logger.warning("Claude token refresh category=http_failure")
                        return None
                    payload = await response.json(content_type=None)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            logger.warning("Claude token refresh category=timeout")
            return None
        except (aiohttp.ClientError, OSError, json.JSONDecodeError, ValueError, TypeError):
            logger.warning("Claude token refresh category=unavailable")
            return None
        if not isinstance(payload, dict):
            logger.warning("Claude token refresh category=malformed_response")
            return None
        return payload

    async def _run(self) -> None:
        while True:
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Claude token keepalive category=unavailable")
            await asyncio.sleep(self._interval_seconds)
