from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Iterable

import numpy as np

from sentinela.precipitation.constants import EARTH_RADIUS_KM, SUPPORTED_LATITUDE


def _canonical_number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("grid coordinates must be finite")
    return format(float(value), ".15g")


@dataclass(frozen=True, slots=True)
class GridIdentity:
    algorithm: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.algorithm.strip():
            raise ValueError("grid identity algorithm is required")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("grid identity must contain a lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class RectilinearGrid:
    lat_edges: tuple[float, ...]
    lon_edges: tuple[float, ...]
    identity: GridIdentity = field(init=False)

    def __init__(self, lat_edges: Iterable[float], lon_edges: Iterable[float]) -> None:
        lat = tuple(float(value) for value in lat_edges)
        lon = tuple(float(value) for value in lon_edges)
        if len(lat) < 2 or len(lon) < 2:
            raise ValueError("grid requires at least one cell")
        if any(not a < b for a, b in zip(lat, lat[1:])):
            raise ValueError("latitude edges must be strictly increasing")
        if any(not a < b for a, b in zip(lon, lon[1:])):
            raise ValueError("longitude edges must be strictly increasing")
        if lat[0] < SUPPORTED_LATITUDE[0] or lat[-1] > SUPPORTED_LATITUDE[1]:
            raise ValueError("grid exceeds supported latitude range [-60, +60]")
        if lon[0] < -180 or lon[-1] > 180:
            raise ValueError("longitude edges must be within [-180, 180]")
        payload = json.dumps(
            {
                "lat_edges": [_canonical_number(value) for value in lat],
                "lon_edges": [_canonical_number(value) for value in lon],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        object.__setattr__(self, "lat_edges", lat)
        object.__setattr__(self, "lon_edges", lon)
        object.__setattr__(
            self,
            "identity",
            GridIdentity("rectilinear-latlon-v1", hashlib.sha256(payload).hexdigest()),
        )

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.lat_edges) - 1, len(self.lon_edges) - 1)

    def validate_field(self, values: np.ndarray) -> np.ndarray:
        array = np.asarray(values, dtype=np.float64)
        if array.shape != self.shape:
            raise ValueError(f"field shape {array.shape} does not match grid {self.shape}")
        return array

    def assert_identity(self, identity: GridIdentity | str) -> None:
        sha256 = identity.sha256 if isinstance(identity, GridIdentity) else identity
        if sha256 != self.identity.sha256:
            raise ValueError("grid identity mismatch")

    def cell_areas_km2(self) -> np.ndarray:
        lat_radians = np.radians(np.asarray(self.lat_edges, dtype=np.float64))
        lon_radians = np.radians(np.asarray(self.lon_edges, dtype=np.float64))
        lat_factor = np.abs(np.sin(lat_radians[1:]) - np.sin(lat_radians[:-1]))
        lon_width = lon_radians[1:] - lon_radians[:-1]
        areas = (EARTH_RADIUS_KM**2) * lat_factor[:, None] * lon_width[None, :]
        areas.setflags(write=False)
        return areas


def spherical_cell_area_km2(
    lat1: float, lat2: float, lon1: float, lon2: float
) -> float:
    if lat2 <= lat1 or lon2 <= lon1:
        return 0.0
    return (
        EARTH_RADIUS_KM**2
        * math.radians(lon2 - lon1)
        * abs(math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)))
    )
