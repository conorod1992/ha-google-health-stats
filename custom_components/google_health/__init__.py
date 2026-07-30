"""Google Health integration setup and services."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import GoogleHealthApiClient
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DAYS,
    ATTR_END_DATE,
    ATTR_START_DATE,
    CONF_HISTORY_DAYS,
    DEFAULT_HISTORY_DAYS,
    DOMAIN,
    MAX_HISTORY_DAYS,
    MIN_HISTORY_DAYS,
    SERVICE_BACKFILL,
    SERVICE_GET_HISTORY,
    SERVICE_REFRESH,
)
from .coordinator import GoogleHealthCoordinator
from .history import GoogleHealthHistory

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


@dataclass(slots=True)
class GoogleHealthRuntimeData:
    """Objects owned by one config entry."""

    client: GoogleHealthApiClient
    history: GoogleHealthHistory
    coordinator: GoogleHealthCoordinator


GoogleHealthConfigEntry = ConfigEntry[GoogleHealthRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register integration services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        partial(_handle_refresh, hass),
        schema=vol.Schema({vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BACKFILL,
        partial(_handle_backfill, hass),
        schema=vol.Schema(
            {
                vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
                vol.Required(ATTR_DAYS, default=DEFAULT_HISTORY_DAYS): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_HISTORY_DAYS, max=MAX_HISTORY_DAYS),
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HISTORY,
        partial(_handle_get_history, hass),
        schema=vol.Schema(
            {
                vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
                vol.Required(ATTR_START_DATE): cv.date,
                vol.Required(ATTR_END_DATE): cv.date,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: GoogleHealthConfigEntry
) -> bool:
    """Set up a Google Health config entry."""
    try:
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
    except config_entry_oauth2_flow.ImplementationUnavailableError as err:
        raise ConfigEntryNotReady(
            "OAuth2 implementation temporarily unavailable"
        ) from err
    except ValueError as err:
        raise ConfigEntryNotReady("OAuth2 implementation is unavailable") from err

    timezone = ZoneInfo(hass.config.time_zone)
    oauth_session = OAuth2Session(hass, entry, implementation)
    client = GoogleHealthApiClient(oauth_session, timezone)
    history = GoogleHealthHistory(
        hass,
        entry.entry_id,
        entry.options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS),
    )
    await history.async_load()
    coordinator = GoogleHealthCoordinator(hass, entry, client, history, timezone)
    entry.runtime_data = GoogleHealthRuntimeData(client, history, coordinator)

    if history.records:
        await coordinator.async_config_entry_first_refresh()
    else:
        try:
            data = await coordinator.async_backfill(
                entry.options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)
            )
            coordinator.async_set_updated_data(data)
        except ConfigEntryAuthFailed:
            raise
        except UpdateFailed as err:
            raise ConfigEntryNotReady(str(err)) from err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: GoogleHealthConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(
    hass: HomeAssistant, entry: GoogleHealthConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _entries_for_call(
    hass: HomeAssistant, call: ServiceCall
) -> list[GoogleHealthConfigEntry]:
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED and hasattr(entry, "runtime_data")
    ]
    requested = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if requested:
        entries = [entry for entry in entries if entry.entry_id == requested]
    if not entries:
        raise ServiceValidationError("No matching loaded Google Health entry")
    if requested is None and len(entries) > 1:
        raise ServiceValidationError(
            "config_entry_id is required when multiple Google Health accounts exist"
        )
    return entries


async def _handle_refresh(hass: HomeAssistant, call: ServiceCall) -> None:
    for entry in _entries_for_call(hass, call):
        await entry.runtime_data.coordinator.async_request_refresh()


async def _handle_backfill(hass: HomeAssistant, call: ServiceCall) -> None:
    days = call.data[ATTR_DAYS]
    for entry in _entries_for_call(hass, call):
        data = await entry.runtime_data.coordinator.async_backfill(days)
        entry.runtime_data.coordinator.async_set_updated_data(data)


async def _handle_get_history(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    start_date: date = call.data[ATTR_START_DATE]
    end_date: date = call.data[ATTR_END_DATE]
    if end_date < start_date:
        raise ServiceValidationError("end_date must be on or after start_date")
    if (end_date - start_date).days >= MAX_HISTORY_DAYS:
        raise ServiceValidationError("Requested range may not exceed 120 days")
    entry = _entries_for_call(hass, call)[0]
    records = await entry.runtime_data.history.async_get_daily_records(
        start_date, end_date
    )
    return {"records": [record.as_dict() for record in records]}
