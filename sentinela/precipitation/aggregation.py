from __future__ import annotations

import numpy as np

from sentinela.precipitation.constants import (
    MIN_SPATIAL_COVERAGE,
    MIN_TEMPORAL_COVERAGE,
    MIN_VALID_ROI_CELLS_FRACTION,
)
from sentinela.precipitation.grid import RectilinearGrid
from sentinela.precipitation.models import (
    ClassAreaSummary,
    RoiVerificationSummary,
    VerificationClass,
)
from sentinela.precipitation.verification import classify_verification


def aggregate_roi_verification(
    forecast_probability: np.ndarray,
    observed_mm: np.ndarray,
    *,
    threshold_mm: float,
    grid: RectilinearGrid,
    roi_fraction: np.ndarray,
    temporal_coverage: np.ndarray | float,
    spatial_coverage: np.ndarray | float = 1.0,
) -> RoiVerificationSummary:
    forecast = grid.validate_field(forecast_probability)
    observed = grid.validate_field(observed_mm)
    roi = grid.validate_field(roi_fraction)
    if np.any((roi < 0) | (roi > 1)):
        raise ValueError("ROI fractions must be within [0, 1]")
    temporal = np.broadcast_to(np.asarray(temporal_coverage, dtype=np.float64), grid.shape)
    spatial = np.broadcast_to(np.asarray(spatial_coverage, dtype=np.float64), grid.shape)
    if np.any((temporal < 0) | (temporal > 1)) or np.any((spatial < 0) | (spatial > 1)):
        raise ValueError("coverage values must be within [0, 1]")

    roi_cells = roi > 0
    total_cell_count = int(np.count_nonzero(roi_cells))
    if total_cell_count == 0:
        raise ValueError("ROI contains no comparison cells")
    areas = grid.cell_areas_km2() * roi
    total_area = float(np.sum(areas))
    valid = roi_cells & np.isfinite(forecast) & np.isfinite(observed)
    valid_area = float(np.sum(areas[valid]))
    valid_count = int(np.count_nonzero(valid))
    weighted_temporal = float(np.sum(areas * temporal) / total_area)
    weighted_spatial = float(np.sum(areas * spatial) / total_area)
    valid_cell_fraction = valid_count / total_cell_count
    if weighted_temporal < MIN_TEMPORAL_COVERAGE:
        raise ValueError("insufficient temporal coverage")
    if weighted_spatial < MIN_SPATIAL_COVERAGE:
        raise ValueError("insufficient spatial coverage")
    if valid_cell_fraction < MIN_VALID_ROI_CELLS_FRACTION:
        raise ValueError("insufficient valid ROI cells")

    classes = classify_verification(
        forecast, observed, threshold_mm=threshold_mm
    )

    def summarize(label: VerificationClass) -> ClassAreaSummary:
        selected = valid & (classes == label.value)
        area = float(np.sum(areas[selected]))
        return ClassAreaSummary(
            int(np.count_nonzero(selected)),
            area,
            area / valid_area if valid_area else 0.0,
        )

    return RoiVerificationSummary(
        temporal_coverage=weighted_temporal,
        spatial_coverage=weighted_spatial,
        valid_roi_cells_fraction=valid_cell_fraction,
        valid_cell_count=valid_count,
        total_cell_count=total_cell_count,
        valid_area_km2=valid_area,
        total_area_km2=total_area,
        hit=summarize(VerificationClass.HIT),
        miss=summarize(VerificationClass.MISS),
        false_alarm=summarize(VerificationClass.FALSE_ALARM),
        correct_negative=summarize(VerificationClass.CORRECT_NEGATIVE),
        observed_max_mm=float(np.nanmax(np.where(valid, observed, np.nan))),
        observed_area_mean_mm=float(np.sum(areas[valid] * observed[valid]) / valid_area),
    )
