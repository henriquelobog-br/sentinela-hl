from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np

from sentinela.precipitation.constants import IMERG_INTERVAL_HOURS
from sentinela.precipitation.grid import RectilinearGrid
from sentinela.precipitation.models import AccumulatedField, ImergInterval


def accumulate_imerg_30_minute(
    intervals: Iterable[ImergInterval],
    *,
    valid_from: datetime,
    valid_to: datetime,
    grid: RectilinearGrid,
) -> AccumulatedField:
    if valid_from.tzinfo is None or valid_from.utcoffset() is None:
        raise ValueError("valid_from must be timezone-aware")
    if valid_to.tzinfo is None or valid_to.utcoffset() is None:
        raise ValueError("valid_to must be timezone-aware")
    start = valid_from.astimezone(timezone.utc)
    end = valid_to.astimezone(timezone.utc)
    if end - start != timedelta(hours=24):
        raise ValueError("IMERG accumulation requires an exact 24-hour window")

    expected_starts = {
        start + timedelta(minutes=30 * index) for index in range(48)
    }
    by_start: dict[datetime, ImergInterval] = {}
    for interval in intervals:
        grid.assert_identity(interval.grid_identity)
        if interval.start not in expected_starts or interval.end > end:
            raise ValueError("IMERG interval falls outside or misaligns with forecast window")
        if interval.start in by_start:
            raise ValueError("duplicate IMERG interval")
        grid.validate_field(interval.rate_mm_per_hour)
        by_start[interval.start] = interval

    total = np.zeros(grid.shape, dtype=np.float64)
    valid_count = np.zeros(grid.shape, dtype=np.int16)
    for interval_start in sorted(expected_starts):
        interval = by_start.get(interval_start)
        if interval is None:
            continue
        rates = interval.rate_mm_per_hour
        valid = np.isfinite(rates)
        total[valid] += rates[valid] * IMERG_INTERVAL_HOURS
        valid_count[valid] += 1

    coverage = valid_count.astype(np.float64) / 48.0
    total[valid_count == 0] = np.nan
    return AccumulatedField(start, end, total, coverage, grid.identity)
