"""Tests for transport-neutral callback routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from ductor_bot.config import AgentConfig
from ductor_bot.messenger.callback_router import route_callback
from ductor_bot.orchestrator.core import Orchestrator
from ductor_bot.session.key import SessionKey
from ductor_bot.workspace.paths import DuctorPaths


@pytest.fixture
def orch(tmp_path: Path) -> Orchestrator:
    return Orchestrator(AgentConfig(), DuctorPaths(ductor_home=tmp_path))


async def test_removed_callback_prefix_is_not_handled(orch: Orchestrator) -> None:
    removed_prefix = "tsc"
    result = await route_callback(orch, SessionKey.telegram(1), f"{removed_prefix}:r")
    assert result.handled is False
