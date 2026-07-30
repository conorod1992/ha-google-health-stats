"""Privacy-preserving diagnostics for Google Health."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import GoogleHealthConfigEntry
from .api import METRIC_AZM, METRIC_CALORIES, METRIC_RHR, METRIC_SLEEP
from .const import (
    SUPPORTED_METRICS,
    UNSUPPORTED_REQUESTED_METRICS,
    VERSION,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GoogleHealthConfigEntry
) -> dict[str, Any]:
    """Return diagnostics without tokens, identifiers, or health values."""
    runtime = entry.runtime_data
    days = sorted(runtime.history.records)
    coordinator = runtime.coordinator
    return {
        "integration_version": VERSION,
        "options": dict(entry.options),
        "last_successful_update": (
            coordinator.last_successful_update.isoformat()
            if coordinator.last_successful_update
            else None
        ),
        "last_update_success": coordinator.last_update_success,
        "supported_metrics": list(SUPPORTED_METRICS),
        "unsupported_requested_metrics": list(UNSUPPORTED_REQUESTED_METRICS),
        "metric_status": {
            "sleep_duration": coordinator.metric_errors.get(METRIC_SLEEP, "ok"),
            "resting_heart_rate": coordinator.metric_errors.get(METRIC_RHR, "ok"),
            "total_calories": coordinator.metric_errors.get(METRIC_CALORIES, "ok"),
            "active_zone_minutes": coordinator.metric_errors.get(METRIC_AZM, "ok"),
        },
        "history": {
            "days_cached": len(days),
            "oldest_date": days[0].isoformat() if days else None,
            "newest_date": days[-1].isoformat() if days else None,
        },
    }
