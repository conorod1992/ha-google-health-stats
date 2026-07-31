"""Data models for Google Health."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class DailyRecord:
    """Normalized values for one civil calendar day."""

    date: date
    sleep_duration_seconds: int | None = None
    resting_heart_rate: int | None = None
    total_calories_kcal: float | None = None
    active_zone_minutes: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        value = asdict(self)
        value["date"] = self.date.isoformat()
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DailyRecord:
        """Create a record from stored JSON."""
        return cls(
            date=date.fromisoformat(value["date"]),
            sleep_duration_seconds=_optional_int(value.get("sleep_duration_seconds")),
            resting_heart_rate=_optional_int(value.get("resting_heart_rate")),
            total_calories_kcal=_optional_float(value.get("total_calories_kcal")),
            active_zone_minutes=_optional_int(value.get("active_zone_minutes")),
        )

    def merged(self, update: DailyRecord) -> DailyRecord:
        """Merge independently available metrics from an update."""
        if update.date != self.date:
            raise ValueError("Cannot merge records for different dates")
        return DailyRecord(
            date=self.date,
            sleep_duration_seconds=(
                update.sleep_duration_seconds
                if update.sleep_duration_seconds is not None
                else self.sleep_duration_seconds
            ),
            resting_heart_rate=(
                update.resting_heart_rate
                if update.resting_heart_rate is not None
                else self.resting_heart_rate
            ),
            total_calories_kcal=(
                update.total_calories_kcal
                if update.total_calories_kcal is not None
                else self.total_calories_kcal
            ),
            active_zone_minutes=(
                update.active_zone_minutes
                if update.active_zone_minutes is not None
                else self.active_zone_minutes
            ),
        )

    @property
    def has_data(self) -> bool:
        """Return whether at least one metric is present."""
        return any(
            value is not None
            for value in (
                self.sleep_duration_seconds,
                self.resting_heart_rate,
                self.total_calories_kcal,
                self.active_zone_minutes,
            )
        )


@dataclass(slots=True)
class CoordinatorData:
    """Coordinator state exposed to entities and diagnostics."""

    records: dict[date, DailyRecord]
    last_synced: datetime | None
    metric_errors: dict[str, str]


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)
