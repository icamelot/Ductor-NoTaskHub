"""Tests for command handlers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Self
from unittest.mock import AsyncMock, patch

import aiohttp

from ductor_bot.cli.auth import AuthResult, AuthStatus
from ductor_bot.orchestrator.commands import (
    _deepseek_balance_url,
    _parse_total_balance,
    cmd_cron,
    cmd_diagnose,
    cmd_memory,
    cmd_model,
    cmd_status,
    cmd_usage,
)
from ductor_bot.orchestrator.core import Orchestrator
from ductor_bot.session.key import SessionKey

# -- cmd_model (wizard + direct switch) --

_AUTHED = {
    "claude": AuthResult("claude", AuthStatus.AUTHENTICATED),
    "codex": AuthResult("codex", AuthStatus.AUTHENTICATED),
}


async def test_model_list_returns_keyboard(orch: Orchestrator) -> None:
    with patch(
        "ductor_bot.orchestrator.selectors.model_selector.check_all_auth", return_value=_AUTHED
    ):
        result = await cmd_model(orch, SessionKey(chat_id=1), "/model")
    assert result.buttons is not None
    assert "Model Selector" in result.text


async def test_model_direct_switch(orch: Orchestrator) -> None:
    kill_mock = AsyncMock(return_value=0)
    object.__setattr__(orch._process_registry, "kill_all", kill_mock)
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model sonnet")
    assert "opus" in result.text
    assert "sonnet" in result.text
    assert orch._config.model == "sonnet"
    kill_mock.assert_called_once_with(1)


async def test_model_already_set(orch: Orchestrator) -> None:
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model opus")
    assert "Already running" in result.text


async def test_model_provider_change(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model o3")
    assert "Provider:" in result.text


async def test_model_switch_persists_to_config(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    await cmd_model(orch, SessionKey(chat_id=1), "/model sonnet")
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["model"] == "sonnet"
    assert saved["provider"] == "claude"


async def test_model_provider_change_persists_to_config(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    await cmd_model(orch, SessionKey(chat_id=1), "/model o3")
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["model"] == "o3"
    assert saved["provider"] == "codex"


async def test_model_same_provider_does_not_show_reset(orch: Orchestrator) -> None:
    kill_mock = AsyncMock(return_value=0)
    object.__setattr__(orch._process_registry, "kill_all", kill_mock)
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model sonnet")
    assert "Session reset" not in result.text
    assert "Provider:" not in result.text
    kill_mock.assert_called_once_with(1)


# -- cmd_status --


async def test_status_no_session(orch: Orchestrator) -> None:
    with patch("ductor_bot.orchestrator.commands.check_all_auth", return_value={}):
        result = await cmd_status(orch, SessionKey(chat_id=1), "/status")
    assert "No active session" in result.text
    assert "opus" in result.text


async def test_status_with_session(orch: Orchestrator) -> None:
    await orch._sessions.resolve_session(SessionKey(chat_id=1))
    with patch("ductor_bot.orchestrator.commands.check_all_auth", return_value={}):
        result = await cmd_status(orch, SessionKey(chat_id=1), "/status")
    assert "Session:" in result.text
    assert "Messages:" in result.text


async def test_status_prefers_session_model_over_config(orch: Orchestrator) -> None:
    await orch._sessions.resolve_session(
        SessionKey(chat_id=1), provider="codex", model="gpt-5.2-codex"
    )
    with patch("ductor_bot.orchestrator.commands.check_all_auth", return_value={}):
        result = await cmd_status(orch, SessionKey(chat_id=1), "/status")
    assert "Model: gpt-5.2-codex (configured: opus)" in result.text


async def test_status_shows_streaming_visibility_flags(orch: Orchestrator) -> None:
    orch._config.streaming.show_reasoning_stream = True
    orch._config.streaming.show_tool_progress = False
    orch._config.streaming.show_thinking_indicator = False

    with patch("ductor_bot.orchestrator.commands.check_all_auth", return_value={}):
        result = await cmd_status(orch, SessionKey(chat_id=1), "/status")

    assert "Reasoning stream: on" in result.text
    assert "Tool progress: off" in result.text
    assert "Thinking indicator: off" in result.text


# -- cmd_memory --


async def test_memory_shows_content(orch: Orchestrator) -> None:
    orch.paths.mainmemory_path.write_text("# My Memories\n- Learned X")
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory")
    assert "My Memories" in result.text


async def test_memory_empty(orch: Orchestrator) -> None:
    orch.paths.mainmemory_path.write_text("")
    result = await cmd_memory(orch, SessionKey(chat_id=0), "/memory")
    assert "empty" in result.text.lower()


# -- cmd_cron --


async def test_cron_no_jobs(orch: Orchestrator) -> None:
    result = await cmd_cron(orch, SessionKey(chat_id=0), "/cron")
    assert "No cron jobs" in result.text


async def test_cron_lists_jobs(orch: Orchestrator) -> None:
    from ductor_bot.cron.manager import CronJob

    orch._cron_manager.add_job(
        CronJob(
            id="test-job",
            title="Test Job",
            description="A test job",
            schedule="0 9 * * *",
            agent_instruction="do stuff",
            task_folder="test-task",
        ),
    )
    result = await cmd_cron(orch, SessionKey(chat_id=0), "/cron")
    assert result.buttons is not None
    assert "0 9 * * *" in result.text
    assert "Test Job" in result.text
    assert "active" in result.text


# -- cmd_diagnose --


async def test_diagnose_no_logs(orch: Orchestrator) -> None:
    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")
    assert "Diagnostics" in result.text
    assert "No log file" in result.text


async def test_diagnose_with_logs(orch: Orchestrator) -> None:
    log_path = orch.paths.logs_dir / "agent.log"
    log_path.write_text("2024-01-01 INFO Started\n2024-01-01 ERROR Something broke\n")
    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")
    assert "Something broke" in result.text


async def test_diagnose_shows_cache_status(orch: Orchestrator) -> None:
    """Should display Codex cache status in /diagnose output."""
    from datetime import UTC, datetime
    from unittest.mock import MagicMock

    from ductor_bot.cli.codex_cache import CodexModelCache
    from ductor_bot.cli.codex_discovery import CodexModelInfo

    # Create mock cache with test data
    mock_cache = CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=[
            CodexModelInfo(
                id="gpt-4o",
                display_name="GPT-4o",
                description="Test model",
                supported_efforts=("low", "medium", "high"),
                default_effort="medium",
                is_default=True,
            ),
        ],
    )

    # Mock the cache observer
    mock_observer = MagicMock()
    mock_observer.get_cache = MagicMock(return_value=mock_cache)
    orch._observers.codex_cache_obs = mock_observer

    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")

    # Verify cache info is in output
    assert "Codex Model Cache" in result.text
    assert "Models cached: 1" in result.text
    assert "Default model: gpt-4o" in result.text


async def test_diagnose_shows_effective_runtime_target(orch: Orchestrator) -> None:
    orch._providers._available_providers = frozenset({"codex"})

    result = await cmd_diagnose(orch, SessionKey(chat_id=0), "/diagnose")

    assert "Configured: claude / opus" in result.text
    assert "Effective runtime: claude / opus" in result.text


# -- cmd_model (unknown model) --


async def test_model_unknown_name(orch: Orchestrator) -> None:
    """Unknown model names are treated as codex models and the switch succeeds."""
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    result = await cmd_model(orch, SessionKey(chat_id=1), "/model totally_fake_model")
    assert "Model switched" in result.text
    assert "totally_fake_model" in result.text
    assert orch._config.model == "totally_fake_model"
    assert orch._config.provider == "codex"


# -- cmd_usage (DeepSeek balance) --


class _FakeResp:
    """Minimal async-context stand-in for an aiohttp response."""

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
    """Minimal async-context stand-in for aiohttp.ClientSession."""

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


_SESSION_PATCH = "ductor_bot.orchestrator.commands.aiohttp.ClientSession"

_BALANCE_OK = {
    "is_available": True,
    "balance_infos": [
        {
            "currency": "CNY",
            "total_balance": "88.50",
            "granted_balance": "8.50",
            "topped_up_balance": "80.00",
        }
    ],
}


def _enable_deepseek(orch: Orchestrator) -> None:
    orch.config.deepseek.enabled = True
    orch.config.deepseek.api_key = "sk-test-key"


async def test_usage_disabled_when_no_key(orch: Orchestrator) -> None:
    result = await cmd_usage(orch, SessionKey(chat_id=1), "/usage")
    assert "未启用" in result.text
    assert "sk-test" not in result.text


async def test_usage_success_balance_only(orch: Orchestrator) -> None:
    _enable_deepseek(orch)
    session = _FakeSession(_FakeResp(200, _BALANCE_OK))
    with patch(_SESSION_PATCH, return_value=session):
        result = await cmd_usage(orch, SessionKey(chat_id=1), "/usage")
    assert "¥88.50" in result.text
    assert "今日消费" not in result.text  # no snapshot file present
    assert "sk-test-key" not in result.text


async def test_usage_success_with_today_consumption(orch: Orchestrator) -> None:
    _enable_deepseek(orch)
    snap_dir = orch.paths.workspace / "skills" / "personal-assistant"
    snap_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    (snap_dir / ".balance_snapshots.json").write_text(
        json.dumps([{"label": "morning", "timestamp": now, "balance": 100.0}]),
        encoding="utf-8",
    )
    session = _FakeSession(_FakeResp(200, _BALANCE_OK))
    with patch(_SESSION_PATCH, return_value=session):
        result = await cmd_usage(orch, SessionKey(chat_id=1), "/usage")
    assert "¥88.50" in result.text
    assert "今日消费: ¥11.50" in result.text


async def test_usage_http_error(orch: Orchestrator) -> None:
    _enable_deepseek(orch)
    session = _FakeSession(_FakeResp(401, None))
    with patch(_SESSION_PATCH, return_value=session):
        result = await cmd_usage(orch, SessionKey(chat_id=1), "/usage")
    assert "HTTP 401" in result.text


async def test_usage_network_error(orch: Orchestrator) -> None:
    _enable_deepseek(orch)
    session = _FakeSession(_FakeResp(200, _BALANCE_OK), raise_on_enter=aiohttp.ClientError("boom"))
    with patch(_SESSION_PATCH, return_value=session):
        result = await cmd_usage(orch, SessionKey(chat_id=1), "/usage")
    assert "网络异常" in result.text


async def test_usage_missing_balance_infos(orch: Orchestrator) -> None:
    _enable_deepseek(orch)
    session = _FakeSession(_FakeResp(200, {"is_available": False, "balance_infos": []}))
    with patch(_SESSION_PATCH, return_value=session):
        result = await cmd_usage(orch, SessionKey(chat_id=1), "/usage")
    assert "未返回可用余额" in result.text


def test_deepseek_balance_url_derivation() -> None:
    assert (
        _deepseek_balance_url("https://api.deepseek.com/anthropic")
        == "https://api.deepseek.com/user/balance"
    )
    assert _deepseek_balance_url("") == "https://api.deepseek.com/user/balance"
    assert (
        _deepseek_balance_url("https://proxy.example.com/anthropic/v1")
        == "https://proxy.example.com/user/balance"
    )


def test_parse_total_balance() -> None:
    assert _parse_total_balance(_BALANCE_OK) == 88.5
    assert _parse_total_balance({"balance_infos": []}) is None
    assert _parse_total_balance({"balance_infos": [{"total_balance": "nope"}]}) is None
    assert _parse_total_balance("garbage") is None
