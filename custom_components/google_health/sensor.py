"""Sensor platform for Google Health."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import GoogleHealthConfigEntry
from .api import METRIC_AZM, METRIC_CALORIES, METRIC_RHR, METRIC_SLEEP
from .const import DOMAIN, NAME
from .coordinator import GoogleHealthCoordinator
from .models import DailyRecord


@dataclass(frozen=True, kw_only=True)
class GoogleHealthSensorDescription(SensorEntityDescription):
    """Describe a Google Health sensor."""

    value_fn: Callable[[dict[date, DailyRecord], date], int | float | None]
    metric: str
    attribute_fn: Callable[[dict[date, DailyRecord], date], dict[str, Any]] | None = (
        None
    )


def _today_value(field: str) -> Callable[[dict[date, DailyRecord], date], Any]:
    def value(records: dict[date, DailyRecord], today: date) -> Any:
        record = records.get(today)
        return getattr(record, field) if record is not None else None

    return value


def _latest_value(field: str) -> Callable[[dict[date, DailyRecord], date], Any]:
    def value(records: dict[date, DailyRecord], today: date) -> Any:
        for day in sorted((day for day in records if day <= today), reverse=True):
            candidate = getattr(records[day], field)
            if candidate is not None:
                return candidate
        return None

    return value


def weekly_azm(records: dict[date, DailyRecord], today: date) -> int | None:
    """Sum AZM from Monday through today, ignoring missing days."""
    week_start = today - timedelta(days=today.weekday())
    values = [
        record.active_zone_minutes
        for day, record in records.items()
        if week_start <= day <= today and record.active_zone_minutes is not None
    ]
    return sum(values) if values else None


def weekly_average_sleep(records: dict[date, DailyRecord], today: date) -> float | None:
    """Average completed primary sleeps assigned to their civil end date."""
    week_start = today - timedelta(days=today.weekday())
    values = [
        record.sleep_duration_seconds
        for day, record in records.items()
        if week_start <= day <= today and record.sleep_duration_seconds is not None
    ]
    if not values:
        return None
    return sum(values) / len(values) / 3600


def _week_attributes(
    records: dict[date, DailyRecord], today: date, field: str
) -> dict[str, Any]:
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    days = sum(
        1
        for day, record in records.items()
        if week_start <= day <= today and getattr(record, field) is not None
    )
    return {
        "days_with_data": days,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
    }


def _sleep_week_attributes(
    records: dict[date, DailyRecord], today: date
) -> dict[str, Any]:
    attributes = _week_attributes(records, today, "sleep_duration_seconds")
    average = weekly_average_sleep(records, today)
    if average is not None:
        total_minutes = round(average * 60)
        attributes["human_readable_duration"] = (
            f"{total_minutes // 60}h {total_minutes % 60}m"
        )
    attributes["sleep_assigned_to"] = "civil end date"
    return attributes


SENSORS: tuple[GoogleHealthSensorDescription, ...] = (
    GoogleHealthSensorDescription(
        key="sleep_duration",
        translation_key="sleep_duration",
        icon="mdi:sleep",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda records, today: (
            value / 3600
            if (value := _latest_value("sleep_duration_seconds")(records, today))
            is not None
            else None
        ),
        metric=METRIC_SLEEP,
    ),
    GoogleHealthSensorDescription(
        key="resting_heart_rate",
        translation_key="resting_heart_rate",
        icon="mdi:heart-pulse",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_latest_value("resting_heart_rate"),
        metric=METRIC_RHR,
    ),
    GoogleHealthSensorDescription(
        key="calories_burned",
        translation_key="calories_burned",
        icon="mdi:fire",
        native_unit_of_measurement=UnitOfEnergy.KILO_CALORIE,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=_today_value("total_calories_kcal"),
        metric=METRIC_CALORIES,
    ),
    GoogleHealthSensorDescription(
        key="active_zone_minutes",
        translation_key="active_zone_minutes",
        icon="mdi:run-fast",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        value_fn=_today_value("active_zone_minutes"),
        metric=METRIC_AZM,
    ),
    GoogleHealthSensorDescription(
        key="active_zone_minutes_this_week",
        translation_key="active_zone_minutes_this_week",
        icon="mdi:calendar-week",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL,
        value_fn=weekly_azm,
        metric=METRIC_AZM,
        attribute_fn=lambda records, today: _week_attributes(
            records, today, "active_zone_minutes"
        ),
    ),
    GoogleHealthSensorDescription(
        key="average_sleep_this_week",
        translation_key="average_sleep_this_week",
        icon="mdi:sleep",
        native_unit_of_measurement=UnitOfTime.HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=weekly_average_sleep,
        metric=METRIC_SLEEP,
        attribute_fn=_sleep_week_attributes,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHealthConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Google Health sensors."""
    async_add_entities(
        GoogleHealthSensor(entry.runtime_data.coordinator, entry, description)
        for description in SENSORS
    )


class GoogleHealthSensor(CoordinatorEntity[GoogleHealthCoordinator], SensorEntity):
    """A normalized Google Health sensor."""

    _attr_has_entity_name = True
    entity_description: GoogleHealthSensorDescription

    def __init__(
        self,
        coordinator: GoogleHealthCoordinator,
        entry: GoogleHealthConfigEntry,
        description: GoogleHealthSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=NAME,
            manufacturer="Google",
            model="Google Health API",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int | float | None:
        """Return the current normalized value."""
        data = self.coordinator.data
        if data is None:
            return None
        return self.entity_description.value_fn(data.records, dt_util.now().date())

    @property
    def available(self) -> bool:
        """Mark only the affected metric unavailable after partial failures."""
        return (
            super().available
            and self.entity_description.metric not in self.coordinator.metric_errors
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return compact sync and aggregate context."""
        data = self.coordinator.data
        if data is None:
            return {}
        attributes: dict[str, Any] = {}
        if self.entity_description.attribute_fn is not None:
            attributes.update(
                self.entity_description.attribute_fn(data.records, dt_util.now().date())
            )
        if data.last_synced is not None:
            attributes["last_synced"] = data.last_synced.isoformat()
        return attributes
