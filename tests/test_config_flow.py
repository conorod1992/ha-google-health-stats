"""OAuth config and reauthentication flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH

from custom_components.google_health.config_flow import GoogleHealthConfigFlow

TOKEN_DATA = {
    "auth_implementation": "google_health",
    "token": {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "expires_at": 9999999999,
    },
}


@pytest.mark.asyncio
async def test_oauth_success_creates_identity_based_entry() -> None:
    flow = GoogleHealthConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.time_zone = "UTC"
    flow.context = {"source": "user"}
    flow.flow_impl = MagicMock(domain="google_health")
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow.async_create_entry = MagicMock(
        return_value={
            "type": "create_entry",
            "title": "Google Health",
            "data": TOKEN_DATA,
        }
    )
    with patch(
        "custom_components.google_health.config_flow.GoogleHealthApiClient.async_get_identity",
        AsyncMock(return_value="stable-health-user-id"),
    ):
        result = await flow.async_oauth_create_entry(TOKEN_DATA)
    flow.async_set_unique_id.assert_awaited_once_with("stable-health-user-id")
    flow._abort_if_unique_id_configured.assert_called_once()
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_reauthentication_updates_existing_entry() -> None:
    flow = GoogleHealthConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.time_zone = "UTC"
    flow.context = {"source": SOURCE_REAUTH}
    flow.flow_impl = MagicMock(domain="google_health")
    entry = MagicMock(unique_id="stable-health-user-id")
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_mismatch = MagicMock()
    flow._get_reauth_entry = MagicMock(return_value=entry)
    flow.async_update_reload_and_abort = MagicMock(
        return_value={"type": "abort", "reason": "reauth_successful"}
    )
    with patch(
        "custom_components.google_health.config_flow.GoogleHealthApiClient.async_get_identity",
        AsyncMock(return_value="stable-health-user-id"),
    ):
        result = await flow.async_oauth_create_entry(TOKEN_DATA)
    flow._abort_if_unique_id_mismatch.assert_called_once_with(reason="wrong_account")
    flow.async_update_reload_and_abort.assert_called_once_with(
        entry, data_updates=TOKEN_DATA
    )
    assert result["reason"] == "reauth_successful"


@pytest.mark.asyncio
async def test_reauth_confirmation() -> None:
    flow = GoogleHealthConfigFlow()
    flow.hass = MagicMock()
    flow.context = {"source": SOURCE_REAUTH}
    flow._flow_id = "test"
    result = await flow.async_step_reauth_confirm()
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
