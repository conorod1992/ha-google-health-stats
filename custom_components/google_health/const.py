"""Constants for Google Health."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "google_health"
NAME: Final = "Google Health"
VERSION: Final = "0.1.0"

PLATFORMS: Final = ["sensor"]

API_BASE_URL: Final = "https://health.googleapis.com/v4"
AUTHORIZE_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL: Final = "https://oauth2.googleapis.com/token"

SCOPE_ACTIVITY: Final = (
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
)
SCOPE_HEALTH: Final = "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
SCOPE_SLEEP: Final = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"
OAUTH_SCOPES: Final = [SCOPE_ACTIVITY, SCOPE_HEALTH, SCOPE_SLEEP]

CONF_POLL_INTERVAL: Final = "poll_interval"
CONF_HISTORY_DAYS: Final = "history_days"
DEFAULT_POLL_INTERVAL: Final = 15
MIN_POLL_INTERVAL: Final = 5
MAX_POLL_INTERVAL: Final = 120
DEFAULT_HISTORY_DAYS: Final = 120
MIN_HISTORY_DAYS: Final = 1
MAX_HISTORY_DAYS: Final = 120
RECENT_REFRESH_DAYS: Final = 3

DEFAULT_UPDATE_INTERVAL: Final = timedelta(minutes=DEFAULT_POLL_INTERVAL)
STORAGE_VERSION: Final = 1
STORAGE_KEY_PREFIX: Final = f"{DOMAIN}.history"

SERVICE_REFRESH: Final = "refresh"
SERVICE_BACKFILL: Final = "backfill"
SERVICE_GET_HISTORY: Final = "get_history"

ATTR_DAYS: Final = "days"
ATTR_START_DATE: Final = "start_date"
ATTR_END_DATE: Final = "end_date"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"

SUPPORTED_METRICS: Final = (
    "sleep_duration",
    "resting_heart_rate",
    "total_calories",
    "active_zone_minutes",
)
UNSUPPORTED_REQUESTED_METRICS: Final = ("sleep_quality", "cardio_load")
