"""Application credentials support for Google Health."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant

from .const import AUTHORIZE_URL, TOKEN_URL


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return Google's OAuth 2.0 authorization server."""
    return AuthorizationServer(authorize_url=AUTHORIZE_URL, token_url=TOKEN_URL)


async def async_get_description_placeholders(
    hass: HomeAssistant,
) -> dict[str, str]:
    """Return placeholders for the Application Credentials dialog."""
    return {
        "console_url": "https://console.cloud.google.com/apis/credentials",
        "setup_url": "https://developers.google.com/health/setup",
    }
