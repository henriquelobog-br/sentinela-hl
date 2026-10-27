from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct

import numpy as np

from sentinela.precipitation.constants import REGRID_ALGORITHM_VERSION
from sentinela.precipitation.grid import RectilinearGrid, spherical_cell_area_km2
from sentinela.precipitation.models import immutable_array


@dataclass(frozen=True, slots=True)
class RegridResult:
    values: np.ndarray
    valid_area_fraction: np.ndarray

    def __post_init__(self) -> None:
        values = immutable_array(self.values)
        coverage = immutable_array(self.valid_area_fraction)
        if values.shape != coverage.shape:
            raise ValueError("regridded values and coverage shapes differ")
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "valid_area_fraction", coverage)


@dataclass(frozen=True, slots=True)
class ConservativeWeights:
    source_grid_sha256: str
    target_grid_sha256: str
    target_shape: tuple[int, int]
    source_shape: tuple[int, int]
    target_indices: np.ndarray
    source_indices: np.ndarray
    weights: np.ndarray
    version: str
    sha256: str

    def __post_init__(self) -> None:
        targets = immutable_array(self.target_indices, dtype=np.int64)
        sources = immutable_array(self.source_indices, dtype=np.int64)
        weights = immutable_array(self.weights)
        if not (targets.shape == sources.shape == weights.shape):
            raise ValueError("sparse regrid arrays must have equal shape")
        object.__setattr__(self, "target_indices", targets)
        object.__setattr__(self, "source_indices", sources)
        object.__setattr__(self, "weights", weights)

    def apply(
        self,
        source_values: np.ndarray,
        *,
        source_grid: RectilinearGrid,
        target_grid: RectilinearGrid,
    ) -> RegridResult:
        source_grid.assert_identity(self.source_grid_sha256)
        target_grid.assert_identity(self.target_grid_sha256)
        if source_grid.shape != self.source_shape or target_grid.shape != self.target_shape:
            raise ValueError("grid shape does not match conservative weights")
        source = source_grid.validate_field(source_values).reshape(-1)
        numerator = np.zeros(np.prod(self.target_shape), dtype=np.float64)
        valid_weight = np.zeros_like(numerator)
        valid = np.isfinite(source[self.source_indices])
        np.add.at(
            numerator,
            self.target_indices[valid],
            self.weights[valid] * source[self.source_indices[valid]],
        )
        np.add.at(valid_weight, self.target_indices[valid], self.weights[valid])
        result = np.full_like(numerator, np.nan)
        np.divide(numerator, valid_weight, out=result, where=valid_weight > 0)
        return RegridResult(
            result.reshape(self.target_shape),
            np.clip(valid_weight, 0.0, 1.0).reshape(self.target_shape),
        )

    def target_weight_sums(self) -> np.ndarray:
        sums = np.zeros(np.prod(self.target_shape), dtype=np.float64)
        np.add.at(sums, self.target_indices, self.weights)
        return sums.reshape(self.target_shape)


def build_conservative_weights(
    source_grid: RectilinearGrid,
    target_grid: RectilinearGrid,
    *,
    version: str = REGRID_ALGORITHM_VERSION,
) -> ConservativeWeights:
    target_indices: list[int] = []
    source_indices: list[int] = []
    weights: list[float] = []
    source_nlon = source_grid.shape[1]
    target_nlon = target_grid.shape[1]

    for target_lat in range(target_grid.shape[0]):
        t_lat1 = target_grid.lat_edges[target_lat]
        t_lat2 = target_grid.lat_edges[target_lat + 1]
        for target_lon in range(target_grid.shape[1]):
            t_lon1 = target_grid.lon_edges[target_lon]
            t_lon2 = target_grid.lon_edges[target_lon + 1]
            target_area = spherical_cell_area_km2(t_lat1, t_lat2, t_lon1, t_lon2)
            target_flat = target_lat * target_nlon + target_lon
            for source_lat in range(source_grid.shape[0]):
                lat1 = max(t_lat1, source_grid.lat_edges[source_lat])
                lat2 = min(t_lat2, source_grid.lat_edges[source_lat + 1])
                if lat2 <= lat1:
                    continue
                for source_lon in range(source_grid.shape[1]):
                    lon1 = max(t_lon1, source_grid.lon_edges[source_lon])
                    lon2 = min(t_lon2, source_grid.lon_edges[source_lon + 1])
                    if lon2 <= lon1:
                        continue
                    overlap = spherical_cell_area_km2(lat1, lat2, lon1, lon2)
                    if overlap <= 0:
                        continue
                    target_indices.append(target_flat)
                    source_indices.append(source_lat * source_nlon + source_lon)
                    weights.append(overlap / target_area)

    target_array = np.asarray(target_indices, dtype=np.int64)
    source_array = np.asarray(source_indices, dtype=np.int64)
    weight_array = np.asarray(weights, dtype=np.float64)
    digest = hashlib.sha256()
    digest.update(version.encode("ascii"))
    digest.update(bytes.fromhex(source_grid.identity.sha256))
    digest.update(bytes.fromhex(target_grid.identity.sha256))
    for target, source, weight in zip(
        target_array, source_array, weight_array, strict=True
    ):
        digest.update(struct.pack(">qqd", int(target), int(source), float(weight)))
    return ConservativeWeights(
        source_grid.identity.sha256,
        target_grid.identity.sha256,
        target_grid.shape,
        source_grid.shape,
        target_array,
        source_array,
        weight_array,
        version,
        digest.hexdigest(),
    )
