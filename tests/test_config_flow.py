"""OAuth config and reauthentication flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH

from custom_components.google_health.api import (
    GoogleHealthAccountNotLinkedError,
    GoogleHealthPermissionError,
)
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


def test_oauth_does_not_combine_previously_granted_scopes() -> None:
    flow = GoogleHealthConfigFlow()
    authorize_data = flow.extra_authorize_data
    assert "include_granted_scopes" not in authorize_data
    assert "googlehealth.activity_and_fitness.readonly" in authorize_data["scope"]


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


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (GoogleHealthAccountNotLinkedError(), "account_not_linked"),
        (
            GoogleHealthPermissionError("missing", "MISSING_OAUTH_SCOPE"),
            "missing_permissions",
        ),
        (
            GoogleHealthPermissionError("combined", "DISALLOWED_OAUTH_SCOPES"),
            "disallowed_permissions",
        ),
        (
            GoogleHealthPermissionError(
                "unavailable", "API_PRIVATE_PREVIEW_ACCESS_DENIED"
            ),
            "access_not_available",
        ),
        (
            GoogleHealthPermissionError("denied", "DATA_ACCESS_DENIED"),
            "data_access_denied",
        ),
    ],
)
@pytest.mark.asyncio
async def test_oauth_reports_actionable_google_error(
    error: Exception, reason: str
) -> None:
    flow = GoogleHealthConfigFlow()
    flow.hass = MagicMock()
    flow.hass.config.time_zone = "UTC"
    flow.context = {"source": "user"}
    flow.flow_impl = MagicMock(domain="google_health")
    with patch(
        "custom_components.google_health.config_flow.GoogleHealthApiClient.async_get_identity",
        AsyncMock(side_effect=error),
    ):
        result = await flow.async_oauth_create_entry(TOKEN_DATA)
    assert result["type"] == "abort"
    assert result["reason"] == reason
