"""Tests for Ductor-owned DeepSeek balance history."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from ductor_bot.usage.models import Balance
from ductor_bot.usage.snapshots import BalanceSnapshotRepository, SnapshotUnavailable


@pytest.fixture
def repo(tmp_path: Path) -> BalanceSnapshotRepository:
    return BalanceSnapshotRepository(tmp_path / "snapshots.json", tmp_path / "legacy.json")


def _temporary_files(path: Path) -> list[Path]:
    return list(path.glob("*.tmp"))


async def test_record_round_trips_decimal_strings(tmp_path: Path) -> None:
    repository = BalanceSnapshotRepository(
        tmp_path / "deepseek_balance_snapshots.json",
        tmp_path / "legacy.json",
    )
    await repository.record(
        (Balance("CNY", Decimal("123.450")), Balance("USD", Decimal("8.20"))),
        captured_at=datetime(2026, 8, 13, 1, tzinfo=UTC),
    )
    raw = json.loads((tmp_path / "deepseek_balance_snapshots.json").read_text())
    assert raw == {
        "version": 1,
        "legacy_import_completed": True,
        "snapshots": [
            {
                "captured_at": "2026-08-13T01:00:00Z",
                "balances": [
                    {"currency": "CNY", "total": "123.450"},
                    {"currency": "USD", "total": "8.20"},
                ],
            }
        ],
    }
    assert await asyncio.to_thread(_temporary_files, tmp_path) == []


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"version": 2, "legacy_import_completed": True, "snapshots": []},
        {"version": 1, "legacy_import_completed": "yes", "snapshots": []},
        {"version": 1, "legacy_import_completed": True, "snapshots": {}},
        {
            "version": 1,
            "legacy_import_completed": True,
            "snapshots": [{"captured_at": "not-a-date", "balances": []}],
        },
        {
            "version": 1,
            "legacy_import_completed": True,
            "snapshots": [{"captured_at": "2026-08-13T01:00:00Z"}],
        },
        {
            "version": 1,
            "legacy_import_completed": True,
            "snapshots": [
                {
                    "captured_at": "2026-08-13T01:00:00Z",
                    "balances": [{"currency": "", "total": "1"}],
                }
            ],
        },
    ],
)
async def test_invalid_current_documents_are_preserved(tmp_path: Path, document: object) -> None:
    path = tmp_path / "snapshots.json"
    evidence = json.dumps(document).encode()
    path.write_bytes(evidence)
    repository = BalanceSnapshotRepository(path, tmp_path / "legacy.json")

    with pytest.raises(SnapshotUnavailable):
        await repository.load()

    assert path.read_bytes() == evidence


@pytest.mark.parametrize(
    "balance",
    [
        Balance("", Decimal(1)),
        Balance("CNY", Decimal("NaN")),
        Balance("CNY", Decimal("Infinity")),
        Balance("CNY", Decimal("0.0000000000000000001")),
    ],
)
async def test_invalid_balance_is_rejected_without_writing(
    tmp_path: Path, balance: Balance
) -> None:
    path = tmp_path / "snapshots.json"
    repository = BalanceSnapshotRepository(path, tmp_path / "legacy.json")

    with pytest.raises(SnapshotUnavailable):
        await repository.record((balance,))

    assert not path.exists()


async def test_atomic_write_failure_preserves_original_target(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.json"
    repository = BalanceSnapshotRepository(path, tmp_path / "legacy.json")
    first = datetime(2026, 8, 13, tzinfo=UTC)
    await repository.record((Balance("CNY", Decimal(100)),), captured_at=first)
    evidence = path.read_bytes()

    with (
        patch(
            "ductor_bot.usage.snapshots.atomic_text_save",
            side_effect=OSError("simulated atomic failure"),
        ),
        pytest.raises(OSError, match="simulated atomic failure"),
    ):
        await repository.record(
            (Balance("CNY", Decimal(99)),),
            captured_at=first + timedelta(minutes=1),
        )

    assert path.read_bytes() == evidence


async def test_identical_sample_inside_30_minutes_is_deduplicated(
    repo: BalanceSnapshotRepository,
) -> None:
    first = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    balances = (Balance("CNY", Decimal(100)),)
    assert await repo.record(balances, captured_at=first) is True
    assert await repo.record(balances, captured_at=first + timedelta(minutes=29)) is False


async def test_deduplication_compares_normalized_currency_balances(
    repo: BalanceSnapshotRepository,
) -> None:
    first = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    assert await repo.record(
        (Balance("cny", Decimal(100)), Balance("USD", Decimal(10))),
        captured_at=first,
    )

    assert (
        await repo.record(
            (Balance("usd", Decimal(10)), Balance("CNY", Decimal(100))),
            captured_at=first + timedelta(minutes=29),
        )
        is False
    )


async def test_deduplicated_record_still_prunes_expired_history(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    path = tmp_path / "snapshots.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "legacy_import_completed": True,
                "snapshots": [
                    {
                        "captured_at": (now - timedelta(days=36)).isoformat(),
                        "balances": [{"currency": "CNY", "total": "100"}],
                    },
                    {
                        "captured_at": (now - timedelta(minutes=20)).isoformat(),
                        "balances": [{"currency": "CNY", "total": "90"}],
                    },
                ],
            }
        )
    )
    repository = BalanceSnapshotRepository(path, tmp_path / "legacy.json")

    assert await repository.record((Balance("CNY", Decimal(90)),), captured_at=now) is False
    assert len(await repository.load()) == 1


async def test_changed_sample_inside_30_minutes_is_retained(
    repo: BalanceSnapshotRepository,
) -> None:
    first = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    assert await repo.record((Balance("CNY", Decimal(100)),), captured_at=first)
    assert await repo.record(
        (Balance("CNY", Decimal(99)),), captured_at=first + timedelta(minutes=5)
    )


async def test_today_delta_uses_local_midnight_and_same_currency(
    repo: BalanceSnapshotRepository,
) -> None:
    current_at = datetime(2026, 8, 13, 4, 0, tzinfo=UTC)
    await repo.record(
        (Balance("CNY", Decimal(105)), Balance("USD", Decimal(12))),
        captured_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
    )
    await repo.record(
        (Balance("CNY", Decimal(100)),),
        captured_at=datetime(2026, 8, 12, 16, 5, tzinfo=UTC),
    )
    await repo.record(
        (Balance("CNY", Decimal(95)),),
        captured_at=datetime(2026, 8, 12, 18, 0, tzinfo=UTC),
    )
    deltas = await repo.today_deltas(
        (
            Balance("CNY", Decimal(90)),
            Balance("USD", Decimal(10)),
            Balance("EUR", Decimal(7)),
        ),
        timezone=ZoneInfo("Asia/Shanghai"),
        now=current_at,
    )
    assert deltas[0].change == Decimal(10)
    assert deltas[0].kind == "spend"
    assert deltas[1].change == Decimal(2)
    assert deltas[1].kind == "spend"
    assert deltas[2].kind == "unavailable"


async def test_recharge_and_35_day_retention(repo: BalanceSnapshotRepository) -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    await repo.record((Balance("CNY", Decimal(50)),), captured_at=now - timedelta(days=36))
    await repo.record((Balance("CNY", Decimal(60)),), captured_at=now - timedelta(hours=1))
    deltas = await repo.today_deltas(
        (Balance("CNY", Decimal(70)),), timezone=ZoneInfo("UTC"), now=now
    )
    assert deltas[0].kind == "recharge"
    assert deltas[0].change == Decimal(-10)
    loaded = await repo.load()
    assert all(item.captured_at >= now - timedelta(days=35) for item in loaded)


async def test_today_delta_falls_back_to_latest_pre_midnight(
    repo: BalanceSnapshotRepository,
) -> None:
    now = datetime(2026, 8, 13, 4, tzinfo=UTC)
    await repo.record(
        (Balance("CNY", Decimal(102)),),
        captured_at=datetime(2026, 8, 12, 14, tzinfo=UTC),
    )
    await repo.record(
        (Balance("CNY", Decimal(100)),),
        captured_at=datetime(2026, 8, 12, 15, tzinfo=UTC),
    )

    deltas = await repo.today_deltas(
        (Balance("CNY", Decimal(90)),),
        timezone=ZoneInfo("Asia/Shanghai"),
        now=now,
    )

    assert deltas[0].change == Decimal(10)


async def test_today_delta_excludes_future_records(
    repo: BalanceSnapshotRepository,
) -> None:
    now = datetime(2026, 8, 13, 4, tzinfo=UTC)
    await repo.record(
        (Balance("CNY", Decimal(100)),),
        captured_at=now + timedelta(minutes=1),
    )

    deltas = await repo.today_deltas(
        (Balance("CNY", Decimal(90)),), timezone=ZoneInfo("UTC"), now=now
    )

    assert deltas[0].kind == "unavailable"
    assert deltas[0].change is None


async def test_malformed_current_file_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.json"
    evidence = b'{"version": 1, "snapshots": [broken]}'
    path.write_bytes(evidence)
    repository = BalanceSnapshotRepository(path, tmp_path / "legacy.json")
    with pytest.raises(SnapshotUnavailable):
        await repository.load()
    with pytest.raises(SnapshotUnavailable):
        await repository.record((Balance("CNY", Decimal(10)),))
    assert path.read_bytes() == evidence


async def test_legacy_import_is_one_time_and_never_mutates_source(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.json"
    legacy_bytes = json.dumps([{"timestamp": "2026-08-12T00:00:00Z", "balance": 123.45}]).encode()
    legacy.write_bytes(legacy_bytes)
    repository = BalanceSnapshotRepository(tmp_path / "snapshots.json", legacy)
    await repository.initialize()
    legacy.write_text("malformed after import")
    await repository.initialize()
    loaded = await repository.load()
    assert loaded[0].balances == (Balance("CNY", Decimal("123.45")),)
    assert legacy.read_text() == "malformed after import"


async def test_legacy_import_normalizes_deduplicates_and_skips_invalid(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy.json"
    source = [
        {"timestamp": "2026-08-12T00:00:00Z", "balance": 123.45},
        {"timestamp": "2026-08-12T00:00:00+00:00", "balance": "123.45"},
        {"timestamp": "invalid", "balance": "7"},
        {"timestamp": "2026-08-12T01:00:00Z", "balance": "NaN"},
        {"timestamp": "2026-08-12T02:00:00Z", "balance": "120.25"},
    ]
    evidence = json.dumps(source).encode()
    legacy.write_bytes(evidence)
    repository = BalanceSnapshotRepository(tmp_path / "snapshots.json", legacy)

    await repository.initialize()

    loaded = await repository.load()
    assert [item.balances[0].total for item in loaded] == [
        Decimal("123.45"),
        Decimal("120.25"),
    ]
    assert all(item.balances[0].currency == "CNY" for item in loaded)
    assert legacy.read_bytes() == evidence


@pytest.mark.parametrize("legacy_contents", [None, "", "not json", "{}", "[]"])
async def test_legacy_absence_or_malformed_content_is_marked_complete(
    tmp_path: Path, legacy_contents: str | None
) -> None:
    legacy = tmp_path / "legacy.json"
    if legacy_contents is not None:
        legacy.write_text(legacy_contents)
    target = tmp_path / "snapshots.json"
    repository = BalanceSnapshotRepository(target, legacy)

    await repository.initialize()

    assert json.loads(target.read_text()) == {
        "version": 1,
        "legacy_import_completed": True,
        "snapshots": [],
    }


async def test_two_instances_serialize_concurrent_records(tmp_path: Path) -> None:
    path = tmp_path / "snapshots.json"
    first = BalanceSnapshotRepository(path, tmp_path / "legacy.json")
    second = BalanceSnapshotRepository(path, tmp_path / "legacy.json")
    now = datetime(2026, 8, 13, tzinfo=UTC)
    await asyncio.gather(
        first.record((Balance("CNY", Decimal(100)),), captured_at=now),
        second.record((Balance("CNY", Decimal(99)),), captured_at=now + timedelta(minutes=1)),
    )
    assert len(await first.load()) == 2
