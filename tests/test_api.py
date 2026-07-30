"""Google Health API parsing, pagination, chunking, and error tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.google_health.api import (
    METRIC_CALORIES,
    GoogleHealthApiClient,
    GoogleHealthAuthError,
    GoogleHealthRateLimitError,
    GoogleHealthTemporaryError,
    iter_date_chunks,
    parse_active_zone_minutes_rollup,
    parse_sleep_session,
)


class FakeResponse:
    """Small aiohttp response stand-in."""

    def __init__(self, status: int, payload: object, headers=None) -> None:
        self.status = status
        self._payload = payload
        self.headers = headers or {}
        self.released = False

    async def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def release(self) -> None:
        self.released = True


class FakeRequester:
    """Queue authenticated responses and capture requests."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    async def async_request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_sleep_duration_uses_official_summary_and_civil_end_date() -> None:
    """Actual sleep excludes awake time via Google's minutesAsleep summary."""
    result = parse_sleep_session(
        {
            "interval": {
                "startTime": "2026-07-29T22:00:00Z",
                "endTime": "2026-07-30T06:30:00Z",
                "civilEndTime": {"date": {"year": 2026, "month": 7, "day": 30}},
            },
            "metadata": {"nap": False},
            "summary": {"minutesInSleepPeriod": "510", "minutesAsleep": "455"},
        },
        ZoneInfo("Europe/Dublin"),
    )
    assert result == (date(2026, 7, 30), 27_300, False)


def test_sleep_stage_fallback_excludes_awake_and_restless() -> None:
    """Only documented asleep stage types contribute to fallback duration."""
    result = parse_sleep_session(
        {
            "interval": {
                "endTime": "2026-07-30T07:00:00Z",
                "civilEndTime": {"date": {"year": 2026, "month": 7, "day": 30}},
            },
            "stages": [
                {
                    "type": "LIGHT",
                    "startTime": "2026-07-30T00:00:00Z",
                    "endTime": "2026-07-30T01:00:00Z",
                },
                {
                    "type": "AWAKE",
                    "startTime": "2026-07-30T01:00:00Z",
                    "endTime": "2026-07-30T01:30:00Z",
                },
                {
                    "type": "DEEP",
                    "startTime": "2026-07-30T01:30:00Z",
                    "endTime": "2026-07-30T03:00:00Z",
                },
            ],
        },
        ZoneInfo("UTC"),
    )
    assert result == (date(2026, 7, 30), 9_000, False)


def test_daily_timezone_assignment_without_civil_time() -> None:
    """Home Assistant timezone is the fallback when civil time is absent."""
    result = parse_sleep_session(
        {
            "interval": {"endTime": "2026-07-29T23:30:00Z"},
            "summary": {"minutesAsleep": "420"},
        },
        ZoneInfo("Europe/Dublin"),
    )
    assert result is not None
    assert result[0] == date(2026, 7, 30)


def test_active_zone_rollup_missing_and_zero() -> None:
    """Missing AZM stays missing while explicit zeros stay zero."""
    assert parse_active_zone_minutes_rollup(None) is None
    assert parse_active_zone_minutes_rollup({}) is None
    assert (
        parse_active_zone_minutes_rollup(
            {
                "sumInFatBurnHeartZone": "10",
                "sumInCardioHeartZone": "8",
                "sumInPeakHeartZone": "4",
            }
        )
        == 22
    )
    assert parse_active_zone_minutes_rollup({"sumInCardioHeartZone": "0"}) == 0


def test_query_chunking_endpoint_limits() -> None:
    """A 120-day total-calorie range is split into documented 14-day calls."""
    chunks = list(iter_date_chunks(date(2026, 4, 2), date(2026, 7, 30), 14))
    assert len(chunks) == 9
    assert chunks[0] == (date(2026, 4, 2), date(2026, 4, 16))
    assert chunks[-1] == (date(2026, 7, 23), date(2026, 7, 31))
    assert all((end - start).days <= 14 for start, end in chunks)


@pytest.mark.asyncio
async def test_rollup_parsing_and_request_shape() -> None:
    """Daily total calories use the official dailyRollUp endpoint and kcalSum."""
    requester = FakeRequester(
        FakeResponse(
            200,
            {
                "rollupDataPoints": [
                    {
                        "civilStartTime": {
                            "date": {"year": 2026, "month": 7, "day": 30}
                        },
                        "totalCalories": {"kcalSum": 2458.5},
                    }
                ]
            },
        )
    )
    client = GoogleHealthApiClient(requester, ZoneInfo("UTC"))
    values = await client.async_fetch_metric(
        METRIC_CALORIES, date(2026, 7, 30), date(2026, 7, 30)
    )
    assert values == {date(2026, 7, 30): 2458.5}
    method, url, kwargs = requester.calls[0]
    assert method == "POST"
    assert url.endswith("/total-calories/dataPoints:dailyRollUp")
    assert kwargs["json"]["windowSizeDays"] == 1


@pytest.mark.asyncio
async def test_pagination() -> None:
    """List endpoints follow nextPageToken until exhausted."""
    requester = FakeRequester(
        FakeResponse(
            200,
            {
                "dataPoints": [
                    {
                        "dailyRestingHeartRate": {
                            "date": {"year": 2026, "month": 7, "day": 29},
                            "beatsPerMinute": "61",
                        }
                    }
                ],
                "nextPageToken": "next",
            },
        ),
        FakeResponse(
            200,
            {
                "dataPoints": [
                    {
                        "dailyRestingHeartRate": {
                            "date": {"year": 2026, "month": 7, "day": 30},
                            "beatsPerMinute": "62",
                        }
                    }
                ]
            },
        ),
    )
    client = GoogleHealthApiClient(requester, ZoneInfo("UTC"))
    values = await client._async_fetch_rhr(date(2026, 7, 29), date(2026, 7, 31))
    assert values == {date(2026, 7, 29): 61, date(2026, 7, 30): 62}
    assert requester.calls[1][2]["params"]["pageToken"] == "next"


@pytest.mark.asyncio
async def test_api_401() -> None:
    client = GoogleHealthApiClient(
        FakeRequester(FakeResponse(401, {})), ZoneInfo("UTC")
    )
    with pytest.raises(GoogleHealthAuthError):
        await client.async_get_identity()


@pytest.mark.asyncio
async def test_api_429() -> None:
    client = GoogleHealthApiClient(
        FakeRequester(*(FakeResponse(429, {}) for _ in range(3))), ZoneInfo("UTC")
    )
    with (
        patch("custom_components.google_health.api.asyncio.sleep", AsyncMock()),
        pytest.raises(GoogleHealthRateLimitError),
    ):
        await client.async_get_identity()


@pytest.mark.asyncio
async def test_api_5xx() -> None:
    client = GoogleHealthApiClient(
        FakeRequester(*(FakeResponse(503, {}) for _ in range(3))), ZoneInfo("UTC")
    )
    with (
        patch("custom_components.google_health.api.asyncio.sleep", AsyncMock()),
        pytest.raises(GoogleHealthTemporaryError),
    ):
        await client.async_get_identity()
