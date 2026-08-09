"""Tests for process registry."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from ductor_bot.cli.process_registry import (
    _PRESERVED_LABEL_PREFIXES,
    ProcessRegistry,
    TrackedProcess,
)


def _mock_process(*, pid: int = 1, returncode: int | None = None) -> MagicMock:
    proc = MagicMock(spec=asyncio.subprocess.Process)
    proc.pid = pid
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    proc.send_signal = MagicMock()
    return proc


def test_register_returns_tracked() -> None:
    reg = ProcessRegistry()
    proc = _mock_process(pid=42)
    tracked = reg.register(chat_id=1, process=proc, label="main")
    assert isinstance(tracked, TrackedProcess)
    assert tracked.chat_id == 1
    assert tracked.label == "main"


def test_unregister_removes_process() -> None:
    reg = ProcessRegistry()
    proc = _mock_process()
    tracked = reg.register(chat_id=1, process=proc, label="main")
    reg.unregister(tracked)


def test_unregister_idempotent() -> None:
    reg = ProcessRegistry()
    proc = _mock_process()
    tracked = reg.register(chat_id=1, process=proc, label="main")
    reg.unregister(tracked)
    reg.unregister(tracked)  # no error


async def test_kill_all() -> None:
    reg = ProcessRegistry()
    proc = _mock_process(pid=10)
    reg.register(chat_id=1, process=proc, label="main")
    with patch("ductor_bot.cli.process_registry.asyncio.sleep", new_callable=AsyncMock):
        count = await reg.kill_all(chat_id=1)
    assert count == 1


async def test_kill_all_sets_aborted() -> None:
    reg = ProcessRegistry()
    proc = _mock_process()
    reg.register(chat_id=1, process=proc, label="main")
    assert reg.was_aborted(1) is False
    with patch("ductor_bot.cli.process_registry.asyncio.sleep", new_callable=AsyncMock):
        await reg.kill_all(chat_id=1)
    assert reg.was_aborted(1) is True


def test_clear_abort() -> None:
    reg = ProcessRegistry()
    reg._aborted.add(1)
    assert reg.was_aborted(1) is True
    reg.clear_abort(1)
    assert reg.was_aborted(1) is False


async def test_kill_all_empty_returns_zero() -> None:
    reg = ProcessRegistry()
    count = await reg.kill_all(chat_id=999)
    assert count == 0


async def test_kill_all_active_across_chats() -> None:
    reg = ProcessRegistry()
    proc1 = _mock_process(pid=11)
    proc2 = _mock_process(pid=12)
    reg.register(chat_id=1, process=proc1, label="main")
    reg.register(chat_id=2, process=proc2, label="main")

    with patch("ductor_bot.cli.process_registry.asyncio.sleep", new_callable=AsyncMock):
        count = await reg.kill_all_active()

    assert count == 2
    assert reg.has_active(1) is False
    assert reg.has_active(2) is False
    assert reg.was_aborted(1) is True
    assert reg.was_aborted(2) is True


def test_multiple_chats_isolated() -> None:
    reg = ProcessRegistry()
    proc1 = _mock_process(pid=1)
    proc2 = _mock_process(pid=2)
    reg.register(chat_id=1, process=proc1, label="main")
    reg.register(chat_id=2, process=proc2, label="main")
    assert reg.has_active(1) is True
    assert reg.has_active(2) is True
    assert reg.has_active(3) is False


def test_unregister_ignores_foreign_tracked_same_chat() -> None:
    reg = ProcessRegistry()
    proc = _mock_process(pid=11)
    reg.register(chat_id=1, process=proc, label="main")
    foreign = TrackedProcess(process=proc, chat_id=1, label="main")
    reg.unregister(foreign)  # no error
    assert reg.has_active(1) is True


async def test_kill_stale_returns_zero_when_none_stale() -> None:
    reg = ProcessRegistry()
    proc = _mock_process(pid=21)
    reg.register(chat_id=1, process=proc, label="main")
    killed = await reg.kill_stale(max_age_seconds=9999)
    assert killed == 0


async def test_kill_stale_kills_and_unregisters_old_entries() -> None:
    reg = ProcessRegistry()
    old_proc = _mock_process(pid=30)
    fresh_proc = _mock_process(pid=31)
    done_proc = _mock_process(pid=32, returncode=0)

    old = reg.register(chat_id=1, process=old_proc, label="old")
    fresh = reg.register(chat_id=1, process=fresh_proc, label="fresh")
    reg.register(chat_id=1, process=done_proc, label="done")
    old.registered_at = time.time() - 1000
    fresh.registered_at = time.time()

    with patch("ductor_bot.cli.process_registry.asyncio.sleep", new_callable=AsyncMock):
        killed = await reg.kill_stale(max_age_seconds=60)

    assert killed == 1
    assert reg.has_active(1) is True  # fresh process remains


def test_register_stores_topic_id() -> None:
    reg = ProcessRegistry()
    proc = _mock_process(pid=50)
    tracked = reg.register(chat_id=1, process=proc, label="main", topic_id=42)
    assert tracked.topic_id == 42


def test_register_topic_id_defaults_to_none() -> None:
    reg = ProcessRegistry()
    proc = _mock_process(pid=51)
    tracked = reg.register(chat_id=1, process=proc, label="main")
    assert tracked.topic_id is None


def test_has_active_with_topic_id_filters() -> None:
    reg = ProcessRegistry()
    proc1 = _mock_process(pid=60)
    proc2 = _mock_process(pid=61)
    reg.register(chat_id=1, process=proc1, label="main", topic_id=10)
    reg.register(chat_id=1, process=proc2, label="main", topic_id=20)
    assert reg.has_active(1, topic_id=10) is True
    assert reg.has_active(1, topic_id=20) is True
    assert reg.has_active(1, topic_id=99) is False
    assert reg.has_active(1) is True  # no topic_id -> all


def test_has_active_topic_id_ignores_exited() -> None:
    reg = ProcessRegistry()
    done = _mock_process(pid=70, returncode=0)
    alive = _mock_process(pid=71)
    reg.register(chat_id=1, process=done, label="done", topic_id=10)
    reg.register(chat_id=1, process=alive, label="alive", topic_id=20)
    assert reg.has_active(1, topic_id=10) is False
    assert reg.has_active(1, topic_id=20) is True


class TestKillByChatTopicAbortMarker:
    """Topic-scoped /stop marker behavior."""

    async def test_sets_topic_abort_marker(self) -> None:
        reg = ProcessRegistry()
        proc = _mock_process(pid=80)
        reg.register(chat_id=1, process=proc, label="main", topic_id=10)

        with patch(
            "ductor_bot.cli.process_registry._kill_processes",
            new_callable=AsyncMock,
            return_value=1,
        ):
            killed = await reg.kill_by_chat_topic(1, 10)

        assert killed == 1
        assert reg.was_aborted_topic(1, 10) is True
        assert reg.was_aborted(1) is False

    async def test_no_kill_no_marker(self) -> None:
        reg = ProcessRegistry()
        proc = _mock_process(pid=81)
        reg.register(chat_id=1, process=proc, label="main", topic_id=10)

        killed = await reg.kill_by_chat_topic(1, 20)

        assert killed == 0
        assert reg.was_aborted_topic(1, 20) is False
        assert reg.was_aborted_topic(1, 10) is False

    def test_clear_topic_abort_removes_marker(self) -> None:
        reg = ProcessRegistry()
        reg._aborted_topics.add((1, 10))

        assert reg.was_aborted_topic(1, 10) is True
        reg.clear_topic_abort(1, 10)
        assert reg.was_aborted_topic(1, 10) is False

    async def test_topic_a_kill_does_not_kill_topic_b(self) -> None:
        reg = ProcessRegistry()
        proc_a = _mock_process(pid=82)
        proc_b = _mock_process(pid=83)
        reg.register(chat_id=1, process=proc_a, label="main", topic_id=10)
        reg.register(chat_id=1, process=proc_b, label="main", topic_id=20)

        with patch(
            "ductor_bot.cli.process_registry._kill_processes",
            new_callable=AsyncMock,
            return_value=1,
        ):
            killed = await reg.kill_by_chat_topic(1, 10)

        assert killed == 1
        assert reg.has_active(1, topic_id=10) is False
        assert reg.has_active(1, topic_id=20) is True
        assert proc_b.returncode is None

    async def test_kill_by_chat_topic_preserves_only_named_sessions(self) -> None:
        reg = ProcessRegistry()
        legacy_task = reg.register(
            chat_id=1, process=_mock_process(pid=84), label="task:AAAAAAAA", topic_id=10
        )
        neutral = reg.register(
            chat_id=1, process=_mock_process(pid=85), label="async-result", topic_id=10
        )
        named_session = reg.register(
            chat_id=1, process=_mock_process(pid=86), label="ns:review", topic_id=10
        )

        with patch(
            "ductor_bot.cli.process_registry._kill_processes",
            new_callable=AsyncMock,
            return_value=2,
        ):
            killed = await reg.kill_by_chat_topic(1, 10)

        assert killed == 2
        remaining_ids = {id(t) for t in reg._processes[1]}
        assert id(named_session) in remaining_ids
        assert id(legacy_task) not in remaining_ids
        assert id(neutral) not in remaining_ids

    async def test_kill_by_chat_topic_protected_only_returns_zero(self) -> None:
        reg = ProcessRegistry()
        reg.register(chat_id=1, process=_mock_process(pid=89), label="ns:review", topic_id=10)

        killed = await reg.kill_by_chat_topic(1, 10)

        assert killed == 0
        assert reg.was_aborted_topic(1, 10) is False
        assert reg.has_active(1, topic_id=10) is True
        assert len(reg._processes[1]) == 1

    async def test_kill_all_sweeps_protected_labels(self) -> None:
        reg = ProcessRegistry()
        reg.register(chat_id=1, process=_mock_process(pid=90), label="main", topic_id=10)
        reg.register(chat_id=1, process=_mock_process(pid=91), label="async-result", topic_id=10)
        reg.register(chat_id=1, process=_mock_process(pid=92), label="ns:review", topic_id=10)

        with patch(
            "ductor_bot.cli.process_registry._kill_processes",
            new_callable=AsyncMock,
            return_value=3,
        ):
            killed = await reg.kill_all(1)

        assert killed == 3
        assert reg.has_active(1) is False
        assert 1 not in reg._processes

    def test_only_named_sessions_are_preserved(self) -> None:
        assert _PRESERVED_LABEL_PREFIXES == ("ns:",)

    async def test_kill_by_chat_topic_preserves_other_topics(self) -> None:
        reg = ProcessRegistry()
        proc_topic_a = _mock_process(pid=93)
        proc_topic_b = _mock_process(pid=94)
        reg.register(chat_id=1, process=proc_topic_a, label="main", topic_id=10)
        reg.register(chat_id=1, process=proc_topic_b, label="main", topic_id=20)

        with patch(
            "ductor_bot.cli.process_registry._kill_processes",
            new_callable=AsyncMock,
            return_value=1,
        ):
            killed = await reg.kill_by_chat_topic(1, 20)

        assert killed == 1
        assert reg.has_active(1, topic_id=10) is True
        assert reg.has_active(1, topic_id=20) is False
        assert proc_topic_a.returncode is None

    async def test_kill_by_chat_topic_none_topic_flat_chat(self) -> None:
        reg = ProcessRegistry()
        flat_normal = reg.register(
            chat_id=1, process=_mock_process(pid=95), label="main", topic_id=None
        )
        flat_async = reg.register(
            chat_id=1, process=_mock_process(pid=96), label="async-result", topic_id=None
        )
        topic_normal = reg.register(
            chat_id=1, process=_mock_process(pid=97), label="main", topic_id=10
        )

        with patch(
            "ductor_bot.cli.process_registry._kill_processes",
            new_callable=AsyncMock,
            return_value=2,
        ):
            killed = await reg.kill_by_chat_topic(1, None)

        assert killed == 2
        remaining_ids = {id(t) for t in reg._processes[1]}
        assert id(flat_normal) not in remaining_ids
        assert id(flat_async) not in remaining_ids
        assert id(topic_normal) in remaining_ids


async def test_kill_stale_handles_already_exited() -> None:
    reg = ProcessRegistry()
    proc = _mock_process(pid=40, returncode=0)
    tracked = reg.register(chat_id=1, process=proc, label="gone")
    tracked.registered_at = time.time() - 1000

    killed = await reg.kill_stale(max_age_seconds=60)
    assert killed == 0
