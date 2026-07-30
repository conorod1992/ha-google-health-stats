# Google Health for Home Assistant

Google Health is an independent, HACS-ready Home Assistant custom integration for health and fitness data synced by Fitbit and Pixel Watch devices to the **Google Health API v4**. It does not use the legacy Fitbit Web API and is not an official Google, Fitbit, or Home Assistant project.

The integration provides current sensors, week-to-date aggregates, and a private local cache of up to 120 normalized daily records. The cache is deliberately separate from sensor entities so automations, Jarvis, or future local analysis can query it without putting a large health dataset in entity attributes.

## Requirements

- Home Assistant 2026.7 or newer
- A Google account with relevant data in the Fitbit app
- A compatible Fitbit or Pixel Watch (or other source that makes the requested types available through Google Health)
- A Google Cloud project and OAuth 2.0 client

Data appears only after the tracker has synced to the Fitbit app. Device compatibility does not guarantee that every metric exists for every day.

## Installation through HACS

Until this repository is included in HACS defaults:

1. Open HACS in Home Assistant.
2. Open **Integrations**, then the three-dot menu, and choose **Custom repositories**.
3. Enter `https://github.com/conorod1992/ha-google-health-stats`.
4. Select **Integration** as the category and add it.
5. Find **Google Health**, choose **Download**, and restart Home Assistant.

Manual installation is also possible by copying `custom_components/google_health` into the same path under the Home Assistant configuration directory, then restarting.

## Google Cloud and OAuth setup

Google's console changes occasionally; the labels below match the current Google Health setup documentation.

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Open **APIs & Services → Library**, search for **Google Health API**, and enable it.
3. Open **Google Auth Platform** and configure **Branding**, **Audience**, and **Data Access** if prompted.
4. Under **Audience**, choose the appropriate user type. For a private installation, **External** with publishing status **Testing** is sufficient, but add the Google account you will authorize under **Test users**.
5. Under **Data Access**, add these three Google Health read-only scopes:
   - `.../auth/googlehealth.activity_and_fitness.readonly`
   - `.../auth/googlehealth.health_metrics_and_measurements.readonly`
   - `.../auth/googlehealth.sleep.readonly`
6. In Home Assistant, open **Settings → Devices & services**, open the three-dot menu, and select **Application credentials**. Start adding credentials for **Google Health**. Home Assistant shows the OAuth redirect URI you must register.
7. Back in Google Cloud, open **Google Auth Platform → Clients**, create an **OAuth client ID**, and select **Web application**.
8. Add the exact redirect URI shown by Home Assistant under **Authorized redirect URIs**. With My Home Assistant enabled this is normally `https://my.home-assistant.io/redirect/oauth`; otherwise it is your externally reachable Home Assistant URL followed by `/auth/external/callback`.
9. Copy the client ID and client secret into the Home Assistant Application Credentials dialog and save.

The client must be a **Web application**, and the redirect URI must match exactly, including scheme, hostname, port, and path.

### Testing-mode token expiry

Google OAuth refresh tokens issued while the consent screen has **Testing** publishing status expire after **7 days**. Home Assistant will then ask you to reconnect the integration. Moving the OAuth app to **In production** avoids that testing-mode lifetime, although Google may require verification/security review for broad public use. A personal unverified project is also limited to its configured test users and Google's user caps. Never publish a client secret in this repository.

## Adding the integration

1. Open **Settings → Devices & services**.
2. Choose **Add integration** and search for **Google Health**.
3. Select the application credential if Home Assistant asks.
4. Sign in to Google and grant the three requested read-only permissions.
5. Home Assistant validates the Google Health identity, prevents duplicate account entries, and begins the 120-day initial import.

No YAML configuration is required. Options allow a polling interval from 5 to 120 minutes (default 15) and history retention from 1 to 120 days (default 120).

## Sensors

Only metrics documented by Google Health are created. Entity IDs assume the default device/entity naming and can still be customized in Home Assistant.

| Sensor | Default entity ID | Unit | Description | Google Health source |
|---|---|---:|---|---|
| Sleep duration | `sensor.google_health_sleep_duration` | h | Actual minutes asleep for the newest completed primary sleep, assigned to its civil end date | `sleep` session → `summary.minutesAsleep` |
| Resting heart rate | `sensor.google_health_resting_heart_rate` | bpm | Latest official daily resting heart rate; it is never calculated from raw samples | `daily-resting-heart-rate` → `beatsPerMinute` |
| Calories burned | `sensor.google_health_calories_burned` | kcal | Today's total calories, including basal and active expenditure | `total-calories` daily rollup → `kcalSum` |
| Active Zone Minutes | `sensor.google_health_active_zone_minutes` | min | Today's AZM summed across fat-burn, cardio, and peak rollup fields | `active-zone-minutes` daily rollup |
| Active Zone Minutes this week | `sensor.google_health_active_zone_minutes_this_week` | min | Monday through today; missing days are ignored | Local aggregate of AZM daily records |
| Average sleep this week | `sensor.google_health_average_sleep_this_week` | h | Mean of completed primary sleeps assigned to the current Monday–Sunday week; missing days are not zero | Local aggregate of `sleep` records |

An overnight sleep belongs to the date on which Google reports that it ended in the user's civil time. Naps are excluded from the primary daily sleep value. The API's official `minutesAsleep` summary is preferred; stage durations are used only as a defensive fallback and awake/restless stages are excluded.

## Historical data

Normalized daily records are stored with Home Assistant's supported local storage mechanism and persist across restarts. Records are upserted so later Google/Fitbit corrections replace prior metric values, missing metrics remain `null`, and records older than the selected retention window are pruned. The integration refreshes the latest three days on normal polls and performs the full backfill only on first setup or when requested.

Available actions:

- `google_health.refresh` — perform a normal recent refresh now.
- `google_health.backfill` — refresh 1–120 days; requests are split to respect Google's 14-day and 90-day endpoint limits.
- `google_health.get_history` — response-only action that returns cached normalized records for an inclusive range of at most 120 days.

If more than one account is configured, pass `config_entry_id`. Full history is never copied into entity attributes or diagnostics.

## Privacy

Health data travels directly from Google Health to the user's Home Assistant instance and is stored locally by this integration. OAuth tokens are managed by Home Assistant. Diagnostics exclude OAuth credentials, Google account identifiers, and all health measurements; they contain only status, options, metric support, and cache date/count metadata.

Review Google's Health API terms and user-data policy before using or distributing an application built with the API.

## API limitations

As of the current Google Health API v4 documentation:

- **Sleep Score / Sleep Quality is not exposed as a genuine Google Health data type or field.** This integration does not invent a score and does not create a permanently unknown entity.
- **Fitbit Cardio Load is not exposed as a genuine Google Health metric.** This integration does not approximate it from heart rate, workouts, calories, or AZM and does not create an entity.

The internal normalized model can add these values later without changing the storage/query architecture if Google publishes official fields.

## Troubleshooting

- **Authorization stops after sign-in:** verify the account is listed under **Test users**, the three scopes are configured under **Data Access**, and the OAuth client is a Web application.
- **`redirect_uri_mismatch`:** copy Home Assistant's redirect URI exactly into the client's authorized redirect URIs.
- **Reconnect required every seven days:** the OAuth consent screen is in Testing mode; this is Google's expected refresh-token behavior.
- **A sensor has no value:** the source may not provide that metric/day, the tracker may not have synced, or the required permission was not granted. Missing data is intentionally not converted to zero.
- **Only one metric is unavailable:** Google can reject or temporarily fail an individual data type. Other metrics and cached history continue working.
- **Rate limiting/server outage:** requests use bounded retries, prior values are retained, and Home Assistant retries on later coordinator updates.
- **Wrong account during reconnect:** reauthentication must use the same Google Health account. Add a separate integration entry for a second account.

Enable debug logging temporarily if needed:

```yaml
logger:
  logs:
    custom_components.google_health: debug
```

Logs contain status information, not health payloads or OAuth secrets.

## Development and contributing

Contributions are welcome. Create a focused branch, add tests for behavioral changes, and run:

```text
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy custom_components/google_health
```

Open a pull request describing the API documentation relied on and any privacy impact. Never include real tokens or health data in fixtures.

## Releases

Update the semantic version in `custom_components/google_health/manifest.json`, add release notes, create a tag such as `v0.1.0`, and publish a GitHub release using that tag. HACS installs the integration files from the release/repository root.

## License

MIT — see [LICENSE](LICENSE).
