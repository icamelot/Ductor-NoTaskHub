"""Headless keep-alive for the Claude Code OAuth *login* token.

The subscription usage endpoint (``/usage``) needs the short-lived,
``user:profile``-scoped login token in ``~/.claude/.credentials.json`` — the
long-lived ``setup-token`` lacks that scope. That login token expires after
~8h and is normally only refreshed when the Claude CLI runs native Claude,
which a DeepSeek-driven ductor rarely does. This task refreshes it via its
``refresh_token`` before it expires so ``/usage`` keeps working without a
manual ``claude auth login``.

Runs as one of ductor's in-process asyncio background tasks (started in
``ObserverManager.start_all`` for the **main agent only**, cancelled on stop) —
no subprocess, so no zombies, and no concurrent refreshers to race the
single-use rotating refresh token.

Safety:
- refreshes only when the token expires within ``_REFRESH_BEFORE_SEC`` and at
  most once per ``_MIN_REFRESH_GAP_SEC`` (rate-limit / WAF-lockout guard),
- a 200 response proves the refresh_token we sent was current, so the file was
  not rotated under us; new tokens are written ATOMICALLY (temp + replace,
  mode 0600),
- on ANY failure the credentials file is left untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"  # noqa: S105 - endpoint, not a secret
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_USER_AGENT = "claude-cli/1.0 (external, cli)"

_CHECK_INTERVAL_SEC = 30 * 60  # wake every 30 min to check expiry (no POST)
_REFRESH_BEFORE_SEC = 2 * 3600  # refresh when the token expires within 2h
_MIN_REFRESH_GAP_SEC = 4 * 3600  # never POST more than once per 4h


def _creds_path(home: Path | None) -> Path:
    return (home or (Path.home() / ".claude")) / ".credentials.json"


def _read_credentials(path: Path) -> dict[str, object] | None:
    """Return the full credentials dict if it holds a ``claudeAiOauth`` object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("claudeAiOauth"), dict):
        return data
    return None


def _remaining_sec(oauth: dict[str, object]) -> float:
    exp = oauth.get("expiresAt")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return -1.0
    return exp / 1000 - time.time()


def _atomic_write(path: Path, data: dict[str, object]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.chmod(0o600)  # keep credentials private
    tmp.replace(path)  # atomic on the same filesystem


async def _post_refresh(refresh_token: str) -> object | None:
    """POST the refresh grant; return parsed JSON on 200, else None."""
    body = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": _CLIENT_ID}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }
    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
            session.post(_TOKEN_URL, data=body) as resp,
        ):
            if resp.status != 200:
                detail = (await resp.text())[:200]
                logger.warning("Claude token refresh failed: HTTP %s %s", resp.status, detail)
                return None
            payload: object = await resp.json(content_type=None)
            return payload
    except (aiohttp.ClientError, TimeoutError, ValueError):
        logger.warning("Claude token refresh error", exc_info=True)
        return None


def _apply_token_response(oauth: dict[str, object], payload: object) -> bool:
    """Update *oauth* in place from a token response. False if unusable."""
    if not isinstance(payload, dict):
        return False
    new_access = payload.get("access_token")
    if not isinstance(new_access, str) or not new_access:
        logger.warning("Claude token refresh: response missing access_token")
        return False
    oauth["accessToken"] = new_access
    new_refresh = payload.get("refresh_token")
    if isinstance(new_refresh, str) and new_refresh:
        oauth["refreshToken"] = new_refresh
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool):
        oauth["expiresAt"] = int((time.time() + float(expires_in)) * 1000)
    return True


async def refresh_claude_token(home: Path | None = None) -> bool:
    """Attempt one refresh. Returns True only when new tokens were written."""
    path = _creds_path(home)
    data = _read_credentials(path)
    if data is None:
        return False
    oauth = data["claudeAiOauth"]
    if not isinstance(oauth, dict):
        return False
    refresh_token = oauth.get("refreshToken")
    if not isinstance(refresh_token, str) or not refresh_token:
        return False

    payload = await _post_refresh(refresh_token)
    if payload is None or not _apply_token_response(oauth, payload):
        return False

    data["claudeAiOauth"] = oauth
    try:
        _atomic_write(path, data)
    except OSError:
        logger.warning("Claude token refreshed but write failed", exc_info=True)
        return False
    logger.info("Claude login token refreshed")
    return True


async def watch_claude_token(home: Path | None = None) -> None:
    """Background loop: keep the Claude login token fresh. Cancel-safe."""
    path = _creds_path(home)
    last_attempt = 0.0
    while True:
        try:
            data = _read_credentials(path)
            oauth = data.get("claudeAiOauth") if data else None
            if isinstance(oauth, dict):
                remaining = _remaining_sec(oauth)
                now = time.monotonic()
                if remaining < _REFRESH_BEFORE_SEC and (now - last_attempt) >= _MIN_REFRESH_GAP_SEC:
                    last_attempt = now
                    await refresh_claude_token(home)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Claude token keep-alive iteration failed", exc_info=True)
        await asyncio.sleep(_CHECK_INTERVAL_SEC)
