from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping

import numpy as np

from sentinela.precipitation.grid import GridIdentity


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def immutable_array(values: np.ndarray, *, dtype: np.dtype | type = np.float64) -> np.ndarray:
    array = np.array(values, dtype=dtype, copy=True)
    array.setflags(write=False)
    return array


class ForecastDecision(str, Enum):
    YES = "YES"
    NO = "NO"


class VerificationClass(str, Enum):
    HIT = "HIT"
    MISS = "MISS"
    FALSE_ALARM = "FALSE_ALARM"
    CORRECT_NEGATIVE = "CORRECT_NEGATIVE"


@dataclass(frozen=True, slots=True)
class ImergInterval:
    start: datetime
    end: datetime
    rate_mm_per_hour: np.ndarray
    grid_identity: GridIdentity

    def __post_init__(self) -> None:
        start = _utc(self.start)
        end = _utc(self.end)
        if end - start != timedelta(minutes=30):
            raise ValueError("IMERG intervals must be exactly 30 minutes")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "rate_mm_per_hour", immutable_array(self.rate_mm_per_hour))


@dataclass(frozen=True, slots=True)
class AccumulatedField:
    valid_from: datetime
    valid_to: datetime
    accumulation_mm: np.ndarray
    temporal_coverage: np.ndarray
    grid_identity: GridIdentity

    def __post_init__(self) -> None:
        valid_from = _utc(self.valid_from)
        valid_to = _utc(self.valid_to)
        if valid_to - valid_from != timedelta(hours=24):
            raise ValueError("precipitation accumulation window must be 24 hours")
        accumulation = immutable_array(self.accumulation_mm)
        coverage = immutable_array(self.temporal_coverage)
        if accumulation.shape != coverage.shape:
            raise ValueError("accumulation and temporal coverage shapes differ")
        if np.any((coverage < 0) | (coverage > 1)):
            raise ValueError("temporal coverage must be within [0, 1]")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_to", valid_to)
        object.__setattr__(self, "accumulation_mm", accumulation)
        object.__setattr__(self, "temporal_coverage", coverage)


@dataclass(frozen=True, slots=True)
class ClassAreaSummary:
    cell_count: int
    area_km2: float
    area_fraction: float


@dataclass(frozen=True, slots=True)
class RoiVerificationSummary:
    temporal_coverage: float
    spatial_coverage: float
    valid_roi_cells_fraction: float
    valid_cell_count: int
    total_cell_count: int
    valid_area_km2: float
    total_area_km2: float
    hit: ClassAreaSummary
    miss: ClassAreaSummary
    false_alarm: ClassAreaSummary
    correct_negative: ClassAreaSummary
    observed_max_mm: float
    observed_area_mean_mm: float


@dataclass(frozen=True, slots=True)
class Provenance:
    algorithm_versions: Mapping[str, str]
    artifact_sha256: tuple[str, ...]
    parameters: Mapping[str, str | int | float | bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm_versions", MappingProxyType(dict(self.algorithm_versions)))
        object.__setattr__(self, "artifact_sha256", tuple(self.artifact_sha256))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        for digest in self.artifact_sha256:
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("provenance artifact hashes must be lowercase SHA-256")
