"""OAuth2 config and options flows for Google Health."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GoogleHealthAccountNotLinkedError,
    GoogleHealthApiClient,
    GoogleHealthAuthError,
    GoogleHealthError,
    GoogleHealthPermissionError,
)
from .const import (
    CONF_HISTORY_DAYS,
    CONF_POLL_INTERVAL,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_HISTORY_DAYS,
    MAX_POLL_INTERVAL,
    MIN_HISTORY_DAYS,
    MIN_POLL_INTERVAL,
    OAUTH_SCOPES,
)

_LOGGER = logging.getLogger(__name__)


class GoogleHealthConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle Google Health OAuth2 configuration."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        """Request offline access and only the required read-only scopes."""
        return {
            "scope": " ".join(OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the reauthentication flow."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Validate OAuth and identify the linked account."""
        oauth_session = _ConfigFlowSession(self.hass, data[CONF_TOKEN])
        client = GoogleHealthApiClient(
            oauth_session, ZoneInfo(self.hass.config.time_zone)
        )
        try:
            health_user_id = await client.async_get_identity()
        except GoogleHealthAuthError:
            return self.async_abort(reason="invalid_auth")
        except GoogleHealthAccountNotLinkedError:
            return self.async_abort(reason="account_not_linked")
        except GoogleHealthPermissionError as err:
            if err.reason in {"MISSING_OAUTH_SCOPE", "DISALLOWED_OAUTH_SCOPES"}:
                return self.async_abort(reason="missing_permissions")
            if err.reason == "API_PRIVATE_PREVIEW_ACCESS_DENIED":
                return self.async_abort(reason="access_not_available")
            return self.async_abort(reason="data_access_denied")
        except GoogleHealthError:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(health_user_id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates=data
            )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Google Health", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> GoogleHealthOptionsFlow:
        """Return the options flow."""
        return GoogleHealthOptionsFlow(config_entry)


class GoogleHealthOptionsFlow(OptionsFlow):
    """Configure safe polling and cache retention defaults."""

    def __init__(self, config_entry: Any) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self._entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                    vol.Required(
                        CONF_HISTORY_DAYS,
                        default=self._entry.options.get(
                            CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_HISTORY_DAYS, max=MAX_HISTORY_DAYS),
                    ),
                }
            ),
        )


class _ConfigFlowSession:
    """Minimal requester for validating a newly issued access token."""

    def __init__(self, hass: Any, token: dict[str, Any]) -> None:
        self._hass = hass
        self._token = token

    async def async_request(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        return await async_get_clientsession(self._hass).request(
            method,
            url,
            **kwargs,
            headers={
                **headers,
                "authorization": f"Bearer {self._token['access_token']}",
            },
        )
