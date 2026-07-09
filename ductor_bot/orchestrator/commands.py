"""Command handlers for all slash commands."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import aiohttp

from ductor_bot.cli.auth import check_all_auth
from ductor_bot.i18n import t
from ductor_bot.infra.version import check_pypi, get_current_version
from ductor_bot.orchestrator.registry import OrchestratorResult
from ductor_bot.orchestrator.selectors.cron_selector import cron_selector_start
from ductor_bot.orchestrator.selectors.model_selector import model_selector_start, switch_model
from ductor_bot.orchestrator.selectors.models import Button, ButtonGrid
from ductor_bot.orchestrator.selectors.session_selector import session_selector_start
from ductor_bot.orchestrator.selectors.task_selector import task_selector_start
from ductor_bot.text.response_format import SEP, fmt, new_session_text
from ductor_bot.workspace.loader import read_mainmemory

if TYPE_CHECKING:
    from ductor_bot.orchestrator.core import Orchestrator
    from ductor_bot.session.key import SessionKey
    from ductor_bot.workspace.paths import DuctorPaths

logger = logging.getLogger(__name__)


# -- Command wrappers (registered by Orchestrator._register_commands) --


async def cmd_reset(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /new: kill processes and reset only active provider session."""
    logger.info("Reset requested")
    await orch._process_registry.kill_all(key.chat_id)
    provider = await orch.reset_active_provider_session(key)
    return OrchestratorResult(text=new_session_text(provider))


async def cmd_reset_current(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /reset: kill processes and reset the *current* provider session."""
    logger.info("Reset (current) requested")
    await orch._process_registry.kill_all(key.chat_id)
    provider = await orch.reset_current_provider_session(key)
    return OrchestratorResult(text=new_session_text(provider))


async def cmd_status(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /status."""
    logger.info("Status requested")
    return OrchestratorResult(text=await _build_status(orch, key))


_USAGE_HEADER = "🐳 DeepSeek 余额"
_DEEPSEEK_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Personal-assistant skill's balance snapshot file (relative to the workspace).
# Optional: only present when that skill is installed, so reads are best-effort.
_BALANCE_SNAPSHOT_REL = ("skills", "personal-assistant", ".balance_snapshots.json")


async def cmd_usage(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /usage: show the DeepSeek account balance (and today's spend)."""
    logger.info("Usage (DeepSeek balance) requested")
    ds = orch.config.deepseek
    if not ds.enabled or not ds.api_key:
        return OrchestratorResult(
            text=(
                f"{_USAGE_HEADER}\n"
                "DeepSeek 未启用或未配置 API key。\n"
                "请在 `~/.ductor/config/config.json` 的 `deepseek` 段中设置 "
                "`enabled: true` 并填入 `api_key`。"
            ),
        )

    url = _deepseek_balance_url(ds.base_url)
    headers = {"Authorization": f"Bearer {ds.api_key}", "Accept": "application/json"}
    try:
        async with (
            aiohttp.ClientSession(timeout=_DEEPSEEK_TIMEOUT, headers=headers) as session,
            session.get(url) as resp,
        ):
            status = resp.status
            data = await resp.json(content_type=None) if status == 200 else None
    except (aiohttp.ClientError, TimeoutError, ValueError):
        logger.warning("DeepSeek balance query failed", exc_info=True)
        return OrchestratorResult(text=f"{_USAGE_HEADER}\n查询余额时网络异常或超时。请稍后再试。")

    if data is None:
        return OrchestratorResult(
            text=f"{_USAGE_HEADER}\n查询失败: HTTP {status}。请检查 API key 是否有效或稍后再试。",
        )

    balance = _parse_total_balance(data)
    if balance is None:
        return OrchestratorResult(text=f"{_USAGE_HEADER}\nDeepSeek 未返回可用余额信息。")

    lines = [f"🐳 DeepSeek 余额: ¥{balance:.2f}"]
    spent = await asyncio.to_thread(_today_consumption, orch.paths, balance)
    if spent is not None:
        if spent >= 0:
            lines.append(f"📉 今日消费: ¥{spent:.2f}")
        else:
            lines.append(f"📈 今日充值: ¥{abs(spent):.2f}")
    return OrchestratorResult(text="\n".join(lines))


async def cmd_model(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /model [name]."""
    logger.info("Model requested")
    parts = text.split(None, 1)
    if len(parts) < 2:
        resp = await model_selector_start(orch, key)
        return OrchestratorResult(text=resp.text, buttons=resp.buttons)
    name = parts[1].strip()
    result_text = await switch_model(orch, key, name)
    return OrchestratorResult(text=result_text)


async def cmd_memory(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /memory."""
    logger.info("Memory requested")
    content = await asyncio.to_thread(read_mainmemory, orch.paths)
    if not content.strip():
        return OrchestratorResult(
            text=fmt(
                t("memory.header"),
                SEP,
                t("memory.empty"),
                SEP,
                t("memory.empty_tip"),
            ),
        )
    return OrchestratorResult(
        text=fmt(
            t("memory.header"),
            SEP,
            content,
            SEP,
            t("memory.filled_tip"),
        ),
    )


async def cmd_sessions(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /sessions."""
    logger.info("Sessions requested")
    resp = await session_selector_start(orch, key.chat_id)
    return OrchestratorResult(text=resp.text, buttons=resp.buttons)


async def cmd_tasks(orch: Orchestrator, key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /tasks."""
    logger.info("Tasks requested")
    hub = orch.task_hub
    if hub is None:
        return OrchestratorResult(
            text=fmt(t("tasks.header"), SEP, t("tasks.disabled")),
        )
    resp = task_selector_start(hub, key.chat_id)
    return OrchestratorResult(text=resp.text, buttons=resp.buttons)


async def cmd_cron(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /cron."""
    logger.info("Cron requested")
    resp = await cron_selector_start(orch)
    return OrchestratorResult(text=resp.text, buttons=resp.buttons)


async def cmd_upgrade(_orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /upgrade: check for updates and offer upgrade."""
    logger.info("Upgrade check requested")

    from ductor_bot.infra.install import detect_install_mode

    if detect_install_mode() == "dev":
        return OrchestratorResult(
            text=fmt(
                t("upgrade.dev_header"),
                SEP,
                t("upgrade.dev_body"),
            ),
        )

    info = await check_pypi(fresh=True)

    if info is None:
        return OrchestratorResult(
            text=t("upgrade.pypi_unreachable"),
        )

    if not info.update_available:
        keyboard = ButtonGrid(
            rows=[
                [
                    Button(
                        text=t("upgrade.btn_changelog", version=info.current),
                        callback_data=f"upg:cl:{info.current}",
                    )
                ],
            ]
        )
        return OrchestratorResult(
            text=fmt(
                t("upgrade.up_to_date_header"),
                SEP,
                t("upgrade.up_to_date_body", current=info.current, latest=info.latest),
            ),
            buttons=keyboard,
        )

    keyboard = ButtonGrid(
        rows=[
            [
                Button(
                    text=t("upgrade.btn_changelog", version=info.latest),
                    callback_data=f"upg:cl:{info.latest}",
                )
            ],
            [
                Button(
                    text=t("upgrade.btn_yes"),
                    callback_data=f"upg:yes:{info.latest}",
                ),
                Button(text=t("upgrade.btn_not_now"), callback_data="upg:no"),
            ],
        ]
    )

    return OrchestratorResult(
        text=fmt(
            t("upgrade.available_header"),
            SEP,
            t("upgrade.available_body", current=info.current, latest=info.latest),
        ),
        buttons=keyboard,
    )


def _build_codex_cache_block(orch: Orchestrator) -> str:
    """Build the Codex model cache section for /diagnose."""
    if not orch._observers.codex_cache_obs:
        return "\n🔄 " + t("diagnose.codex_cache_not_init")
    cache = orch._observers.codex_cache_obs.get_cache()
    if not cache or not cache.models:
        return "\n🔄 " + t("diagnose.codex_cache_not_loaded")
    default_model = next((m.id for m in cache.models if m.is_default), "N/A")
    return "\n🔄 " + t(
        "diagnose.codex_cache_info",
        updated=cache.last_updated,
        count=len(cache.models),
        default=default_model,
    )


def _build_diagnose_health_block(orch: Orchestrator) -> str:
    """Build the multi-agent health section for /diagnose."""
    supervisor = orch._supervisor
    if supervisor is None:
        return ""
    status_icon = {"running": "●", "starting": "◐", "crashed": "✖", "stopped": "○"}
    agent_lines = ["\n" + t("diagnose.health_header")]
    for name in sorted(supervisor.health.keys()):
        h = supervisor.health[name]
        icon = status_icon.get(h.status, "?")
        role = "main" if name == "main" else "sub"
        line = f"  {icon} `{name}` [{role}] — {h.status}"
        if h.status == "running" and h.uptime_human:
            line += f" ({h.uptime_human})"
        if h.restart_count > 0:
            line += f" | restarts: {h.restart_count}"
        if h.status == "crashed" and h.last_crash_error:
            line += f"\n      `{h.last_crash_error[:100]}`"
        agent_lines.append(line)
    return "\n".join(agent_lines)


def _resolve_log_path(orch: Orchestrator) -> Path:
    """Return the best available log file path.

    Sub-agents don't have their own log files — fall back to the central
    log in the main ductor home (parent of ``agents/<name>``).
    """
    log_path = orch.paths.logs_dir / "agent.log"
    if not log_path.exists():
        main_logs = orch.paths.ductor_home.parent.parent / "logs" / "agent.log"
        if main_logs.exists():
            return main_logs
    return log_path


async def cmd_diagnose(orch: Orchestrator, _key: SessionKey, _text: str) -> OrchestratorResult:
    """Handle /diagnose."""
    logger.info("Diagnose requested")
    version = get_current_version()
    effective_model, effective_provider = orch.resolve_runtime_target(orch._config.model)
    info_block = (
        f"{t('diagnose.version_line', version=version)}\n"
        f"{t('diagnose.configured_line', provider=orch._config.provider, model=orch._config.model)}\n"
        f"{t('diagnose.effective_line', provider=effective_provider, model=effective_model)}"
    )

    cache_block = _build_codex_cache_block(orch)
    agent_block = _build_diagnose_health_block(orch)

    log_tail = await _read_log_tail(_resolve_log_path(orch))
    log_block = (
        f"{t('diagnose.log_header')}\n```\n{log_tail}\n```" if log_tail else t("diagnose.no_log")
    )

    return OrchestratorResult(
        text=fmt(t("diagnose.header"), SEP, info_block, cache_block, agent_block, SEP, log_block),
    )


# -- Helpers ------------------------------------------------------------------


def _deepseek_balance_url(base_url: str) -> str:
    """Derive the balance endpoint from the Anthropic-compatible base URL.

    ``base_url`` is typically ``https://api.deepseek.com/anthropic``; the balance
    endpoint lives at the domain root (``/user/balance``), so only scheme + host
    are reused.
    """
    parts = urlsplit(base_url or "https://api.deepseek.com")
    scheme = parts.scheme or "https"
    netloc = parts.netloc or "api.deepseek.com"
    return f"{scheme}://{netloc}/user/balance"


def _parse_total_balance(data: object) -> float | None:
    """Extract ``balance_infos[0].total_balance`` as a float, or None on any gap."""
    if not isinstance(data, dict):
        return None
    infos = data.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        return None
    first = infos[0]
    if not isinstance(first, dict):
        return None
    try:
        return float(str(first.get("total_balance")))
    except ValueError:
        return None


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp, returning the epoch on failure."""
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=UTC)


def _load_balance_snapshots(paths: DuctorPaths) -> list[object]:
    """Read the personal-assistant skill's snapshot list, or [] if unavailable.

    The file is optional (only present when that skill is installed), so any
    read/parse problem degrades gracefully to an empty list.
    """
    snapshot_file = paths.workspace.joinpath(*_BALANCE_SNAPSHOT_REL)
    try:
        raw = snapshot_file.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _reference_snapshot(snapshots: list[object]) -> dict[str, object] | None:
    """Pick today's first snapshot, else the most recent one before today."""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    today_first: dict[str, object] | None = None
    yesterday_last: dict[str, object] | None = None
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        ts = _parse_ts(str(snap.get("timestamp", "")))
        if ts >= today_start:
            if today_first is None or ts < _parse_ts(str(today_first.get("timestamp", ""))):
                today_first = snap
        elif yesterday_last is None or ts > _parse_ts(str(yesterday_last.get("timestamp", ""))):
            yesterday_last = snap
    return today_first or yesterday_last


def _today_consumption(paths: DuctorPaths, current_balance: float) -> float | None:
    """Best-effort today's spend: (today's first snapshot balance) minus current.

    Returns None when no usable snapshot exists (e.g. the skill isn't installed),
    so the balance still renders on machines without it.
    """
    ref = _reference_snapshot(_load_balance_snapshots(paths))
    if ref is None:
        return None
    try:
        ref_balance = float(str(ref.get("balance")))
    except ValueError:
        return None
    return ref_balance - current_balance


def _build_agent_health_block(orch: Orchestrator) -> str:
    """Build the multi-agent health section for /status (main agent only)."""
    supervisor = orch._supervisor
    if supervisor is None or len(supervisor.health) <= 1:
        return ""

    status_icon = {
        "running": "●",
        "starting": "◐",
        "crashed": "✖",
        "stopped": "○",
    }
    agent_lines = [t("status.agents_header")]
    for name in sorted(supervisor.health.keys()):
        if name == "main":
            continue
        h = supervisor.health[name]
        icon = status_icon.get(h.status, "?")
        line = f"  {icon} {name} — {h.status}"
        if h.status == "running" and h.uptime_human:
            line += f" ({h.uptime_human})"
        if h.restart_count > 0:
            line += f" ⟳{h.restart_count}"
        if h.status == "crashed" and h.last_crash_error:
            line += f"\n      {h.last_crash_error[:80]}"
        agent_lines.append(line)
    return "\n".join(agent_lines)


async def _build_status(orch: Orchestrator, key: SessionKey) -> str:
    """Build the /status response text."""
    runtime_model, _runtime_provider = orch.resolve_runtime_target(orch._config.model)
    configured_model = orch._config.model

    def _model_line(model_name: str) -> str:
        if model_name == configured_model:
            return t("status.model_line", model=model_name)
        return t("status.model_line_configured", model=model_name, configured=configured_model)

    session = await orch._sessions.get_active(key)
    if session:
        topic_line = (
            f"{t('status.topic_line', topic=session.topic_name)}\n" if session.topic_name else ""
        )
        session_block = (
            f"{topic_line}"
            f"{t('status.session_line', sid=session.session_id[:8] + '...')}\n"
            f"{t('status.messages_line', count=session.message_count)}\n"
            f"{t('status.tokens_line', tokens=f'{session.total_tokens:,}')}\n"
            f"{t('status.cost_line', cost=f'{session.total_cost_usd:.4f}')}\n"
            f"{_model_line(session.model)}"
        )
    else:
        session_block = f"{t('status.no_session')}\n{_model_line(runtime_model)}"

    bg_tasks = orch.active_background_tasks(key.chat_id)
    bg_block = ""
    if bg_tasks:
        import time

        bg_lines = [t("status.bg_header", count=len(bg_tasks))]
        for bg_t in bg_tasks:
            age = time.monotonic() - bg_t.submitted_at
            bg_lines.append(f"  `{bg_t.task_id}` {bg_t.prompt[:40]}... ({age:.0f}s)")
        bg_block = "\n".join(bg_lines)

    auth = await asyncio.to_thread(check_all_auth)
    auth_lines: list[str] = []
    for provider, result in auth.items():
        age_label = f" ({result.age_human})" if result.age_human else ""
        auth_lines.append(f"  [{provider}] {result.status.value}{age_label}")
    auth_block = t("status.auth_header") + "\n" + "\n".join(auth_lines)

    streaming_cfg = orch._config.streaming
    streaming_block = "\n".join(
        [
            "Streaming visibility:",
            f"  Reasoning stream: {'on' if streaming_cfg.show_reasoning_stream else 'off'}",
            f"  Tool progress: {'on' if streaming_cfg.show_tool_progress else 'off'}",
            f"  Thinking indicator: {'on' if streaming_cfg.show_thinking_indicator else 'off'}",
        ]
    )

    agent_block = _build_agent_health_block(orch)

    blocks = [t("status.header"), SEP, session_block]
    if bg_block:
        blocks += [SEP, bg_block]
    blocks += [SEP, auth_block, SEP, streaming_block]
    if agent_block:
        blocks += [SEP, agent_block]
    return fmt(*blocks)


async def _read_log_tail(log_path: Path, lines: int = 50) -> str:
    """Read the last *lines* of a log file without blocking the event loop."""

    def _read() -> str:
        if not log_path.is_file():
            return ""
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            return "\n".join(text.strip().splitlines()[-lines:])
        except OSError:
            return "(could not read log file)"

    return await asyncio.to_thread(_read)
