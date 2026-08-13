"""Versioned, atomic DeepSeek balance snapshot persistence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from ductor_bot.infra.atomic_io import atomic_text_save
from ductor_bot.usage.models import Balance, BalanceDelta

_VERSION = 1
_RETENTION = timedelta(days=35)
_DEDUPE_INTERVAL = timedelta(minutes=30)
_LOCKS: dict[Path, asyncio.Lock] = {}


class SnapshotUnavailable(RuntimeError):  # noqa: N818 - public contract from the plan
    """Current-format snapshot state is malformed or inaccessible."""


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    captured_at: datetime
    balances: tuple[Balance, ...]


@dataclass(slots=True)
class _Document:
    legacy_import_completed: bool
    snapshots: list[BalanceSnapshot]


def _lock_for(path: Path) -> asyncio.Lock:
    canonical = path.expanduser().resolve()
    return _LOCKS.setdefault(canonical, asyncio.Lock())


def _money(value: object) -> Decimal:
    if isinstance(value, bool):
        raise TypeError
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError from None
    exponent = result.as_tuple().exponent
    if not result.is_finite() or not isinstance(exponent, int) or exponent < -18:
        raise ValueError
    return result


def _balance(currency: object, total: object) -> Balance:
    if not isinstance(currency, str):
        raise TypeError
    if not currency.strip():
        raise ValueError
    return Balance(currency.strip().upper(), _money(total))


def _balances(value: object) -> tuple[Balance, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError
    if not value:
        raise ValueError
    normalized: list[Balance] = []
    currencies: set[str] = set()
    for entry in value:
        if isinstance(entry, Balance):
            balance = _balance(entry.currency, entry.total)
        elif isinstance(entry, dict):
            balance = _balance(entry.get("currency"), entry.get("total"))
        else:
            raise TypeError
        if balance.currency in currencies:
            raise ValueError
        normalized.append(balance)
        currencies.add(balance.currency)
    return tuple(normalized)


def _captured_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError from None
    if result.tzinfo is None:
        raise ValueError
    return result.astimezone(UTC)


def _balance_identity(balances: tuple[Balance, ...]) -> tuple[tuple[str, Decimal], ...]:
    return tuple(sorted((balance.currency, balance.total) for balance in balances))


def _parse_document(raw: object) -> _Document:
    if not isinstance(raw, dict):
        raise TypeError
    if raw.get("version") != _VERSION:
        raise ValueError
    marker = raw.get("legacy_import_completed")
    snapshots = raw.get("snapshots")
    if not isinstance(marker, bool) or not isinstance(snapshots, list):
        raise TypeError
    parsed: list[BalanceSnapshot] = []
    for item in snapshots:
        if not isinstance(item, dict):
            raise TypeError
        parsed.append(
            BalanceSnapshot(
                _captured_at(item.get("captured_at")),
                _balances(item.get("balances")),
            )
        )
    return _Document(marker, parsed)


def _serialize(document: _Document) -> str:
    payload = {
        "version": _VERSION,
        "legacy_import_completed": document.legacy_import_completed,
        "snapshots": [
            {
                "captured_at": item.captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "balances": [
                    {"currency": balance.currency, "total": str(balance.total)}
                    for balance in item.balances
                ],
            }
            for item in document.snapshots
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


class BalanceSnapshotRepository:
    def __init__(self, path: Path, legacy_path: Path) -> None:
        self._path = path
        self._legacy_path = legacy_path
        self._lock = _lock_for(path)

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize_locked)

    async def record(
        self,
        balances: tuple[Balance, ...],
        *,
        captured_at: datetime | None = None,
    ) -> bool:
        async with self._lock:
            return await asyncio.to_thread(
                self._record_locked, balances, captured_at or datetime.now(UTC)
            )

    async def load(self) -> tuple[BalanceSnapshot, ...]:
        async with self._lock:
            return await asyncio.to_thread(self._load_locked)

    async def today_deltas(
        self,
        current: tuple[Balance, ...],
        *,
        timezone: ZoneInfo,
        now: datetime | None = None,
    ) -> tuple[BalanceDelta, ...]:
        async with self._lock:
            return await asyncio.to_thread(
                self._today_deltas_locked, current, timezone, now or datetime.now(UTC)
            )

    def _read_current(self) -> _Document:
        try:
            return _parse_document(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SnapshotUnavailable from exc

    def _save(self, document: _Document) -> None:
        atomic_text_save(self._path, _serialize(document))

    def _initialize_locked(self) -> _Document:
        if self._path.exists():
            document = self._read_current()
            if document.legacy_import_completed:
                return document
            document.snapshots = _deduplicate([*document.snapshots, *self._read_legacy()])
            document.legacy_import_completed = True
            self._save(document)
            return document
        document = _Document(legacy_import_completed=True, snapshots=self._read_legacy())
        self._save(document)
        return document

    def _read_legacy(self) -> list[BalanceSnapshot]:
        try:
            raw = json.loads(self._legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict) and isinstance(raw.get("snapshots"), list):
            entries = raw["snapshots"]
        else:
            entries = []
        imported: list[BalanceSnapshot] = []
        seen: set[tuple[datetime, Decimal]] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                timestamp = _captured_at(entry.get("timestamp") or entry.get("captured_at"))
                total = _money(entry.get("balance"))
            except (TypeError, ValueError):
                continue
            identity = (timestamp, total)
            if identity not in seen:
                imported.append(BalanceSnapshot(timestamp, (Balance("CNY", total),)))
                seen.add(identity)
        return sorted(imported, key=lambda item: item.captured_at)

    def _record_locked(self, balances: tuple[Balance, ...], captured_at: datetime) -> bool:
        try:
            normalized = _balances(balances)
        except (TypeError, ValueError) as exc:
            raise SnapshotUnavailable from exc
        if captured_at.tzinfo is None:
            raise SnapshotUnavailable
        document = self._initialize_locked()
        captured_at = captured_at.astimezone(UTC)
        cutoff = captured_at - _RETENTION
        retained = [
            item for item in document.snapshots if cutoff <= item.captured_at <= captured_at
        ]
        pruned = len(retained) != len(document.snapshots)
        document.snapshots = retained
        latest = max(document.snapshots, key=lambda item: item.captured_at, default=None)
        if (
            latest is not None
            and timedelta(0) <= captured_at - latest.captured_at < _DEDUPE_INTERVAL
            and _balance_identity(latest.balances) == _balance_identity(normalized)
        ):
            if pruned:
                self._save(document)
            return False
        document.snapshots.append(BalanceSnapshot(captured_at, normalized))
        document.snapshots.sort(key=lambda item: item.captured_at)
        self._save(document)
        return True

    def _load_locked(self) -> tuple[BalanceSnapshot, ...]:
        return tuple(self._initialize_locked().snapshots)

    def _today_deltas_locked(
        self,
        current: tuple[Balance, ...],
        timezone: ZoneInfo,
        now: datetime,
    ) -> tuple[BalanceDelta, ...]:
        if now.tzinfo is None:
            raise SnapshotUnavailable
        snapshots = [
            item for item in self._initialize_locked().snapshots if item.captured_at <= now
        ]
        midnight = now.astimezone(timezone).replace(hour=0, minute=0, second=0, microsecond=0)
        midnight_utc = midnight.astimezone(UTC)
        result: list[BalanceDelta] = []
        for balance in current:
            candidates = [
                (item.captured_at, stored)
                for item in snapshots
                for stored in item.balances
                if stored.currency == balance.currency
            ]
            after = sorted(item for item in candidates if midnight_utc <= item[0] <= now)
            before = sorted(item for item in candidates if item[0] < midnight_utc)
            baseline = after[0][1] if after else (before[-1][1] if before else None)
            if baseline is None:
                result.append(BalanceDelta(balance.currency, balance.total, None, "unavailable"))
                continue
            change = baseline.total - balance.total
            kind: Literal["spend", "recharge"] = "spend" if change >= 0 else "recharge"
            result.append(BalanceDelta(balance.currency, balance.total, change, kind))
        return tuple(result)


def _deduplicate(snapshots: list[BalanceSnapshot]) -> list[BalanceSnapshot]:
    unique: dict[tuple[datetime, tuple[Balance, ...]], BalanceSnapshot] = {}
    for snapshot in snapshots:
        unique[(snapshot.captured_at, snapshot.balances)] = snapshot
    return sorted(unique.values(), key=lambda item: item.captured_at)
