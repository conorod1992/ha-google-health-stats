"""Coordinator update behavior tests."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.google_health.api import (
    METRIC_AZM,
    METRIC_CALORIES,
    METRIC_RHR,
    METRIC_SLEEP,
    GoogleHealthTemporaryError,
)
from custom_components.google_health.coordinator import GoogleHealthCoordinator


class FakeHistory:
    def __init__(self) -> None:
        self.records = {}
        self.saved = []

    async def async_replace_metric(self, metric, values):
        self.saved.append((metric, values))

    async def async_prune(self, today):
        return False


class PartialClient:
    async def async_fetch_metric(self, metric, start, end, callback):
        if metric == METRIC_RHR:
            raise GoogleHealthTemporaryError("temporary")
        await callback(metric, {end: 0 if metric == METRIC_AZM else 1})


@pytest.mark.asyncio
async def test_partial_metric_failure_preserves_other_updates() -> None:
    """One endpoint failure does not discard successful metric chunks."""
    coordinator = object.__new__(GoogleHealthCoordinator)
    coordinator.client = PartialClient()
    coordinator.history = FakeHistory()
    coordinator.metric_errors = {}
    coordinator.last_successful_update = None
    data = await coordinator._async_refresh_range(date(2026, 7, 28), date(2026, 7, 30))
    saved_metrics = {metric for metric, _ in coordinator.history.saved}
    assert saved_metrics == {METRIC_SLEEP, METRIC_CALORIES, METRIC_AZM}
    assert data.metric_errors[METRIC_RHR] == "GoogleHealthTemporaryError"
