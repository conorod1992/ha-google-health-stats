"""Entity calculation and metadata tests."""

from __future__ import annotations

from datetime import date

from homeassistant.const import UnitOfEnergy, UnitOfTime

from custom_components.google_health.models import DailyRecord
from custom_components.google_health.sensor import (
    SENSORS,
    weekly_average_sleep,
    weekly_azm,
)


def test_weekly_azm_calculation() -> None:
    today = date(2026, 7, 30)  # Thursday
    records = {
        date(2026, 7, 26): DailyRecord(date(2026, 7, 26), active_zone_minutes=99),
        date(2026, 7, 27): DailyRecord(date(2026, 7, 27), active_zone_minutes=10),
        date(2026, 7, 29): DailyRecord(date(2026, 7, 29), active_zone_minutes=20),
        date(2026, 7, 30): DailyRecord(date(2026, 7, 30), active_zone_minutes=0),
    }
    assert weekly_azm(records, today) == 30


def test_weekly_average_sleep_ignores_missing_days() -> None:
    today = date(2026, 7, 30)
    records = {
        date(2026, 7, 27): DailyRecord(
            date(2026, 7, 27), sleep_duration_seconds=7 * 3600
        ),
        date(2026, 7, 29): DailyRecord(
            date(2026, 7, 29), sleep_duration_seconds=9 * 3600
        ),
        date(2026, 7, 30): DailyRecord(date(2026, 7, 30)),
    }
    assert weekly_average_sleep(records, today) == 8.0


def test_entity_state_values_and_units() -> None:
    descriptions = {description.key: description for description in SENSORS}
    assert descriptions["sleep_duration"].native_unit_of_measurement == UnitOfTime.HOURS
    assert descriptions["resting_heart_rate"].native_unit_of_measurement == "bpm"
    assert (
        descriptions["calories_burned"].native_unit_of_measurement
        == UnitOfEnergy.KILO_CALORIE
    )
    assert (
        descriptions["active_zone_minutes"].native_unit_of_measurement
        == UnitOfTime.MINUTES
    )
    records = {
        date(2026, 7, 30): DailyRecord(
            date(2026, 7, 30),
            sleep_duration_seconds=27_000,
            resting_heart_rate=64,
            total_calories_kcal=2458,
            active_zone_minutes=38,
        )
    }
    assert descriptions["sleep_duration"].value_fn(records, date(2026, 7, 30)) == 7.5
    assert descriptions["calories_burned"].value_fn(records, date(2026, 7, 30)) == 2458


def test_unsupported_entities_are_not_created() -> None:
    keys = {description.key for description in SENSORS}
    assert "sleep_quality" not in keys
    assert "cardio_load" not in keys
