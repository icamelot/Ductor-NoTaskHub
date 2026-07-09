"""Coding-plan usage (5h + weekly utilization) for Claude Code and Codex.

Reads the OAuth tokens the official CLIs already maintain under ``~/.claude``
and ``~/.codex`` (``$CODEX_HOME`` honored) and queries each provider's
subscription usage endpoint:

- Claude: ``GET https://claude.ai/api/oauth/usage``
  -> ``five_hour.utilization`` / ``seven_day.utilization`` (percent)
- Codex:  ``GET https://chatgpt.com/backend-api/wham/usage``
  -> ``rate_limit.primary_window`` (5h) / ``secondary_window`` (weekly)

Everything is best-effort: on missing/expired auth or any network error a
``PlanUsage`` with ``ok=False`` and a short ``error`` code is returned, so a
caller can still render the providers that did resolve.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_CLAUDE_USAGE_URL = "https://claude.ai/api/oauth/usage"
_CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


@dataclass(frozen=True, slots=True)
class PlanUsage:
    """Utilization snapshot for one subscription provider.

    ``error`` is one of ``"no_auth"`` / ``"expired"`` / ``"error"`` when
    ``ok`` is False. Percentages are 0-100; reset times are timezone-aware.
    """

    provider: str  # "claude" | "codex"
    ok: bool
    plan: str = ""
    error: str = ""
    five_hour_pct: float | None = None
    weekly_pct: float | None = None
    five_hour_reset: datetime | None = None
    weekly_reset: datetime | None = None


def _as_float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _epoch_to_dt(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _claude_home() -> Path:
    return Path.home() / ".claude"


def _codex_home() -> Path:
    env = os.environ.get("CODEX_HOME", "").strip()
    return Path(env) if env else Path.home() / ".codex"


def _load_claude_oauth(home: Path) -> tuple[str, str, bool] | None:
    """Return ``(access_token, subscription_type, expired)`` or None."""
    try:
        data = json.loads((home / ".credentials.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    oauth = data.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token:
        return None
    expires_at = oauth.get("expiresAt")
    expired = isinstance(expires_at, (int, float)) and expires_at / 1000 < time.time()
    return token, str(oauth.get("subscriptionType", "")), expired


def _load_codex_tokens(home: Path) -> tuple[str, str] | None:
    """Return ``(access_token, account_id)`` or None."""
    try:
        data = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access:
        return None
    account_id = tokens.get("account_id")
    return access, account_id if isinstance(account_id, str) else ""


def _parse_claude_usage(data: object, plan: str) -> PlanUsage:
    if not isinstance(data, dict):
        return PlanUsage("claude", ok=False, plan=plan, error="error")
    raw_five = data.get("five_hour")
    five = raw_five if isinstance(raw_five, dict) else {}
    raw_week = data.get("seven_day")
    week = raw_week if isinstance(raw_week, dict) else {}
    return PlanUsage(
        "claude",
        ok=True,
        plan=plan,
        five_hour_pct=_as_float(five.get("utilization")),
        weekly_pct=_as_float(week.get("utilization")),
        five_hour_reset=_parse_iso(five.get("resets_at")),
        weekly_reset=_parse_iso(week.get("resets_at")),
    )


def _parse_codex_usage(data: object) -> PlanUsage:
    if not isinstance(data, dict):
        return PlanUsage("codex", ok=False, error="error")
    plan = str(data.get("plan_type", ""))
    raw_rl = data.get("rate_limit")
    rl = raw_rl if isinstance(raw_rl, dict) else {}
    raw_prim = rl.get("primary_window")
    prim = raw_prim if isinstance(raw_prim, dict) else {}
    raw_sec = rl.get("secondary_window")
    sec = raw_sec if isinstance(raw_sec, dict) else {}
    return PlanUsage(
        "codex",
        ok=True,
        plan=plan,
        five_hour_pct=_as_float(prim.get("used_percent")),
        weekly_pct=_as_float(sec.get("used_percent")),
        five_hour_reset=_epoch_to_dt(prim.get("reset_at")),
        weekly_reset=_epoch_to_dt(sec.get("reset_at")),
    )


async def fetch_claude_usage(home: Path | None = None) -> PlanUsage:
    """Fetch Claude subscription 5h + weekly utilization (best-effort)."""
    creds = _load_claude_oauth(home or _claude_home())
    if creds is None:
        return PlanUsage("claude", ok=False, error="no_auth")
    token, plan, expired = creds
    if expired:
        return PlanUsage("claude", ok=False, plan=plan, error="expired")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": "ductor-usage/1.0",
    }
    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
            session.get(_CLAUDE_USAGE_URL) as resp,
        ):
            if resp.status in (401, 403):
                return PlanUsage("claude", ok=False, plan=plan, error="expired")
            if resp.status != 200:
                return PlanUsage("claude", ok=False, plan=plan, error="error")
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        logger.warning("Claude usage query failed", exc_info=True)
        return PlanUsage("claude", ok=False, plan=plan, error="error")
    return _parse_claude_usage(data, plan)


async def fetch_codex_usage(home: Path | None = None) -> PlanUsage:
    """Fetch Codex subscription 5h + weekly utilization (best-effort)."""
    creds = _load_codex_tokens(home or _codex_home())
    if creds is None:
        return PlanUsage("codex", ok=False, error="no_auth")
    access, account_id = creds
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
        "User-Agent": "ductor-usage/1.0",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
            session.get(_CODEX_USAGE_URL) as resp,
        ):
            if resp.status in (401, 403):
                return PlanUsage("codex", ok=False, error="expired")
            if resp.status != 200:
                return PlanUsage("codex", ok=False, error="error")
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        logger.warning("Codex usage query failed", exc_info=True)
        return PlanUsage("codex", ok=False, error="error")
    return _parse_codex_usage(data)
