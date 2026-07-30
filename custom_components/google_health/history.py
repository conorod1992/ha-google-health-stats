"""Persistent normalized daily history repository."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import MAX_HISTORY_DAYS, STORAGE_KEY_PREFIX, STORAGE_VERSION
from .models import DailyRecord


class GoogleHealthHistory:
    """Small config-entry-scoped repository for daily records."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        retention_days: int = MAX_HISTORY_DAYS,
    ) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._retention_days = max(1, min(retention_days, MAX_HISTORY_DAYS))
        self._records: dict[date, DailyRecord] = {}

    @property
    def records(self) -> dict[date, DailyRecord]:
        """Return a copy of all cached records."""
        return dict(self._records)

    async def async_load(self) -> None:
        """Load records from Home Assistant storage."""
        data = await self._store.async_load()
        if not data:
            return
        records = data.get("records", [])
        self._records = {
            record.date: record
            for raw in records
            if isinstance(raw, dict)
            for record in [DailyRecord.from_dict(raw)]
            if record.has_data
        }

    async def async_upsert(self, records: Iterable[DailyRecord]) -> bool:
        """Upsert normalized records, preserving independently missing metrics."""
        changed = False
        for update in records:
            if not update.has_data:
                continue
            current = self._records.get(update.date)
            merged = update if current is None else current.merged(update)
            if merged != current:
                self._records[update.date] = merged
                changed = True
        if changed:
            await self._async_save()
        return changed

    async def async_replace_metric(
        self,
        metric: str,
        values: dict[date, int | float | None],
    ) -> bool:
        """Replace a metric for queried days, including genuine zero values."""
        changed = False
        for day, value in values.items():
            current = self._records.get(day, DailyRecord(date=day))
            if not hasattr(current, metric):
                raise ValueError(f"Unknown metric: {metric}")
            if getattr(current, metric) == value:
                continue
            setattr(current, metric, value)
            if current.has_data:
                self._records[day] = current
            else:
                self._records.pop(day, None)
            changed = True
        if changed:
            await self._async_save()
        return changed

    async def async_prune(self, today: date) -> bool:
        """Prune records outside the configured inclusive retention window."""
        oldest = today - timedelta(days=self._retention_days - 1)
        stale = [day for day in self._records if day < oldest or day > today]
        if not stale:
            return False
        for day in stale:
            del self._records[day]
        await self._async_save()
        return True

    async def async_get_daily_records(
        self, start_date: date, end_date: date
    ) -> list[DailyRecord]:
        """Return records in an inclusive date range."""
        if end_date < start_date:
            return []
        return [
            self._records[day]
            for day in sorted(self._records)
            if start_date <= day <= end_date
        ]

    async def async_get_latest_record(self) -> DailyRecord | None:
        """Return the newest record."""
        if not self._records:
            return None
        return self._records[max(self._records)]

    async def async_get_week_records(self, day: date) -> list[DailyRecord]:
        """Return records for the Monday-Sunday week containing day."""
        start = day - timedelta(days=day.weekday())
        return await self.async_get_daily_records(start, start + timedelta(days=6))

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"records": [self._records[day].as_dict() for day in sorted(self._records)]}
        )
