"""Data update coordinator for Google Health."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    METRIC_AZM,
    METRIC_CALORIES,
    METRIC_RHR,
    METRIC_SLEEP,
    GoogleHealthApiClient,
    GoogleHealthAuthError,
    GoogleHealthError,
    GoogleHealthPermissionError,
)
from .const import (
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    RECENT_REFRESH_DAYS,
)
from .history import GoogleHealthHistory
from .models import CoordinatorData

_LOGGER = logging.getLogger(__name__)

METRICS = (METRIC_SLEEP, METRIC_RHR, METRIC_CALORIES, METRIC_AZM)


class GoogleHealthCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinate polling and preserve partial success."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GoogleHealthApiClient,
        history: GoogleHealthHistory,
        timezone: ZoneInfo,
    ) -> None:
        self.entry = entry
        self.client = client
        self.history = history
        self.timezone = timezone
        self.last_successful_update: datetime | None = None
        self.metric_errors: dict[str, str] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )

    async def async_backfill(self, days: int) -> CoordinatorData:
        """Refresh an inclusive historical window and save chunks incrementally."""
        today = dt_util.now().date()
        start = today - timedelta(days=days - 1)
        return await self._async_refresh_range(start, today)

    async def _async_update_data(self) -> CoordinatorData:
        today = dt_util.now().date()
        start = today - timedelta(days=RECENT_REFRESH_DAYS - 1)
        return await self._async_refresh_range(start, today)

    async def _async_refresh_range(
        self, start_date: date, end_date: date
    ) -> CoordinatorData:
        successes = 0

        async def save_chunk(
            metric: str, values: dict[date, int | float | None]
        ) -> None:
            await self.history.async_replace_metric(metric, values)

        for metric in METRICS:
            try:
                await self.client.async_fetch_metric(
                    metric, start_date, end_date, save_chunk
                )
            except GoogleHealthAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except GoogleHealthPermissionError:
                self.metric_errors[metric] = "permission_denied"
                _LOGGER.warning("Google Health metric %s lacks permission", metric)
            except GoogleHealthError as err:
                self.metric_errors[metric] = type(err).__name__
                _LOGGER.warning(
                    "Google Health metric %s update failed: %s", metric, err
                )
            else:
                successes += 1
                self.metric_errors.pop(metric, None)

        await self.history.async_prune(end_date)
        if successes == 0:
            raise UpdateFailed("All Google Health metric updates failed")

        self.last_successful_update = dt_util.utcnow()
        return CoordinatorData(
            records=self.history.records,
            last_synced=self.last_successful_update,
            metric_errors=dict(self.metric_errors),
        )
