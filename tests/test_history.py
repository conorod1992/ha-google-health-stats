"""Persistent history repository tests."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.google_health.history import GoogleHealthHistory
from custom_components.google_health.models import DailyRecord


@pytest.fixture
def memory_store(monkeypatch):
    """Replace Home Assistant storage I/O with a persistent in-memory backend."""
    values = {}

    class MemoryStore:
        def __init__(self, hass, version, key):
            self.key = key

        async def async_load(self):
            return values.get(self.key)

        async def async_save(self, data):
            values[self.key] = data

    monkeypatch.setattr("custom_components.google_health.history.Store", MemoryStore)
    return values


@pytest.mark.asyncio
async def test_history_upsert_preserves_missing_metrics(memory_store) -> None:
    hass = MagicMock()
    history = GoogleHealthHistory(hass, "upsert", 120)
    day = date(2026, 7, 30)
    await history.async_upsert(
        [DailyRecord(day, resting_heart_rate=64, active_zone_minutes=20)]
    )
    await history.async_upsert(
        [DailyRecord(day, resting_heart_rate=62, total_calories_kcal=2400)]
    )
    record = history.records[day]
    assert record.resting_heart_rate == 62
    assert record.active_zone_minutes == 20
    assert record.total_calories_kcal == 2400


@pytest.mark.asyncio
async def test_history_120_day_pruning(memory_store) -> None:
    hass = MagicMock()
    today = date(2026, 7, 30)
    history = GoogleHealthHistory(hass, "prune", 120)
    await history.async_upsert(
        [
            DailyRecord(today - timedelta(days=offset), resting_heart_rate=60)
            for offset in range(125)
        ]
    )
    await history.async_prune(today)
    assert len(history.records) == 120
    assert min(history.records) == today - timedelta(days=119)
    assert max(history.records) == today


@pytest.mark.asyncio
async def test_persistence_across_reload(memory_store) -> None:
    hass = MagicMock()
    day = date(2026, 7, 30)
    first = GoogleHealthHistory(hass, "reload", 120)
    await first.async_upsert(
        [DailyRecord(day, sleep_duration_seconds=25_200, resting_heart_rate=63)]
    )
    second = GoogleHealthHistory(hass, "reload", 120)
    await second.async_load()
    assert second.records[day].sleep_duration_seconds == 25_200
    assert second.records[day].resting_heart_rate == 63


@pytest.mark.asyncio
async def test_missing_data_does_not_create_record(memory_store) -> None:
    hass = MagicMock()
    history = GoogleHealthHistory(hass, "missing", 120)
    await history.async_upsert([DailyRecord(date(2026, 7, 30))])
    assert history.records == {}


@pytest.mark.asyncio
async def test_history_range_api(memory_store) -> None:
    hass = MagicMock()
    history = GoogleHealthHistory(hass, "range", 120)
    await history.async_upsert(
        [
            DailyRecord(date(2026, 7, day), resting_heart_rate=60 + day)
            for day in (28, 29, 30)
        ]
    )
    records = await history.async_get_daily_records(
        date(2026, 7, 29), date(2026, 7, 30)
    )
    assert [record.date.day for record in records] == [29, 30]
