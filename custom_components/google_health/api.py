"""Async client and parsers for the documented Google Health API v4."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientResponse
from homeassistant.exceptions import (
    OAuth2TokenRequestReauthError,
    OAuth2TokenRequestTransientError,
)

from .const import API_BASE_URL

_LOGGER = logging.getLogger(__name__)

MetricValues = dict[date, int | float | None]
ChunkCallback = Callable[[str, MetricValues], Awaitable[None]]

METRIC_SLEEP = "sleep_duration_seconds"
METRIC_RHR = "resting_heart_rate"
METRIC_CALORIES = "total_calories_kcal"
METRIC_AZM = "active_zone_minutes"

DATA_TYPE_SLEEP = "sleep"
DATA_TYPE_RHR = "daily-resting-heart-rate"
DATA_TYPE_CALORIES = "total-calories"
DATA_TYPE_AZM = "active-zone-minutes"


class GoogleHealthError(Exception):
    """Base Google Health client error."""


class GoogleHealthAuthError(GoogleHealthError):
    """Authorization is invalid or revoked."""


class GoogleHealthAccountNotLinkedError(GoogleHealthError):
    """The Google account is not linked to a Fitbit account."""


class GoogleHealthPermissionError(GoogleHealthError):
    """A required scope was not granted."""

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class GoogleHealthRateLimitError(GoogleHealthError):
    """Google Health rate limit was exceeded."""


class GoogleHealthTemporaryError(GoogleHealthError):
    """A retryable connectivity or server error occurred."""


class GoogleHealthResponseError(GoogleHealthError):
    """Google Health returned an unexpected response."""


class AsyncOAuthRequester(Protocol):
    """Structural type shared by config-flow and config-entry requesters."""

    async def async_request(
        self, method: str, url: str, **kwargs: Any
    ) -> ClientResponse:
        """Make an authenticated request."""


class GoogleHealthApiClient:
    """Google Health REST API client backed by Home Assistant OAuth."""

    def __init__(self, oauth_session: AsyncOAuthRequester, timezone: ZoneInfo) -> None:
        self._oauth_session = oauth_session
        self._timezone = timezone

    async def async_get_identity(self) -> str:
        """Return the stable Google Health user ID."""
        payload = await self._async_request("GET", "/users/me/identity")
        health_user_id = payload.get("healthUserId")
        if not isinstance(health_user_id, str) or not health_user_id:
            raise GoogleHealthResponseError("Identity response has no healthUserId")
        return health_user_id

    async def async_fetch_metric(
        self,
        metric: str,
        start_date: date,
        end_date: date,
        on_chunk: ChunkCallback | None = None,
    ) -> MetricValues:
        """Fetch a normalized metric over an inclusive date range."""
        if end_date < start_date:
            return {}

        if metric == METRIC_CALORIES:
            chunk_days = 14
        elif metric in (METRIC_SLEEP, METRIC_RHR, METRIC_AZM):
            chunk_days = 90
        else:
            raise ValueError(f"Unsupported metric: {metric}")

        combined: MetricValues = {}
        for chunk_start, chunk_end in iter_date_chunks(
            start_date, end_date, chunk_days
        ):
            values: MetricValues
            if metric == METRIC_SLEEP:
                values = await self._async_fetch_sleep(chunk_start, chunk_end)
            elif metric == METRIC_RHR:
                values = await self._async_fetch_rhr(chunk_start, chunk_end)
            elif metric == METRIC_CALORIES:
                values = await self._async_fetch_daily_rollup(
                    DATA_TYPE_CALORIES, chunk_start, chunk_end
                )
            else:
                values = await self._async_fetch_daily_rollup(
                    DATA_TYPE_AZM, chunk_start, chunk_end
                )

            # A successful query authoritatively represents each day in its range.
            normalized: MetricValues = {
                day: values.get(day)
                for day in date_range(chunk_start, chunk_end - timedelta(days=1))
            }
            combined.update(normalized)
            if on_chunk is not None:
                await on_chunk(metric, normalized)
        return combined

    async def _async_fetch_sleep(
        self, start_date: date, end_exclusive: date
    ) -> MetricValues:
        filter_value = (
            f'sleep.interval.civil_end_time >= "{start_date.isoformat()}" AND '
            f'sleep.interval.civil_end_time < "{end_exclusive.isoformat()}"'
        )
        points = await self._async_list_data_points(
            DATA_TYPE_SLEEP, filter_value, page_size=25
        )
        result: MetricValues = {}
        for point in points:
            sleep = point.get("sleep")
            if not isinstance(sleep, dict):
                continue
            parsed = parse_sleep_session(sleep, self._timezone)
            if parsed is None:
                continue
            sleep_day, seconds, is_nap = parsed
            if is_nap or sleep_day < start_date or sleep_day >= end_exclusive:
                continue
            # Multiple non-nap logs can exist after edits; prefer the longest.
            existing = result.get(sleep_day)
            result[sleep_day] = (
                seconds if existing is None else max(seconds, int(existing))
            )
        return result

    async def _async_fetch_rhr(
        self, start_date: date, end_exclusive: date
    ) -> MetricValues:
        filter_value = (
            f'dailyRestingHeartRate.date >= "{start_date.isoformat()}" AND '
            f'dailyRestingHeartRate.date < "{end_exclusive.isoformat()}"'
        )
        points = await self._async_list_data_points(DATA_TYPE_RHR, filter_value)
        result: MetricValues = {}
        for point in points:
            value = point.get("dailyRestingHeartRate")
            if not isinstance(value, dict):
                continue
            day = parse_google_date(value.get("date"))
            bpm = _as_int(value.get("beatsPerMinute"))
            if day is not None and bpm is not None:
                result[day] = bpm
        return result

    async def _async_fetch_daily_rollup(
        self, data_type: str, start_date: date, end_exclusive: date
    ) -> MetricValues:
        request_body: dict[str, Any] = {
            "range": {
                "start": {"date": google_date(start_date)},
                "end": {"date": google_date(end_exclusive)},
            },
            "windowSizeDays": 1,
            "pageSize": 10000,
        }
        result: MetricValues = {}
        page_token: str | None = None
        while True:
            body = dict(request_body)
            if page_token:
                body["pageToken"] = page_token
            payload = await self._async_request(
                "POST",
                f"/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp",
                json=body,
            )
            points = payload.get("rollupDataPoints", [])
            if not isinstance(points, list):
                raise GoogleHealthResponseError("rollupDataPoints is not a list")
            for point in points:
                if not isinstance(point, dict):
                    continue
                day = parse_google_date(
                    point.get("civilStartTime", {}).get("date")
                    if isinstance(point.get("civilStartTime"), dict)
                    else None
                )
                if day is None:
                    continue
                if data_type == DATA_TYPE_CALORIES:
                    rollup = point.get("totalCalories")
                    value = (
                        _as_float(rollup.get("kcalSum"))
                        if isinstance(rollup, dict)
                        else None
                    )
                else:
                    rollup = point.get("activeZoneMinutes")
                    value = parse_active_zone_minutes_rollup(rollup)
                if value is not None:
                    result[day] = value
            page_token = payload.get("nextPageToken")
            if not isinstance(page_token, str) or not page_token:
                break
        return result

    async def _async_list_data_points(
        self, data_type: str, filter_value: str, page_size: int = 10000
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, str | int] = {
                "filter": filter_value,
                "pageSize": page_size,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = await self._async_request(
                "GET",
                f"/users/me/dataTypes/{data_type}/dataPoints",
                params=params,
            )
            raw_points = payload.get("dataPoints", [])
            if not isinstance(raw_points, list):
                raise GoogleHealthResponseError("dataPoints is not a list")
            points.extend(point for point in raw_points if isinstance(point, dict))
            page_token = payload.get("nextPageToken")
            if not isinstance(page_token, str) or not page_token:
                break
        return points

    async def _async_request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make an authenticated request with bounded transient retries."""
        for attempt in range(3):
            response: ClientResponse | None = None
            try:
                response = await self._oauth_session.async_request(
                    method, f"{API_BASE_URL}{path}", **kwargs
                )
                if response.status == 401:
                    raise GoogleHealthAuthError("Google authorization is invalid")
                if response.status == 403:
                    reason = await _google_error_reason(response)
                    raise GoogleHealthPermissionError(
                        "Google Health permission or required scope is missing",
                        reason,
                    )
                if response.status == 429:
                    if attempt < 2:
                        await asyncio.sleep(_retry_delay(response, attempt))
                        continue
                    raise GoogleHealthRateLimitError(
                        "Google Health rate limit exceeded"
                    )
                if response.status >= 500:
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise GoogleHealthTemporaryError(
                        f"Google Health server error ({response.status})"
                    )
                if response.status >= 400:
                    reason = await _google_error_reason(response)
                    if reason == "ACCOUNT_NOT_LINKED":
                        raise GoogleHealthAccountNotLinkedError(
                            "Google account is not linked to Fitbit"
                        )
                    raise GoogleHealthResponseError(
                        f"Google Health request failed ({response.status}, "
                        f"reason={reason or 'unknown'})"
                    )
                try:
                    payload = await response.json()
                except (ValueError, TypeError) as err:
                    raise GoogleHealthResponseError(
                        "Google Health returned malformed JSON"
                    ) from err
                if not isinstance(payload, dict):
                    raise GoogleHealthResponseError(
                        "Google Health returned a non-object response"
                    )
                return payload
            except GoogleHealthError, asyncio.CancelledError:
                raise
            except OAuth2TokenRequestReauthError as err:
                raise GoogleHealthAuthError("Google authorization is invalid") from err
            except OAuth2TokenRequestTransientError as err:
                if attempt == 2:
                    raise GoogleHealthTemporaryError(
                        "Google OAuth token refresh is temporarily unavailable"
                    ) from err
                await asyncio.sleep(2**attempt)
            except (ClientError, TimeoutError) as err:
                if attempt == 2:
                    raise GoogleHealthTemporaryError(
                        "Unable to reach Google Health"
                    ) from err
                await asyncio.sleep(2**attempt)
            finally:
                if response is not None:
                    response.release()
        raise GoogleHealthTemporaryError("Unable to reach Google Health")


async def _google_error_reason(response: ClientResponse) -> str | None:
    """Extract a documented Google ErrorInfo reason without retaining its message."""
    try:
        payload = await response.json()
    except ValueError, TypeError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    details = error.get("details")
    if not isinstance(details, list):
        return None
    for detail in details:
        if not isinstance(detail, dict):
            continue
        reason = detail.get("reason")
        if isinstance(reason, str) and reason:
            return reason
    return None


def iter_date_chunks(
    start_date: date, end_date: date, maximum_days: int
) -> Iterator[tuple[date, date]]:
    """Yield half-open chunks covering an inclusive date range."""
    if maximum_days < 1:
        raise ValueError("maximum_days must be positive")
    cursor = start_date
    end_exclusive = end_date + timedelta(days=1)
    while cursor < end_exclusive:
        chunk_end = min(cursor + timedelta(days=maximum_days), end_exclusive)
        yield cursor, chunk_end
        cursor = chunk_end


def date_range(start_date: date, end_date: date) -> Iterator[date]:
    """Yield every date in an inclusive range."""
    cursor = start_date
    while cursor <= end_date:
        yield cursor
        cursor += timedelta(days=1)


def parse_sleep_session(
    sleep: dict[str, Any], timezone: ZoneInfo
) -> tuple[date, int, bool] | None:
    """Return sleep-day, actual asleep seconds and nap status."""
    interval = sleep.get("interval")
    if not isinstance(interval, dict):
        return None
    sleep_day = _civil_date(interval.get("civilEndTime"))
    if sleep_day is None:
        end_time = _parse_datetime(interval.get("endTime"))
        if end_time is None:
            return None
        sleep_day = end_time.astimezone(timezone).date()

    metadata = sleep.get("metadata")
    is_nap = bool(metadata.get("nap", False)) if isinstance(metadata, dict) else False
    summary = sleep.get("summary")
    if isinstance(summary, dict):
        minutes_asleep = _as_int(summary.get("minutesAsleep"))
        if minutes_asleep is not None and minutes_asleep >= 0:
            return sleep_day, minutes_asleep * 60, is_nap

    stage_seconds = 0
    saw_sleep_stage = False
    stages = sleep.get("stages", [])
    if isinstance(stages, list):
        for stage in stages:
            if not isinstance(stage, dict) or stage.get("type") not in {
                "LIGHT",
                "DEEP",
                "REM",
                "ASLEEP",
            }:
                continue
            start = _parse_datetime(stage.get("startTime"))
            end = _parse_datetime(stage.get("endTime"))
            if start is None or end is None or end < start:
                continue
            stage_seconds += int((end - start).total_seconds())
            saw_sleep_stage = True
    if saw_sleep_stage:
        return sleep_day, stage_seconds, is_nap
    return None


def parse_active_zone_minutes_rollup(value: Any) -> int | None:
    """Sum the three documented AZM heart-zone rollup fields."""
    if not isinstance(value, dict):
        return None
    fields = (
        "sumInCardioHeartZone",
        "sumInPeakHeartZone",
        "sumInFatBurnHeartZone",
    )
    parsed = [_as_int(value.get(field)) for field in fields]
    if all(item is None for item in parsed):
        return None
    return sum(item or 0 for item in parsed)


def parse_google_date(value: Any) -> date | None:
    """Parse google.type.Date."""
    if not isinstance(value, dict):
        return None
    try:
        return date(int(value["year"]), int(value["month"]), int(value["day"]))
    except KeyError, TypeError, ValueError:
        return None


def google_date(value: date) -> dict[str, int]:
    """Serialize a date as google.type.Date."""
    return {"year": value.year, "month": value.month, "day": value.day}


def _civil_date(value: Any) -> date | None:
    if not isinstance(value, dict):
        return None
    return parse_google_date(value.get("date"))


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _retry_delay(response: ClientResponse, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass
    return float(2**attempt)
